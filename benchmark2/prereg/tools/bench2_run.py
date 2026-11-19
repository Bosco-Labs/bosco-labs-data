"""Benchmark 2 runner: the Web, API and Memory arms, one journal line per attempt.

    uv run python tools/bench2_run.py --pilot            # 6 pilot companies, cap from config
    uv run python tools/bench2_run.py --replicate 1      # within 24 h of the draw
    uv run python tools/bench2_run.py --replicate 2      # 20 to 72 h after replicate 1
    uv run python tools/bench2_run.py --replicate 1 --dry-run   # the plan, no keys, no network

A real run prints the projected cost and, in a terminal, asks for "yes" before it spends
anything (--yes skips the question).

What differs from the first benchmark's runner (tools/counterparty_benchmark.py), and why this is
a new file: every attempt is written to disk at once, so a crash loses nothing and a restart
continues; a turn that stops with pause_turn or tool_use is resumed instead of scored as an
answer; a failed attempt is retried by one rule in every arm; and the model settings come from
the frozen config, not from a shared helper with its own defaults.

Keys: ANTHROPIC_API_KEY and BOSCO_API_SMOKE_KEY, from the environment or --env-file. They are
sent in headers only and never printed or written. API_BASE overrides the product's address.
The spend cap comes from the frozen config; there is no flag to raise it.
"""

import argparse
import json
import os
import platform
import sys
import threading
import time
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from datetime import timedelta
from pathlib import Path

import anthropic
import bench2_lib as lib
import httpx

SLEEP = time.sleep  # tests replace this
ARMS = {0: ("web", "api", "memory"), 1: ("web", "api", "memory"), 2: ("web", "api")}
# A 4xx from the model API (bad request, bad key, no credit) is a fault of the harness or the
# account, not an outcome of the model. Retrying it three times would turn every run of an arm
# into a "failed run", so the replicate stops instead and continues once the fault is fixed.
RETRYABLE_STATUS = (408, 409, 429)
INPUT = input  # tests replace this


def interactive() -> bool:
    return sys.stdin is not None and sys.stdin.isatty()


class Refused(SystemExit):
    """A precondition of the protocol does not hold; nothing was run."""


class StopReplicate(Exception):
    def __init__(self, reason: str, detail: str):
        super().__init__(f"{reason}: {detail}")
        self.reason, self.detail = reason, detail


# --- prompts --------------------------------------------------------------------------------------


def system_prompt(cfg: dict, arm: str, today: str) -> str:
    return cfg["system_common"].format(arm_sentence=cfg["arm_sentence"][arm], today=today)


def question(cfg: dict, c: dict) -> str:
    """The same question for every arm: name, country, number, the register's name and the
    public by-number links we know (which helps the web arm most, on purpose)."""
    src = cfg["official_sources"][c["country"]]
    links = "\n".join("- " + u.replace("{n}", c["number"]) for u in src["urls"])
    lists = "\n".join(f"- {s['name']}: {s['url']}" for s in cfg["sanctions_sources"])
    return cfg["question_template"].format(
        legal_name=c["legal_name"],
        country_name=cfg["countries"][c["country"]]["name"],
        country=c["country"],
        number=c["number"],
        register=src["register"],
        register_links=links,
        sanctions_links=lists,
        answer_format=cfg["answer_format"],
        **cfg["fields"],
    )


def api_prompt(cfg: dict, c: dict, http_status: int, shown) -> tuple[str, int]:
    """(user message, characters of the tool result). The result is passed whole: no cut."""
    text = json.dumps(shown, ensure_ascii=False)
    label = cfg["api_result_label"].format(http_status=http_status)
    return f"{question(cfg, c)}\n\n{label}\n{text}", len(text)


# --- the model loop -------------------------------------------------------------------------------


def create(client, cfg: dict, arm: str, system: str, messages: list):
    """One request. No thinking, sampling or fallbacks parameter: see config model_notes."""
    kw = {
        "model": cfg["model"],
        "max_tokens": cfg["max_tokens"],
        "system": system,
        "messages": messages,
        "output_config": {"effort": cfg["effort"]},
    }
    if arm == "web":  # each resume re-sends the growing conversation, so cache it
        kw |= {"tools": cfg["web_tools"], "cache_control": {"type": "ephemeral"}}
    return client.messages.create(**kw)


