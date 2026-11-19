"""Benchmark 2, the pre-registration: freeze, verify and the public export. Offline."""

import json
import shutil
from datetime import timedelta

import pytest
from test_bench2_kit import (
    NOW,
    REPO,
    ROUND_TIME,
    complete_truth_map,
    drawn_root,
    freeze,
    lib,
    make_root,
    prereg,
    write_frames,
    write_pilot_journal,
)

FIXTURES = REPO / "tests/fixtures/bench2"


def test_manifest_round_trip_and_one_changed_byte(tmp_path):
    paths = make_root(tmp_path)
    pre = freeze(paths)
    assert lib.verify_prereg(paths) == []
    assert prereg.main(["verify"], root=paths.root) == 0
    man = pre["manifest"]
    assert pre["bundle_hash"] == lib.bundle_hash(man) and len(pre["bundle_hash"]) == 64
    for name in (
        "docs/benchmark2/PROTOCOL.md",
        "data/benchmark2/config.json",
        "data/benchmark2/truth_map.json",
        "data/benchmark2/frames.json",
        "tools/bench2_run.py",
        "tools/bench2_analyze.py",
        "tests/test_bench2_run.py",
    ):
        assert man[name] == lib.sha256_norm(paths.root / name)
    assert man["prereg:settings"] == lib.settings_hash(pre["settings"])
    assert pre["settings"]["group_size"] == 30 and pre["settings"]["api_commit"] == "abc1234"
    assert pre["settings"]["countries"] == ["GB", "IE", "LV"]
    # CRLF on a Windows checkout changes nothing
    script = paths.root / "tools/bench2_analyze.py"
    script.write_bytes(script.read_bytes().replace(b"\n", b"\r\n"))
    assert lib.verify_prereg(paths) == []
    # one byte anywhere in the bundle does
    protocol = paths.protocol.read_bytes()
    paths.protocol.write_bytes(protocol.replace(b"30", b"31", 1))
    assert lib.verify_prereg(paths) == ["changed since the freeze: docs/benchmark2/PROTOCOL.md"]
    assert prereg.main(["verify"], root=paths.root) == 1
    paths.protocol.write_bytes(protocol)
    # and so does a changed frozen number, even with the hashes recomputed around it
    p = lib.read_json(paths.prereg)
    p["settings"]["group_size"] = 25
    lib.write_json(paths.prereg, p)
    assert "changed since the freeze: prereg:settings" in lib.verify_prereg(paths)
    # an added test file is a change to the bundle too
    lib.write_json(paths.prereg, pre)
    (paths.root / "tests/test_bench2_extra.py").write_text("x = 1\n", encoding="utf-8")
    assert lib.verify_prereg(paths) == [
        "added or removed since the freeze: tests/test_bench2_extra.py"
    ]


def test_round_arithmetic():
    g, p = 1692803367, 3
    assert lib.round_for(lib.round_time(1, g, p), g, p) == 1
    assert lib.round_time(1, g, p).timestamp() == g
    assert lib.round_for(lib.round_time(1, g, p) + timedelta(seconds=1), g, p) == 2
    assert lib.round_for(lib.round_time(1000, g, p), g, p) == 1000
    r = lib.round_for(ROUND_TIME, g, p)
    assert lib.round_time(r, g, p) >= ROUND_TIME > lib.round_time(r - 1, g, p)


def test_freeze_refusals(tmp_path):
    paths = make_root(tmp_path, prices_checked=False)
    args = ["freeze", "--round-time", lib.iso(NOW + timedelta(hours=23)), "--api-commit", "abc"]
    with pytest.raises(prereg.Refused) as e:
        prereg.main(args, root=paths.root, now=NOW)
    why = str(e.value)
    assert "at least 24 h away" in why
    assert "price input: fill in source and checked" in why
    assert "frames.json is missing" in why and "no pilot journal" in why
    assert not paths.prereg.exists()
    # a probed status the table does not know
    write_frames(paths)
    write_pilot_journal(paths)
    args[2] = lib.iso(ROUND_TIME)
    with pytest.raises(prereg.Refused, match="no entry for IE status: receivership"):
        prereg.main(args, root=paths.root, now=NOW)
    complete_truth_map(paths)
    # no group size fits the budget: the study is not run
    shutil.rmtree(paths.pilot_journal.parent)
    write_pilot_journal(paths, web=0.5)
    with pytest.raises(prereg.Refused, match="no group size fits"):
        prereg.main(args, root=paths.root, now=NOW)
    assert not paths.prereg.exists()


def test_group_size_follows_the_pilot(tmp_path):
    paths = make_root(tmp_path)
    complete_truth_map(paths)
    write_frames(paths)
    write_pilot_journal(paths, web=0.2, api=0.07, memory=0.01)  # 102 x $0.55 = $56.1: over $50
    args = ["freeze", "--round-time", lib.iso(ROUND_TIME), "--api-commit", "abc"]
    assert prereg.main(args, root=paths.root, now=NOW) == 0
    pre = lib.read_json(paths.prereg)
    assert pre["settings"]["group_size"] == 25 and pre["pilot"]["measured"] is True
    assert pre["projected_usd"] == {"30": 56.1, "25": 47.85, "20": 39.6}
    d = pre["drand"]
    assert pre["settings"]["round"] == lib.round_for(ROUND_TIME, d["genesis_time"], d["period"])


