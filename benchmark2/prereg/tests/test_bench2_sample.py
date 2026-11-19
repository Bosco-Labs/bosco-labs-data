"""Benchmark 2, the sampler: mapping table, sanctions parsers, the draw and its refusals.
Offline: the registers are served by test_bench2_kit.Registers from invented companies."""

import ast
import gzip
import json
from datetime import date, timedelta

import httpx
import pytest
from test_bench2_kit import (
    FRAMES,
    NOW,
    REPO,
    ROUND_TIME,
    Registers,
    analyze,
    commit,
    freeze,
    lib,
    make_root,
    sample,
)

CFG = lib.read_json(REPO / "data/benchmark2/config.json")
TM = lib.read_json(REPO / "data/benchmark2/truth_map.json")
REF = date(2026, 11, 11)
WINDOW = ("2024-11-11", "2026-11-11")


@pytest.fixture(autouse=True)
def no_waiting(monkeypatch):
    monkeypatch.setattr(sample, "SLEEP", lambda s: None)


def fixture_source(data=None):
    return sample.Fixture(None if data else FRAMES, TM, data)


def env_file(tmp_path, monkeypatch, key="ch-test-key"):
    monkeypatch.delenv("COMPANIES_HOUSE_API_KEY", raising=False)
    path = tmp_path / "keys.env"
    path.write_text(f"COMPANIES_HOUSE_API_KEY={key}\n", encoding="utf-8")
    return str(path)


def test_sampler_shares_nothing_with_the_product():
    tree = ast.parse((REPO / "tools/bench2_sample.py").read_text(encoding="utf-8"))
    modules = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom):
            modules.add((node.module or "").split(".")[0])
    assert modules <= {
        "argparse",
        "csv",
        "gzip",
        "heapq",
        "io",
        "json",
        "os",
        "re",
        "sys",
        "time",
        "xml",
        "zipfile",
        "collections",
        "datetime",
        "pathlib",
        "bench2_lib",
        "httpx",
    }
    strings = [
        n.value.lower()
        for n in ast.walk(tree)
        if isinstance(n, ast.Constant) and isinstance(n.value, str)
    ]
    for banned in ("boscolabs", "bosco_api", "counterparty-check", "importlib", "/actors/"):
        assert not any(banned in s for s in strings), banned
    assert "__import__" not in {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}


def gb_record(number):
    return fixture_source().record("GB", number)["facts"]


def frame_facts(country, number):
    return next(f for f in fixture_source().frame(country) if f["number"] == number)


MAPPING = [
    # facts, group, status, insolvent
    (lambda: gb_record("09100001"), "A", "active", False),
    (lambda: gb_record("09100003"), "B", "winding_up", True),  # creditors' voluntary liquidation
    (lambda: gb_record("09101003"), "B", "winding_up", True),  # administration
    (lambda: gb_record("09100009"), "B", "winding_up", False),  # members' voluntary: solvent
    (lambda: gb_record("09100004"), "C", "dissolved", False),  # struck off, no case
    (lambda: gb_record("09101004"), "C", "dissolved", True),  # after a compulsory liquidation
    (lambda: frame_facts("IE", "700001"), "A", "active", False),  # "Normal " with a space
    (lambda: frame_facts("IE", "700011"), "B", "winding_up", None),
    (lambda: frame_facts("IE", "700021"), "C", "dissolved", None),
    (lambda: frame_facts("IE", "700031"), "C", "dissolved", None),  # struck off: status date
    (lambda: frame_facts("LV", "40103000001"), "A", "active", False),
    (lambda: frame_facts("LV", "40103000006"), "B", "winding_up", None),  # liquidation entry
    (lambda: frame_facts("LV", "40103000008"), "B", "winding_up", True),  # open insolvency
    (lambda: frame_facts("LV", "40103000012"), "C", "dissolved", None),
    (lambda: frame_facts("LV", "40103000013"), "C", "dissolved", True),  # insolvency before removal
    (lambda: frame_facts("EE", "14000001"), "A", "active", False),
    (lambda: frame_facts("EE", "14000011"), "B", "winding_up", None),
    (lambda: frame_facts("EE", "14000013"), "B", "winding_up", True),  # bankrupt
]


