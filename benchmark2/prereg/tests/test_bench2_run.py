"""Benchmark 2, the runner: the model loop, retries, the API arm, the journal, the cap and the
refusals. Offline: a scripted model client and httpx.MockTransport for the product's API."""

import json
import subprocess
from datetime import timedelta

import anthropic
import httpx
import pytest
from test_bench2_kit import (
    ANSWER,
    REPO,
    ROUND_TIME,
    FakeClient,
    analyze,
    api_client,
    commit,
    drawn_root,
    fetch_result,
    lib,
    make_root,
    reply,
    run,
    search_error,
    search_result,
    server_use,
    text,
    tool_use,
)

CFG = lib.read_json(REPO / "data/benchmark2/config.json")
SET = lib.read_json(REPO / "tests/fixtures/bench2/set.json")
COMPANY = SET["companies"][0]
DRAWN_AT = ROUND_TIME + timedelta(hours=1)
FINAL = f"Done.\n{ANSWER}"


@pytest.fixture(autouse=True)
def no_waiting(monkeypatch):
    waits = []
    monkeypatch.setattr(run, "SLEEP", waits.append)
    return waits


def context(tmp_path, client, api=None, cfg=CFG):
    journal = lib.Journal(tmp_path / "runs.jsonl")
    return run.Context(
        cfg, journal, client, api or api_client(), "https://api.test", "2026-11-15", {}, 0.0
    )


def loop(client, arm="web"):
    return run.model_loop(client, CFG, arm, run.system_prompt(CFG, arm, "2026-11-15"), "Q?")


def server_error(status=500):
    response = httpx.Response(status, request=httpx.Request("POST", "https://model.test"))
    return anthropic.APIStatusError("boom", response=response, body=None)


# --- the model loop -------------------------------------------------------------------------------


def test_end_turn_is_one_call():
    client = FakeClient([reply(FINAL)])
    got = loop(client)
    assert got["valid"] and got["answer"]["status"] == "active" and got["continuations"] == []
    assert got["stop_reasons"] == ["end_turn"] and got["request_ids"] == ["req_test"]
    assert len(client.calls) == 1


def test_pause_turn_is_resumed_without_a_user_message():
    first = [server_use("web_search", query="x"), search_result("https://a.example")]
    client = FakeClient([reply(first, stop="pause_turn"), reply(FINAL)])
    got = loop(client)
    assert got["valid"] and got["continuations"] == ["pause_turn"]
    assert got["stop_reasons"] == ["pause_turn", "end_turn"]
    second = client.calls[1]["messages"]
    assert [m["role"] for m in second] == ["user", "assistant"]  # no extra user message
    assert second[1]["content"] == first


def test_tool_use_with_only_server_blocks_is_resumed_like_pause_turn():
    first = [text("Looking."), server_use("web_fetch", url="https://reg.example/1")]
    client = FakeClient([reply(first, stop="tool_use"), reply(FINAL)])
    got = loop(client)
    assert got["valid"] and got["continuations"] == ["tool_use_server"]
    assert [m["role"] for m in client.calls[1]["messages"]] == ["user", "assistant"]
    assert got["fetched_urls"] == ["https://reg.example/1"]


def test_tool_use_with_a_client_block_gets_an_error_result():
    first = [text("Let me run code."), tool_use("toolu_1", "code_execution")]
    client = FakeClient([reply(first, stop="tool_use"), reply(FINAL)])
    got = loop(client)
    assert got["valid"] and got["continuations"] == ["tool_use_client"]
    msgs = client.calls[1]["messages"]
    assert [m["role"] for m in msgs] == ["user", "assistant", "user"]
    assert msgs[2]["content"] == [
        {
            "type": "tool_result",
            "tool_use_id": "toolu_1",
            "is_error": True,
            "content": CFG["client_tool_error"],
        }
    ]


