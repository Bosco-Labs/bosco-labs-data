"""Offline tests: the demo fixture and a stubbed API, no network."""

import csv
import json

import pytest
import vendor_check
from vendor_check import VendorCheckError, check_vendor, demo_names
from vendor_check.__main__ import csv_rows, main


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def refuse(*a, **k):
        raise AssertionError("network used in an offline test")

    monkeypatch.setattr(vendor_check.urllib.request, "urlopen", refuse)
    monkeypatch.delenv("BOSCO_API_KEY", raising=False)


def test_demo_set_is_three_dated_companies():
    assert demo_names() == ["Novo Nordisk A/S", "Tesco PLC", "Apple Inc."]
    r = check_vendor("tesco plc", demo=True)
    assert r["demo"] and r["fetched_at"] and r["lei_candidates"][0]["legal_name"] == "TESCO PLC"
    assert vendor_check.price_usd(r) == 0.05


def test_example_paid_row_is_labelled_and_sourced():
    ex = check_vendor("Novo Nordisk A/S", demo=True)["example_paid"]
    assert "not live data" in ex["label"]
    statuses = {c["status"] for c in ex["row"]["checks"]}
    assert statuses <= {"pass", "fail", "review", "unverified"}
    assert all({"check", "detail", "source", "source_url"} <= c.keys() for c in ex["row"]["checks"])


def test_unknown_demo_name_and_empty_name_fail():
    with pytest.raises(VendorCheckError):
        check_vendor("Nope Ltd", demo=True)
    with pytest.raises(VendorCheckError):
        check_vendor("  ")


def test_paid_mode_uses_key_and_counterparty_endpoint(monkeypatch):
    row = check_vendor("Novo Nordisk A/S", demo=True)["example_paid"]["row"]
    seen = {}

    def fake_post(path, body, key=None, timeout=90):
        seen.update(path=path, body=body, key=key)
        return {"rows": [row], "charged_usd": 0.05, "warnings": []}

    monkeypatch.setattr(vendor_check, "_post", fake_post)
    r = check_vendor("24256790", country="DK", iban="DK5000400440116243", api_key="k")
    assert seen == {
        "path": "/v1/counterparty-check",
        "key": "k",
        "body": {"query": "24256790", "country": "DK", "iban": "DK5000400440116243"},
    }
    rows = list(csv_rows(r))
    assert len(rows) == len(row["checks"]) and rows[0]["status"] == "pass"


def test_cli_demo_writes_json_and_csv(tmp_path, capsys):
    assert main(["--demo", "--out", str(tmp_path / "r.json")]) == 0
    assert len(json.loads((tmp_path / "r.json").read_text(encoding="utf-8"))) == 3
    assert main(["Apple Inc.", "--demo", "--out", str(tmp_path / "r.csv")]) == 0
    rows = list(csv.DictReader(open(tmp_path / "r.csv", encoding="utf-8")))
    assert rows[-1]["status"] == "not run (no key)"
    assert "never 'safe'" in capsys.readouterr().out


def test_paid_csv_run_needs_yes(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("BOSCO_API_KEY", "k")
    f = tmp_path / "v.csv"
    f.write_text("name,country\nA Ltd,GB\nB AS,NO\n", encoding="utf-8")
    assert main(["--csv", str(f)]) == 2
    assert "$0.10" in capsys.readouterr().out
