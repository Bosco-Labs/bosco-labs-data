"""Benchmark 2, shared helpers: hashing, seed and keys, answers and decisions, the journal."""

import json
from datetime import UTC, datetime

import pytest
from test_bench2_kit import lib


def test_crlf_and_lf_hash_the_same(tmp_path):
    (tmp_path / "unix.txt").write_bytes(b"a\nb\n")
    (tmp_path / "windows.txt").write_bytes(b"a\r\nb\r\n")
    assert lib.sha256_norm(tmp_path / "unix.txt") == lib.sha256_norm(tmp_path / "windows.txt")
    assert lib.sha256_norm(tmp_path / "unix.txt") == lib.sha256_bytes(b"a\nb\n")


def test_seed_and_key_vectors():
    # sha256("bundle:rand"), sha256("s|GB|01234567"), sha256("s|order|r1|gb-01234567")
    assert lib.seed("bundle", "rand") == (
        "caf53829a04926dd5f6bf3ae976d0c142f331ed146faba2ced1ee467f4c15102"
    )
    assert lib.key("s", "GB", "01234567") == (
        "75bc339b8077b64700edee40223749a18bb0adc72fb9c928e487bba77a554fdc"
    )
    assert lib.key("s", "order", "r1", "gb-01234567") == (
        "32aeeafff29e249a4c470b05f1036a29b8f82a42b151ff7f98e301d6910e8853"
    )


def test_rank_does_not_move_when_a_frame_gains_a_row():
    numbers = [f"{n:08d}" for n in range(1, 400)]
    before = sorted(numbers, key=lambda n: lib.key("seed", "GB", n))
    after = sorted([*numbers, "99999999"], key=lambda n: lib.key("seed", "GB", n))
    assert [n for n in after if n != "99999999"] == before  # a key depends on its own row only


def test_parse_answer_nested_last_and_none():
    nested = 'So: {"status": "dissolved", "why": {"status": "inner", "n": [1, {"a": 2}]}}'
    assert lib.parse_answer(nested)["why"] == {"status": "inner", "n": [1, {"a": 2}]}
    assert lib.parse_answer(nested)["status"] == "dissolved"  # not the object inside it
    text = 'Draft {"status": "active"} then {"note": 1} final:\n{"status": "winding_up"}'
    assert lib.parse_answer(text) == {"status": "winding_up"}
    assert lib.parse_answer('{"status": "active"} and then {"status": "x", broken') == {
        "status": "active"
    }
    for nothing in ("no json here", '{"foo": 1} {bad json}', "", None, "[1, 2]"):
        assert lib.parse_answer(nothing) is None


TABLE = [
    # answer, register, sanctions, A right, B right, A outcome, B outcome
    (("active", False, False), "clear", "clear", True, False, "cleared", "false_all_clear"),
    (("active", False, None), "clear", "none", False, False, "no_verdict", "false_all_clear"),
    (("active", False, True), "clear", "problem", False, False, "false_alarm", "false_all_clear"),
    (("active", None, False), "none", "clear", False, False, "no_verdict", "no_verdict"),
    (("active", True, False), "problem", "clear", False, True, "false_alarm", "caught"),
    (("winding_up", None, False), "problem", "clear", False, True, "false_alarm", "caught"),
    (("dissolved", False, False), "problem", "clear", False, True, "false_alarm", "caught"),
    (("unknown", None, None), "none", "none", False, False, "no_verdict", "no_verdict"),
    (("unknown", True, None), "problem", "none", False, True, "false_alarm", "caught"),
    (("Active ", False, False), "clear", "clear", True, False, "cleared", "false_all_clear"),
    (("inactive", "no", "no"), "none", "none", False, False, "no_verdict", "no_verdict"),
]


@pytest.mark.parametrize("row", TABLE)
def test_verdict_correct_and_outcome_table(row):
    (status, insolvent, sanctioned), register, sanctions, a_ok, b_ok, a_out, b_out = row
    v = lib.verdicts({"status": status, "insolvent": insolvent, "sanctioned": sanctioned})
    assert v == {"register": register, "sanctions": sanctions}
    assert (lib.correct("A", v), lib.correct("B", v), lib.correct("C", v)) == (a_ok, b_ok, b_ok)
    assert (lib.outcome("A", v), lib.outcome("B", v), lib.outcome("C", v)) == (a_out, b_out, b_out)
    assert lib.correct("S", v) == (sanctions == "problem")
    want = {"problem": "caught", "clear": "false_all_clear", "none": "no_verdict"}[sanctions]
    assert lib.outcome("S", v) == want


def test_no_answer_is_no_verdict():
    v = lib.verdicts(None)
    assert v == {"register": "none", "sanctions": "none"}
    assert not lib.correct("A", v) and not lib.correct("B", v)