def test_continuations_are_capped():
    client = FakeClient(default=reply([server_use("web_search", query="q")], stop="pause_turn"))
    got = loop(client)
    assert not got["valid"] and got["invalid_reason"] == "continuations_used_up"
    assert len(got["continuations"]) == CFG["continuations"] == 10
    assert len(client.calls) == 11


@pytest.mark.parametrize(
    "script, reason",
    [
        ([reply("half an answer", stop="max_tokens")], "max_tokens"),
        ([reply("I can't help.", stop="refusal")], "refusal"),
        ([server_error(500)], "api_error_500"),
        ([anthropic.APITimeoutError(request=httpx.Request("POST", "https://m.test"))], "timeout"),
        ([reply("No JSON here.")], "no_readable_answer"),
    ],
)
def test_what_makes_an_attempt_invalid(script, reason):
    got = loop(FakeClient(script))
    assert not got["valid"] and got["invalid_reason"] == reason and got["answer"] is None


def test_retries_then_a_failed_run(tmp_path, no_waiting):
    script = [reply("x", stop="max_tokens"), reply("no", stop="refusal"), server_error(503)]
    ctx = context(tmp_path, FakeClient(script))
    run.run_one(ctx, COMPANY, "web", 1)
    lines = ctx.journal.read()
    assert [x["invalid_reason"] for x in lines] == ["max_tokens", "refusal", "api_error_503"]
    assert [x["attempt"] for x in lines] == [1, 2, 3]
    assert lib.run_state(lines, 3) == "failed" and no_waiting == [5, 30]
    # a second invocation does not try a fourth time
    again = context(tmp_path, FakeClient())
    again.attempts = lib.attempts_by_run(again.journal.read())
    run.run_one(again, COMPANY, "web", 1)
    assert len(ctx.journal.read()) == 3


def test_a_retry_that_succeeds_counts_every_attempt(tmp_path):
    ctx = context(tmp_path, FakeClient([reply("x", stop="max_tokens"), reply(FINAL)]))
    run.run_one(ctx, COMPANY, "memory", 1)
    lines = ctx.journal.read()
    assert [x["valid"] for x in lines] == [False, True]
    assert ctx.spent == pytest.approx(sum(x["usd"]["total"] for x in lines)) and ctx.spent > 0


def test_a_model_api_4xx_stops_the_replicate_instead_of_failing_runs(tmp_path):
    ctx = context(tmp_path, FakeClient([server_error(400)]))
    with pytest.raises(run.StopReplicate, match="HTTP 400"):
        run.run_one(ctx, COMPANY, "web", 1)
    assert ctx.journal.read() == []


# --- requests -------------------------------------------------------------------------------------


def test_system_prompts_differ_only_in_the_arm_sentence_and_tools_equal_the_config(tmp_path):
    prompts = {a: run.system_prompt(CFG, a, "2026-11-15") for a in ("web", "api", "memory")}
    stripped = {p.replace(CFG["arm_sentence"][a], "") for a, p in prompts.items()}
    assert len(stripped) == 1 and len(set(prompts.values())) == 3
    client = FakeClient(default=reply(FINAL))
    ctx = context(tmp_path, client)
    for arm in ("web", "api", "memory"):
        run.run_one(ctx, COMPANY, arm, 1)
    web, api, memory = client.calls
    assert web["tools"] == CFG["web_tools"] and web["cache_control"] == {"type": "ephemeral"}
    for call in (api, memory):
        assert "tools" not in call and "cache_control" not in call
    for call in client.calls:
        assert call["model"] == "claude-sonnet-5-5" and call["max_tokens"] == 16000
        assert call["output_config"] == {"effort": "medium"}
        assert not {"thinking", "temperature", "top_p", "top_k", "fallbacks"} & set(call)
    tools = {t["name"]: t for t in CFG["web_tools"]}
    assert set(tools) == {"web_search", "web_fetch"}  # no code execution
    assert tools["web_search"]["max_uses"] == tools["web_fetch"]["max_uses"] == 6
    assert tools["web_fetch"]["max_content_tokens"] == 10000
    for t in tools.values():
        assert t["blocked_domains"] == ["boscolabs.dev", "huggingface.co", "github.com"]
    # the same question in every arm; the API arm adds the tool result below it
    q = run.question(CFG, COMPANY)
    assert web["messages"][0]["content"] == memory["messages"][0]["content"] == q
    assert api["messages"][0]["content"].startswith(q + "\n\n" + "Tool result")
    assert "https://find-and-update.company-information.service.gov.uk/company/09900001" in q