@pytest.mark.parametrize("case", MAPPING)
def test_mapping_from_register_rows(case):
    facts, group, status, insolvent = case
    f = facts()
    got = sample.classify(f, TM["countries"][f["country"]], WINDOW)
    assert got == {
        "group": group,
        "truth": {
            "status": status,
            "insolvent": insolvent,
            "sanctioned": False,
            "sanctions_lists": [],
        },
    }


SKIPPED = [
    (lambda: gb_record("09100005"), "skip", "legal_form"),  # a plc
    (lambda: gb_record("09100006"), "skip", "ambiguous"),  # proposal to strike off
    (lambda: gb_record("09101008"), "skip", "ambiguous"),  # insolvency history, active
    (lambda: gb_record("09101007"), "skip", "ambiguous"),  # receivership
    (lambda: gb_record("00000000"), "skip", "status_not_mapped"),  # not on the register
    (lambda: gb_record("09101005"), "out", "dissolved outside the window"),
    (lambda: frame_facts("IE", "700036"), "skip", "status_not_mapped"),  # unknown raw status
    (lambda: frame_facts("IE", "700033"), "skip", "ambiguous"),  # strike off listed
    (lambda: frame_facts("IE", "700035"), "skip", "ambiguous"),  # examinership
    (lambda: frame_facts("IE", "700034"), "skip", "legal_form"),  # a plc
    (lambda: frame_facts("IE", "700032"), "out", "dissolved outside the window"),
    (lambda: frame_facts("LV", "40103000017"), "skip", "legal_form"),  # IK: one person's business
    (lambda: frame_facts("LV", "40103000018"), "skip", "legal_form"),  # AS
    (lambda: frame_facts("LV", "40103000010"), "skip", "ambiguous"),  # legal protection
    (lambda: frame_facts("LV", "40103000011"), "skip", "ambiguous"),  # ended insolvency, active
    (lambda: frame_facts("LV", "40103000016"), "skip", "status_not_mapped"),  # reorganised
    (lambda: frame_facts("LV", "40103000019"), "skip", "status_not_mapped"),
    (lambda: frame_facts("LV", "40103000015"), "out", "dissolved outside the window"),
    (lambda: frame_facts("EE", "14000015"), "skip", "legal_form"),  # FIE: a sole trader
    (lambda: frame_facts("EE", "14000016"), "skip", "legal_form"),
]


@pytest.mark.parametrize("case", SKIPPED)
def test_skips_have_a_reason_from_the_fixed_list(case):
    facts, kind, reason = case
    f = facts()
    got = sample.classify(f, TM["countries"][f["country"]], WINDOW)
    assert got.get(kind) == reason and "group" not in got
    if kind == "skip":
        assert reason in TM["skip_reasons"]


def test_an_unknown_case_type_is_not_judged_by_hand():
    f = gb_record("09100003")
    f["cases"] = [{"type": "some-new-procedure", "dates": []}]
    got = sample.classify(f, TM["countries"]["GB"], WINDOW)
    assert got == {"skip": "status_not_mapped", "detail": "case type some-new-procedure"}
    f = gb_record("09100003") | {"cases": []}  # in liquidation, but the register shows no case
    assert sample.classify(f, TM["countries"]["GB"], WINDOW)["skip"] == "ambiguous"


def test_allocation_and_remainder():
    countries = ["GB", "IE", "LV", "EE"]
    even = sample.allocate("seed", "A", countries, 28)
    assert set(even.values()) == {7}
    got = sample.allocate("seed", "A", countries, 30)
    assert sum(got.values()) == 30 and sorted(got.values()) == [7, 7, 8, 8]
    order = sorted(countries, key=lambda c: lib.key("seed", "alloc", "A", c))
    assert [c for c in countries if got[c] == 8] == sorted(order[:2], key=countries.index)
    assert sample.allocate("seed", "C", ["GB", "IE", "LV"], 30) == {"GB": 10, "IE": 10, "LV": 10}
    # Estonia is out until its licence is confirmed, and never has a group C
    assert sample.enabled_countries(CFG) == ["GB", "IE", "LV"]
    with_ee = CFG | {"ee_licence_confirmed": {"checked": "2026-11-12"}}
    q = sample.quotas("seed", with_ee, 30)
    assert sum(v for (c, g), v in q.items() if g == "A") == 30 and ("EE", "C") not in q
    assert q[("EE", "A")] in (7, 8) and sum(v for (c, g), v in q.items() if g == "C") == 30
    pilot = sample.quotas("seed", CFG, 2)
    assert sum(pilot.values()) == 6 and set(pilot.values()) <= {0, 1}