def test_wilson():
    lo, hi = lib.wilson(5, 10)
    assert (round(lo, 4), round(hi, 4)) == (0.2366, 0.7634)
    assert lib.wilson(0, 12)[0] == 0.0 and round(lib.wilson(0, 12)[1], 4) == 0.2425
    assert round(lib.wilson(12, 12)[0], 4) == 0.7575
    assert lib.wilson(0, 0) == (0.0, 1.0)


def test_round_arithmetic():
    genesis, period = 1692803367, 3
    at = lambda s: datetime.fromtimestamp(s, UTC)  # noqa: E731
    assert lib.round_for(at(genesis), genesis, period) == 1
    assert lib.round_for(at(genesis + 1), genesis, period) == 2  # the first round not before it
    assert lib.round_for(at(genesis + 3), genesis, period) == 2
    assert lib.round_for(at(genesis + 4), genesis, period) == 3
    r = lib.round_for(lib.parse_time("2026-11-14T12:00:00Z"), genesis, period)
    assert r == 33951412
    assert lib.round_time(r, genesis, period) == lib.parse_time("2026-11-14T12:00:00Z")
    assert lib.round_time(r, genesis, period) >= lib.parse_time("2026-11-14T12:00:00Z")


def test_journal_appends_and_survives_a_cut_off_line(tmp_path):
    j = lib.Journal(tmp_path / "deep" / "runs.jsonl")
    j.append({"run_id": "a|web|r1", "attempt": 1, "valid": False, "usd": {"total": 0.1}})
    j.append({"run_id": "a|web|r1", "attempt": 2, "valid": True, "usd": {"total": 0.2}, "t": "é"})
    raw = j.path.read_bytes()
    assert raw.count(b"\n") == 2 and b"\r" not in raw and "é".encode() in raw
    with j.path.open("ab") as f:
        f.write(b'{"run_id": "b|web|r1", "attem')  # a crash in the middle of a write
    lines = j.read()
    assert [x["attempt"] for x in lines] == [1, 2]
    runs = lib.attempts_by_run(lines)
    assert lib.run_state(runs["a|web|r1"], 3) == "valid"
    assert lib.run_state([{"valid": False}] * 3, 3) == "failed"
    assert lib.run_state([{"valid": False}] * 2, 3) == "open" and lib.run_state([], 3) == "open"
    assert round(lib.spent_usd(lines), 2) == 0.3
    j.path.write_text('{"a": 1}\nnot json\n{"b": 2}\n', encoding="utf-8")
    with pytest.raises(ValueError, match="line 2"):
        j.read()


def test_normalise_name():
    tokens = ["sia", "sabiedrība ar ierobežotu atbildību", "ltd", "limited", "the", "co"]
    lv = 'Sabiedrība ar ierobežotu atbildību "Courland Venison"'
    assert lib.normalise_name(lv, tokens) == "courland venison"
    assert lib.normalise_name("COURLAND VENISON, SIA", tokens) == "courland venison"
    assert lib.normalise_name("Büvosta Ltd.", tokens) == "buvosta"
    assert lib.normalise_name("The Co Ltd", tokens) == ""  # only legal-form words: no name left
    assert lib.normalise_name(None, tokens) == ""


def test_env_file_and_cost(tmp_path, monkeypatch):
    env = tmp_path / "jobs.env"
    env.write_text('# note\nA_KEY="secret one"\nEMPTY=\nB_KEY=two\n', encoding="utf-8")
    assert lib.load_env(env) == {"A_KEY": "secret one", "B_KEY": "two"}
    monkeypatch.setenv("A_KEY", "already set")
    monkeypatch.delenv("B_KEY", raising=False)
    assert lib.apply_env(str(env)) == str(env)
    import os

    assert (os.environ["A_KEY"], os.environ["B_KEY"]) == ("already set", "two")
    prices = json.loads((lib.ROOT / "data/benchmark2/config.json").read_text("utf-8"))["prices"]
    usage = {
        "input_tokens": 1_000_000,
        "output_tokens": 100_000,
        "web_searches": 3,
        "cache_read_input_tokens": 2_000_000,
        "cache_creation_input_tokens": 400_000,
    }
    # 2.00 + 1.00 output + 0.20 cache read + 0.4 M * 2.0 * 1.25 cache write; 3 searches at 0.01
    assert lib.cost(usage, prices) == {"model": 4.2, "search": 0.03}
    per_run = {"web": 0.15, "api": 0.07, "memory": 0.01}
    assert round(lib.projected_usd(30, 12, per_run), 2) == 45.9
    lines = [
        {"run_id": "a|web|r0", "attempt": 1, "usd": {"total": 0.1}},
        {"run_id": "a|web|r0", "attempt": 2, "usd": {"total": 0.3}},
        {"run_id": "b|web|r0", "attempt": 1, "usd": {"total": 0.2}},
    ]
    assert lib.mean_cost_per_run(lines) == {"web": pytest.approx(0.3)}  # retries count