def test_queries_urls_citations_and_tool_errors_are_extracted():
    cite = [{"type": "web_search_result_location", "url": "https://cited.example/1"}]
    blocks = [
        server_use("web_search", query="FIXTURE ALPHA LTD 09900001"),
        search_result("https://r.example/1", "https://r.example/2"),
        server_use("web_fetch", url="https://find.example/company/09900001"),
        fetch_result("https://find.example/company/09900001"),
        server_use("web_fetch", url="https://blocked.example/"),
        search_error("max_uses_exceeded"),
        text("It is active.", citations=cite),
        text(f" {ANSWER}"),
    ]
    got = loop(FakeClient([reply(blocks)]))
    assert got["search_queries"] == ["FIXTURE ALPHA LTD 09900001"]
    assert got["result_urls"] == ["https://r.example/1", "https://r.example/2"]
    assert got["fetched_urls"] == [
        "https://find.example/company/09900001",
        "https://blocked.example/",
    ]
    assert got["cited_urls"] == ["https://cited.example/1"]
    assert got["tool_errors"] == [{"tool": "web_search", "error_code": "max_uses_exceeded"}]
    assert got["final_text"] == f"It is active. {ANSWER}" and got["valid"]


# --- the API arm ----------------------------------------------------------------------------------


def test_people_reach_neither_the_prompt_nor_the_journal_and_a_long_row_is_not_cut(tmp_path):
    seen = []
    checks = [{"check": "register_status", "status": "pass", "detail": "Active."}]
    row = {
        "status": "checked",
        "checks": checks,
        "notes": "x" * 60000,
        "people": [{"name": "A Secret Officer"}],
    }
    client = FakeClient([reply(FINAL)])
    ctx = context(tmp_path, client, api_client(seen=seen, row=row))
    run.run_one(ctx, COMPANY, "api", 1)
    prompt = client.calls[0]["messages"][0]["content"]
    assert "x" * 60000 in prompt and "A Secret Officer" not in prompt and "people" not in prompt
    journal = ctx.journal.path.read_text(encoding="utf-8")
    assert "A Secret Officer" not in journal and '"people"' not in journal
    line = ctx.journal.read()[0]
    assert line["api"]["shown_chars"] > 60000 and line["api"]["charged_usd"] == 0.05
    assert line["usd"]["api"] == 0.05 and line["api"]["checks"][0]["status"] == "pass"
    assert line["api"]["body_bytes"] > 60000 and len(line["api"]["body_sha256"]) == 64
    (request,) = seen
    assert request.url.path == "/v1/counterparty-check"
    assert json.loads(request.content) == {"query": "09900001", "country": "GB"}


def test_a_4xx_body_is_shown_to_the_model(tmp_path):
    def not_found(request):
        if request.url.path == "/v1/counterparty-check":
            return httpx.Response(404, json={"error": "not_found", "detail": "No such company"})

    client = FakeClient([reply(FINAL)])
    ctx = context(tmp_path, client, api_client(not_found))
    run.run_one(ctx, COMPANY, "api", 1)
    prompt = client.calls[0]["messages"][0]["content"]
    assert "HTTP 404" in prompt and "No such company" in prompt
    line = ctx.journal.read()[0]
    assert line["valid"] and line["api"]["http_status"] == 404