def add_usage(total: dict, usage) -> None:
    for k in (
        "input_tokens",
        "output_tokens",
        "cache_creation_input_tokens",
        "cache_read_input_tokens",
    ):
        total[k] = total.get(k, 0) + (getattr(usage, k, 0) or 0)
    tools = getattr(usage, "server_tool_use", None)
    for k, attr in (("web_searches", "web_search_requests"), ("web_fetches", "web_fetch_requests")):
        total[k] = total.get(k, 0) + (getattr(tools, attr, 0) or 0)


def dump(block) -> dict:
    if isinstance(block, dict):
        return block
    return block.model_dump() if hasattr(block, "model_dump") else dict(vars(block))


def evidence(blocks: list[dict]) -> dict:
    """What the content blocks show: queries, pages, citations, tool errors, and the final text
    (the text after the last tool call or result, where the answer is)."""
    queries, fetched, results, cited, errors, tools = [], [], [], [], [], {}
    last_tool = -1
    for i, b in enumerate(blocks):
        kind = b.get("type") or ""
        if kind == "server_tool_use":
            last_tool, name, inp = i, b.get("name") or "", b.get("input") or {}
            tools[name] = tools.get(name, 0) + 1
            if name == "web_search" and inp.get("query"):
                queries.append(inp["query"])
            if name == "web_fetch" and inp.get("url"):
                fetched.append(inp["url"])
        elif kind.endswith("_tool_result"):
            last_tool, content = i, b.get("content")
            if isinstance(content, dict) and content.get("error_code"):
                # server tools report an error as a result block, not as an exception
                errors.append(
                    {"tool": kind.removesuffix("_tool_result"), "error_code": content["error_code"]}
                )
            elif kind == "web_search_tool_result":
                results += [x["url"] for x in content or [] if isinstance(x, dict) and x.get("url")]
            elif kind == "web_fetch_tool_result" and isinstance(content, dict):
                fetched += [content["url"]] if content.get("url") else []
        elif kind == "tool_use":
            last_tool = i
        elif kind == "text":
            cited += [c["url"] for c in b.get("citations") or [] if c.get("url")]
    final = "".join(b.get("text") or "" for b in blocks[last_tool + 1 :] if b.get("type") == "text")
    return {
        "search_queries": list(dict.fromkeys(queries)),
        "fetched_urls": list(dict.fromkeys(fetched)),
        "result_urls": list(dict.fromkeys(results)),
        "cited_urls": list(dict.fromkeys(cited)),
        "tool_errors": errors,
        "server_tools": tools,
        "final_text": final,
    }


def model_loop(client, cfg: dict, arm: str, system: str, prompt: str) -> dict:
    """One attempt at the model: call, resume while the turn is only paused, stop on an answer
    or on anything that makes the attempt invalid. Never raises for an outcome of the model."""
    messages = [{"role": "user", "content": prompt}]
    usage, stops, kinds, request_ids, blocks = {}, [], [], [], []
    reason = None
    while True:
        try:
            resp = create(client, cfg, arm, system, messages)
        except anthropic.APITimeoutError:
            reason = "timeout"
            break
        except anthropic.APIConnectionError:
            reason = "connection_error"
            break
        except anthropic.APIStatusError as e:
            if 400 <= e.status_code < 500 and e.status_code not in RETRYABLE_STATUS:
                raise StopReplicate("model_api", f"HTTP {e.status_code}: {e.message[:300]}") from e
            if e.status_code in (429, 529):  # busy, not broken: wait as told before the retry
                told = e.response.headers.get("retry-after", "")
                SLEEP(min(int(told) if told.isdigit() else 30, 120))
            reason = f"api_error_{e.status_code}"
            break
        add_usage(usage, resp.usage)
        stop = resp.stop_reason
        stops.append(stop)
        request_ids.append(getattr(resp, "_request_id", None))
        blocks += [dump(b) for b in resp.content]
        if stop == "end_turn":
            break
        if stop not in ("pause_turn", "tool_use"):  # max_tokens, refusal, ...
            reason = stop or "no_stop_reason"
            break
        calls = [b for b in map(dump, resp.content) if b.get("type") == "tool_use"]
        if len(kinds) >= int(cfg["continuations"]):
            reason = "continuations_used_up"
            break
        # pause_turn, or tool_use that only names server tools: the server continues when the
        # assistant content is sent back as it is, with no extra user message.
        messages.append({"role": "assistant", "content": resp.content})
        if stop == "tool_use" and calls:  # the model called a tool that does not exist here
            kinds.append("tool_use_client")
            results = [
                {
                    "type": "tool_result",
                    "tool_use_id": b.get("id"),
                    "is_error": True,
                    "content": cfg["client_tool_error"],
                }
                for b in calls
            ]
            messages.append({"role": "user", "content": results})
        else:
            kinds.append("pause_turn" if stop == "pause_turn" else "tool_use_server")
    seen = evidence(blocks)
    # A web search or fetch that the search service itself could not serve (busy, down) is a
    # fault of the service, not an answer of the model: the attempt is retried by the same rule
    # as a network error. Other tool errors (a page that does not open, a limit used up) are
    # part of what web search is, are kept, and are left out by a named check of the analysis.
    retried = set(cfg["retry"]["tool_error_codes"])
    if reason is None and (bad := [e for e in seen["tool_errors"] if e["error_code"] in retried]):
        reason = f"tool_error_{bad[0]['tool']}_{bad[0]['error_code']}"
    answer = lib.parse_answer(seen["final_text"]) if reason is None else None
    if reason is None and answer is None:
        reason = "no_readable_answer"
    return {
        "valid": reason is None,
        "invalid_reason": reason,
        "stop_reasons": stops,
        "continuations": kinds,
        "request_ids": request_ids,
        "usage": usage,
        "searches": usage.get("web_searches", 0),
        "fetches": usage.get("web_fetches", 0),
        **seen,
        "answer": answer,
    }


