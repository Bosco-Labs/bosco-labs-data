"""Benchmark 2 analysis: the report, from the run journal and the frozen set.

    uv run python tools/bench2_analyze.py                    # writes report.md and report.json
    uv run python tools/bench2_analyze.py --dry-run          # the test fixture, prints only
    uv run python tools/bench2_analyze.py --journal reports/benchmark2/<seed8>/runs_public.jsonl

Works on the private journal or on the public runs_public.jsonl alone and gives the same
numbers, so a reader can recompute the report. Standard library only, no network, no keys.

The measure is fixed in docs/benchmark2/PROTOCOL.md section 7: per company and arm the share of
its runs with the right decision; per arm the mean of the three group means (A, B, C); the
comparison is the paired difference API minus Web in percentage points, with a bootstrap
interval over companies within groups and a plus-or-minus 2 standard error interval beside it.
"""

import argparse
import math
import random
import statistics
import sys
from collections import Counter
from pathlib import Path

import bench2_lib as lib

MODEL_ARMS = ("web", "api", "memory")
ALL_ARMS = ("web", "api", "memory", "rule")
REPLICATES = (1, 2)
COLUMNS = ("cleared", "flagged", "no_verdict", "failed_run")
LABEL = {"web": "Web", "api": "API", "memory": "Memory", "rule": "Rule"}


# --- runs -----------------------------------------------------------------------------------------


def rule_verdicts(checks: list[dict], rule: dict) -> dict:
    """The Rule arm: the API's own pass / fail words turned into a decision by the frozen
    table, no model. review, unverified and a missing check give no verdict."""
    by = {c.get("check"): c.get("status") for c in checks or []}

    def side(names: list[str]) -> str:
        got = [by.get(n) for n in names]
        if "fail" in got:
            return "problem"
        return "clear" if all(s == "pass" for s in got) else "none"

    return {"register": side(rule["register_checks"]), "sanctions": side(rule["sanctions_checks"])}


def answered_by_api(attempt: dict) -> bool:
    """The product gave an answer in this attempt (a 5xx, a 429 or a timeout is none)."""
    status = (attempt.get("api") or {}).get("http_status") or 0
    return 0 < status < 500 and status != 429


def build_runs(lines: list[dict], companies: list[dict], cfg: dict) -> dict:
    """{(company id, arm, replicate): run}. A run is valid (it has an answer), failed (every
    allowed attempt was invalid) or absent (never finished: cap, or not run yet)."""
    by_run, n = lib.attempts_by_run(lines), int(cfg["retry"]["attempts"])
    runs = {}
    for c in companies:
        for rep in (0, *REPLICATES):
            for arm in MODEL_ARMS:
                tries = by_run.get(lib.run_id(c["id"], arm, rep), [])
                state = lib.run_state(tries, n)
                if state == "open":
                    continue
                good = next((a for a in tries if a.get("valid")), None)
                run = {
                    "state": state,
                    "answer": (good or {}).get("answer"),
                    "attempts": len(tries),
                    "seconds": (good or {}).get("seconds"),
                    "tool_error": any(a.get("tool_errors") for a in tries),
                }
                if state == "valid":
                    v = lib.verdicts(run["answer"])
                    run |= {
                        "verdicts": v,
                        "correct": lib.correct(c["group"], v),
                        "outcome": lib.outcome(c["group"], v),
                    }
                else:
                    run |= {"verdicts": None, "correct": False, "outcome": "failed_run"}
                runs[(c["id"], arm, rep)] = run | {"group": c["group"]}
                if arm == "api":  # Rule reuses the API arm's response of the same run
                    # the API may have answered in an attempt whose model call then failed:
                    # Rule needs no model, so it reads that answer
                    answered = [a for a in tries if answered_by_api(a)]
                    source = good or (answered[-1] if answered else None)
                    rule = {
                        "tool_error": False,
                        "state": "valid" if source else "failed",
                        "answer": None,
                        "attempts": 0,
                        "seconds": None,
                        "verdicts": None,
                        "correct": False,
                        "outcome": "failed_run",
                    }
                    if source:
                        v = rule_verdicts((source.get("api") or {}).get("checks"), cfg["rule_arm"])
                        rule |= {
                            "verdicts": v,
                            "correct": lib.correct(c["group"], v),
                            "outcome": lib.outcome(c["group"], v),
                        }
                    runs[(c["id"], "rule", rep)] = rule | {"group": c["group"]}
    return runs


def failed(run: dict) -> bool:
    return run["state"] == "failed"


def had_tool_error(run: dict) -> bool:
    return bool(run.get("tool_error"))


def pair_reps(runs: dict, cid: str, reps=REPLICATES, drop=None) -> list[int]:
    """The replicates in which the company has a finished Web and a finished API run; `drop`
    (a test on one run) leaves out a replicate where it holds for either arm."""
    out = []
    for r in reps:
        web, api = runs.get((cid, "web", r)), runs.get((cid, "api", r))
        if web and api and not (drop and (drop(web) or drop(api))):
            out.append(r)
    return out


def register_only(group: str, v: dict | None) -> bool:
    """The named check without sanctions: group A is right on register and insolvency alone.
    The web arm is given no by-number sanctions page (the lists are searched by name), so this
    shows how much of the headline rests on proving a negative sanctions answer."""
    if v is None:
        return False
    return v["register"] == "clear" if group == "A" else lib.correct(group, v)