def test_months_before():
    assert sample.months_before(date(2026, 11, 11), 24) == date(2024, 11, 11)
    assert sample.months_before(date(2024, 2, 29), 12) == date(2023, 2, 28)
    assert sample.months_before(date(2026, 1, 31), 2) == date(2025, 11, 30)


def uk_days(n_days):
    """Each day: two active, one in liquidation, one dissolved in the window."""
    gb = lib.read_json(FRAMES / "gb.json")
    return {
        "gb": {"any_day": gb["any_day"][:n_days], "companies": gb["companies"]},
        "sanctions": [],
    }


@pytest.mark.parametrize("minimum, maximum, days_read", [(2, 60, 5), (8, 60, 8), (2, 3, 3)])
def test_uk_dates_are_listed_in_hash_order_until_the_pool_is_full(minimum, maximum, days_read):
    cfg = CFG | {"uk_frame": CFG["uk_frame"] | {"min_dates": minimum, "max_dates": maximum}}
    source = fixture_source(uk_days(10))
    result = sample.draw_set(source, "seed-x", cfg, TM, 3, REF)
    # quota 1 per UK cell, so each cell needs 5: reached after the fifth day
    assert result["quotas"]["GB/A"] == result["quotas"]["GB/B"] == result["quotas"]["GB/C"] == 1
    assert source.days_read == sample.gb_dates("seed-x", cfg)[:days_read]
    assert result["skips"]["gb_dates"] == source.days_read
    dates = sample.gb_dates("seed-x", cfg)
    assert min(dates) == "2000-01-01" and max(dates) == "2025-10-31" and len(set(dates)) == 9436
    assert dates != sorted(dates) and dates != sample.gb_dates("seed-y", cfg)


def test_draw_takes_the_smallest_keys_and_logs_every_skip():
    # a quota no cell can fill, so every company of every cell is walked
    r = sample.draw_set(fixture_source(), "seed-1", CFG, TM, 90, REF)
    ids = {c["id"]: c for c in r["companies"]}
    per_cell = {}
    for c in r["companies"]:
        per_cell[(c["country"], c["group"])] = per_cell.get((c["country"], c["group"]), 0) + 1
    assert per_cell == {
        ("GB", "A"): 20,
        ("GB", "B"): 11,
        ("GB", "C"): 10,
        ("GB", "S"): 1,
        ("IE", "A"): 6,
        ("IE", "B"): 3,
        ("IE", "C"): 4,
        ("LV", "A"): 5,
        ("LV", "B"): 4,
        ("LV", "C"): 3,
        ("LV", "S"): 1,
    }
    skips = {(s["number"], s["reason"]) for s in r["skips"]["skips"]}
    assert skips == {
        ("09100006", "ambiguous"),
        ("09101008", "ambiguous"),
        ("09101006", "ambiguous"),  # listed as active, the record says dissolved
        ("09100007", "sanctions_name"),
        ("09100008", "sanctions_name"),
        ("40103000020", "sanctions_name"),
    }
    assert all(s["reason"] in TM["skip_reasons"] for s in r["skips"]["skips"])
    out = r["skips"]["not_in_a_cell"]
    assert out["GB"] == {
        "ambiguous: receivership": 1,
        "dissolved outside the window": 1,
        "legal_form": 1,
    }
    assert out["IE"]["status_not_mapped: receivership"] == 1 and out["IE"]["legal_form"] == 1
    assert out["LV"]["legal_form"] == 2  # the sole trader is counted, never listed by name
    assert "Paraugs" not in json.dumps(r["skips"], ensure_ascii=False)
    assert r["skips"]["shortfalls"]["GB/A"] == {"quota": 30, "drawn": 20, "keys_walked": 25}
    # a smaller draw is the head of the same ranking
    small = sample.draw_set(fixture_source(), "seed-1", CFG, TM, 3, REF)
    for cell in (("GB", "A"), ("IE", "B"), ("LV", "C")):
        ranked = sorted(
            (c for c in r["companies"] if (c["country"], c["group"]) == cell),
            key=lambda c: c["key"],
        )
        mine = [c["id"] for c in small["companies"] if (c["country"], c["group"]) == cell]
        assert mine == [ranked[0]["id"]]
        assert ranked[0]["key"] == lib.key("seed-1", cell[0], ranked[0]["number"])
    up = r["skips"]["runner_up"]["GB/A"]
    assert [x["key"] for x in up] == sorted(x["key"] for x in up) and len(up) == 25
    assert {x["fate"] for x in up} == {"selected", "skipped: ambiguous", "skipped: sanctions_name"}
    assert ids["gb-09100009"]["truth"]["insolvent"] is False
    assert ids["gb-09100009"]["legal_form"] == "ltd" and ids["gb-09100009"]["raw_status"] == (
        "liquidation"
    )