def test_a_5xx_is_an_invalid_attempt_and_429_waits_at_most_120_s(tmp_path, no_waiting):
    answers = iter([httpx.Response(503), httpx.Response(429, headers={"Retry-After": "900"})])

    def flaky(request):
        if request.url.path == "/v1/counterparty-check":
            return next(answers, None)

    client = FakeClient([reply(FINAL)])
    ctx = context(tmp_path, client, api_client(flaky))
    run.run_one(ctx, COMPANY, "api", 1)
    lines = ctx.journal.read()
    assert [x["invalid_reason"] for x in lines] == ["api_http_503", "api_http_429", None]
    assert 120 in no_waiting and len(client.calls) == 1


def test_a_401_stops_the_replicate_with_the_journal_intact(tmp_path, monkeypatch):
    paths = drawn_root(tmp_path)
    monkeypatch.setattr(lib, "now", lambda: DRAWN_AT + timedelta(hours=1))

    calls = []

    def refuse(request):  # the key runs out after the first company's API call
        if request.url.path == "/v1/counterparty-check":
            calls.append(request)
            if len(calls) > 1:
                return httpx.Response(401, json={"error": "bad key"})

    args = ["--replicate", "1", "--workers", "1"]
    client = FakeClient(default=reply(FINAL))
    assert run.main(args, paths.root, client, api_client(refuse), lib.now()) == 2
    seed = lib.read_json(paths.set)["seed"]
    lines = lib.read_journal(paths.journal(seed))
    stop = [x for x in lines if x.get("type") == "stop"]
    assert stop and stop[0]["reason"] == "product_api_key"
    done = [x for x in lines if "attempt" in x]
    assert sum("|api|" in x["run_id"] for x in done) == 1  # the 401 left no attempt behind
    assert len(done) >= 3 and all(x["valid"] for x in done)  # the runs before it are kept
    before = paths.journal(seed).read_bytes()
    # fixed key: the same command continues, nothing finished is run again
    client2 = FakeClient(default=reply(FINAL))
    assert run.main(args, paths.root, client2, api_client(), lib.now()) == 0
    assert paths.journal(seed).read_bytes().startswith(before)
    after = lib.attempts_by_run(lib.read_journal(paths.journal(seed)))
    assert len(after) == 30 and all(len(a) == 1 for a in after.values())
    assert len(client2.calls) == 30 - len(done)


# --- journal, order, cap --------------------------------------------------------------------------


def test_resume_skips_finished_runs_and_rewrites_nothing(tmp_path, monkeypatch):
    paths = drawn_root(tmp_path)
    monkeypatch.setattr(lib, "now", lambda: DRAWN_AT + timedelta(hours=2))
    seed = lib.read_json(paths.set)["seed"]
    client = FakeClient(default=reply(FINAL))
    args = ["--replicate", "1", "--workers", "1"]
    assert run.main(args, paths.root, client, api_client(), lib.now()) == 0
    lines = lib.read_journal(paths.journal(seed))
    header = lines[0]
    assert header["type"] == "header" and header["seed"] == seed and header["model"] == CFG["model"]
    assert header["set_hash"] == lib.sha256_norm(paths.set) and header["set_commit"]
    assert header["freeze_commit"] == lib.read_json(paths.set)["freeze_commit"]
    assert set(header["scripts"]) == set(lib.SCRIPTS) and header["health"]["http_status"] == 200
    assert lines[-1]["type"] == "end" and "health" in lines[-1]
    attempts = [x for x in lines if "attempt" in x]
    assert len(attempts) == 30 == len(client.calls)  # 10 companies x web, api, memory
    keys = {
        "v",
        "run_id",
        "attempt",
        "started_at",
        "seconds",
        "valid",
        "invalid_reason",
        "stop_reasons",
        "continuations",
        "request_ids",
        "usage",
        "searches",
        "fetches",
        "search_queries",
        "fetched_urls",
        "result_urls",
        "cited_urls",
        "tool_errors",
        "final_text",
        "answer",
        "api",
        "usd",
    }
    assert all(keys <= set(x) for x in attempts)
    before = paths.journal(seed).read_bytes()
    again = FakeClient()
    assert run.main(["--replicate", "1"], paths.root, again, api_client(), lib.now()) == 0
    assert again.calls == [] and paths.journal(seed).read_bytes().startswith(before)
    # back to back (one worker): the three arms of a company follow each other
    ids = [x["run_id"].split("|")[0] for x in attempts]
    assert all(len(set(ids[i : i + 3])) == 1 for i in range(0, 30, 3))


