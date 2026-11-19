"""Benchmark 2, the analysis: a fixture of 9 companies (3 per group) and one group S company,
two replicates, scored by hand below. Offline."""

import copy

import pytest
from test_bench2_kit import REPO, analyze, lib, make_root, prereg

FX = REPO / "tests/fixtures/bench2"
CFG = lib.read_json(REPO / "data/benchmark2/config.json")
SET = lib.read_json(FX / "set.json")
LINES = lib.read_journal(FX / "runs.jsonl")
TRUTH2 = lib.read_json(FX / "truth2.json")
AUDIT = lib.read_json(FX / "audit.json")

# Right decision per company, (replicate 1, replicate 2), worked out from runs.jsonl by hand:
#              Web          API          note
# A gb-01      1, 1         1, 1
# A ie-01      1, 0         1, 1         web r2 says insolvent: true on a healthy company
# A lv-01      1, 1         0, 1         api r1 answered unknown
# B gb-02      0, 0         1, 1         web r1 active (false all-clear), r2 unknown
# B ie-02      1, 1         1, 1
# B lv-02      fail, 1      1, 1         web r1 failed three times (timeouts)
# C gb-03      1, 1         1, 1
# C ie-03      1, 0         1, 1         web r2 active (false all-clear)
# C lv-03      1, 1         1, fail      api r2 failed three times (HTTP 503)
# Shares: Web A (1, .5, 1) B (0, 1, .5) C (1, .5, 1); API A (1, 1, .5) B (1, 1, 1) C (1, 1, .5)
# Group means: Web A 5/6 B 1/2 C 5/6 -> 72.22; API A 5/6 B 1 C 5/6 -> 88.89; diff 16.67.
# Paired differences: A (0, .5, -.5) B (1, 0, .5) C (0, .5, -.5); each group's sample variance is
# 0.25, so SE = 100 * sqrt(3 * 0.25 / 3) / 3 = 16.67 points and the 2 SE interval is -16.67 to 50.
# Replicate 1 alone: differences A (0, 0, -1) B (1, 0, 1) C (0, 0, 0) -> (-1/3 + 2/3 + 0) / 3.
# Replicate 2 alone: A (0, 1, 0) B (1, 0, 0) C (0, 1, -1) -> (1/3 + 1/3 + 0) / 3.


def report(lines=LINES, set_file=SET, truth2=TRUTH2, audit=AUDIT):
    return analyze.analyse(lines, set_file, truth2, audit, CFG)


def test_the_hand_computed_headline():
    r = report()
    h = r["headline"]
    assert h["web"] == pytest.approx(100 * 13 / 18)
    assert h["api"] == pytest.approx(100 * 16 / 18)
    assert h["diff"] == pytest.approx(100 / 6)
    assert h["group_means"]["web"] == pytest.approx({"A": 5 / 6, "B": 0.5, "C": 5 / 6})
    assert h["group_means"]["api"] == pytest.approx({"A": 5 / 6, "B": 1.0, "C": 5 / 6})
    assert h["standard_error"] == pytest.approx(100 / 6)
    assert h["se_interval"] == pytest.approx([-100 / 6, 50.0])
    assert h["n"] == {"A": 3, "B": 3, "C": 3}
    assert r["replicates"]["1"]["diff"] == pytest.approx(100 / 9)
    assert r["replicates"]["2"]["diff"] == pytest.approx(200 / 9)
    assert r["always_clear_baseline"] == pytest.approx(100 / 3)
    assert r["companies"] == {
        "drawn": 10,
        "analysed": 10,
        "per_group": {"A": 3, "B": 3, "C": 3, "S": 1},
    }
    # both replicates favour the API, but the 2 SE interval holds zero: no difference shown
    v = r["verdict"]
    assert v["name"] == "no_difference" and v["why"] == ["an interval includes zero"]
    assert v["sentence"].startswith("This study shows no difference")
    assert f"about {v['resolution_points']} points" in v["sentence"]