def test_group_s_needs_number_and_name_on_a_list():
    r = sample.draw_set(fixture_source(), "seed-1", CFG, TM, 3, REF)
    s = {c["id"]: c["truth"] for c in r["companies"] if c["group"] == "S"}
    assert s == {
        "gb-09100008": {
            "status": "active",
            "insolvent": False,
            "sanctioned": True,
            "sanctions_lists": ["UK"],
        },
        "lv-40103000020": {
            "status": "active",
            "insolvent": False,
            "sanctioned": True,
            "sanctions_lists": ["EU", "OFAC SDN"],
        },
    }
    assert r["skips"]["group_s"] == {"matched": 2, "drawn": 2, "beyond_the_cap": []}
    assert all(not c["truth"]["sanctioned"] for c in r["companies"] if c["group"] != "S")
    capped = sample.draw_set(fixture_source(), "seed-1", CFG | {"group_s_max": 1}, TM, 3, REF)
    assert capped["skips"]["group_s"]["drawn"] == 1
    assert len(capped["skips"]["group_s"]["beyond_the_cap"]) == 1
    # the number alone is not enough: same number, another name
    data = {k: lib.read_json(FRAMES / f"{k}.json") for k in ("gb", "ie", "lv", "sanctions")}
    for row in data["lv"]["register"]:
        if row["regcode"] == 40103000020:
            row["name"] = 'SIA "Pavisam cits nosaukums"'
    other = sample.draw_set(fixture_source(data), "seed-1", CFG, TM, 3, REF)
    assert [c["id"] for c in other["companies"] if c["group"] == "S"] == ["gb-09100008"]
    # a pilot company is passed over in the main draw, with that reason
    pilot = {c["id"] for c in r["companies"] if c["group"] != "S"}
    again = sample.draw_set(fixture_source(), "seed-1", CFG, TM, 3, REF, pilot)
    assert not pilot & {c["id"] for c in again["companies"]}
    assert sum(s["reason"] == "pilot" for s in again["skips"]["skips"]) >= len(pilot)