# --- the API arm ----------------------------------------------------------------------------------


def without_people(body):
    """The API's answer without the officers section, at the top level and in every row."""
    if not isinstance(body, dict):
        return body
    out = {k: v for k, v in body.items() if k != "people"}
    if isinstance(out.get("rows"), list):
        out["rows"] = [
            {k: v for k, v in row.items() if k != "people"} if isinstance(row, dict) else row
            for row in out["rows"]
        ]
    return out


CHECK_FIELDS = ("check", "status", "detail", "source", "source_url")


def api_call(api: httpx.Client, base: str, cfg: dict, c: dict) -> dict:
    """One POST to counterparty-check: {"invalid": reason} or the journal's `api` object plus
    `shown` (what the model gets). 401, 402 and 403 stop the replicate: that is our key or our
    credit, not the product's answer."""
    try:
        r = api.post(
            f"{base}/v1/counterparty-check",
            json={"query": c["number"], "country": c["country"]},
            timeout=cfg["timeouts"]["api_seconds"],
        )
    except httpx.TimeoutException:
        return {"invalid": "api_timeout"}
    except httpx.TransportError:
        return {"invalid": "api_connection_error"}
    if r.status_code in (401, 402, 403):
        raise StopReplicate("product_api_key", f"HTTP {r.status_code}: {r.text[:300]}")
    if r.status_code == 429:
        told = r.headers.get("Retry-After", "")
        SLEEP(min(int(told) if told.isdigit() else 60, cfg["timeouts"]["api_429_max_wait_seconds"]))
        return {"invalid": "api_http_429", "http_status": 429}
    if r.status_code >= 500:
        return {"invalid": f"api_http_{r.status_code}", "http_status": r.status_code}
    try:
        body = without_people(r.json())
    except ValueError:
        body = {"not_json": r.text}
    rows = body.get("rows") if isinstance(body, dict) else None
    row = rows[0] if r.status_code == 200 and rows and isinstance(rows[0], dict) else None
    checks = [{k: x.get(k) for k in CHECK_FIELDS} for x in (row or {}).get("checks") or []]
    charged = float(body.get("charged_usd") or 0) if isinstance(body, dict) else 0.0
    return {
        "http_status": r.status_code,
        "charged_usd": charged,
        "body": body,
        "body_sha256": lib.sha256_bytes(r.content),
        "body_bytes": len(r.content),
        "checks": checks,
        "shown": row if row is not None else body,  # a 4xx body is the product's answer too
    }


# --- one run --------------------------------------------------------------------------------------


class Context:
    def __init__(self, cfg, journal, client, api, base, today, attempts, spent):
        self.cfg, self.journal, self.client, self.api, self.base = cfg, journal, client, api, base
        self.today, self.attempts = today, attempts
        self.spent, self.lock, self.stop = spent, threading.Lock(), threading.Event()
        self.stopped: StopReplicate | None = None