def test_the_bootstrap_is_seeded_and_deterministic():
    diffs = report()["headline"]
    boot = diffs["bootstrap_interval"]
    again = report()["headline"]["bootstrap_interval"]
    assert boot == again and boot[0] <= diffs["diff"] <= boot[1]
    d = {"A": [0, 0.5, -0.5], "B": [1, 0, 0.5], "C": [0, 0.5, -0.5]}
    assert analyze.bootstrap(d, SET["seed"], CFG) == pytest.approx(boot)
    # with more distinct values the seed shows: another seed, another interval
    rich = {g: [((i * 37 + k) % 11) / 10 - 0.5 for i in range(30)] for k, g in enumerate("ABC")}
    assert analyze.bootstrap(rich, "s1", CFG) == analyze.bootstrap(rich, "s1", CFG)
    assert analyze.bootstrap(rich, "s1", CFG) != analyze.bootstrap(rich, "s2", CFG)
    # every resample of a group with a single value is that value
    fixed = analyze.bootstrap({"A": [0.3], "B": [0.3], "C": [0.3]}, "s", CFG)
    assert fixed == pytest.approx((30.0, 30.0))


@pytest.mark.parametrize(
    "boot, se, reps, name",
    [
        ((5, 20), (2, 25), (10, 3), "product_ahead"),
        ((-20, -5), (-25, -2), (-10, -3), "web_ahead"),
        ((5, 20), (2, 25), (10, -3), "no_difference"),  # the replicates disagree
        ((5, 20), (-1, 25), (10, 3), "no_difference"),  # one interval holds zero
        ((5, 20), (2, 25), (10, None), "no_difference"),  # a replicate is missing
    ],
)
def test_the_three_verdicts(boot, se, reps, name):
    by_rep = {
        r: ({"diff": d} if d is not None else None) for r, d in zip((1, 2), reps, strict=True)
    }
    v = analyze.verdict({}, boot, (*se, 1.0), by_rep, CFG)
    assert v["name"] == name
    assert v["sentence"] == CFG["verdict_sentences"][name].format(n=v["resolution_points"])
    if reps == (10, -3):
        assert "the two replicates do not agree on the direction" in v["why"]
    if name == "web_ahead":
        assert v["sentence"] == (
            "On these companies the model with web search reached the right decision more often "
            "than the model reading counterparty-check."
        )


def test_tables_under_the_headline():
    r = report()
    assert r["false_all_clear"]["web"]["k"] == 2 and r["false_all_clear"]["web"]["n"] == 12
    assert r["false_all_clear"]["api"]["k"] == 0 and r["false_all_clear"]["api"]["n"] == 12
    lo, hi = lib.wilson(2, 12)
    assert r["false_all_clear"]["web"]["low"] == pytest.approx(100 * lo)
    assert r["outcomes"]["web"]["B"] == {
        "cleared": 1,
        "flagged": 3,
        "no_verdict": 1,
        "failed_run": 1,
    }
    assert r["outcomes"]["web"]["A"] == {
        "cleared": 5,
        "flagged": 1,
        "no_verdict": 0,
        "failed_run": 0,
    }
    assert r["outcomes"]["api"]["C"]["failed_run"] == 1
    assert r["group_s"]["web"] == {"caught": 1, "missed": 1, "no_verdict": 0, "failed_run": 0}
    assert r["group_s"]["api"] == {"caught": 2, "missed": 0, "no_verdict": 0, "failed_run": 0}
    assert r["false_sanction_flags"]["web"] == {"k": 1, "n": 18}  # ie-03 r2
    assert r["flips"]["web"]["k"] == 3 and r["flips"]["web"]["n"] == 9
    assert r["flips"]["api"]["k"] == 2 and r["flips"]["api"]["n"] == 9
    # every API run but lv-01 r1 (null) and the failed lv-03 r2 says not sanctioned
    assert r["exact"]["api"]["sanctioned"] == {"k": 16, "n": 18}
    assert "all_three" in r["exact"]["web"] and "rule" not in r["exact"]
    assert r["per_country"]["web"]["GB"] == {"k": 4, "n": 6}
    f = r["failed_runs"]
    assert f["web"]["runs_without_an_answer"] == 1 and f["web"]["retries"] == 2
    assert f["web"]["invalid_reasons"] == {"timeout": 3}
    assert f["api"]["invalid_reasons"] == {"api_http_503": 3}
    assert r["cost"]["api"]["usd_api_fee"] > 0 and r["cost"]["web"]["searches"] > 0