def share(runs: dict, cid: str, arm: str, reps: list[int], score=None) -> float | None:
    got = [runs[(cid, arm, r)] for r in reps if (cid, arm, r) in runs]
    if score is not None:
        got = [{"correct": score(run["group"], run["verdicts"])} for run in got]
    got = [run["correct"] for run in got]
    return sum(got) / len(got) if got else None


# --- the measure ----------------------------------------------------------------------------------


def group_means(values: dict[str, list[float]]) -> dict[str, float | None]:
    return {g: (sum(v) / len(v) if v else None) for g, v in values.items()}


def headline(values: dict[str, list[float]]) -> float | None:
    """Mean of the three group means, in percent; None when a group is empty."""
    means = list(group_means(values).values())
    return None if any(m is None for m in means) else 100 * sum(means) / len(means)


def bootstrap(diffs: dict[str, list[float]], seed: str, cfg: dict) -> tuple[float, float]:
    """Percentile interval of the headline difference, resampling companies within groups."""
    b, level = int(cfg["bootstrap"]["resamples"]), float(cfg["bootstrap"]["level"])
    rng = random.Random(int(lib.key(seed, "bootstrap"), 16))
    groups = [diffs[g] for g in lib.GROUPS]
    draws = sorted(
        100 * sum(sum(rng.choices(d, k=len(d))) / len(d) for d in groups) / len(groups)
        for _ in range(b)
    )
    tail = (1 - level) / 2
    return draws[math.floor(tail * b)], draws[math.ceil((1 - tail) * b) - 1]


def se_interval(diffs: dict[str, list[float]], cfg: dict) -> tuple[float, float, float] | None:
    """(low, high, standard error) in points: the group means are independent, so the variance
    of their mean is the sum of each group's variance of the mean, divided by 9. None when a
    group has fewer than two companies: its variance is unknown, not zero."""
    if any(len(d) < 2 for d in diffs.values()):
        return None
    var = sum(statistics.variance(d) / len(d) for d in diffs.values())
    se = 100 * math.sqrt(var) / len(diffs)
    mid, k = headline(diffs), float(cfg["bootstrap"]["se_multiplier"])
    return mid - k * se, mid + k * se, se


def compare(
    runs: dict, companies: list[dict], reps=REPLICATES, drop=None, score=None
) -> dict | None:
    """Web against API on the given companies and replicates: {web, api, diff, diffs, n}."""
    web = {g: [] for g in lib.GROUPS}
    api = {g: [] for g in lib.GROUPS}
    diffs = {g: [] for g in lib.GROUPS}
    for c in companies:
        if c["group"] not in lib.GROUPS:
            continue
        have = pair_reps(runs, c["id"], reps, drop)
        if not have:
            continue
        w = share(runs, c["id"], "web", have, score)
        a = share(runs, c["id"], "api", have, score)
        web[c["group"]].append(w)
        api[c["group"]].append(a)
        diffs[c["group"]].append(a - w)
    if any(not v for v in diffs.values()):
        return None
    return {
        "web": headline(web),
        "api": headline(api),
        "diff": headline(diffs),
        "diffs": diffs,
        "n": {g: len(v) for g, v in diffs.items()},
        "group_means": {"web": group_means(web), "api": group_means(api)},
    }


def verdict(main: dict, boot, se, by_rep: dict, cfg: dict, too_many_excluded=False) -> dict:
    reps = [by_rep[r]["diff"] if by_rep.get(r) else None for r in REPLICATES]
    both = all(d is not None for d in reps)
    above = se is not None and boot[0] > 0 and se[0] > 0
    below = se is not None and boot[1] < 0 and se[1] < 0
    if too_many_excluded:
        name = "no_difference"
    elif above and both and all(d > 0 for d in reps):
        name = "product_ahead"
    elif below and both and all(d < 0 for d in reps):
        name = "web_ahead"
    else:
        name = "no_difference"
    half = (boot[1] - boot[0]) / 2
    if se is not None:
        half = max(half, (se[1] - se[0]) / 2)
    why = []
    if name == "no_difference":
        if too_many_excluded:
            why.append("more companies were excluded after the runs than the protocol allows")
        if not both:
            why.append("a replicate is missing")
        elif not (all(d > 0 for d in reps) or all(d < 0 for d in reps)):
            why.append("the two replicates do not agree on the direction")
        if se is None:
            why.append("a group has fewer than two companies, so the standard error is unknown")
        elif not (above or below):
            why.append("an interval includes zero")
    return {
        "name": name,
        "why": why,
        "resolution_points": round(half),
        "sentence": cfg["verdict_sentences"][name].format(n=round(half)),
    }


def arm_headline(runs: dict, companies: list[dict], arm: str) -> dict:
    """A control arm on its own: Memory (replicate 1) or Rule (the API arm's replicates)."""
    values = {g: [] for g in lib.GROUPS}
    for c in companies:
        if c["group"] in lib.GROUPS:
            reps = [1] if arm == "memory" else pair_reps(runs, c["id"])
            s = share(runs, c["id"], arm, reps)
            if s is not None:
                values[c["group"]].append(s)
    return {
        "headline": headline(values),
        "group_means": group_means(values),
        "n": {g: len(v) for g, v in values.items()},
    }