def test_the_three_list_parsers_keep_organisations_only():
    uk = sample.parse_uk((FRAMES / "uk.xml").read_bytes())
    ofac = sample.parse_ofac((FRAMES / "ofac.xml").read_bytes())
    eu = sample.parse_eu((FRAMES / "eu.xml").read_bytes())
    assert [o["name"] for o in uk] == ["VOLGA TRADE HOLDINGS LIMITED", "BALTIC SHADOW TRADING"]
    assert uk[0]["numbers"] == ["09100008 (UK company number)"] and uk[0]["countries"] == ["GB"]
    assert uk[0]["aliases"] == ["VOLGA TRADE", "Волга Трейд"]
    assert [o["name"] for o in ofac] == ["DAUGAVA SHADOW LOGISTICS SIA", "NORTHERN FIXTURE BANK"]
    assert ofac[0]["numbers"] == ["40103000020"]  # the website "id" is not a registration number
    assert ofac[0]["aliases"] == ["DAUGAVA SHADOW"] and ofac[0]["countries"] == ["LV"]
    assert [o["name"] for o in eu] == ["Daugava Shadow Logistics", "Northern Fixture Bank"]
    assert eu[0]["numbers"] == ["40103000020"] and eu[0]["countries"] == ["LV"]
    everything = json.dumps(uk + ofac + eu, ensure_ascii=False)
    for person_or_ship in ("Fixtureperson", "FIXTUREPERSON", "Vessel", "TANKER", "1970"):
        assert person_or_ship not in everything
    assert uk + ofac + eu == lib.read_json(FRAMES / "sanctions.json")  # what the dry runs use
    s = sample.Sanctions(uk + ofac + eu, TM["name_tokens"])
    assert s.lists_naming("Baltic Shadow Trading Ltd") == ["UK"]
    assert s.lists_naming('SIA "Daugava Shadow Logistics"') == ["EU", "OFAC SDN"]
    assert s.lists_naming("Baltic Shadow Trading Partners Ltd") == []
    assert s.lists_naming("Ltd") == []  # nothing but a legal form never matches
    numbers = s.number_candidates(["GB", "IE", "LV", "EE"])
    assert list(numbers["GB"]) == ["09100008"] and list(numbers["LV"]) == ["40103000020"]
    assert numbers["IE"] == {} and numbers["EE"] == {}


def test_draw_refuses_before_the_round_and_on_a_changed_frozen_file(tmp_path, monkeypatch):
    paths = make_root(tmp_path)
    env = env_file(tmp_path, monkeypatch)
    reg = Registers()
    with pytest.raises(sample.Refused, match="does not exist: nothing was frozen"):
        sample.main(["draw", "--env-file", env], paths.root, reg.client(), ROUND_TIME)
    freeze(paths)
    with pytest.raises(sample.Refused, match="wait"):
        early = ROUND_TIME - timedelta(seconds=1)
        sample.main(["draw", "--env-file", env], paths.root, reg.client(), early)
    with pytest.raises(sample.Refused, match="draw window closed"):
        late = ROUND_TIME + timedelta(hours=48, seconds=1)
        sample.main(["draw", "--env-file", env], paths.root, reg.client(), late)
    table = paths.truth_map.read_text(encoding="utf-8")
    paths.truth_map.write_text(table.replace('"normal"', '"normal "', 1), encoding="utf-8")
    with pytest.raises(sample.Refused, match="changed since the freeze: data/benchmark2/truth_map"):
        sample.main(["draw", "--env-file", env], paths.root, reg.client(), ROUND_TIME)
    paths.truth_map.write_text(table, encoding="utf-8")
    (paths.root / "tools/bench2_run.py").write_bytes(
        (paths.root / "tools/bench2_run.py").read_bytes().replace(b"\n", b"\r\n")
    )  # a Windows checkout: other bytes, same hash, but git sees a change
    with pytest.raises(sample.Refused, match="not committed as frozen: .*bench2_run.py"):
        sample.main(["draw", "--env-file", env], paths.root, reg.client(), ROUND_TIME)
    assert not reg.seen and not paths.set.exists()  # refused before any request