def attempt(ctx: Context, c: dict, arm: str, replicate: int, number: int) -> dict:
    cfg, started, t0 = ctx.cfg, lib.iso(lib.now()), time.monotonic()
    api, prompt = None, question(cfg, c)
    if arm == "api":
        api = api_call(ctx.api, ctx.base, cfg, c)
        if "invalid" not in api:
            prompt, shown_chars = api_prompt(cfg, c, api["http_status"], api.pop("shown"))
            api["shown_chars"] = shown_chars
    if api and "invalid" in api:
        got = {
            "valid": False,
            "invalid_reason": api.pop("invalid"),
            "stop_reasons": [],
            "continuations": [],
            "request_ids": [],
            "usage": {},
            "searches": 0,
            "fetches": 0,
            **evidence([]),
            "answer": None,
        }
    else:
        try:
            got = model_loop(ctx.client, cfg, arm, system_prompt(cfg, arm, ctx.today), prompt)
        except StopReplicate:
            if api:  # the product was paid for: keep that in the journal and the spend count
                aborted(ctx, c, arm, replicate, number, started, api)
            raise
    usd = lib.cost(got["usage"], cfg["prices"]) | {"api": (api or {}).get("charged_usd", 0.0)}
    usd["total"] = round(usd["model"] + usd["search"] + usd["api"], 6)
    return {
        "v": 1,
        "type": "attempt",
        "run_id": lib.run_id(c["id"], arm, replicate),
        "attempt": number,
        "started_at": started,
        "seconds": round(time.monotonic() - t0, 1),
        **got,
        "api": api,
        "usd": usd,
    }


def aborted(ctx: Context, c: dict, arm: str, replicate: int, number: int, started, api) -> None:
    """A product call whose attempt the model API then stopped (a 4xx: key, credit). It is not
    an attempt (the run is continued later), but its fee is spent and is counted."""
    fee = float(api.get("charged_usd") or 0)
    ctx.journal.append(
        {
            "v": 1,
            "type": "attempt_aborted",
            "run_id": lib.run_id(c["id"], arm, replicate),
            "would_be_attempt": number,
            "started_at": started,
            "api": {k: api.get(k) for k in ("http_status", "charged_usd", "body_sha256")},
            "usd": {"model": 0.0, "search": 0.0, "api": fee, "total": round(fee, 6)},
        }
    )
    with ctx.lock:
        ctx.spent += fee


def run_one(ctx: Context, c: dict, arm: str, replicate: int) -> None:
    """Attempts until one is valid or the allowed number is used up. Continues a run that an
    earlier invocation left half way."""
    rid = lib.run_id(c["id"], arm, replicate)
    retry = ctx.cfg["retry"]
    done = ctx.attempts.setdefault(rid, [])
    while lib.run_state(done, retry["attempts"]) == "open" and not ctx.stop.is_set():
        if done:  # wait before a retry: 5 s, then 30 s
            waits = retry["backoff_seconds"]
            SLEEP(waits[min(len(done), len(waits)) - 1])
        line = attempt(ctx, c, arm, replicate, len(done) + 1)
        ctx.journal.append(line)
        done.append(line)
        with ctx.lock:
            ctx.spent += line["usd"]["total"]
        mark = "ok" if line["valid"] else f"invalid ({line['invalid_reason']})"
        print(f"{rid} attempt {line['attempt']}: {mark} ${line['usd']['total']:.4f}", flush=True)


def arm_order(seed: str, replicate: int, cid: str) -> list[str]:
    return sorted(ARMS[replicate], key=lambda a: lib.key(seed, "arm", f"r{replicate}", cid, a))


def company_order(seed: str, replicate: int, companies: list[dict]) -> list[dict]:
    return sorted(companies, key=lambda c: lib.key(seed, "order", f"r{replicate}", c["id"]))


def run_company(ctx: Context, seed: str, c: dict, replicate: int) -> None:
    try:
        for arm in arm_order(seed, replicate, c["id"]):  # back to back
            run_one(ctx, c, arm, replicate)
    except StopReplicate as e:
        ctx.stopped = ctx.stopped or e
        ctx.stop.set()


def company_done(ctx: Context, c: dict, replicate: int) -> bool:
    n = ctx.cfg["retry"]["attempts"]
    return all(
        lib.run_state(ctx.attempts.get(lib.run_id(c["id"], arm, replicate), []), n) != "open"
        for arm in ARMS[replicate]
    )