# --- the tables under the headline ----------------------------------------------------------------


def arm_runs(runs: dict, companies: list[dict], arm: str):
    """(company, replicate, run) of every finished run of the arm that counts."""
    for c in companies:
        reps = [1] if arm == "memory" else pair_reps(runs, c["id"])
        for r in reps:
            if (c["id"], arm, r) in runs:
                yield c, r, runs[(c["id"], arm, r)]


def column(group: str, outcome: str) -> str:
    """cleared = the run gave the all-clear, flagged = it reported a problem."""
    if outcome in ("cleared", "false_all_clear"):
        return "cleared"
    return "flagged" if outcome in ("false_alarm", "caught") else outcome


def interval(k: int, n: int) -> dict:
    lo, hi = lib.wilson(k, n)
    return {"k": k, "n": n, "pct": 100 * k / n if n else None, "low": 100 * lo, "high": 100 * hi}


def exact(company: dict, run: dict) -> dict:
    """Exact match per field, as the first benchmark scored; a null truth is not scored."""
    truth, a = company["truth"], run["answer"] if isinstance(run["answer"], dict) else {}
    out = {}
    if truth.get("status") is not None:
        out["status"] = str(a.get("status") or "").strip().lower() == truth["status"]
    if truth.get("insolvent") is not None:
        out["insolvent"] = a.get("insolvent") is truth["insolvent"]
    out["sanctioned"] = a.get("sanctioned") is truth["sanctioned"]
    out["all_three"] = all(out.values())
    return out


def tables(runs: dict, companies: list[dict], lines: list[dict]) -> dict:
    abc = [c for c in companies if c["group"] in lib.GROUPS]
    out = {
        "outcomes": {},
        "false_all_clear": {},
        "flips": {},
        "exact": {},
        "group_s": {},
        "false_sanction_flags": {},
        "per_country": {},
        "failed_runs": {},
    }
    for arm in ALL_ARMS:
        table = {g: dict.fromkeys(COLUMNS, 0) for g in (*lib.GROUPS, "S")}
        problem_runs = clear_on_problem = flags = flag_runs = 0
        fields: dict[str, list[bool]] = {}
        country: dict[str, list[bool]] = {}
        for c, _, run in arm_runs(runs, companies, arm):
            table[c["group"]][column(c["group"], run["outcome"])] += 1
            if c["group"] in ("B", "C"):
                problem_runs += 1
                clear_on_problem += run["outcome"] == "false_all_clear"
            if c["group"] in lib.GROUPS:
                flag_runs += 1
                flags += (run["verdicts"] or {}).get("sanctions") == "problem"
                country.setdefault(c["country"], []).append(run["correct"])
                for f, ok in exact(c, run).items():
                    fields.setdefault(f, []).append(ok)
        out["outcomes"][arm] = table
        out["false_all_clear"][arm] = interval(clear_on_problem, problem_runs)
        out["false_sanction_flags"][arm] = {"k": flags, "n": flag_runs}
        if arm != "rule":  # Rule gives decisions, not field values
            out["exact"][arm] = {f: {"k": sum(v), "n": len(v)} for f, v in sorted(fields.items())}
        out["per_country"][arm] = {
            cc: {"k": sum(v), "n": len(v)} for cc, v in sorted(country.items())
        }
        s = table["S"]
        out["group_s"][arm] = {
            "caught": s["flagged"],
            "missed": s["cleared"],
            "no_verdict": s["no_verdict"],
            "failed_run": s["failed_run"],
        }
        if arm != "memory":  # one Memory run per company: nothing to compare
            both = [c for c in abc if len(pair_reps(runs, c["id"])) == 2]
            flip = sum(
                runs[(c["id"], arm, 1)]["correct"] != runs[(c["id"], arm, 2)]["correct"]
                for c in both
            )
            out["flips"][arm] = interval(flip, len(both))
    attempts = [x for x in lines if "attempt" in x and not x["run_id"].endswith("|r0")]
    aborted = [
        x for x in lines if x.get("type") == "attempt_aborted" and not x["run_id"].endswith("|r0")
    ]
    out["cost"] = {}
    for arm in MODEL_ARMS:
        mine = [x for x in attempts if x["run_id"].split("|")[1] == arm]
        lost = [x for x in aborted if x["run_id"].split("|")[1] == arm]
        lost_usd = sum(float(x["usd"]["total"]) for x in lost)
        ids = {x["run_id"] for x in mine}
        usage = Counter()
        for x in mine:
            usage.update({k: v for k, v in (x.get("usage") or {}).items() if isinstance(v, int)})
        secs = [x["seconds"] for x in mine if x.get("valid")]
        failed = [r for r in ids if not any(x.get("valid") for x in mine if x["run_id"] == r)]
        out["cost"][arm] = {
            "runs": len(ids),
            "attempts": len(mine),
            "usd": round(sum(x["usd"]["total"] for x in mine) + lost_usd, 4),
            "usd_api_fee": round(sum(x["usd"].get("api", 0) for x in mine) + lost_usd, 4),
            "usd_per_run": round((sum(x["usd"]["total"] for x in mine) + lost_usd) / len(ids), 4)
            if ids
            else None,
            "aborted_api_calls": len(lost),
            "tokens": dict(sorted(usage.items())),
            "median_seconds": statistics.median(secs) if secs else None,
            "searches": sum(x.get("searches") or 0 for x in mine),
            "fetches": sum(x.get("fetches") or 0 for x in mine),
        }
        out["failed_runs"][arm] = {
            "runs_without_an_answer": len(failed),
            "retries": len(mine) - len(ids),
            "invalid_reasons": dict(
                Counter(x["invalid_reason"] for x in mine if not x.get("valid"))
            ),
            "tool_errors": dict(
                Counter(
                    f"{e.get('tool')}: {e.get('error_code')}"
                    for x in mine
                    for e in x.get("tool_errors") or []
                )
            ),
        }
    return out