def test_memory_and_rule_arms():
    r = report()
    memory, rule = r["controls"]["memory"], r["controls"]["rule"]
    # Memory, replicate 1 only: A right for gb-01 and lv-01; nothing right in B and C
    assert memory["headline"] == pytest.approx(100 * (2 / 3) / 3)
    # Rule: every pass / fail read right except ie-03 r1 (unverified) and lv-03 r2 (failed run)
    assert rule["group_means"] == pytest.approx({"A": 1.0, "B": 1.0, "C": 2 / 3})
    assert rule["headline"] == pytest.approx(100 * 8 / 9)
    assert analyze.rule_verdicts(
        [
            {"check": "register_status", "status": "review"},
            {"check": "insolvency", "status": "pass"},
        ],
        CFG["rule_arm"],
    ) == {"register": "none", "sanctions": "none"}


def test_the_named_checks():
    c = report()["checks"]
    assert c["first_replicate_only"]["diff"] == pytest.approx(100 / 9)
    # without failed runs: lv-02 keeps replicate 2 only (diff 0), lv-03 replicate 1 only (0)
    # A (0, .5, -.5) B (1, 0, 0) C (0, .5, 0) -> (0 + 1/3 + 1/6) / 3
    assert c["without_failed_runs"]["diff"] == pytest.approx(100 / 6)
    # UK and Latvia: A (0, -.5) B (1, .5) C (0, -.5) -> (-1/4 + 3/4 - 1/4) / 3
    assert c["uk_and_latvia_only"]["diff"] == pytest.approx(100 / 12)
    # every web and API run answered sanctions, so leaving it out of group A changes nothing
    assert c["group_a_without_sanctions"]["diff"] == pytest.approx(100 / 6)
    assert c["all_drawn_companies_no_exclusions"]["diff"] == pytest.approx(100 / 6)
    assert c["without_runs_that_had_a_tool_error"]["diff"] == pytest.approx(100 / 6)


def test_exclusions_are_listed_and_every_company_is_in_the_table():
    t2 = copy.deepcopy(TRUTH2)
    row = next(r for r in t2["companies"] if r["id"] == "ie-799001")
    row["truth2"]["status"] = "winding_up"
    row |= {"changed": True, "why": "status changed"}
    audit = copy.deepcopy(AUDIT)
    next(r for r in audit["rows"] if r["id"] == "gb-09900002")["agrees"] = False
    s = copy.deepcopy(SET)
    extra = copy.deepcopy(s["companies"][0]) | {"id": "gb-09999999", "number": "09999999"}
    s["companies"].append(extra)
    # the extra company never ran: the spend cap dropped it in both replicates
    caps = [
        {"v": 1, "type": "cap_stop", "replicate": rep, "dropped": ["gb-09999999"]} for rep in (1, 2)
    ]
    r = report(lines=[*LINES, *caps], set_file=s, truth2=t2, audit=audit)
    assert set(r["excluded"]) == {"ie-799001", "gb-09900002", "gb-09999999"}
    assert "register facts changed" in r["excluded"]["ie-799001"]
    assert "hand check" in r["excluded"]["gb-09900002"]
    assert "no complete Web and API pair" in r["excluded"]["gb-09999999"]
    assert r["companies"]["analysed"] == 8 and r["headline"]["n"] == {"A": 2, "B": 2, "C": 3}
    assert [c["id"] for c in r["per_company"]] == [c["id"] for c in s["companies"]]
    text = analyze.markdown(r, CFG)
    for c in s["companies"]:
        assert f"| {c['id']} |" in text


def test_the_same_numbers_from_the_public_file_alone(tmp_path):
    public = prereg.public_jsonl(LINES)
    path = tmp_path / "runs_public.jsonl"
    path.write_text(public, encoding="utf-8")
    from_public = report(lines=lib.read_journal(path))
    assert from_public == report()


def test_dry_run_prints_and_writes_nothing(tmp_path, capsys):
    paths = make_root(tmp_path)
    before = sorted(p for p in paths.root.rglob("*") if ".git" not in p.parts)
    assert analyze.main(["--dry-run"], root=paths.root) == 0
    out = capsys.readouterr().out
    assert "## Headline" in out and "+16.7 points" in out and "nothing written" in out
    assert "## Every company" in out and "gb-09900004" in out
    assert sorted(p for p in paths.root.rglob("*") if ".git" not in p.parts) == before


def test_a_report_is_written_from_a_public_journal(tmp_path):
    paths = make_root(tmp_path)
    lib.write_json(paths.set, SET)
    out = paths.report_dir(SET["seed"])
    out.mkdir(parents=True)
    (out / "runs_public.jsonl").write_text(prereg.public_jsonl(LINES), encoding="utf-8")
    (out / "truth2.json").write_bytes((FX / "truth2.json").read_bytes())
    lib.write_json(paths.audit, AUDIT)
    assert analyze.main([], root=paths.root) == 0
    assert lib.read_json(out / "report.json")["headline"]["diff"] == pytest.approx(100 / 6)
    assert "Preliminary" not in (out / "report.md").read_text(encoding="utf-8")