def run_replicate(ctx: Context, seed: str, companies: list, replicate: int, cap: float, workers):
    """Companies in the seeded order. The cap is checked before each company; once it would be
    passed, the rest of the order is dropped, and a line in the journal says so."""
    reserve = float(ctx.cfg["caps"]["reserve_per_company_usd"])
    todo = [
        c for c in company_order(seed, replicate, companies) if not company_done(ctx, c, replicate)
    ]
    active: set = set()
    submitted = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for i, c in enumerate(todo):
            while len(active) >= workers:
                _, active = wait(active, return_when=FIRST_COMPLETED)
            if ctx.stop.is_set():
                break
            with ctx.lock:
                spent = ctx.spent
            if spent + reserve * (len(active) + 1) > cap:
                dropped = [x["id"] for x in todo[i:]]
                ctx.journal.append(
                    {
                        "v": 1,
                        "type": "cap_stop",
                        "replicate": replicate,
                        "at": lib.iso(lib.now()),
                        "spent_usd": round(spent, 4),
                        "cap_usd": cap,
                        "dropped": dropped,
                    }
                )
                print(f"cap ${cap}: {len(dropped)} companies of replicate {replicate} dropped")
                break
            submitted.append(pool.submit(run_company, ctx, seed, c, replicate))
            active.add(submitted[-1])
        wait(active)
    for f in submitted:
        f.result()  # a bug in the runner surfaces here instead of vanishing in a thread


# --- preconditions --------------------------------------------------------------------------------


def first_start(lines: list[dict], replicate: int) -> str | None:
    times = [
        x["started_at"]
        for x in lines
        if "attempt" in x and x.get("run_id", "").endswith(f"|r{replicate}")
    ]
    return min(times) if times else None


def cap_stopped(lines: list[dict], replicate: int) -> bool:
    return any(x.get("type") == "cap_stop" and x.get("replicate") == replicate for x in lines)


def check_audit(audit: dict, cfg: dict) -> None:
    rows = audit.get("rows") or []
    if blank := [r["id"] for r in rows if r.get("agrees") not in (True, False)]:
        raise Refused(f"audit.json: fill in agrees (true or false) for {', '.join(blank)}")
    bad = [r["id"] for r in rows if r["agrees"] is False and r.get("group") != "S"]
    if len(bad) > int(cfg["audit"]["max_disagreements"]):
        raise Refused(
            f"{len(bad)} audited rows disagree with the answer key ({', '.join(bad)}): the "
            "protocol aborts the study. Document it; a second attempt needs a new freeze."
        )


def preconditions(paths: lib.Paths, cfg: dict, set_file: dict, lines: list, replicate: int, now):
    """Everything section 6 and 8 of the protocol ask for before a main run starts."""
    if problems := lib.verify_prereg(paths):
        raise Refused("the pre-registration does not verify:\n  " + "\n  ".join(problems))
    need = [*lib.manifest_files(paths), paths.prereg, paths.set, paths.audit]
    if dirty := lib.is_committed_clean(paths.root, need):
        raise Refused("commit these before any arm runs: " + ", ".join(dirty))
    pre = lib.read_json(paths.prereg)
    if set_file.get("bundle_hash") != pre["bundle_hash"] or set_file["seed"] != lib.seed(
        pre["bundle_hash"], set_file["drand"]["randomness"]
    ):
        raise Refused("set.json was not drawn from this pre-registration (seed does not recompute)")
    check_audit(lib.read_json(paths.audit), cfg)
    w, n = cfg["windows"], cfg["retry"]["attempts"]
    if replicate == 1 and first_start(lines, 1) is None:
        limit = lib.parse_time(set_file["drawn_at"]) + timedelta(
            hours=w["replicate1_within_hours_of_draw"]
        )
        if now > limit:
            raise Refused(f"replicate 1 had to start by {lib.iso(limit)} (24 h after the draw)")
    if replicate == 2:
        runs = lib.attempts_by_run(lines)
        open_ = [
            c["id"]
            for c in set_file["companies"]
            if any(
                lib.run_state(runs.get(lib.run_id(c["id"], a, 1), []), n) == "open" for a in ARMS[1]
            )
        ]
        began = first_start(lines, 1)
        if began is None or (open_ and not cap_stopped(lines, 1)):
            raise Refused(
                f"replicate 1 is not finished ({len(open_)} companies open): run it first"
            )
        if first_start(lines, 2) is None:
            gap = now - lib.parse_time(began)
            lo, hi = w["replicate_gap_min_hours"], w["replicate_gap_max_hours"]
            if gap < timedelta(hours=lo):
                raise Refused(f"replicate 2 starts at least {lo} h after replicate 1 began: wait")
            if gap > timedelta(hours=hi):
                raise Refused(f"replicate 2 had to start within {hi} h of replicate 1")