# --- what may leave the analysis -----------------------------------------------------------------


def unfinished_runs(lines: list[dict], companies: list[dict], cfg: dict) -> list[str]:
    """Runs of a replicate that has started which are neither valid nor failed, and whose
    company the spend cap did not drop. Such a run would silently leave the headline (a fourth
    attempt might have made it a failed run), so the report has no headline while one exists:
    the same run command continues it."""
    by_run, n = lib.attempts_by_run(lines), int(cfg["retry"]["attempts"])
    out = []
    for rep, arms in ((1, MODEL_ARMS), (2, ("web", "api"))):
        if not any(x["run_id"].endswith(f"|r{rep}") for x in lines if "attempt" in x):
            continue  # not started: shown as a missing replicate, not as unfinished runs
        dropped = {
            cid
            for x in lines
            if x.get("type") == "cap_stop" and x.get("replicate") == rep
            for cid in x.get("dropped") or []
        }
        for c in companies:
            if c["id"] in dropped:
                continue
            for arm in arms:
                rid = lib.run_id(c["id"], arm, rep)
                if lib.run_state(by_run.get(rid, []), n) == "open":
                    out.append(rid)
    return out


def truth2_changes(set_file: dict, truth2: dict | None) -> tuple[dict[str, str], list[str]]:
    """({company id: what changed}, ids whose `changed` flag disagrees with the values). The
    exclusion is recomputed from the second read's values, not taken from the flag."""
    truth = {c["id"]: c for c in set_file["companies"]}
    changed, mismatch = {}, []
    for row in (truth2 or {}).get("companies") or []:
        c, new = truth.get(row["id"]), row.get("truth2") or {}
        if c is None:
            mismatch.append(row["id"])
            continue
        why = []
        for f in ("status", "insolvent"):
            if new.get(f) != c["truth"].get(f):
                why.append(f"{f} {c['truth'].get(f)} -> {new.get(f)}")
        if c["group"] == "S":
            if new.get("sanctioned") is not True:
                why.append("no longer listed with this number and name")
        else:
            if new.get("group") != c["group"]:
                why.append(f"group {c['group']} -> {new.get('group')}")
            if new.get("sanctioned") is not False:
                why.append("name now on a sanctions list")
        if why:
            changed[row["id"]] = "; ".join(why)
        if bool(why) != bool(row.get("changed")):
            mismatch.append(row["id"])
    return changed, mismatch


def sanctions_name_skips(skips: dict | None) -> dict[str, int]:
    """Per cell, how many companies the draw passed over because their name is on a sanctions
    list without a number match. These are the companies on which a name screen could raise a
    false alarm, so leaving them out can only help the arm that screens by name (section 10)."""
    out: Counter = Counter()
    for x in (skips or {}).get("skips") or []:
        if x.get("reason") == "sanctions_name":
            out[x["cell"]] += 1
    return dict(sorted(out.items()))


# --- the report -----------------------------------------------------------------------------------