def test_order_is_seeded():
    order = run.company_order("s", 1, SET["companies"])
    assert [c["id"] for c in order] == sorted(
        (c["id"] for c in SET["companies"]), key=lambda i: lib.key("s", "order", "r1", i)
    )
    assert order != run.company_order("s", 2, SET["companies"])
    assert sorted(run.arm_order("s", 1, "gb-1")) == ["api", "memory", "web"]
    assert sorted(run.arm_order("s", 2, "gb-1")) == ["api", "web"]  # Memory runs once


def test_cap_stop_drops_the_rest_of_the_replicate(tmp_path):
    ctx = context(tmp_path, FakeClient(default=reply(FINAL)))
    run.run_replicate(ctx, "s", SET["companies"], 1, cap=0.7, workers=1)
    lines = ctx.journal.read()
    stop = [x for x in lines if x.get("type") == "cap_stop"]
    assert len(stop) == 1 and stop[0]["cap_usd"] == 0.7
    order = [c["id"] for c in run.company_order("s", 1, SET["companies"])]
    ran = list(dict.fromkeys(x["run_id"].split("|")[0] for x in lines if "attempt" in x))
    assert ran == order[:2] and stop[0]["dropped"] == order[2:]
    assert run.cap_stopped(lines, 1)


# --- refusals and the dry run ---------------------------------------------------------------------


def test_refuses_on_an_unfilled_audit(tmp_path):
    paths = drawn_root(tmp_path, audited=False)
    with pytest.raises(run.Refused, match="fill in agrees"):
        run.main(["--replicate", "1"], paths.root, FakeClient(), api_client(), DRAWN_AT)


def test_refuses_on_too_many_disagreements(tmp_path):
    paths = drawn_root(tmp_path)
    audit = lib.read_json(paths.audit)
    for row in [r for r in audit["rows"] if r["group"] != "S"][:4]:
        row["agrees"] = False
    lib.write_json(paths.audit, audit)
    commit(paths.root, "audit")
    with pytest.raises(run.Refused, match="aborts the study"):
        run.main(["--replicate", "1"], paths.root, FakeClient(), api_client(), DRAWN_AT)


def test_refuses_on_an_uncommitted_set(tmp_path):
    paths = drawn_root(tmp_path)
    paths.set.write_text(paths.set.read_text(encoding="utf-8") + " ", encoding="utf-8")
    with pytest.raises(run.Refused, match="commit these.*set.json"):
        run.main(["--replicate", "1"], paths.root, FakeClient(), api_client(), DRAWN_AT)