# --- command line ---------------------------------------------------------------------------------


def health(api: httpx.Client, base: str) -> dict:
    """The product's /v1/health body, logged at the start and the end. Today it carries a fixed
    version string, not the deployed commit, so it shows a change of tools, not every deploy."""
    try:
        r = api.get(f"{base}/v1/health", timeout=20)
        return {"http_status": r.status_code, "json": r.json()}
    except (httpx.HTTPError, ValueError) as e:
        return {"error": type(e).__name__}


def plan(paths: lib.Paths, cfg: dict, set_file: dict, replicate: int, cap: float, today: str):
    """--dry-run: what would run, in which order, with which prompts and tools. No network."""
    seed, companies = set_file["seed"], set_file["companies"]
    order = company_order(seed, replicate, companies)
    arms = ARMS[replicate]
    print(
        f"replicate {replicate}: {len(order)} companies x {', '.join(arms)} = "
        f"{len(order) * len(arms)} runs; model {cfg['model']}, effort {cfg['effort']}, "
        f"max_tokens {cfg['max_tokens']}; up to {cfg['retry']['attempts']} attempts and "
        f"{cfg['continuations']} continuations"
    )
    for c in order[:8]:
        arms_ = ", ".join(arm_order(seed, replicate, c["id"]))
        print(f"  {c['id']:18} {c['group']}  arms in order: {arms_}")
    print(f"  ... ({len(order)} in all)" if len(order) > 8 else "")
    print("web tools:", json.dumps(cfg["web_tools"]))
    first = order[0]
    for arm in arms:
        print(f"\n--- {arm} arm, system prompt ---\n{system_prompt(cfg, arm, today)}")
        user = question(cfg, first)
        if arm == "api":
            user, _ = api_prompt(cfg, first, 200, "<the full counterparty-check row, no officers>")
        print(f"--- {arm} arm, user message ({first['id']}) ---\n{user}")
    print("\n" + cost_line(paths, cfg, companies, replicate, cap))


def cost_line(paths: lib.Paths, cfg: dict, companies: list, replicate: int, cap: float) -> str:
    per_run = dict(cfg["estimates_usd_per_run"])
    source = "protocol estimates"
    if pilot := lib.mean_cost_per_run(lib.read_journal(paths.pilot_journal)):
        per_run, source = per_run | pilot, "pilot means"
    cost = len(companies) * sum(per_run[a] for a in ARMS[replicate])
    return (
        f"projected cost of this replicate ({source}): ${cost:.2f}; cap ${cap} for "
        f"{'the pilot' if replicate == 0 else 'both replicates together'}, reserve "
        f"${cfg['caps']['reserve_per_company_usd']} per company"
    )