def analyse(lines, set_file, truth2, audit, cfg, skips=None) -> dict:
    companies, seed = set_file["companies"], set_file["seed"]
    runs = build_runs(lines, companies, cfg)
    excluded, after_runs = {}, set()
    changed, mismatch = truth2_changes(set_file, truth2)
    for cid, why in changed.items():
        excluded[cid] = f"register facts changed between the two reads: {why}"
        after_runs.add(cid)
    for row in (audit or {}).get("rows") or []:
        if row.get("agrees") is False:
            excluded.setdefault(row["id"], "the hand check disagreed with the answer key")
            after_runs.add(row["id"])
    for c in companies:
        if c["id"] not in excluded and not pair_reps(runs, c["id"]):
            excluded[c["id"]] = "no complete Web and API pair in any replicate"
    kept = [c for c in companies if c["id"] not in excluded]
    abc = [c for c in companies if c["group"] in lib.GROUPS]
    late = [c for c in abc if c["id"] in after_runs]
    limit = float(cfg["exclusions"]["max_share_after_runs"])
    unfinished = unfinished_runs(lines, companies, cfg)
    report = {
        "version": 1,
        "seed": seed,
        "model": cfg["model"],
        "companies": {
            "drawn": len(companies),
            "analysed": len(kept),
            "per_group": dict(sorted(Counter(c["group"] for c in kept).items())),
        },
        "excluded": dict(sorted(excluded.items())),
        "excluded_after_runs": {
            "abc": len(late),
            "abc_drawn": len(abc),
            "limit_share": limit,
            "over_limit": bool(abc) and len(late) / len(abc) > limit,
        },
        "truth2_flag_mismatch": mismatch,
        "unfinished_runs": unfinished,
        "sanctions_name_skips": sanctions_name_skips(skips),
        "second_truth_read": truth2 is not None,
        "hand_check": audit is not None,
        "always_clear_baseline": 100 / len(lib.GROUPS),
    }
    if unfinished:
        note = (
            f"{len(unfinished)} runs are unfinished (not valid, not failed, not dropped by the "
            "cap); run the same replicate command again to finish them"
        )
        return report | {"headline": None, "note": note}
    main = compare(runs, kept)
    if main is None:
        return report | {"headline": None, "note": "a group has no analysable company yet"}
    boot, se = bootstrap(main["diffs"], seed, cfg), se_interval(main["diffs"], cfg)
    by_rep = {r: compare(runs, kept, reps=(r,)) for r in REPLICATES}

    def brief(x: dict | None) -> dict | None:
        if x is None:
            return None
        lo, hi, err = se_interval(x["diffs"], cfg) or (None, None, None)
        return {
            "web": x["web"],
            "api": x["api"],
            "diff": x["diff"],
            "n": x["n"],
            "se_interval": None if lo is None else [lo, hi],
            "standard_error": err,
        }

    report["headline"] = brief(main) | {
        "bootstrap_interval": list(boot),
        "group_means": main["group_means"],
    }
    report["replicates"] = {str(r): brief(by_rep[r]) for r in REPLICATES}
    over = report["excluded_after_runs"]["over_limit"]
    report["verdict"] = verdict(main, boot, se, by_rep, cfg, too_many_excluded=over)
    report["controls"] = {arm: arm_headline(runs, kept, arm) for arm in ("memory", "rule")}
    report["checks"] = {
        "first_replicate_only": brief(by_rep[1]),
        "without_failed_runs": brief(compare(runs, kept, drop=failed)),
        "without_runs_that_had_a_tool_error": brief(compare(runs, kept, drop=had_tool_error)),
        "uk_and_latvia_only": brief(
            compare(runs, [c for c in kept if c["country"] in ("GB", "LV")])
        ),
        "group_a_without_sanctions": brief(compare(runs, kept, score=register_only)),
        "all_drawn_companies_no_exclusions": brief(compare(runs, companies)),
    }
    report |= tables(runs, kept, lines)
    report["per_company"] = [
        {
            "id": c["id"],
            "group": c["group"],
            "country": c["country"],
            "truth": c["truth"],
            "excluded": excluded.get(c["id"]),
            "runs": {
                f"{arm} r{r}": runs[(c["id"], arm, r)]["outcome"]
                for arm in ALL_ARMS
                for r in REPLICATES
                if (c["id"], arm, r) in runs
            },
        }
        for c in companies
    ]
    return report


# --- provenance -----------------------------------------------------------------------------------


def journal_problems(lines: list[dict], strict: bool) -> list[str]:
    """What shows that lines were removed: attempt numbers of a run must be 1, 2, ... without a
    gap, and each end line states how many attempt lines came before it (strict: it must)."""
    problems = []
    for rid, tries in lib.attempts_by_run(lines).items():
        if sorted(a["attempt"] for a in tries) != list(range(1, len(tries) + 1)):
            problems.append(f"{rid}: attempt numbers have a gap or a repeat")
    seen = 0
    for i, x in enumerate(lines):
        seen += "attempt" in x
        if x.get("type") == "end":
            if "attempt_lines" not in x:
                if strict:
                    problems.append(f"line {i + 1}: an end line without attempt_lines")
            elif x["attempt_lines"] != seen:
                problems.append(
                    f"line {i + 1}: the end line counts {x['attempt_lines']} attempt lines before "
                    f"it, the journal has {seen}"
                )
    return problems


def provenance(paths: lib.Paths, lines, set_path: Path, set_file: dict, audit_path: Path):
    """Every run file must come from the frozen scripts, the frozen bundle, this set and this
    hand check. Returns the problems ([] = fine); None when there is no prereg.json to check
    against (the fixture, or a folder without the bundle)."""
    if not paths.prereg.is_file():
        return None
    problems = list(lib.verify_prereg(paths))
    pre = lib.read_json(paths.prereg)
    if set_file.get("bundle_hash") != pre.get("bundle_hash"):
        problems.append("the set was drawn from another bundle")
    elif set_file.get("seed") != lib.seed(pre["bundle_hash"], set_file["drand"]["randomness"]):
        problems.append("the seed in the set does not recompute from the bundle and the beacon")
    scripts = {n: (pre.get("manifest") or {}).get(f"tools/bench2_{n}.py") for n in lib.SCRIPTS}
    set_hash = lib.sha256_norm(set_path)
    audit_hash = lib.sha256_norm(audit_path) if audit_path.is_file() else None
    headers = [x for x in lines if x.get("type") == "header" and x.get("replicate") in REPLICATES]
    for rep in REPLICATES:
        ran = any(x["run_id"].endswith(f"|r{rep}") for x in lines if "attempt" in x)
        if ran and not any(h["replicate"] == rep for h in headers):
            problems.append(f"replicate {rep} has runs but no header line")
    for h in headers:
        where = f"header of replicate {h['replicate']} ({h.get('started_at')})"
        if h.get("bundle_hash") != pre.get("bundle_hash") or h.get("seed") != set_file["seed"]:
            problems.append(f"{where}: another bundle or seed")
        if h.get("set_hash") != set_hash:
            problems.append(f"{where}: the set file differs from the one the arms ran on")
        if h.get("scripts") != scripts:
            problems.append(f"{where}: the scripts differ from the frozen ones")
        if h.get("audit_sha256") != audit_hash:
            problems.append(f"{where}: audit.json differs from the hand check the arms ran with")
    return problems + journal_problems(lines, strict=True)