def test_refuses_replicate_1_late_and_replicate_2_early(tmp_path, monkeypatch):
    paths = drawn_root(tmp_path)
    late = DRAWN_AT + timedelta(hours=25)
    with pytest.raises(run.Refused, match="24 h after the draw"):
        run.main(["--replicate", "1"], paths.root, FakeClient(), api_client(), late)
    with pytest.raises(run.Refused, match="replicate 1 is not finished"):
        run.main(["--replicate", "2"], paths.root, FakeClient(), api_client(), DRAWN_AT)
    start = DRAWN_AT + timedelta(hours=1)
    monkeypatch.setattr(lib, "now", lambda: start)
    client = FakeClient(default=reply(FINAL))
    assert run.main(["--replicate", "1"], paths.root, client, api_client(), start) == 0
    early = start + timedelta(hours=19)
    with pytest.raises(run.Refused, match="at least 20 h"):
        run.main(["--replicate", "2"], paths.root, client, api_client(), early)
    with pytest.raises(run.Refused, match="within 72 h"):
        run.main(
            ["--replicate", "2"], paths.root, client, api_client(), start + timedelta(hours=73)
        )
    ok = start + timedelta(hours=21)
    monkeypatch.setattr(lib, "now", lambda: ok)
    assert run.main(["--replicate", "2"], paths.root, client, api_client(), ok) == 0
    seed = lib.read_json(paths.set)["seed"]
    runs = lib.attempts_by_run(lib.read_journal(paths.journal(seed)))
    assert sum(r.endswith("|r2") for r in runs) == 20  # Web and API only


def test_dry_run_needs_no_keys_and_no_network(tmp_path, monkeypatch, capsys):
    def explode(*a, **kw):
        raise AssertionError("a dry run opened a connection")

    monkeypatch.setattr(httpx.Client, "send", explode)
    for k in ("ANTHROPIC_API_KEY", "BOSCO_API_SMOKE_KEY", "COMPANIES_HOUSE_API_KEY"):
        monkeypatch.delenv(k, raising=False)
    paths = make_root(tmp_path)
    before = sorted(p for p in paths.root.rglob("*") if ".git" not in p.parts)
    for args in (["--replicate", "1"], ["--replicate", "2"], ["--pilot"]):
        assert run.main([*args, "--dry-run"], paths.root) == 0
    out = capsys.readouterr().out
    assert "web tools:" in out and "projected cost" in out and "--- api arm, system prompt" in out
    assert "replicate 2: 10 companies x web, api = 20 runs" in out
    assert sorted(p for p in paths.root.rglob("*") if ".git" not in p.parts) == before


def test_a_real_run_needs_the_keys(tmp_path, monkeypatch):
    paths = drawn_root(tmp_path)
    for k in ("ANTHROPIC_API_KEY", "BOSCO_API_SMOKE_KEY"):
        monkeypatch.delenv(k, raising=False)
    empty = tmp_path / "empty.env"
    empty.write_text("", encoding="utf-8")
    with pytest.raises(run.Refused, match="ANTHROPIC_API_KEY is not set"):
        run.main(["--replicate", "1", "--env-file", str(empty)], paths.root, now=DRAWN_AT)


# --- review fixes ---------------------------------------------------------------------------------


@pytest.mark.parametrize("code", ["unavailable", "too_many_requests"])
def test_a_search_service_error_is_retried_like_a_network_error(tmp_path, code):
    broken = [server_use("web_search", query="q"), search_error(code), text(f"Unknown. {ANSWER}")]
    ctx = context(tmp_path, FakeClient([reply(broken), reply(FINAL)]))
    run.run_one(ctx, COMPANY, "web", 1)
    lines = ctx.journal.read()
    assert [x["valid"] for x in lines] == [False, True]
    assert lines[0]["invalid_reason"] == f"tool_error_web_search_{code}"
    assert lines[0]["answer"] is None and lines[0]["tool_errors"][0]["error_code"] == code


def test_three_search_service_errors_make_a_failed_run(tmp_path):
    broken = reply([server_use("web_search", query="q"), search_error("unavailable"), text(ANSWER)])
    ctx = context(tmp_path, FakeClient(default=broken))
    run.run_one(ctx, COMPANY, "web", 1)
    assert lib.run_state(ctx.journal.read(), 3) == "failed"