def test_freeze_dry_run_writes_nothing(tmp_path, capsys):
    paths = make_root(tmp_path)
    args = ["freeze", "--round-time", lib.iso(ROUND_TIME), "--dry-run"]
    assert prereg.main(args, root=paths.root, now=NOW) == 0
    assert "would refuse" in capsys.readouterr().out and not paths.prereg.exists()


def test_freeze_refuses_after_a_drift_of_the_beacon(tmp_path):
    paths = make_root(tmp_path)
    complete_truth_map(paths)
    write_frames(paths)
    write_pilot_journal(paths)
    frames = lib.read_json(paths.frames)
    frames["drand"]["period"] = 30
    lib.write_json(paths.frames, frames)
    args = ["freeze", "--round-time", lib.iso(ROUND_TIME), "--api-commit", "abc"]
    with pytest.raises(prereg.Refused, match="drand period: config says 3, the beacon 30"):
        prereg.main(args, root=paths.root, now=NOW)


def test_export_keeps_no_text_queries_body_or_people(tmp_path, capsys):
    paths = drawn_root(tmp_path)
    seed = lib.read_json(paths.set)["seed"]
    paths.journal(seed).parent.mkdir(parents=True)
    shutil.copyfile(FIXTURES / "runs.jsonl", paths.journal(seed))
    assert prereg.main(["export", "--dry-run"], root=paths.root) == 0
    assert not paths.report_dir(seed).exists()
    assert prereg.main(["export"], root=paths.root) == 0
    out = paths.report_dir(seed)
    public = (out / "runs_public.jsonl").read_text(encoding="utf-8")
    for banned in (
        '"final_text"',
        '"search_queries"',
        '"body"',
        '"people"',
        "A Fixture Person",
        "Checked the register",
    ):
        assert banned not in public, banned
    lines = [json.loads(x) for x in public.splitlines()]
    private = lib.read_journal(paths.journal(seed))
    assert len(lines) == len(private)
    for pub, priv in zip(lines, private, strict=True):
        if "attempt" not in priv:
            assert pub == priv
            continue
        assert pub["answer"] == priv["answer"] and pub["usd"] == priv["usd"]
        assert pub["final_text_sha256"] == lib.sha256_text(priv["final_text"] or "")
        assert pub["search_queries_count"] == len(priv["search_queries"])
        if priv["api"]:
            checks = [c["check"] for c in priv["api"].get("checks") or []]
            assert [c["check"] for c in pub["api"]["checks"]] == checks
            assert pub["api"].get("body_sha256") == priv["api"].get("body_sha256")
    readme = (out / "README.md").read_text(encoding="utf-8")
    assert "Open Government Licence" in readme and "CC BY 4.0" in readme and "CC0" in readme
    assert (out / "set.json").read_bytes() == paths.set.read_bytes()
    assert (out / "audit.json").is_file() and (out / "prereg.json").is_file()


def test_public_line_refuses_a_leak():
    line = {
        "run_id": "x|api|r1",
        "attempt": 1,
        "final_text": "t",
        "search_queries": ["q"],
        "api": {"body": {}, "checks": [], "extra": {"people": ["n"]}},
    }
    with pytest.raises(prereg.Refused, match="still holds"):
        prereg.public_jsonl([line])


def test_freeze_time_and_pilot_figures_are_hashed_and_consistent(tmp_path):
    """The reviewer's case: frozen_at sets the reference date of group C's window, and the pilot
    means set the group size. Both are in the hashed settings now, and verify checks that they
    agree with each other even when every hash is recomputed around a change."""
    paths = make_root(tmp_path)
    pre = freeze(paths)
    s = pre["settings"]
    assert s["frozen_at"] == pre["frozen_at"] == lib.iso(NOW)
    assert s["reference_date"] == "2026-11-12"
    assert s["pilot"]["mean_usd_per_run"] == {"web": 0.15, "api": 0.07, "memory": 0.01}
    assert s["projected_usd"] == pre["projected_usd"]

    def tamper(change, rehash):
        p = json.loads(json.dumps(pre))
        change(p)
        if rehash:  # a tamperer who also recomputes the manifest and the bundle hash
            p["manifest"] = lib.manifest(paths, p["settings"])
            p["bundle_hash"] = lib.bundle_hash(p["manifest"])
        lib.write_json(paths.prereg, p)
        return lib.verify_prereg(paths)

    def later(p):
        p["settings"]["frozen_at"] = p["frozen_at"] = "2030-01-01T00:00:00Z"

    assert "changed since the freeze: prereg:settings" in tamper(later, rehash=False)
    got = tamper(later, rehash=True)
    assert any("less than 24 h before the round" in x for x in got)
    assert any("reference_date is not the date" in x for x in got)

    def top_only(p):
        p["frozen_at"] = "2026-11-01T00:00:00Z"

    assert tamper(top_only, rehash=False) == ["frozen_at differs from settings.frozen_at"]

    def cheaper(p):
        p["settings"]["pilot"]["mean_usd_per_run"]["web"] = 0.01

    assert any("does not follow from the pilot means" in x for x in tamper(cheaper, rehash=True))
    lib.write_json(paths.prereg, pre)
    assert lib.verify_prereg(paths) == []
    # the pilot journal the means came from is checked when it is on disk
    lib.Journal(paths.pilot_journal).append({"v": 1, "type": "note"})
    assert lib.verify_prereg(paths) == [
        "the pilot journal differs from the one the group size came from"
    ]