def _n(x, digits=1) -> str:
    return "n/a" if x is None else f"{x:.{digits}f}"


def _kn(x: dict) -> str:
    return f"{x['k']}/{x['n']}" + (f" ({100 * x['k'] / x['n']:.0f}%)" if x["n"] else "")


def markdown(r: dict, cfg: dict) -> str:
    out = [f"# Counterparty-check benchmark 2: report of draw {r['seed'][:8]}", ""]
    c = r["companies"]
    out += [
        "A vendor benchmark: Bosco Labs designed it, ran it and sells one of the two things "
        "compared. Protocol: `docs/benchmark2/PROTOCOL.md`. This report is written by the frozen "
        "script `tools/bench2_analyze.py`.",
        "",
        f"Model {r['model']}. {c['drawn']} companies drawn, {c['analysed']} analysed "
        f"({', '.join(f'{g}: {n}' for g, n in c['per_group'].items())}); {len(r['excluded'])} "
        "excluded (listed at the end).",
    ]
    if r.get("provenance"):
        out += ["", f"Run files: {r['provenance']}."]
    if not r["second_truth_read"]:
        out += ["", "**Preliminary:** the second truth read (truth2.json) is not in yet."]
    x = r["excluded_after_runs"]
    out += [
        "",
        f"Excluded after the runs (changed register facts, hand-check disagreement): {x['abc']} "
        f"of {x['abc_drawn']} companies in groups A, B and C; the protocol's limit is "
        f"{100 * x['limit_share']:.0f}%"
        + (
            ", **which is passed: the verdict is 'no difference shown'**."
            if x["over_limit"]
            else "."
        ),
    ]
    if r["truth2_flag_mismatch"]:
        out += [
            "",
            "**Warning:** in truth2.json the `changed` flag does not match the values for "
            f"{', '.join(r['truth2_flag_mismatch'])}; exclusions were recomputed from the values.",
        ]
    if r["unfinished_runs"]:
        out += ["", f"Unfinished runs: {', '.join(r['unfinished_runs'])}."]
    if r.get("headline") is None:
        return "\n".join(out + ["", f"No headline: {r.get('note')}."]) + "\n"
    h, v = r["headline"], r["verdict"]
    out += [
        "",
        "## Headline",
        "",
        f"**{v['sentence']}**",
        "",
        "Share of runs with the right decision, mean of the three group means (A healthy, B in a "
        "procedure, C gone):",
        "",
        "| | Web search | counterparty-check API | API minus Web |",
        "|---|---|---|---|",
        f"| both replicates | {_n(h['web'])}% | {_n(h['api'])}% | {h['diff']:+.1f} points |",
    ]
    for rep, x in r["replicates"].items():
        if x:
            out.append(
                f"| replicate {rep} alone | {_n(x['web'])}% | {_n(x['api'])}% "
                f"| {x['diff']:+.1f} points |"
            )
        else:
            out.append(f"| replicate {rep} alone | not run | not run | |")
    b, s = h["bootstrap_interval"], h["se_interval"]
    out += [
        "",
        f"- 95% interval of the difference, resampling companies within groups "
        f"{cfg['bootstrap']['resamples']:,} times: {b[0]:+.1f} to {b[1]:+.1f} points.",
        f"- Mean plus or minus {cfg['bootstrap']['se_multiplier']} standard errors "
        f"({_n(h['standard_error'], 2)} points): "
        + (f"{s[0]:+.1f} to {s[1]:+.1f} points." if s else "n/a (a group has one company)."),
        f'- Always answering "all clear" scores {_n(r["always_clear_baseline"])}%.',
        f"- Verdict rule: {v['name'].replace('_', ' ')}"
        + (f" ({'; '.join(v['why'])})" if v["why"] else "")
        + ".",
        "",
        "| Group mean | Web | API |",
        "|---|---|---|",
    ]
    for g in lib.GROUPS:
        web, api = (100 * h["group_means"][arm][g] for arm in ("web", "api"))
        out.append(f"| {g} ({h['n'][g]} companies) | {_n(web)}% | {_n(api)}% |")
    out += ["", "## False all-clear: a problem company answered active and not insolvent", ""]
    out += [
        "| Arm | Runs on B and C | False all-clear | 95% interval (Wilson, runs) |",
        "|---|---|---|---|",
    ]
    for arm in ALL_ARMS:
        x = r["false_all_clear"][arm]
        out.append(f"| {LABEL[arm]} | {x['n']} | {_kn(x)} | {_n(x['low'])}% to {_n(x['high'])}% |")
    out += ["", "## What each arm answered, per group (runs)", ""]
    out += [
        "| Arm | Group | Cleared | Flagged | No verdict | Failed run |",
        "|---|---|---|---|---|---|",
    ]
    for arm in ALL_ARMS:
        for g in (*lib.GROUPS, "S"):
            t = r["outcomes"][arm][g]
            out.append(
                f"| {LABEL[arm]} | {g} | {t['cleared']} | {t['flagged']} | {t['no_verdict']} "
                f"| {t['failed_run']} |"
            )
    out += [
        "",
        "Cleared is right for group A and the expensive mistake for B, C and S; flagged is the "
        "reverse.",
        "",
        "## Run-to-run noise: companies whose two runs disagree",
        "",
    ]
    for arm, x in r["flips"].items():
        out.append(f"- {LABEL[arm]}: {_kn(x)}, 95% interval {_n(x['low'])}% to {_n(x['high'])}%.")
    out += ["", "## Exact match per field (the first benchmark's measure)", ""]
    out += [
        "| Arm | status | insolvent | sanctioned | all scored fields |",
        "|---|---|---|---|---|",
    ]
    for arm in MODEL_ARMS:
        e = r["exact"][arm]
        cells = [
            _kn(e[f]) if f in e else "n/a"
            for f in ("status", "insolvent", "sanctioned", "all_three")
        ]
        out.append(f"| {LABEL[arm]} | " + " | ".join(cells) + " |")
    out += [
        "",
        "Insolvent is scored only where the register says whether a winding-up is solvent. The "
        "Rule arm gives decisions, not field values, so it has no row here.",
        "",
        "## Group S (sanctioned), counts only",
        "",
        "| Arm | Listing caught | Listing missed | No verdict | Failed run "
        "| False sanction flags on A, B, C |",
        "|---|---|---|---|---|---|",
    ]
    for arm in ALL_ARMS:
        x, f = r["group_s"][arm], r["false_sanction_flags"][arm]
        out.append(
            f"| {LABEL[arm]} | {x['caught']} | {x['missed']} | {x['no_verdict']} "
            f"| {x['failed_run']} | {f['k']}/{f['n']} |"
        )
    out += ["", "## Control arms", ""]
    for arm, what in (("memory", "no tools, one run"), ("rule", "the API's verdicts, no model")):
        x = r["controls"][arm]
        gm = ", ".join(
            f"{g} {_n(100 * m) if m is not None else 'n/a'}%" for g, m in x["group_means"].items()
        )
        out.append(f"- {LABEL[arm]} ({what}): {_n(x['headline'])}% ({gm}).")
    out += ["", "## Cost and time", ""]
    out += [
        "| Arm | Runs | Attempts | $ total | $ per run | of which API fee | Median s | Searches "
        "| Fetches | Tokens in / out |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for arm in MODEL_ARMS:
        x = r["cost"][arm]
        t = x["tokens"]
        tin = sum(
            t.get(k, 0)
            for k in ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens")
        )
        out.append(
            f"| {LABEL[arm]} | {x['runs']} | {x['attempts']} | ${x['usd']:.2f} "
            f"| ${_n(x['usd_per_run'], 3)} | ${x['usd_api_fee']:.2f} | {_n(x['median_seconds'])} "
            f"| {x['searches']} | {x['fetches']} | {tin:,} / {t.get('output_tokens', 0):,} |"
        )
    out += ["", "## Per country (too small for intervals)", ""]
    countries = sorted({cc for arm in ALL_ARMS for cc in r["per_country"][arm]})
    out += ["| Arm | " + " | ".join(countries) + " |", "|---|" + "---|" * len(countries)]
    for arm in ALL_ARMS:
        cells = [
            _kn(r["per_country"][arm][cc]) if cc in r["per_country"][arm] else "n/a"
            for cc in countries
        ]
        out.append(f"| {LABEL[arm]} | " + " | ".join(cells) + " |")
    out += ["", "## Checks named in advance", ""]
    out += ["| Check | Web | API | API minus Web | plus or minus 2 SE |", "|---|---|---|---|---|"]
    for name, x in r["checks"].items():
        label = name.replace("_", " ")
        if x:
            i = x["se_interval"]
            out.append(
                f"| {label} | {_n(x['web'])}% | {_n(x['api'])}% | {x['diff']:+.1f} "
                f"| {f'{i[0]:+.1f} to {i[1]:+.1f}' if i else 'n/a'} |"
            )
        else:
            out.append(f"| {label} | n/a | n/a | n/a | a group is empty |")
    out += [
        "",
        "Group A without sanctions: group A is scored on register status and insolvency only. "
        "The web arm gets no by-number page for the sanctions lists (they are searched by name), "
        "so this check shows how much of the headline is the sanctions answer.",
    ]
    out += ["", "## Failed runs and retries", ""]
    for arm in MODEL_ARMS:
        x = r["failed_runs"][arm]
        out.append(
            f"- {LABEL[arm]}: {x['runs_without_an_answer']} runs without an answer, "
            f"{x['retries']} retries; invalid attempts: {x['invalid_reasons'] or 'none'}; tool "
            f"errors: {x['tool_errors'] or 'none'}; product calls paid in an attempt the model "
            f"API then stopped: {r['cost'][arm]['aborted_api_calls']}."
        )
    skipped = r["sanctions_name_skips"]
    out += [
        "",
        "Passed over at the draw because the name is on a sanctions list without a number match "
        "(these would be the false-alarm cases of a name screen): "
        + (", ".join(f"{cell} {n}" for cell, n in skipped.items()) or "none")
        + ".",
    ]
    out += [
        "",
        "## Every company",
        "",
        "Truth as status / insolvent (None = the register does not say, not scored).",
        "",
        "| Company | Group | Truth | "
        + " | ".join(f"{LABEL[a]} r{n}" for a in ("web", "api") for n in REPLICATES)
        + " | Memory | Rule r1 | Rule r2 | Excluded |",
        "|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    order = [f"{a} r{n}" for a in ("web", "api") for n in REPLICATES] + [
        "memory r1",
        "rule r1",
        "rule r2",
    ]
    for c in r["per_company"]:
        t = c["truth"]
        cells = [c["runs"].get(k, "-").replace("_", " ") for k in order]
        out.append(
            f"| {c['id']} | {c['group']} | {t.get('status')} / {t.get('insolvent')} | "
            + " | ".join(cells)
            + f" | {c['excluded'] or ''} |"
        )
    out += [
        "",
        "## Limits",
        "",
        "Four of nine registers; the vendor ran it; the answer key and the product read the same "
        "registers; one model at one effort level; the right registration number was always "
        "given; ambiguous companies were skipped. Groups are not pooled into one accuracy "
        "figure: problem companies are two thirds of this set and a few percent of real "
        "suppliers. Companies whose name is on a sanctions list without a number match were "
        "skipped, which removes the cases where a name screen raises a false alarm. The full "
        "list is in the protocol, section 10.",
    ]
    return "\n".join(out) + "\n"


def main(argv: list[str] | None = None, root: Path = lib.ROOT) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--dry-run", action="store_true", help="print the report, write nothing")
    ap.add_argument("--journal", type=Path, help="runs.jsonl or runs_public.jsonl")
    ap.add_argument("--set", type=Path, dest="set_file")
    ap.add_argument("--truth2", type=Path)
    ap.add_argument("--audit", type=Path)
    ap.add_argument("--skips", type=Path, help="set_skips.json (default next to set.json)")
    ap.add_argument("--env-file", help="accepted for symmetry; this script needs no keys")
    args = ap.parse_args(argv)
    lib.utf8_stdio()
    paths = lib.Paths(root)
    fixture = args.dry_run and not args.journal
    cfg = lib.read_json(paths.config)
    if args.dry_run and not args.journal:  # the hand-computed fixture
        fx = paths.fixtures
        args.journal = fx / "runs.jsonl"
        args.set_file, args.truth2, args.audit = (
            fx / "set.json",
            fx / "truth2.json",
            fx / "audit.json",
        )
    set_path = args.set_file or paths.set
    if not set_path.is_file():
        raise SystemExit(f"{set_path} does not exist: nothing was drawn")
    set_file = lib.read_json(set_path)
    out_dir = paths.report_dir(set_file["seed"])
    journal = args.journal or paths.journal(set_file["seed"])
    if not journal.is_file():
        journal = out_dir / "runs_public.jsonl"
    lines = lib.read_journal(journal)
    if not lines:
        raise SystemExit(f"no runs found in {journal}")
    truth2_path = args.truth2 or out_dir / "truth2.json"
    audit_path = args.audit or paths.audit
    truth2 = lib.read_json(truth2_path) if truth2_path.is_file() else None
    audit = lib.read_json(audit_path) if audit_path.is_file() else None
    skips_path = args.skips or set_path.parent / "set_skips.json"
    skips = lib.read_json(skips_path) if skips_path.is_file() else set_file.get("skips")
    if problems := journal_problems(lines, strict=False):
        raise SystemExit("the journal is not complete:\n  " + "\n  ".join(problems))
    checked = None if fixture else provenance(paths, lines, set_path, set_file, audit_path)
    if checked:
        raise SystemExit(
            "the run files do not match the pre-registration:\n  " + "\n  ".join(checked)
        )
    report = analyse(lines, set_file, truth2, audit, cfg, skips)
    report["provenance"] = (
        "checked against prereg.json"
        if checked == []
        else "not checked: no prereg.json next to the scripts"
    )
    report["file_sha256"] = {
        name: lib.sha256_norm(path) if path.is_file() else None
        for name, path in (
            ("journal", journal),
            ("set", set_path),
            ("truth2", truth2_path),
            ("audit", audit_path),
        )
    }
    if report.get("unfinished_runs") and not args.dry_run:
        print(f"NOT FINISHED: {report['note']}", file=sys.stderr)
    text = markdown(report, cfg)
    print(text)
    if args.dry_run:
        print("dry run: nothing written")
        return 0
    lib.write_text(out_dir / "report.md", text)
    lib.write_json(out_dir / "report.json", report)
    print(f"wrote {paths.rel(out_dir / 'report.md')} and report.json")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