def test_rule_reads_an_api_answer_whose_model_call_failed():
    lines = copy.deepcopy(LINES)
    good = next(x for x in lines if x.get("run_id") == "gb-09900003|api|r1")
    good |= {"valid": False, "invalid_reason": "max_tokens", "answer": None}
    for n in (2, 3):  # two more attempts: the API answered, the model ran out of tokens
        lines.append(good | {"attempt": n})
    runs = analyze.build_runs(lines, SET["companies"], CFG)
    assert runs[("gb-09900003", "api", 1)]["outcome"] == "failed_run"
    assert runs[("gb-09900003", "rule", 1)]["outcome"] == "caught"
    # a 5xx is no answer: Rule has nothing to read either
    assert runs[("lv-40103999003", "rule", 2)]["outcome"] == "failed_run"


# --- review fixes: what may leave the analysis, and how ---------------------------------------


def _with(lines, run_id, **change):
    """The journal with every attempt of one run replaced by `change` (one attempt each)."""
    out = [x for x in copy.deepcopy(lines) if x.get("run_id") != run_id]
    base = next(x for x in lines if x.get("run_id") == run_id)
    return out + [base | change]


def test_unfinished_runs_block_the_headline_unless_the_cap_dropped_them():
    # the reviewer's case: two Web runs of replicate 1 stopped after 2 invalid attempts
    lines = copy.deepcopy(LINES)
    for cid in ("gb-09900001", "ie-799001"):
        rid = f"{cid}|web|r1"
        first = next(x for x in lines if x.get("run_id") == rid)
        lines = [x for x in lines if x.get("run_id") != rid]
        bad = first | {"valid": False, "invalid_reason": "timeout", "answer": None}
        lines += [bad, bad | {"attempt": 2}]
    r = report(lines=lines)
    assert r["headline"] is None and "2 runs are unfinished" in r["note"]
    assert r["unfinished_runs"] == ["gb-09900001|web|r1", "ie-799001|web|r1"]
    assert "No headline: 2 runs are unfinished" in analyze.markdown(r, CFG)
    # the spend cap is the one allowed way to leave runs open (protocol section 6)
    stop = {"v": 1, "type": "cap_stop", "replicate": 1, "dropped": ["gb-09900001", "ie-799001"]}
    r = report(lines=[*lines, stop])
    assert r["unfinished_runs"] == [] and r["headline"] is not None
    # a replicate that has not started is a missing replicate, not unfinished runs
    r = report(lines=[x for x in LINES if not str(x.get("run_id", "")).endswith("|r2")])
    assert r["unfinished_runs"] == [] and "a replicate is missing" in r["verdict"]["why"]


def test_exclusions_come_from_the_second_read_values_not_the_flag():
    t2 = copy.deepcopy(TRUTH2)
    row = next(r for r in t2["companies"] if r["id"] == "gb-09900001")
    row |= {"changed": True, "why": "edited by hand"}  # values unchanged
    r = report(truth2=t2)
    assert "gb-09900001" not in r["excluded"] and r["truth2_flag_mismatch"] == ["gb-09900001"]
    assert "does not match the values" in analyze.markdown(r, CFG)
    t2 = copy.deepcopy(TRUTH2)
    row = next(r for r in t2["companies"] if r["id"] == "gb-09900002")
    row["truth2"]["group"] = None  # the facts are now skipped: a change, even with the flag off
    r = report(truth2=t2)
    assert "group B -> None" in r["excluded"]["gb-09900002"]
    assert r["truth2_flag_mismatch"] == ["gb-09900002"]


def test_too_many_exclusions_after_the_runs_force_no_difference():
    audit = copy.deepcopy(AUDIT)
    next(r for r in audit["rows"] if r["id"] == "gb-09900002")["agrees"] = False
    r = report(audit=audit)
    x = r["excluded_after_runs"]
    assert (x["abc"], x["abc_drawn"], x["over_limit"]) == (1, 9, True)  # 11% > 10%
    assert r["verdict"]["name"] == "no_difference"
    assert r["verdict"]["why"][0].startswith("more companies were excluded after the runs")
    # the check on every drawn company is printed beside it
    assert r["checks"]["all_drawn_companies_no_exclusions"]["diff"] == pytest.approx(100 / 6)
    assert not report()["excluded_after_runs"]["over_limit"]