def test_the_one_draw_end_to_end(tmp_path, monkeypatch):
    paths = make_root(tmp_path)
    env = env_file(tmp_path, monkeypatch)
    pre = freeze(paths)
    reg = Registers()
    at = ROUND_TIME + timedelta(hours=2)
    assert sample.main(["draw", "--env-file", env], paths.root, reg.client(), at) == 0
    s = lib.read_json(paths.set)
    assert s["drand"]["round"] == pre["settings"]["round"] and s["drawn_at"] == lib.iso(at)
    assert s["seed"] == lib.seed(pre["bundle_hash"], s["drand"]["randomness"])
    assert s["bundle_hash"] == pre["bundle_hash"] and s["reference_date"] == "2026-11-12"
    assert s["freeze_commit"] == lib.commit_of(paths.root, paths.prereg)
    groups = [c["group"] for c in s["companies"]]
    assert groups.count("S") == 2 and groups.count("A") == 21 and groups.count("C") == 17
    for c in s["companies"]:
        assert set(c) == {
            "id",
            "country",
            "group",
            "number",
            "legal_name",
            "legal_form",
            "key",
            "raw_status",
            "truth",
            "evidence",
        }
        assert c["key"] == lib.key(s["seed"], c["country"], c["number"])
        assert all(
            e["url"].startswith("https://") and len(e["sha256"]) == 64 for e in c["evidence"]
        )
    # which UK liquidation is drawn depends on the seed, so take whichever one it is
    gb = next(c for c in s["companies"] if c["country"] == "GB" and len(c["evidence"]) == 2)
    assert [e["what"] for e in gb["evidence"]] == ["profile", "insolvency"]
    assert gb["evidence"][0]["url"] == (
        f"https://find-and-update.company-information.service.gov.uk/company/{gb['number']}"
    )
    audit = lib.read_json(paths.audit)
    by_group = [r["group"] for r in audit["rows"]]
    assert {g: by_group.count(g) for g in "ABCS"} == {"A": 4, "B": 4, "C": 4, "S": 2}
    assert all(r["agrees"] is None and r["official_url"] for r in audit["rows"])
    skips = lib.read_json(paths.set_skips)
    assert skips["seed"] == s["seed"] and len(skips["gb_dates"]) == 60
    assert verify_ok(paths)
    # the private copies: no practitioner, no address, no officer, no sole trader's name
    private = paths.private(s["seed"])
    kept = "".join(p.read_text(encoding="utf-8") for p in (private / "evidence").glob("*.json"))
    frames = "".join(
        gzip.decompress(p.read_bytes()).decode() for p in (private / "frames").glob("*")
    )
    assert len(list((private / "evidence").glob("*.json"))) == len(s["companies"])
    assert "creditors-voluntary-liquidation" in kept and "wound-up-on" in kept
    public = paths.set.read_text(encoding="utf-8") + paths.set_skips.read_text(encoding="utf-8")
    for banned in (
        "ractitioner",
        "Fixture Street",
        "address",
        "Parauga iela",
        "Paraugs",
        "Fixtureperson",
        "court",
    ):
        assert banned not in kept and banned not in frames and banned not in public, banned
    assert "09100001" in frames and "Likvidācija" in frames  # the listing itself is kept
    # the key travels as Basic auth to Companies House only, never in a URL
    for request in reg.seen:
        ch = request.url.host == "api.company-information.service.gov.uk"
        assert ("authorization" in request.headers) == ch
        assert "ch-test-key" not in str(request.url)
    assert all(m["sha256"] and m["url"].startswith("https://") for m in s["frames"])
    with pytest.raises(sample.Refused, match="one draw only"):
        sample.main(["draw", "--env-file", env], paths.root, reg.client(), at)

    # second read: one company was dissolved in the meantime, one got a new status
    commit(paths.root, "set")
    reg.gb["companies"]["09100001"]["profile"]["company_status"] = "dissolved"
    reg.gb["companies"]["09100001"]["profile"]["date_of_cessation"] = "2026-11-10"
    assert sample.main(["truth2", "--env-file", env], paths.root, reg.client(), at) == 0
    second = lib.read_json(paths.report_dir(s["seed"]) / "truth2.json")
    changed = {r["id"]: r["why"] for r in second["companies"] if r["changed"]}
    drawn = {c["id"] for c in s["companies"]}
    assert set(changed) == {"gb-09100001"} & drawn or not ({"gb-09100001"} & drawn)
    assert len(second["companies"]) == len(s["companies"])
    # the analysis recomputes the same changes from the values the second read stores
    got, mismatch = analyze.truth2_changes(s, second)
    assert set(got) == set(changed) and mismatch == []


def verify_ok(paths):
    return lib.verify_prereg(paths) == []


