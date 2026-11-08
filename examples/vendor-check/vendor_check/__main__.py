"""vendor-check "Novo Nordisk A/S" --country DK | --csv vendors.csv | --demo"""

import argparse
import csv
import json
import os
import sys

from . import GET_KEY, VendorCheckError, check_vendor, demo_names, price_usd

MARK = {"pass": "PASS", "fail": "FAIL", "review": "REVIEW", "unverified": "UNVERIFIED"}


def checklist(row: dict) -> list[dict]:
    return row.get("checks") or []


def show(result: dict) -> None:
    out = print
    title = result["query"] + (f" ({result['country']})" if result.get("country") else "")
    out(f"\n== {title}")
    if result.get("demo"):
        out(f"   demo data, {result['label']}, fetched {result['fetched_at']}")
    row = result.get("row")
    if result["mode"] == "paid" and row and row.get("status") == "ambiguous":
        out(f"   {row.get('message')}")
        for c in row.get("candidates") or []:
            out("   - " + ", ".join(str(v) for v in c.values() if isinstance(v, str | int)))
        return
    if result["mode"] == "paid" and row:
        co = row.get("company") or {}
        out(
            f"   {co.get('legal_name')} | {co.get('register')} {co.get('registration_number')}"
            f" | LEI {co.get('lei')}"
        )
        for c in checklist(row):
            out(f"   [{MARK.get(c['status'], c['status']):<10}] {c['check']}: {c['detail']}")
            if c.get("source_url"):
                out(f"                {c['source_url']}")
        s = row.get("summary") or {}
        out(
            f"   needs attention: {s.get('needs_attention') or 'none'}; "
            f"unverified (not checked, not 'safe'): {s.get('unverified_checks') or 'none'}"
        )
        out(f"   charged: ${result.get('charged_usd')}. {row.get('notice', '')}")
        return
    if result["mode"] == "paid":
        out("   no result returned")
        return
    for r in result.get("lei_candidates") or []:
        out(
            f"   LEI {r.get('lei')} {r.get('legal_name')} [{r.get('entity_status')}, "
            f"LEI {r.get('registration_status')}] reg. {r.get('registered_as') or '-'} "
            f"{r.get('source_url')}"
        )
    for r in result.get("sec_matches") or []:
        out(f"   SEC {r.get('name')} CIK {r.get('cik')} {r.get('source_url', '')}")
    if not result.get("lei_candidates") and not result.get("sec_matches"):
        out("   no LEI record found by name (most small companies have none)")
    plan = result.get("plan") or {}
    if plan.get("not_covered"):
        out(f"   not covered: {plan['not_covered']}")
    ex = result.get("example_paid")
    if ex:
        out(f"   paid checklist below is an {ex['label']}:")
        show(
            {
                "mode": "paid",
                "query": ex["row"]["query"],
                "row": ex["row"],
                "charged_usd": "0.05 (example)",
            }
        )
    out(
        f"   Full checklist (register, insolvency, accounts, sanctions on company and officers, "
        f"VAT, IBAN): up to ${price_usd(result)} with a key. Get one: {GET_KEY}"
    )


def csv_rows(result: dict):
    base = {
        "vendor": result["query"],
        "country": result.get("country") or "",
        "mode": result["mode"],
    }
    row = result.get("row") or {}
    if result["mode"] == "paid":
        if row.get("status") == "ambiguous" or not row:
            yield {
                **base,
                "check": "identity",
                "status": "ambiguous",
                "detail": row.get("message", "no result"),
                "source_url": "",
            }
        for c in checklist(row):
            yield {
                **base,
                **{k: c.get(k) or "" for k in ("check", "status", "detail", "source_url")},
            }
        return
    for r in result.get("lei_candidates") or []:
        yield {
            **base,
            "check": "lei_candidate",
            "status": r.get("registration_status", ""),
            "detail": f"{r.get('legal_name')} LEI {r.get('lei')}",
            "source_url": r.get("source_url", ""),
        }
    yield {
        **base,
        "check": "counterparty_check",
        "status": "not run (no key)",
        "detail": f"up to ${price_usd(result)}",
        "source_url": GET_KEY,
    }


def write(results: list[dict], path: str) -> None:
    with open(path, "w", encoding="utf-8", newline="") as f:
        if path.lower().endswith(".csv"):
            cols = ["vendor", "country", "mode", "check", "status", "detail", "source_url"]
            w = csv.DictWriter(f, cols)
            w.writeheader()
            for r in results:
                w.writerows(csv_rows(r))
        else:
            json.dump(results, f, indent=2, ensure_ascii=False)
    print(f"\nwrote {path}")


def read_vendors(path: str) -> list[dict]:
    with open(path, encoding="utf-8-sig", newline="") as f:
        rows = [
            {k.strip().lower(): (v or "").strip() for k, v in r.items() if k}
            for r in csv.DictReader(f)
        ]
    vendors = [r for r in rows if r.get("name")]
    if not vendors:
        raise VendorCheckError(
            f"{path}: needs a `name` column (optional: country, vat_number, iban)"
        )
    return vendors


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="vendor-check", description=__doc__)
    p.add_argument("name", nargs="?", help="company name or identifier (LEI, CVR, ticker, ...)")
    p.add_argument("--country", help="ISO 2-letter country code, e.g. DK, GB, US")
    p.add_argument("--vat", help="the VAT number the vendor gave you, e.g. DK24256790")
    p.add_argument("--iban", help="the IBAN the vendor wants to be paid on")
    p.add_argument("--csv", metavar="FILE", help="vendor list: name,country,vat_number,iban")
    p.add_argument("--demo", action="store_true", help="offline: recorded responses, no network")
    p.add_argument("--out", metavar="FILE", help="write results to .json or .csv")
    p.add_argument("--yes", action="store_true", help="confirm a paid CSV run (costs money)")
    a = p.parse_args(argv)
    sys.stdout.reconfigure(errors="replace")  # odd register characters on cp1252 consoles
    key = os.environ.get("BOSCO_API_KEY")
    try:
        if a.csv:
            vendors = read_vendors(a.csv)
        elif a.name:
            vendors = [{"name": a.name, "country": a.country, "vat_number": a.vat, "iban": a.iban}]
        elif a.demo:
            vendors = [{"name": n} for n in demo_names()]
        else:
            p.error("give a company name, --csv FILE or --demo")
        if key and not a.demo and len(vendors) > 1 and not a.yes:
            print(
                f"{len(vendors)} vendors x $0.05 = up to ${0.05 * len(vendors):.2f} on your key "
                "(ambiguous names are free). Re-run with --yes to go ahead."
            )
            return 2
        if not key and not a.demo:
            print(f"No BOSCO_API_KEY: free lookups only (planner, LEI, SEC). Key: {GET_KEY}")
        results = []
        for v in vendors:
            r = check_vendor(
                v["name"],
                v.get("country") or None,
                v.get("vat_number") or None,
                v.get("iban") or None,
                demo=a.demo,
            )
            show(r)
            results.append(r)
        if a.out:
            write(results, a.out)
    except VendorCheckError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    print(
        "\nScreening aid from official sources, not a compliance verdict. "
        "'unverified' means not checked, never 'safe'."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