def main(argv=None, root: Path = lib.ROOT, client=None, api=None, now=None) -> int:
    """`client` (Anthropic) and `api` (httpx) replace the real clients in tests."""
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    which = ap.add_mutually_exclusive_group(required=True)
    which.add_argument("--replicate", type=int, choices=(1, 2))
    which.add_argument("--pilot", action="store_true", help="the 6 pilot companies")
    ap.add_argument("--dry-run", action="store_true", help="print the plan; no keys, no network")
    ap.add_argument("--workers", type=int, help="companies in parallel (default from config)")
    ap.add_argument("--env-file", help="KEY=value file (default .env, then ~/.bosco/jobs.env)")
    ap.add_argument("--yes", action="store_true", help="start without asking (after the cost)")
    args = ap.parse_args(argv)
    lib.utf8_stdio()
    paths = lib.Paths(root)
    cfg = lib.read_json(paths.config)
    replicate = 0 if args.pilot else args.replicate
    cap = float(cfg["caps"]["pilot_usd" if args.pilot else "main_usd"])
    set_path = paths.pilot_set if args.pilot else paths.set
    now = now or lib.now()
    today = now.date().isoformat()
    if args.dry_run:
        if not set_path.is_file():
            print(f"{paths.rel(set_path)} does not exist yet: showing the plan on the test fixture")
            set_path = paths.fixtures / "set.json"
        plan(paths, cfg, lib.read_json(set_path), replicate, cap, today)
        return 0
    if not set_path.is_file():
        raise Refused(f"{paths.rel(set_path)} does not exist: draw first")
    set_file = lib.read_json(set_path)
    seed = set_file["seed"]
    journal = lib.Journal(paths.pilot_journal if args.pilot else paths.journal(seed))
    lines = journal.read()
    if not args.pilot:
        preconditions(paths, cfg, set_file, lines, replicate, now)
    if cap_stopped(lines, replicate):
        print(f"replicate {replicate} was stopped by the cap; its remaining companies stay dropped")
        return 0
    print(cost_line(paths, cfg, set_file["companies"], replicate, cap))
    print(f"spent so far (this journal): ${lib.spent_usd(lines):.2f}")
    if not args.yes and interactive():
        if INPUT("Type yes to start (anything else stops, nothing is spent): ").strip() != "yes":
            print("not started")
            return 1
    lib.apply_env(args.env_file, paths.root)
    if client is None:
        if not os.environ.get("ANTHROPIC_API_KEY"):
            raise Refused("ANTHROPIC_API_KEY is not set")
        # max_retries 0: every retry is ours, so the journal shows each one
        client = anthropic.Anthropic(
            api_key=os.environ["ANTHROPIC_API_KEY"],
            max_retries=0,
            timeout=float(cfg["timeouts"]["model_seconds"]),
        )
    if api is None:
        if not os.environ.get("BOSCO_API_SMOKE_KEY"):
            raise Refused("BOSCO_API_SMOKE_KEY is not set")
        api = httpx.Client(headers={"Authorization": f"Bearer {os.environ['BOSCO_API_SMOKE_KEY']}"})
    base = (os.environ.get("API_BASE") or cfg["api_default_base"]).rstrip("/")
    tools = paths.root / "tools"
    journal.append(
        {
            "v": 1,
            "type": "header",
            "replicate": replicate,
            "pilot": args.pilot,
            "started_at": lib.iso(lib.now()),
            "resumed": first_start(lines, replicate) is not None,
            "freeze_commit": set_file.get("freeze_commit"),
            "set_commit": lib.commit_of(paths.root, set_path),
            "head_commit": lib.head(paths.root),
            "set_hash": lib.sha256_norm(set_path),
            "bundle_hash": set_file.get("bundle_hash"),
            "seed": seed,
            "scripts": {n: lib.sha256_norm(tools / f"bench2_{n}.py") for n in lib.SCRIPTS},
            # the hand check as it was when the arms ran: the analysis refuses another one
            "audit_sha256": None if args.pilot else lib.sha256_norm(paths.audit),
            "model": cfg["model"],
            "effort": cfg["effort"],
            "python": platform.python_version(),
            "sdk": anthropic.__version__,
            "api_base": base,
            "health": health(api, base),
        }
    )
    ctx = Context(
        cfg, journal, client, api, base, today, lib.attempts_by_run(lines), lib.spent_usd(lines)
    )
    workers = args.workers or int(cfg["workers"])
    run_replicate(ctx, seed, set_file["companies"], replicate, cap, workers)
    if ctx.stopped:
        journal.append(
            {
                "v": 1,
                "type": "stop",
                "replicate": replicate,
                "at": lib.iso(lib.now()),
                "reason": ctx.stopped.reason,
                "detail": ctx.stopped.detail,
            }
        )
        print(
            f"STOPPED ({ctx.stopped.reason}): {ctx.stopped.detail}\nThe journal is intact; "
            "fix the cause and run the same command again."
        )
    now_lines = journal.read()
    attempts = sum("attempt" in x for x in now_lines)
    journal.append(
        {
            "v": 1,
            "type": "end",
            "replicate": replicate,
            "ended_at": lib.iso(lib.now()),
            "spent_usd": round(ctx.spent, 4),
            "attempt_lines": attempts,  # the analysis checks that none was removed later
            "health": health(api, base),
        }
    )
    print(f"journal: {journal.path}; spent so far ${ctx.spent:.2f} of ${cap}")
    if not args.pilot:
        print(
            f"Publish now (a post with a timestamp): replicate {replicate}, {attempts} attempt "
            f"lines, journal sha256 {lib.sha256_norm(journal.path)}"
        )
    return 2 if ctx.stopped else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