def test_pilot_draw_and_probe_end_to_end(tmp_path, monkeypatch):
    paths = make_root(tmp_path)
    env = env_file(tmp_path, monkeypatch)
    reg = Registers()
    assert sample.main(["draw", "--pilot", "--env-file", env], paths.root, reg.client(), NOW) == 0
    pilot = lib.read_json(paths.pilot_set)
    assert pilot["seed"] == lib.sha256_text(CFG["pilot_seed_text"]) and pilot["pilot"] is True
    abc = [c for c in pilot["companies"] if c["group"] != "S"]
    assert len(abc) == 6 and sorted(c["group"] for c in abc) == list("AABBCC")
    assert (paths.storage / "pilot" / "evidence" / f"{abc[0]['id']}.json").is_file()
    with pytest.raises(sample.Refused, match="already drawn"):
        sample.main(["draw", "--pilot", "--env-file", env], paths.root, reg.client(), NOW)

    assert sample.main(["probe", "--env-file", env], paths.root, reg.client(), NOW) == 0
    frames = lib.read_json(paths.frames)
    assert all(frames["sources"][cc]["reachable"] for cc in ("GB", "IE", "LV", "EE"))
    assert frames["sources"]["IE"]["status"]["liquidation"] == 3
    assert frames["sources"]["LV"]["status"]["insolvency:insolvency"] == 2
    assert frames["sources"]["GB"]["test_dates"] == CFG["uk_frame"]["probe_dates"]
    assert frames["sanctions"]["lists"]["organisations"] == {"UK": 2, "OFAC SDN": 2, "EU": 2}
    assert frames["drand"]["chain_hash"] == CFG["drand"]["chain_hash"]
    assert frames["drand"]["period"] == 3
    assert "date_from" in frames["columns"]["lv_liquidation"]
    assert "date_to" not in frames["columns"]["lv_liquidation"]  # the question for the laptop
    assert "practitioners" in frames["columns"]["GB insolvency case"]  # a field name, no value
    assert "company_status" in frames["columns"]["GB search item"]
    # the fixture's Irish "receivership" is in no table: the probe says so
    assert frames["status_not_in_truth_map"] == {"IE": ["receivership"]}
    text = paths.frames.read_text(encoding="utf-8")
    for name in ("FIXTURE", "paraugs", "Näidis", "SAMPLE"):
        assert name not in text  # counts and columns only, no company

    # a wrong key is reported, not hidden, and is never echoed
    bad = env_file(tmp_path, monkeypatch, key="wrong-key-123")
    assert sample.main(["probe", "--env-file", bad], paths.root, reg.client(), NOW) == 1
    frames = lib.read_json(paths.frames)
    assert (
        frames["sources"]["GB"]["reachable"] is False and "401" in frames["sources"]["GB"]["error"]
    )
    assert "wrong-key-123" not in paths.frames.read_text(encoding="utf-8")


def test_dry_runs_make_no_request_and_write_nothing(tmp_path, monkeypatch, capsys):
    def explode(*a, **kw):
        raise AssertionError("a dry run opened a connection")

    monkeypatch.setattr(httpx.Client, "send", explode)
    monkeypatch.delenv("COMPANIES_HOUSE_API_KEY", raising=False)
    paths = make_root(tmp_path)
    before = sorted(p for p in paths.root.rglob("*") if ".git" not in p.parts)
    for command in ("probe", "draw", "truth2"):
        assert sample.main([command, "--dry-run"], paths.root) == 0
    out = capsys.readouterr().out
    assert "gb-09100008" in out and "nothing written" in out
    assert sorted(p for p in paths.root.rglob("*") if ".git" not in p.parts) == before