def test_a_product_call_paid_before_a_model_api_stop_is_journaled_and_counted(tmp_path):
    # the reviewer's case: the product answers and charges, then the model API says 400
    ctx = context(tmp_path, FakeClient([server_error(400)]))
    with pytest.raises(run.StopReplicate, match="HTTP 400"):
        run.run_one(ctx, COMPANY, "api", 1)
    lines = ctx.journal.read()
    assert [x["type"] for x in lines] == ["attempt_aborted"]
    assert lines[0]["usd"]["total"] == 0.05 and lines[0]["api"]["http_status"] == 200
    assert ctx.spent == pytest.approx(0.05) == lib.spent_usd(lines)
    assert lib.attempts_by_run(lines) == {}  # not an attempt: the run is continued later
    assert "body" not in lines[0]["api"]


def test_a_real_run_prints_the_cost_and_asks_before_spending(tmp_path, monkeypatch, capsys):
    paths = drawn_root(tmp_path)
    monkeypatch.setattr(lib, "now", lambda: DRAWN_AT + timedelta(hours=1))
    monkeypatch.setattr(run, "interactive", lambda: True)
    asked = []
    monkeypatch.setattr(run, "INPUT", lambda q: asked.append(q) or "no")
    client, seen = FakeClient(default=reply(FINAL)), []
    assert run.main(["--replicate", "1"], paths.root, client, api_client(seen=seen), lib.now()) == 1
    out = capsys.readouterr().out
    assert "projected cost of this replicate" in out and "not started" in out
    assert asked and client.calls == [] and seen == []
    assert not paths.journal(lib.read_json(paths.set)["seed"]).exists()
    # --yes starts without asking (the cost is still printed)
    asked.clear()
    args = ["--replicate", "1", "--yes", "--workers", "1"]
    assert run.main(args, paths.root, client, api_client(), lib.now()) == 0
    assert asked == [] and len(client.calls) == 30
    assert "projected cost of this replicate" in capsys.readouterr().out


def test_header_binds_the_hand_check_and_the_analysis_refuses_another(tmp_path, monkeypatch):
    paths = drawn_root(tmp_path)
    start = DRAWN_AT + timedelta(hours=1)
    monkeypatch.setattr(lib, "now", lambda: start)
    client = FakeClient(default=reply(FINAL))
    assert run.main(["--replicate", "1"], paths.root, client, api_client(), start) == 0
    later = start + timedelta(hours=21)
    monkeypatch.setattr(lib, "now", lambda: later)
    assert run.main(["--replicate", "2"], paths.root, client, api_client(), later) == 0
    seed = lib.read_json(paths.set)["seed"]
    lines = lib.read_journal(paths.journal(seed))
    headers = [x for x in lines if x.get("type") == "header"]
    assert all(h["audit_sha256"] == lib.sha256_norm(paths.audit) for h in headers)
    ends = [x for x in lines if x.get("type") == "end"]
    assert [e["attempt_lines"] for e in ends] == [30, 50]
    # the analysis checks the run files against the pre-registration and accepts them
    assert analyze.main([], root=paths.root) == 0
    report = lib.read_json(paths.report_dir(seed) / "report.json")
    assert report["provenance"] == "checked against prereg.json"
    assert report["file_sha256"]["audit"] == lib.sha256_norm(paths.audit)
    # a hand check edited after the runs (one more exclusion) is refused
    audit = lib.read_json(paths.audit)
    audit["rows"][0]["agrees"] = False
    lib.write_json(paths.audit, audit)
    with pytest.raises(SystemExit, match="audit.json differs from the hand check"):
        analyze.main([], root=paths.root)
    # and so is a journal from which an attempt was removed
    subprocess.run(["git", "checkout", "--", "."], cwd=paths.root, check=True)
    assert analyze.main([], root=paths.root) == 0  # the committed hand check is accepted again
    kept = [x for x in lines if not (x.get("run_id", "").endswith("|r1") and "attempt" in x)][:5]
    short = tmp_path / "short.jsonl"
    short.write_text("".join(json.dumps(x) + "\n" for x in [*lines[:3], *kept, ends[0]]))
    with pytest.raises(SystemExit, match="end line counts 30 attempt lines"):
        analyze.main(["--journal", str(short)], root=paths.root)