def test_group_a_without_sanctions_shows_a_web_arm_that_cannot_prove_a_negative():
    lines = copy.deepcopy(LINES)
    for x in lines:
        if x.get("answer") and x["run_id"].split("|")[1] == "web":
            x["answer"]["sanctioned"] = None  # "my sources do not establish it"
    r = report(lines=lines)
    # Web group A drops to 0 in the headline; on register facts alone it is 5/6 as before
    assert r["headline"]["group_means"]["web"]["A"] == 0
    assert r["checks"]["group_a_without_sanctions"]["web"] == pytest.approx(100 * 13 / 18)
    assert analyze.register_only("A", {"register": "clear", "sanctions": "none"})
    assert not analyze.register_only("A", None)


def test_runs_with_a_tool_error_are_left_out_by_their_check():
    lines = copy.deepcopy(LINES)
    rid = "ie-799001|web|r2"  # web was wrong here; with the run left out ie-799001 has r1 only
    for x in lines:
        if x.get("run_id") == rid:
            x["tool_errors"] = [{"tool": "web_fetch", "error_code": "url_not_accessible"}]
    c = report(lines=lines)["checks"]["without_runs_that_had_a_tool_error"]
    # A (0, 0, -.5) B (1, 0, .5) C (0, .5, -.5) -> (-1/6 + 1/2 + 0) / 3
    assert c["diff"] == pytest.approx(100 / 9)


def test_the_standard_error_of_a_one_company_group_is_unknown():
    assert analyze.se_interval({"A": [0.5], "B": [1, 0], "C": [0, 1]}, CFG) is None
    v = analyze.verdict({}, (5, 20), None, {1: {"diff": 3}, 2: {"diff": 4}}, CFG)
    assert v["name"] == "no_difference"
    assert v["why"] == ["a group has fewer than two companies, so the standard error is unknown"]
    keep = {"gb-09900001", "gb-09900002", "gb-09900003", "ie-799001", "ie-799002"}
    s = copy.deepcopy(SET)
    s["companies"] = [c for c in s["companies"] if c["id"] in keep]
    r = report(set_file=s)
    assert r["headline"]["se_interval"] is None and r["headline"]["standard_error"] is None
    text = analyze.markdown(r, CFG)
    assert "n/a (a group has one company)" in text


def test_a_paid_product_call_of_an_aborted_attempt_is_counted():
    fee = {"model": 0.0, "search": 0.0, "api": 0.05, "total": 0.05}
    lost = {"v": 1, "type": "attempt_aborted", "run_id": "gb-09900001|api|r1", "usd": fee}
    before, after = report()["cost"]["api"], report(lines=[*LINES, lost])["cost"]["api"]
    assert after["usd"] == pytest.approx(before["usd"] + 0.05)
    assert after["aborted_api_calls"] == 1 and after["attempts"] == before["attempts"]
    assert lib.spent_usd([*LINES, lost]) == pytest.approx(lib.spent_usd(LINES) + 0.05)


def test_sanctions_name_skips_are_counted_per_cell():
    skips = {
        "skips": [
            {"cell": "GB/A", "reason": "sanctions_name"},
            {"cell": "GB/A", "reason": "sanctions_name"},
            {"cell": "LV/B", "reason": "sanctions_name"},
            {"cell": "LV/B", "reason": "pilot"},
        ]
    }
    r = analyze.analyse(LINES, SET, TRUTH2, AUDIT, CFG, skips)
    assert r["sanctions_name_skips"] == {"GB/A": 2, "LV/B": 1}
    assert "GB/A 2, LV/B 1" in analyze.markdown(r, CFG)


def test_a_removed_attempt_is_seen():
    lines = [
        x for x in LINES if not (x.get("run_id") == "lv-40103999002|web|r1" and x["attempt"] == 2)
    ]
    assert "attempt numbers have a gap" in analyze.journal_problems(lines, strict=False)[0]
    end = {"v": 1, "type": "end", "replicate": 2, "attempt_lines": 55}
    got = analyze.journal_problems([*LINES, end], strict=False)
    assert got == ["line 59: the end line counts 55 attempt lines before it, the journal has 54"]
    assert analyze.journal_problems(LINES, strict=True)  # the fixture's end lines lack the count