def test_live_listing_pages_filters_and_retries(monkeypatch):
    calls = []
    items = [
        {
            "company_number": f"0{i:07d}",
            "company_name": f"N{i} LTD",
            "company_type": "ltd",
            "company_status": "active",
            "date_of_creation": "2015-06-15",
            "registered_office_address": {"address_line_1": "1 Home Street"},
        }
        for i in range(5)
    ]
    items[1]["date_of_creation"] = "2015-06-16"  # the day after: asked for, filtered here
    items[2]["company_type"] = "plc"

    def handler(request):
        calls.append(request)
        q = request.url.params
        if len(calls) == 1:
            return httpx.Response(502)
        if len(calls) == 2:
            return httpx.Response(429, headers={"Retry-After": "2"})
        assert (q["incorporated_from"], q["incorporated_to"]) == ("2015-06-15", "2015-06-16")
        assert (q["company_type"], q["size"]) == ("ltd", "5000")
        start = int(q["start_index"])
        return httpx.Response(200, json={"hits": "5", "items": items[start : start + 3]})

    waits = []
    monkeypatch.setattr(sample, "SLEEP", waits.append)
    client = httpx.Client(transport=httpx.MockTransport(handler))
    live = sample.Live(client, "k", CFG, TM, None)
    got = live.gb_day("2015-06-15")
    assert [i["company_number"] for i in got] == ["00000000", "00000003", "00000004"]
    assert "registered_office_address" not in json.dumps(got)
    assert [int(c.url.params["start_index"]) for c in calls] == [0, 0, 0, 3]
    assert 1 in waits and 2 in waits  # backoff after the 502, Retry-After after the 429
    assert len(live.meta) == 2 and live.meta[0]["rows"] == 1 and live.meta[1]["rows"] == 2
    with pytest.raises(sample.Refused, match="COMPANIES_HOUSE_API_KEY"):
        sample.Live(client, "", CFG, TM, None).gb_day("2015-06-15")


def test_beacon_answer_must_be_self_consistent():
    def serve(body):
        return httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, json=body)))

    good = {
        "round": 7,
        "signature": "ab" * 48,
        "randomness": lib.sha256_bytes(bytes.fromhex("ab" * 48)),
    }
    got = sample.beacon_round(serve(good), CFG, 7)
    assert got["randomness"] == good["randomness"] and CFG["drand"]["chain_hash"] in got["url"]
    for bad in (good | {"round": 8}, good | {"randomness": "00" * 32}):
        with pytest.raises(sample.Refused, match="not self-consistent"):
            sample.beacon_round(serve(bad), CFG, 7)
    down = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(503)))
    with pytest.raises(sample.Refused, match="the draw waits"):
        sample.beacon_round(down, CFG, 7)


# --- review fixes ---------------------------------------------------------------------------------


def test_the_draw_printout_survives_a_cp1252_console(tmp_path, monkeypatch):
    """The reviewer's crash: a Windows console in cp1252 cannot encode the Latvian 'ā'."""
    import io
    import sys

    raw = io.BytesIO()
    console = io.TextIOWrapper(raw, encoding="cp1252")
    monkeypatch.setattr(sys, "stdout", console)
    paths = make_root(tmp_path)
    assert sample.main(["draw", "--pilot", "--dry-run"], paths.root) == 0
    console.flush()
    assert 'SIA "Likvidācija viens"' in raw.getvalue().decode("utf-8")


def test_a_missing_companies_house_key_is_refused_before_any_request(tmp_path, monkeypatch):
    paths = make_root(tmp_path)
    monkeypatch.delenv("COMPANIES_HOUSE_API_KEY", raising=False)
    empty = tmp_path / "empty.env"
    empty.write_text("", encoding="utf-8")
    reg = Registers()
    for args in (["draw", "--pilot"], ["probe"]):
        with pytest.raises(sample.Refused, match="COMPANIES_HOUSE_API_KEY is not set"):
            sample.main([*args, "--env-file", str(empty)], paths.root, reg.client(), NOW)
    assert not reg.seen and not paths.pilot_set.exists()


def test_a_network_error_is_one_line_and_exit_1(tmp_path, monkeypatch, capsys):
    paths = make_root(tmp_path)
    monkeypatch.setenv("COMPANIES_HOUSE_API_KEY", "ch-test-key")

    def down(request):
        raise httpx.ConnectError("Name or service not known", request=request)

    client = httpx.Client(transport=httpx.MockTransport(down))
    assert sample.main(["draw", "--pilot"], paths.root, client, NOW) == 1
    err = capsys.readouterr().err
    assert "network error reading https://" in err and "run the same command again" in err
    assert "Traceback" not in err and "ch-test-key" not in err
    assert not paths.pilot_set.exists()
