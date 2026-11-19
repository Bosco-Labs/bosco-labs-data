"""Benchmark 2 sampler: probe the official lists, draw the companies, read the answer key.

    uv run python tools/bench2_sample.py probe            # writes data/benchmark2/frames.json
    uv run python tools/bench2_sample.py draw --pilot     # 6 companies, fixed pilot seed
    uv run python tools/bench2_sample.py draw             # the one draw, after the beacon round
    uv run python tools/bench2_sample.py truth2           # second read of the answer key

This file is the answer key's only author. It reads the registers and the three sanctions list
files itself, with its own small parsers. It imports nothing from the product (the Actors or the
HTTP API) and never calls the product, so a product bug cannot leak into the truth. A test checks
that by reading this file's syntax tree.

Sources (protocol section 3): Companies House advanced search and company profile (UK, needs
COMPANIES_HOUSE_API_KEY, sent as Basic user only), the CRO "Company Records" datastore (Ireland),
the Enterprise Register datastores on data.gov.lv (Latvia), the e-Business Register basic-data
file (Estonia), the UK Sanctions List, OFAC SDN and EU consolidated list files, and the drand
quicknet beacon for the seed. Every command has --dry-run (no network, fixture frames).
"""

import argparse
import csv
import gzip
import heapq
import io
import json
import os
import re
import sys
import time
import xml.etree.ElementTree as ET
import zipfile
from collections import Counter
from datetime import date, timedelta
from pathlib import Path

import bench2_lib as lib
import httpx

CH_API = "https://api.company-information.service.gov.uk"
CH_PAGE = "https://find-and-update.company-information.service.gov.uk/company/"
IE_API = "https://opendata.cro.ie/api/3/action/datastore_search"
IE_RES = "3fef41bc-b8f4-4b10-8434-ce51c29b1bba"  # "Company Records"
LV_API = "https://data.gov.lv/dati/api/3/action/datastore_search"
LV_REG = "25e80bf3-f107-4ab4-89ef-251b5b9374e9"  # the register
LV_LIQ = "59e7ec49-f1c6-4410-8ee6-e7737ac5eaee"  # current liquidation entries
LV_INS = "8065ad80-1a4d-4afb-b1d1-d93b9a62b1cc"  # insolvency proceedings
EE_SITE = "https://avaandmed.ariregister.rik.ee"
EE_DOWNLOADS = EE_SITE + "/en/downloading-open-data"
EE_AUTOCOMPLETE = "https://ariregister.rik.ee/eng/api/autocomplete"
EE_PAGE = "https://ariregister.rik.ee/eng/company/"
LISTS = {
    "UK": "https://sanctionslist.fcdo.gov.uk/docs/UK-Sanctions-List.xml",
    "OFAC SDN": "https://sanctionslistservice.ofac.treas.gov/api/PublicationPreview/exports/SDN.XML",
    "EU": "https://webgate.ec.europa.eu/fsd/fsf/public/files/xmlFullSanctionsList_1_1/content"
    "?token=dG9rZW4tMjAxNw",
}
UA = "counterparty-benchmark2-sampler/1"
CKAN_PAGE = 32000  # CKAN's default ceiling for one datastore_search call
WALK_KEYS = 2000  # smallest keys kept per cell: far more than a quota of 10 can need
SLEEP = time.sleep  # tests replace this

# The only fields ever kept from a response (cut-down copies, frames, evidence). Officers,
# addresses and insolvency practitioners are never in these lists, so they are never stored.
KEEP = {
    "gb_item": (
        "company_number company_name company_type company_status date_of_creation date_of_cessation"
    ).split(),
    "gb_profile": (
        "company_number company_name type subtype company_status company_status_detail "
        "date_of_creation date_of_cessation has_insolvency_history has_been_liquidated"
    ).split(),
    "ie": (
        "company_num company_name company_type company_status company_reg_date "
        "comp_dissolved_date company_status_date"
    ).split(),
    "lv_register": "regcode name type registered terminated closed".split(),
    "lv_liquidation": "legal_entity_registration_number liquidation_type date_from date_to".split(),
    "lv_insolvency": (
        "debtor_registration_number proceeding_form proceeding_type proceeding_started_on "
        "proceeding_ended_on"
    ).split(),
    "ee": (
        "ariregistri_kood nimi ettevotja_oiguslik_vorm ettevotja_staatus ettevotja_esmakande_kpv"
    ).split(),
    "ee_auto": "reg_code name status legal_form".split(),
}
COUNTRY_WORDS = {
    "gb": "GB",
    "uk": "GB",
    "united kingdom": "GB",
    "great britain": "GB",
    "england": "GB",
    "scotland": "GB",
    "wales": "GB",
    "northern ireland": "GB",
    "ie": "IE",
    "ireland": "IE",
    "lv": "LV",
    "latvia": "LV",
    "ee": "EE",
    "estonia": "EE",
}


class Refused(SystemExit):
    """A precondition of the protocol does not hold; nothing was written."""


def norm(value) -> str:
    return " ".join(str(value if value is not None else "").lower().split())


def cut(row: dict, kind: str) -> dict:
    return {k: row.get(k) for k in KEEP[kind] if k in row}


def months_before(day: date, months: int) -> date:
    y, m = divmod(day.year * 12 + day.month - 1 - months, 12)
    for d in (day.day, 30, 29, 28):
        try:
            return date(y, m + 1, d)
        except ValueError:
            continue
    raise ValueError(day)


# --- facts and the mapping table ------------------------------------------------------------------
# Facts: what the register says about one company, in one shape for every country:
# {country, number, name, legal_form, raw_status, dissolved_on, cases, ambiguous}. `cases` is None
# when the listing does not carry them (UK search items); then only the cell can be told.


def gb_item_facts(item: dict) -> dict:
    return {
        "country": "GB",
        "number": str(item.get("company_number") or ""),
        "name": (item.get("company_name") or "").strip(),
        "legal_form": item.get("company_type"),
        "raw_status": item.get("company_status"),
        "dissolved_on": (item.get("date_of_cessation") or "")[:10] or None,
        "cases": None,
        "ambiguous": None,
    }


def gb_cases(insolvency: dict | None) -> list[dict]:
    """Case types and dates only; the practitioners of each case are dropped here."""
    out = []
    for c in (insolvency or {}).get("cases") or []:
        dates = [{"type": d.get("type"), "date": d.get("date")} for d in c.get("dates") or []]
        out.append({"type": c.get("type"), "dates": dates})
    return out


def gb_facts(number: str, profile: dict | None, insolvency: dict | None) -> dict:
    if profile is None:
        return _missing("GB", number)
    cases = gb_cases(insolvency)
    status, why = profile.get("company_status"), None
    if profile.get("company_status_detail"):  # e.g. active-proposal-to-strike-off
        why = f"status detail {profile['company_status_detail']}"
    elif status == "active" and (profile.get("has_insolvency_history") or cases):
        why = "insolvency history on an active company"
    elif profile.get("has_insolvency_history") and not cases:
        why = "insolvency history without a case on the register"
    return {
        "country": "GB",
        "number": number,
        "name": (profile.get("company_name") or "").strip(),
        "legal_form": profile.get("type"),
        "raw_status": status,
        "dissolved_on": (profile.get("date_of_cessation") or "")[:10] or None,
        "cases": cases,
        "ambiguous": why,
    }


def ie_facts(row: dict) -> dict:
    gone = row.get("comp_dissolved_date") or row.get("company_status_date") or ""
    return {
        "country": "IE",
        "number": str(int(row["company_num"])),
        "name": (row.get("company_name") or "").strip(),
        "legal_form": row.get("company_type"),
        "raw_status": row.get("company_status"),
        "dissolved_on": str(gone)[:10] or None,
        "cases": [],
        "ambiguous": None,
    }


def lv_facts(row: dict, liq: list[dict], ins: list[dict], end_fields: list[str]) -> dict:
    """Latvia has no status field: it is derived from the register row, the current liquidation
    entries and the insolvency proceedings (the rule is written out in truth_map.json)."""
    closed, ended = (row.get("closed") or "").strip(), str(row.get("terminated") or "")[:10]
    open_ins = [p for p in ins if not p.get("proceeding_ended_on")]
    current = [x for x in liq if not any(x.get(f) for f in end_fields)]
    why = None
    if closed or ended:
        raw = f"closed:{closed or '?'}"
    elif open_ins:
        forms = sorted({norm(p.get("proceeding_form")) for p in open_ins})
        raw = "insolvency:" + ("insolvency" if "insolvency" in forms else forms[0])
    elif current:
        newest = max(current, key=lambda x: str(x.get("date_from") or ""))
        raw = f"liquidation:{norm(newest.get('liquidation_type'))}"
        why = "ended insolvency proceedings on a company in liquidation" if ins else None
    else:
        raw = "registered:past_insolvency" if ins else "registered"
    cases = [
        {
            "type": norm(p.get("proceeding_form")),
            "dates": [
                {"type": "started", "date": str(p.get("proceeding_started_on") or "")[:10] or None},
                {"type": "ended", "date": str(p.get("proceeding_ended_on") or "")[:10] or None},
            ],
        }
        for p in ins
    ]
    return {
        "country": "LV",
        "number": str(int(row["regcode"])),
        "name": (row.get("name") or "").strip(),
        "legal_form": row.get("type"),
        "raw_status": raw,
        "dissolved_on": ended or None,
        "cases": cases,
        "ambiguous": why,
    }


def ee_facts(row: dict) -> dict:
    return {
        "country": "EE",
        "number": str(row.get("ariregistri_kood") or "").strip(),
        "name": (row.get("nimi") or "").strip(),
        "legal_form": row.get("ettevotja_oiguslik_vorm"),
        "raw_status": row.get("ettevotja_staatus"),
        "dissolved_on": None,
        "cases": [],
        "ambiguous": None,
    }


def _missing(country: str, number: str) -> dict:
    return {
        "country": country,
        "number": number,
        "name": "",
        "legal_form": None,
        "raw_status": "not_found",
        "dissolved_on": None,
        "cases": [],
        "ambiguous": None,
    }


def classify(facts: dict, table: dict, window: tuple[str, str], forms: bool = True) -> dict:
    """Facts -> {"group", "truth"} | {"skip": reason, "detail"} | {"out": why}.

    `out` is not a skip: the company is simply not in a group (dissolved outside the 24 months).
    forms=False leaves the legal form unchecked (group S takes every listed organisation)."""
    form, raw = norm(facts.get("legal_form")), norm(facts.get("raw_status"))
    if raw == "not_found":  # no record at all: there is no legal form to judge either
        return {"skip": "status_not_mapped", "detail": raw}
    if forms and form not in table["legal_forms"]:
        return {"skip": "legal_form", "detail": form}
    entry = table["status"].get(raw)
    if entry is None or "skip" in entry:
        return {"skip": (entry or {}).get("skip", "status_not_mapped"), "detail": raw}
    if facts.get("ambiguous"):
        return {"skip": "ambiguous", "detail": facts["ambiguous"]}
    if entry["group"] == "C":
        gone = facts.get("dissolved_on")
        if not gone:
            return {"out": "no dissolution date"}
        if not window[0] <= gone <= window[1]:
            return {"out": "dissolved outside the window"}
    cases, insolvent = facts.get("cases"), entry["insolvent"]
    if cases and entry.get("requires_no_cases"):
        return {"skip": "ambiguous", "detail": "an insolvency case on an active company"}
    if insolvent == "from_cases" and cases is not None:
        marks = []
        for c in cases:
            kind = norm(c.get("type"))
            if kind not in table["case_types"]:
                return {"skip": "status_not_mapped", "detail": f"case type {kind}"}
            marks.append(table["case_types"][kind])
        if not marks:
            insolvent = entry.get("no_cases")
            if insolvent == "skip":
                return {"skip": "ambiguous", "detail": f"{raw} without a case on the register"}
        else:
            insolvent = True if True in marks else None if None in marks else False
    truth = {
        "status": entry["status"],
        "insolvent": insolvent,
        "sanctioned": False,
        "sanctions_lists": [],
    }
    return {"group": entry["group"], "truth": truth}


# --- sanctions lists: organisations only ----------------------------------------------------------
# An organisation: {list, id, name, aliases, numbers, countries}. Entries of persons, ships and
# aircraft are dropped as soon as their type is read: nothing else of them is looked at or kept.


def _t(el, path: str) -> str:
    return (el.findtext(path) or "").strip()


def _iso2(words) -> list[str]:
    return sorted({COUNTRY_WORDS[norm(w)] for w in words if norm(w) in COUNTRY_WORDS})


def parse_uk(raw: bytes) -> list[dict]:
    out = []
    for _, el in ET.iterparse(io.BytesIO(raw)):
        if el.tag != "Designation":
            continue
        if _t(el, "IndividualEntityShip") == "Entity":
            names = []
            for n in el.findall("Names/Name"):
                names.append(" ".join(_t(n, f"Name{i}") for i in range(1, 7) if _t(n, f"Name{i}")))
            names += [(e.text or "").strip() for e in el.iter("NameNonLatinScript")]
            names = [n for n in dict.fromkeys(names) if n]
            out.append(
                {
                    "list": "UK",
                    "id": _t(el, "UniqueID"),
                    "name": names[0] if names else "",
                    "aliases": names[1:],
                    "numbers": [
                        (e.text or "").strip() for e in el.iter("BusinessRegistrationNumber")
                    ],
                    "countries": _iso2((e.text or "") for e in el.iter("AddressCountry")),
                }
            )
        el.clear()
    return out


OFAC_ID_WORDS = (
    "registration",
    "company number",
    "tax id",
    "business number",
    "v.a.t",
    "commercial registry",
    "enterprise number",
    "identification number",
)


def parse_ofac(raw: bytes) -> list[dict]:
    out = []
    for _, el in ET.iterparse(io.BytesIO(raw)):
        if el.tag.rsplit("}", 1)[-1] != "sdnEntry":
            continue
        if _t(el, "{*}sdnType") == "Entity":
            numbers, places = [], [_t(a, "{*}country") for a in el.findall(".//{*}address")]
            for i in el.findall(".//{*}id"):
                kind, number = _t(i, "{*}idType").lower(), _t(i, "{*}idNumber")
                if number and any(w in kind for w in OFAC_ID_WORDS):
                    numbers.append(number)
                    places.append(_t(i, "{*}idCountry"))
            aliases = [_t(a, "{*}lastName") for a in el.findall(".//{*}aka")]
            out.append(
                {
                    "list": "OFAC SDN",
                    "id": _t(el, "{*}uid"),
                    "name": _t(el, "{*}lastName"),
                    "aliases": [a for a in dict.fromkeys(aliases) if a],
                    "numbers": numbers,
                    "countries": _iso2(places),
                }
            )
        el.clear()
    return out


EU_ID_CODES = {"regnumber", "taxid", "fiscalcode", "euvat"}


def parse_eu(raw: bytes) -> list[dict]:
    out = []
    for _, el in ET.iterparse(io.BytesIO(raw)):
        if el.tag.rsplit("}", 1)[-1] != "sanctionEntity":
            continue
        kind = el.find("{*}subjectType")
        if kind is not None and kind.get("code") == "enterprise":
            names = [a.get("wholeName", "").strip() for a in el.findall("{*}nameAlias")]
            names = [n for n in dict.fromkeys(names) if n]
            out.append(
                {
                    "list": "EU",
                    "id": el.get("euReferenceNumber") or el.get("logicalId") or "",
                    "name": names[0] if names else "",
                    "aliases": names[1:],
                    "numbers": [
                        i.get("number")
                        for i in el.findall("{*}identification")
                        if i.get("identificationTypeCode") in EU_ID_CODES and i.get("number")
                    ],
                    "countries": _iso2(
                        a.get("countryIso2Code") or "" for a in el.findall("{*}address")
                    ),
                }
            )
        el.clear()
    return out


PARSERS = {"UK": parse_uk, "OFAC SDN": parse_ofac, "EU": parse_eu}


class Sanctions:
    """The organisations of the three lists, indexed for the two questions the draw asks."""

    def __init__(self, orgs: list[dict], tokens: list[str]):
        self.orgs, self.tokens = orgs, tokens
        self.by_name: dict[str, set[str]] = {}
        for o in orgs:
            for n in [o["name"], *o["aliases"]]:
                key = lib.normalise_name(n, tokens)
                if key:  # an empty name (only legal-form words) never matches anything
                    self.by_name.setdefault(key, set()).add(o["list"])

    def lists_naming(self, name: str) -> list[str]:
        return sorted(self.by_name.get(lib.normalise_name(name, self.tokens), ()))

    def number_candidates(self, countries: list[str]) -> dict[str, dict[str, list[dict]]]:
        """{country: {registration number: [organisations listing that number]}}: the numbers a
        listing gives, read as each country writes its numbers. A name match is still needed."""
        out: dict[str, dict[str, list[dict]]] = {c: {} for c in countries}
        for o in self.orgs:
            # an 8-digit number is a UK number as often as an Estonian one: Estonia needs the
            # listing to name Estonia, or no country at all
            ee_ok = "EE" in o["countries"] or not o["countries"]
            for value in o["numbers"]:
                for token in re.findall(r"[A-Z]{0,2}\d{5,11}", value.upper()):
                    digits = re.sub(r"\D", "", token)
                    hits = []
                    if token.isdigit() and len(digits) == 11:
                        hits.append(("LV", digits))
                    if token.isdigit() and len(digits) == 8 and ee_ok:
                        hits.append(("EE", digits))
                    if token.isdigit() and len(digits) <= 7 and "IE" in o["countries"]:
                        hits.append(("IE", str(int(digits))))
                    if len(token) <= 8 and "GB" in o["countries"]:
                        hits.append(("GB", token.zfill(8) if token.isdigit() else token))
                    for country, number in hits:
                        if country in out:
                            out[country].setdefault(number, []).append(o)
        return out

    def listed(self, name: str, orgs: list[dict]) -> bool:
        want = lib.normalise_name(name, self.tokens)
        names = {
            lib.normalise_name(n, self.tokens) for o in orgs for n in [o["name"], *o["aliases"]]
        }
        return bool(want) and want in names


# --- network: every function takes the HTTP client ------------------------------------------------


def fetch(client: httpx.Client, url: str, *, params=None, auth=None, ok404=False, tries=4):
    """GET with a short backoff on 429, 5xx and network errors. Keys only travel in `auth`."""
    for attempt in range(tries):
        try:
            r = client.get(url, params=params, auth=auth)
        except httpx.TransportError:
            if attempt == tries - 1:
                raise
            SLEEP(2**attempt)
            continue
        if r.status_code == 429 and attempt < tries - 1:
            wait = r.headers.get("Retry-After", "")
            SLEEP(min(int(wait) if wait.isdigit() else 60, 300))
        elif r.status_code >= 500 and attempt < tries - 1:
            SLEEP(2**attempt)
        else:
            break
    if not (ok404 and r.status_code == 404):
        r.raise_for_status()
    return r


def ckan_rows(client: httpx.Client, api: str, resource: str, fields: list[str]):
    """Every row of a CKAN datastore resource, with only `fields`: yields (rows, response)."""
    offset = 0
    while True:
        params = {
            "resource_id": resource,
            "fields": ",".join(fields),
            "limit": CKAN_PAGE,
            "offset": offset,
            "sort": "_id",
        }
        r = fetch(client, api, params=params)
        result = r.json()["result"]
        rows = result.get("records") or []
        yield rows, r
        offset += len(rows)
        if not rows or offset >= int(result.get("total") or 0):
            return


def ckan_one(client: httpx.Client, api: str, resource: str, column: str, number: str, kind: str):
    """The rows of one registration number, asked with the same cut-down field list."""
    params = {
        "resource_id": resource,
        "fields": ",".join(KEEP[kind]),
        "filters": json.dumps({column: int(number)}),
    }
    r = fetch(client, api, params=params)
    return r.json()["result"].get("records") or [], r


def ckan_columns(client: httpx.Client, api: str, resource: str) -> tuple[list[str], int]:
    """(column names, row count) of a resource; the one sample row it returns is not kept."""
    r = fetch(client, api, params={"resource_id": resource, "limit": 1})
    result = r.json()["result"]
    return [f["id"] for f in result.get("fields") or []], int(result.get("total") or 0)


def ee_csv_url(html: str) -> str:
    found = sorted(
        set(re.findall(r'href="([^"]*ettevotja_rekvisiidid__lihtandmed\.csv\.zip)"', html))
    )
    if not found:
        raise ValueError(f"no basic-data link on {EE_DOWNLOADS}: the page layout changed")
    return EE_SITE + found[-1] if found[-1].startswith("/") else found[-1]


def ee_rows(zip_bytes: bytes):
    z = zipfile.ZipFile(io.BytesIO(zip_bytes))
    text = io.TextIOWrapper(z.open(z.namelist()[0]), encoding="utf-8-sig", newline="")
    yield from csv.DictReader(text, delimiter=";")


def drand_get(client: httpx.Client, cfg: dict, template: str, **kw) -> dict:
    """One beacon answer from the first base that gives it. The bases mirror one chain."""
    d, last = cfg["drand"], None
    for base in d["bases"]:
        try:
            url = d[template].format(base=base, chain_hash=d["chain_hash"], **kw)
            return fetch(client, url, tries=2).json() | {"_url": url}
        except (httpx.HTTPError, ValueError) as e:
            last = e
    raise Refused(f"the drand beacon could not be read ({type(last).__name__}); the draw waits")


def beacon_round(client: httpx.Client, cfg: dict, rnd: int) -> dict:
    got = drand_get(client, cfg, "round_url", round=rnd)
    # quicknet: the randomness is the SHA-256 of the signature. A cheap check that the answer is
    # self-consistent; the signature itself is checked by anyone with a drand client.
    sig = bytes.fromhex(got.get("signature", ""))
    if int(got.get("round", -1)) != rnd or lib.sha256_bytes(sig) != got.get("randomness"):
        raise Refused(f"the beacon answer for round {rnd} is not self-consistent")
    return {
        "round": rnd,
        "randomness": got["randomness"],
        "signature": got["signature"],
        "url": got["_url"],
        "fetched_at": lib.iso(lib.now()),
    }


class Live:
    """The official sources over HTTP. Cut-down copies of what was listed go to `store`."""

    def __init__(self, client: httpx.Client, ch_key: str, cfg: dict, tm: dict, store: Path | None):
        self.client, self.ch_key, self.cfg, self.tm, self.store = client, ch_key, cfg, tm, store
        self.meta: list[dict] = []  # one entry per listing response: url, hash, rows
        self.columns: dict[str, list[str]] = {}
        self._ch_next = 0.0
        self._pages = 0

    def _snap(self, source: str, r: httpx.Response, rows: list) -> None:
        self._pages += 1
        entry = {
            "source": source,
            "url": str(r.request.url),
            "sha256": lib.sha256_bytes(r.content),
            "bytes": len(r.content),
            "rows": len(rows),
            "fetched_at": lib.iso(lib.now()),
        }
        if self.store:
            name = f"{self._pages:04d}-{source.lower().replace(' ', '-')}.json.gz"
            path = self.store / "frames" / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(gzip.compress(json.dumps(rows, ensure_ascii=False).encode("utf-8")))
            entry["file"] = name
        self.meta.append(entry)

    def _ch(self, path: str, **kw) -> httpx.Response:
        if not self.ch_key:
            raise Refused("COMPANIES_HOUSE_API_KEY is not set")
        wait = self._ch_next - time.monotonic()  # the key allows 600 calls per 5 minutes
        if wait > 0:
            SLEEP(wait)
        self._ch_next = time.monotonic() + float(self.cfg["uk_frame"]["interval_seconds"])
        return fetch(self.client, CH_API + path, auth=(self.ch_key, ""), **kw)

    def gb_day(self, day: str) -> list[dict]:
        """Every `ltd` incorporated on the day. One day past the end, then filtered here: right
        whether the API reads `incorporated_to` as inclusive or not."""
        end = (date.fromisoformat(day) + timedelta(days=1)).isoformat()
        size, start, out = int(self.cfg["uk_frame"]["page_size"]), 0, []
        while True:
            params = {
                "incorporated_from": day,
                "incorporated_to": end,
                "company_type": "ltd",
                "size": size,
                "start_index": start,
            }
            r = self._ch("/advanced-search/companies", params=params, ok404=True)
            if r.status_code == 404:  # "No companies found"
                break
            data = r.json()
            items = data.get("items") or []
            seen = set(self.columns.get("GB search item", [])) | {k for i in items for k in i}
            self.columns["GB search item"] = sorted(seen)
            rows = [
                cut(i, "gb_item")
                for i in items
                if i.get("date_of_creation") == day and i.get("company_type") == "ltd"
            ]
            self._snap(f"GB {day}", r, rows)
            out += rows
            start += len(items)
            if not items or start >= int(data.get("hits") or 0):
                break
        return out

    def frame(self, country: str):
        """Yields the facts of every row of the country's full list (not the UK: see gb_day)."""
        if country == "IE":
            for rows, r in ckan_rows(self.client, IE_API, IE_RES, KEEP["ie"]):
                self._snap("IE", r, self._nameless(rows, "IE", "company_type", "company_name"))
                yield from (ie_facts(x) for x in rows if x.get("company_num") is not None)
        elif country == "LV":
            liq, ins = {}, {}
            for res, kind, col, index in (
                (LV_LIQ, "lv_liquidation", "legal_entity_registration_number", liq),
                (LV_INS, "lv_insolvency", "debtor_registration_number", ins),
            ):
                fields = [f for f in KEEP[kind] if f in self._columns(LV_API, res, kind)]
                for rows, r in ckan_rows(self.client, LV_API, res, fields):
                    self._snap(f"LV {kind}", r, rows)
                    for x in rows:
                        index.setdefault(str(x.get(col)), []).append(x)
            ends = self.tm["countries"]["LV"]["liquidation_end_fields"]
            for rows, r in ckan_rows(self.client, LV_API, LV_REG, KEEP["lv_register"]):
                self._snap("LV register", r, self._nameless(rows, "LV", "type", "name"))
                for x in rows:
                    if x.get("regcode") is not None:
                        n = str(x["regcode"])
                        yield lv_facts(x, liq.get(n, []), ins.get(n, []), ends)
        elif country == "EE":
            page = fetch(self.client, EE_DOWNLOADS)
            r = fetch(self.client, ee_csv_url(page.text))
            rows = [cut(x, "ee") for x in ee_rows(r.content)]
            self.columns["EE basic data"] = list(KEEP["ee"])
            self._snap("EE", r, self._nameless(rows, "EE", "ettevotja_oiguslik_vorm", "nimi"))
            yield from (ee_facts(x) for x in rows)

    def _nameless(self, rows: list[dict], cc: str, form: str, name: str) -> list[dict]:
        """The rows as they are stored: a business whose legal form is not in the study (a sole
        trader, a farm) keeps its number and status but not its name, which can be a person's."""
        allowed = self.tm["countries"][cc]["legal_forms"]
        return [x if norm(x.get(form)) in allowed else x | {name: None} for x in rows]

    def _columns(self, api: str, resource: str, name: str) -> list[str]:
        if name not in self.columns:
            self.columns[name], _ = ckan_columns(self.client, api, resource)
        return self.columns[name]

    def probe_columns(self) -> None:
        """Column names for frames.json: of the full lists, and of one fixed UK company that has
        insolvency cases (names of fields only; no value of that company is kept)."""
        self._columns(IE_API, IE_RES, "IE Company Records")
        self._columns(LV_API, LV_REG, "LV register")
        number = self.cfg["uk_frame"]["probe_company"]
        p = self._ch(f"/company/{number}", ok404=True)
        self.columns["GB company profile"] = sorted(p.json()) if p.status_code == 200 else []
        i = self._ch(f"/company/{number}/insolvency", ok404=True)
        cases = (i.json().get("cases") or []) if i.status_code == 200 else []
        self.columns["GB insolvency case"] = sorted({k for c in cases for k in c})

    def record(self, country: str, number: str, legal_form: str | None = None) -> dict:
        """One company, read by number: {facts, evidence, copy}. `copy` is the cut-down answer."""
        ev, copy = [], {}

        def note(what: str, r: httpx.Response, url: str | None = None) -> None:
            ev.append(
                {
                    "url": url or str(r.request.url),
                    "fetched_at": lib.iso(lib.now()),
                    "sha256": lib.sha256_bytes(r.content),
                    "what": what,
                }
            )

        if country == "GB":
            p = self._ch(f"/company/{number}", ok404=True)
            profile = p.json() if p.status_code == 200 else None
            note("profile", p, CH_PAGE + number)
            i = self._ch(f"/company/{number}/insolvency", ok404=True)
            insolvency = i.json() if i.status_code == 200 else None
            note("insolvency", i, CH_PAGE + number + "/insolvency")
            copy = {"profile": cut(profile or {}, "gb_profile"), "cases": gb_cases(insolvency)}
            facts = gb_facts(number, profile, insolvency)
        elif country == "IE":
            rows, r = ckan_one(self.client, IE_API, IE_RES, "company_num", number, "ie")
            note("register", r)
            copy = {"register": rows}
            facts = ie_facts(rows[0]) if rows else _missing("IE", number)
        elif country == "LV":
            parts = {}
            for what, res, kind, col in (
                ("register", LV_REG, "lv_register", "regcode"),
                ("liquidation", LV_LIQ, "lv_liquidation", "legal_entity_registration_number"),
                ("insolvency proceedings", LV_INS, "lv_insolvency", "debtor_registration_number"),
            ):
                have = self._columns(LV_API, res, kind) if kind != "lv_register" else KEEP[kind]
                params = {
                    "resource_id": res,
                    "filters": json.dumps({col: int(number)}),
                    "fields": ",".join(f for f in KEEP[kind] if f in have),
                }
                r = fetch(self.client, LV_API, params=params)
                parts[what] = r.json()["result"].get("records") or []
                note(what, r)
            copy = parts
            ends = self.tm["countries"]["LV"]["liquidation_end_fields"]
            facts = (
                lv_facts(
                    parts["register"][0],
                    parts["liquidation"],
                    parts["insolvency proceedings"],
                    ends,
                )
                if parts["register"]
                else _missing("LV", number)
            )
        elif country == "EE":
            # the register's public autocomplete service: the only keyless per-company answer
            r = fetch(self.client, EE_AUTOCOMPLETE, params={"q": number})
            hits = [x for x in r.json().get("data") or [] if str(x.get("reg_code")) == number]
            note("autocomplete", r, EE_PAGE + number)
            copy = {"autocomplete": [cut(x, "ee_auto") for x in hits]}
            facts = _missing("EE", number)
            if hits:  # the service gives status and name; the legal form comes from the listing
                row = {
                    "ariregistri_kood": number,
                    "nimi": hits[0].get("name"),
                    "ettevotja_oiguslik_vorm": legal_form,
                    "ettevotja_staatus": hits[0].get("status"),
                }
                facts = ee_facts(row)
        else:
            raise ValueError(country)
        return {"facts": facts, "evidence": ev, "copy": copy}

    def sanctions(self) -> list[dict]:
        orgs = []
        for name, url in LISTS.items():
            r = fetch(self.client, url)
            found = PARSERS[name](r.content)
            if not found:
                raise ValueError(f"{name}: the file holds no organisation; the format changed")
            self._snap(f"sanctions {name}", r, found)  # organisations only; persons never kept
            orgs += found
        return orgs


class Fixture:
    """The same interface from JSON files in a folder (or a dict of them): --dry-run and the
    offline tests. gb.json {"any_day": [[items], ...], "companies": {number: {profile,
    insolvency}}}: any_day[i] is served for the i-th date asked, so the fixture works for every
    seed. ie.json [rows], lv.json {register, liquidation, insolvency}, ee.json [rows],
    sanctions.json [organisations], meta.json {"reference_date"}."""

    def __init__(self, folder: Path | None, tm: dict, data: dict | None = None):
        self.folder, self.tm, self.data = folder and Path(folder), tm, data
        self.meta, self.columns, self.store = [], {}, None
        self.days_read: list[str] = []

    def _load(self, name: str, default):
        if self.data is not None:
            return self.data.get(name.removesuffix(".json"), default)
        path = self.folder / name
        return lib.read_json(path) if path.is_file() else default

    @property
    def reference_date(self) -> date:
        text = self._load("meta.json", {}).get("reference_date")
        return date.fromisoformat(text) if text else lib.now().date()

    def gb_day(self, day: str) -> list[dict]:
        if day not in self.days_read:
            self.days_read.append(day)
        lists = self._load("gb.json", {}).get("any_day", [])
        i = self.days_read.index(day)
        items = lists[i] if i < len(lists) else []
        return [cut(x | {"date_of_creation": day}, "gb_item") for x in items]

    def _lv(self):
        d = self._load("lv.json", {})
        liq, ins = {}, {}
        for x in d.get("liquidation", []):
            liq.setdefault(str(x["legal_entity_registration_number"]), []).append(x)
        for x in d.get("insolvency", []):
            ins.setdefault(str(x["debtor_registration_number"]), []).append(x)
        return d.get("register", []), liq, ins

    def frame(self, country: str):
        if country == "IE":
            yield from (ie_facts(x) for x in self._load("ie.json", []))
        elif country == "LV":
            reg, liq, ins = self._lv()
            ends = self.tm["countries"]["LV"]["liquidation_end_fields"]
            for x in reg:
                n = str(x["regcode"])
                yield lv_facts(x, liq.get(n, []), ins.get(n, []), ends)
        elif country == "EE":
            yield from (ee_facts(x) for x in self._load("ee.json", []))

    def record(self, country: str, number: str, legal_form: str | None = None) -> dict:
        ev = [
            {
                "url": f"fixture:{country}/{number}",
                "fetched_at": lib.iso(lib.now()),
                "sha256": lib.sha256_text(f"{country}/{number}"),
                "what": "fixture",
            }
        ]
        if country == "GB":
            c = self._load("gb.json", {}).get("companies", {}).get(number)
            facts = gb_facts(number, (c or {}).get("profile"), (c or {}).get("insolvency"))
            copy = {
                "profile": cut((c or {}).get("profile") or {}, "gb_profile"),
                "cases": gb_cases((c or {}).get("insolvency")),
            }
            return {"facts": facts, "evidence": ev, "copy": copy}
        found = [f for f in self.frame(country) if f["number"] == number]
        facts = found[0] if found else _missing(country, number)
        return {"facts": facts, "evidence": ev, "copy": {"facts": facts}}

    def sanctions(self) -> list[dict]:
        return self._load("sanctions.json", [])


# --- the draw -------------------------------------------------------------------------------------


def enabled_countries(cfg: dict) -> list[str]:
    """Estonia only when the owner has confirmed the open-data licence (protocol section 3)."""
    out = []
    for cc, c in cfg["countries"].items():
        gate = c.get("needs")
        if not gate or (cfg.get(gate) or {}).get("checked"):
            out.append(cc)
    return out


def allocate(seed: str, group: str, countries: list[str], n: int) -> dict[str, int]:
    """n split equally over the countries; a remainder goes to countries in hash order."""
    base, rest = divmod(n, len(countries))
    order = sorted(countries, key=lambda c: lib.key(seed, "alloc", group, c))
    return {c: base + (order.index(c) < rest) for c in countries}


def quotas(seed: str, cfg: dict, n: int) -> dict[tuple[str, str], int]:
    countries = enabled_countries(cfg)
    out = {}
    for g in lib.GROUPS:
        cs = [c for c in countries if g in cfg["countries"][c]["groups"]]
        out |= {(c, g): q for c, q in allocate(seed, g, cs, n).items()}
    return out


def gb_dates(seed: str, cfg: dict) -> list[str]:
    a, b = date.fromisoformat(cfg["uk_frame"]["from"]), date.fromisoformat(cfg["uk_frame"]["to"])
    days = [(a + timedelta(days=i)).isoformat() for i in range((b - a).days + 1)]
    return sorted(days, key=lambda d: lib.key(seed, "GB-date", d))


class Cells:
    """Per (country, group): how many companies are in it and its WALK_KEYS smallest keys."""

    def __init__(self, seed: str, tm: dict, window: tuple[str, str]):
        self.seed, self.tm, self.window = seed, tm, window
        self.population: Counter = Counter()
        self.excluded: dict[str, Counter] = {}
        self._heaps: dict[tuple[str, str], list] = {}

    def add(self, facts: dict) -> None:
        cc = facts["country"]
        c = classify(facts, self.tm["countries"][cc], self.window)
        if "group" not in c:  # counted, not listed one by one: sole traders stay out of the log
            why = c.get("skip") or c["out"]
            label = why if why in ("legal_form",) or "out" in c else f"{why}: {c.get('detail')}"
            self.excluded.setdefault(cc, Counter())[label] += 1
            return
        cell = (cc, c["group"])
        self.population[cell] += 1
        k = lib.key(self.seed, cc, facts["number"])
        heap = self._heaps.setdefault(cell, [])
        item = (-int(k, 16), k, facts)  # a max-heap on the key: the largest is dropped first
        if len(heap) < WALK_KEYS:
            heapq.heappush(heap, item)
        elif item[0] > heap[0][0]:
            heapq.heapreplace(heap, item)

    def ranked(self, cell: tuple[str, str]) -> list[tuple[str, dict]]:
        return [(k, f) for _, k, f in sorted(self._heaps.get(cell, []), key=lambda x: x[1])]


def draw_set(source, seed: str, cfg: dict, tm: dict, n: int, ref: date, pilot_ids=()) -> dict:
    """The whole draw from a seed. Deterministic for a given seed and given registers, so a
    network failure half way can be followed by the same command again."""
    months = int(cfg["windows"]["dissolved_within_months"])
    window = (months_before(ref, months).isoformat(), ref.isoformat())
    want = quotas(seed, cfg, n)
    countries = enabled_countries(cfg)
    sanc = Sanctions(source.sanctions(), tm["name_tokens"])
    candidates = sanc.number_candidates(countries)
    cells = Cells(seed, tm, window)
    s_hits: dict[tuple[str, str], dict] = {}  # (country, number) -> listing facts and lists

    def see(facts: dict) -> None:
        cells.add(facts)
        orgs = candidates[facts["country"]].get(facts["number"])
        if orgs and sanc.listed(facts["name"], orgs):
            s_hits[(facts["country"], facts["number"])] = facts

    days_used = []
    if "GB" in countries:
        uk, gb_cells = cfg["uk_frame"], [c for c in want if c[0] == "GB"]
        for day in gb_dates(seed, cfg)[: int(uk["max_dates"])]:
            for item in source.gb_day(day):
                see(gb_item_facts(item))
            days_used.append(day)
            full = all(cells.population[c] >= uk["pool_factor"] * want[c] for c in gb_cells)
            if len(days_used) >= int(uk["min_dates"]) and full:
                break
    for cc in countries:
        if cc != "GB":
            for facts in source.frame(cc):
                see(facts)

    chosen, skips, runner_up, short = [], [], {}, {}
    keep_n = int(cfg["runner_up_keys_per_cell"])
    for cell in sorted(want):
        cc, group = cell
        table, label = tm["countries"][cc], f"{cc}/{group}"
        ranked, fate, taken = cells.ranked(cell), {}, 0
        for k, listed in ranked:
            if taken >= want[cell]:
                break
            cid = f"{cc.lower()}-{listed['number']}"

            def skip(reason, detail=None, k=k, listed=listed, label=label, fate=fate):
                skips.append(
                    {
                        "cell": label,
                        "number": listed["number"],
                        "key": k,
                        "reason": reason,
                        "detail": detail,
                    }
                )
                fate[k] = f"skipped: {reason}"

            if cid in pilot_ids:
                skip("pilot")
                continue
            if lists := sanc.lists_naming(listed["name"]):
                on_number = (cc, listed["number"]) in s_hits
                skip("sanctions_name", f"{', '.join(lists)}; number match: {on_number}")
                continue
            rec = source.record(cc, listed["number"], listed.get("legal_form"))
            c = classify(rec["facts"], table, window)
            if "skip" in c:
                skip(c["skip"], c.get("detail"))
                continue
            if c.get("group") != group:
                skip("ambiguous", f"listing and record disagree: {c.get('out') or c.get('group')}")
                continue
            if lists := sanc.lists_naming(rec["facts"]["name"]):  # the record's own spelling
                skip("sanctions_name", ", ".join(lists))
                continue
            chosen.append(_company(cid, group, k, rec, c["truth"]))
            fate[k] = "selected"
            taken += 1
        if taken < want[cell]:
            short[label] = {"quota": want[cell], "drawn": taken, "keys_walked": len(ranked)}
        runner_up[label] = [
            {"key": k, "number": f["number"], "fate": fate.get(k, "not reached")}
            for k, f in ranked[:keep_n]
        ]

    s_rows, s_left = [], []
    max_s = int(cfg["group_s_max"])
    gb_extra = [(n_, o) for n_, o in candidates.get("GB", {}).items() if ("GB", n_) not in s_hits]
    for number, orgs in sorted(gb_extra):  # UK-listed numbers the date sample did not contain
        rec = source.record("GB", number)
        if rec["facts"]["raw_status"] != "not_found" and sanc.listed(rec["facts"]["name"], orgs):
            s_hits[("GB", number)] = rec["facts"]
    ranked_s = sorted(s_hits, key=lambda x: lib.key(seed, x[0], x[1]))
    for cc, number in ranked_s:
        k = lib.key(seed, cc, number)
        if len(s_rows) >= max_s:
            s_left.append({"country": cc, "number": number, "key": k})
            continue
        rec = source.record(cc, number, s_hits[(cc, number)].get("legal_form"))
        c = classify(rec["facts"], tm["countries"][cc], window, forms=False)
        truth = c.get("truth") or {"status": None, "insolvent": None}  # unmapped: not scored
        lists = sorted(
            {o["list"] for o in candidates[cc][number]}
            | set(sanc.lists_naming(rec["facts"]["name"]))
        )
        truth = truth | {"sanctioned": True, "sanctions_lists": lists}
        s_rows.append(_company(f"{cc.lower()}-{number}", "S", k, rec, truth))

    companies = sorted(chosen + s_rows, key=lambda c: c["id"])
    return {
        "companies": companies,
        "copies": {c["id"]: c.pop("_copy") for c in companies},
        "quotas": {f"{c}/{g}": q for (c, g), q in sorted(want.items())},
        "window": {"from": window[0], "to": window[1]},
        "skips": {
            "population": {f"{c}/{g}": cells.population[(c, g)] for c, g in sorted(want)},
            "not_in_a_cell": {
                cc: dict(sorted(v.items())) for cc, v in sorted(cells.excluded.items())
            },
            "gb_dates": days_used,
            "skips": skips,
            "runner_up": runner_up,
            "shortfalls": short,
            "group_s": {"matched": len(ranked_s), "drawn": len(s_rows), "beyond_the_cap": s_left},
        },
    }


def _company(cid: str, group: str, k: str, rec: dict, truth: dict) -> dict:
    f = rec["facts"]
    return {
        "id": cid,
        "country": f["country"],
        "group": group,
        "number": f["number"],
        "legal_name": f["name"],
        "legal_form": norm(f["legal_form"]),
        "key": k,
        "raw_status": norm(f["raw_status"]),
        "truth": truth,
        "evidence": rec["evidence"],
        "_copy": rec["copy"],
    }


def official_url(company: dict) -> str:
    return company["evidence"][0]["url"]


def audit_rows(seed: str, companies: list[dict], cfg: dict) -> list[dict]:
    """The rows a person opens by hand: 4 per group by hash, and every group S row."""
    per = int(cfg["audit"]["rows_per_group"])
    picked = []
    for g in lib.GROUPS:
        rows = sorted(
            (c for c in companies if c["group"] == g), key=lambda c: lib.key(seed, "audit", c["id"])
        )
        picked += rows[:per]
    picked += [c for c in companies if c["group"] == "S"]
    return [
        {
            "id": c["id"],
            "group": c["group"],
            "country": c["country"],
            "number": c["number"],
            "legal_name": c["legal_name"],
            "official_url": official_url(c),
            "also_open": [e["url"] for e in c["evidence"][1:]],
            "truth": c["truth"],
            "agrees": None,
            "note": "",
        }
        for c in picked
    ]


# --- probe ----------------------------------------------------------------------------------------


def probe(source, cfg: dict, tm: dict, client: httpx.Client | None) -> dict:
    """What the lists look like today: counts, columns, distinct raw values. No company of the
    sample is named or kept: the probe uses fixed test dates and whole-list counts."""
    out = {"version": 1, "probed_at": lib.iso(lib.now()), "sources": {}, "sanctions": {}}

    def tally(cc: str, facts_iter) -> dict:
        status, form, rows = Counter(), Counter(), 0
        for f in facts_iter:
            rows += 1
            status[norm(f["raw_status"])] += 1
            form[norm(f["legal_form"])] += 1
        return {
            "reachable": True,
            "rows": rows,
            "status": dict(sorted(status.items())),
            "legal_form": dict(sorted(form.items())),
        }

    def guarded(name: str, where: dict, fn) -> None:
        try:
            where[name] = fn()
        except (httpx.HTTPError, ValueError, KeyError, zipfile.BadZipFile, ET.ParseError) as e:
            where[name] = {"reachable": False, "error": f"{type(e).__name__}: {str(e)[:200]}"}

    def gb() -> dict:
        days = cfg["uk_frame"]["probe_dates"]
        got = tally("GB", (gb_item_facts(i) for d in days for i in source.gb_day(d)))
        got["test_dates"] = days
        got["key_works"] = True  # gb_day raises on 401/403
        return got

    guarded("GB", out["sources"], gb)
    for cc in ("IE", "LV", "EE"):
        guarded(cc, out["sources"], lambda cc=cc: tally(cc, source.frame(cc)))

    def lists() -> dict:
        orgs = source.sanctions()
        per = Counter(o["list"] for o in orgs)
        numbered = Counter(o["list"] for o in orgs if o["numbers"])
        return {
            "reachable": True,
            "organisations": dict(per),
            "with_a_registration_number": dict(numbered),
        }

    guarded("lists", out["sanctions"], lists)
    if hasattr(source, "probe_columns"):
        try:
            source.probe_columns()
        except (httpx.HTTPError, ValueError, KeyError) as e:
            out["columns_error"] = f"{type(e).__name__}: {str(e)[:200]}"
    out["columns"] = {k: list(v) for k, v in sorted(source.columns.items())}
    out["estonia_included"] = "EE" in enabled_countries(cfg)
    if client is not None:
        try:
            info = drand_get(client, cfg, "info_url")
            out["drand"] = {
                "reachable": True,
                "chain_hash": info.get("hash"),
                "genesis_time": info.get("genesis_time"),
                "period": info.get("period"),
                "scheme": info.get("schemeID"),
                "url": info["_url"],
            }
        except Refused as e:
            out["drand"] = {"reachable": False, "error": str(e)}
    unmapped = {}
    for cc, s in out["sources"].items():
        table = tm["countries"][cc]["status"]
        missing = sorted(v for v in s.get("status", {}) if v not in table)
        if missing:
            unmapped[cc] = missing
    out["status_not_in_truth_map"] = unmapped
    return out


# --- truth, second read ---------------------------------------------------------------------------


def truth2(source, set_file: dict, cfg: dict, tm: dict) -> dict:
    """Read every company again. `changed` when the register facts, the group or the sanctions
    answer no longer match the set: the analysis then leaves the company out and lists it."""
    window = (set_file["window"]["from"], set_file["window"]["to"])
    sanc = Sanctions(source.sanctions(), tm["name_tokens"])
    candidates = sanc.number_candidates(sorted({c["country"] for c in set_file["companies"]}))
    rows = []
    for c in set_file["companies"]:
        rec = source.record(c["country"], c["number"], c.get("legal_form"))
        got = classify(rec["facts"], tm["countries"][c["country"]], window, forms=c["group"] != "S")
        new = got.get("truth") or {"status": None, "insolvent": None}
        orgs = candidates[c["country"]].get(c["number"]) or []
        if c["group"] == "S":
            still = sanc.listed(rec["facts"]["name"], orgs)
            why = None if still else "no longer listed with this number and name"
            new = new | {"sanctioned": still}
        else:
            named = sanc.lists_naming(rec["facts"]["name"])
            why = f"name now on a sanctions list: {', '.join(named)}" if named else None
            if "skip" in got or got.get("group") != c["group"]:
                why = f"register facts changed: {got.get('skip') or got.get('out') or got['group']}"
            new = new | {"sanctioned": bool(named)}
        # the group as the second read finds it (None when the facts are now skipped), so the
        # analysis can recompute `changed` from the values instead of trusting the flag
        new = new | {"group": "S" if c["group"] == "S" else got.get("group")}
        if why is None:
            for f in ("status", "insolvent"):
                if new.get(f) != c["truth"].get(f):
                    why = f"{f} changed from {c['truth'].get(f)} to {new.get(f)}"
        rows.append(
            {
                "id": c["id"],
                "raw_status": norm(rec["facts"]["raw_status"]),
                "truth2": new,
                "changed": why is not None,
                "why": why,
                "evidence": rec["evidence"],
            }
        )
    return {
        "version": 1,
        "seed": set_file["seed"],
        "read_at": lib.iso(lib.now()),
        "companies": rows,
    }


# --- command line ---------------------------------------------------------------------------------


def need_ch_key() -> None:
    """Before any request: a missing key would otherwise show up only at the first Companies
    House call, many minutes in (after the sanctions lists and the other registers)."""
    if not os.environ.get("COMPANIES_HOUSE_API_KEY"):
        raise Refused(
            "COMPANIES_HOUSE_API_KEY is not set: put it in the env file (.env in the repository "
            "root, ~/.bosco/jobs.env, or --env-file <path>)"
        )


def _live(cfg: dict, tm: dict, store: Path | None, client: httpx.Client | None):
    client = client or httpx.Client(timeout=120, follow_redirects=True, headers={"User-Agent": UA})
    return Live(client, os.environ.get("COMPANIES_HOUSE_API_KEY", ""), cfg, tm, store), client


def cmd_probe(args, paths: lib.Paths, client, now) -> int:
    cfg, tm = lib.read_json(paths.config), lib.read_json(paths.truth_map)
    if args.dry_run:
        out = probe(Fixture(args.frames_dir or paths.fixtures / "frames", tm), cfg, tm, None)
        print(json.dumps(out, indent=2, ensure_ascii=False))
        print("dry run: fixture frames, nothing written")
        return 0
    need_ch_key()
    source, client = _live(cfg, tm, None, client)
    out = probe(source, cfg, tm, client)
    lib.write_json(paths.frames, out)
    bad = [
        k
        for k, v in {**out["sources"], **out["sanctions"], "drand": out.get("drand", {})}.items()
        if not v.get("reachable")
    ]
    print(f"wrote {paths.rel(paths.frames)}")
    if out["status_not_in_truth_map"]:
        print("raw statuses missing from truth_map.json (map them or list them as a skip):")
        print(json.dumps(out["status_not_in_truth_map"], indent=2, ensure_ascii=False))
    if bad:
        print("NOT reachable: " + ", ".join(bad))
    return 1 if bad else 0


def _print_set(result: dict) -> None:
    for c in result["companies"]:
        t = c["truth"]
        print(
            f"{c['id']:18} {c['group']} {t['status']!s:11} insolvent={t['insolvent']!s:5} "
            f"sanctioned={t['sanctioned']!s:5} {c['legal_name']}"
        )
    s = result["skips"]
    print(
        f"{len(result['companies'])} companies; quotas {result['quotas']}; "
        f"{len(s['skips'])} skips; shortfalls {s['shortfalls'] or 'none'}"
    )


def cmd_draw(args, paths: lib.Paths, client, now) -> int:
    cfg, tm = lib.read_json(paths.config), lib.read_json(paths.truth_map)
    if args.dry_run:
        seed = lib.sha256_text("dry-run")
        source = Fixture(args.frames_dir or paths.fixtures / "frames", tm)
        _print_set(draw_set(source, seed, cfg, tm, lib.PILOT_COMPANIES // 3, source.reference_date))
        print("dry run: fixture frames, seed sha256('dry-run'), nothing written")
        return 0
    if "GB" in enabled_countries(cfg):
        need_ch_key()
    if args.pilot:
        if paths.pilot_set.exists():
            raise Refused(f"{paths.rel(paths.pilot_set)} exists: the pilot was already drawn")
        seed = lib.sha256_text(cfg["pilot_seed_text"])
        store, head = paths.storage / "pilot", {"pilot": True, "seed_text": cfg["pilot_seed_text"]}
        n, ref, pilot_ids, target = lib.PILOT_COMPANIES // 3, now.date(), set(), paths.pilot_set
        source, client = _live(cfg, tm, store, client)
    else:
        if paths.set.exists():
            raise Refused(f"{paths.rel(paths.set)} exists: there is one draw only")
        if problems := lib.verify_prereg(paths):
            raise Refused("the pre-registration does not verify:\n  " + "\n  ".join(problems))
        frozen = [*lib.manifest_files(paths), paths.prereg]
        if dirty := lib.is_committed_clean(paths.root, frozen):
            raise Refused("not committed as frozen: " + ", ".join(dirty))
        pre = lib.read_json(paths.prereg)
        s = pre["settings"]
        at = lib.parse_time(s["round_time"])
        if now < at:
            raise Refused(f"the beacon round is at {lib.iso(at)}; it is {lib.iso(now)}: wait")
        limit = at + timedelta(hours=cfg["windows"]["draw_within_hours_of_round"])
        if now > limit:
            raise Refused(f"the draw window closed at {lib.iso(limit)}: a new freeze is needed")
        source, client = _live(cfg, tm, None, client)
        beacon = beacon_round(client, cfg, int(s["round"]))
        seed = lib.seed(pre["bundle_hash"], beacon["randomness"])
        source.store = paths.private(seed)
        head = {
            "bundle_hash": pre["bundle_hash"],
            "drand": beacon,
            "freeze_commit": lib.commit_of(paths.root, paths.prereg),
        }
        # the reference date is in the hashed settings (verify checks it is the freeze date)
        n, ref, target = int(s["group_size"]), date.fromisoformat(s["reference_date"]), paths.set
        pilot_ids = set()
        if paths.pilot_set.is_file():
            pilot_ids = {c["id"] for c in lib.read_json(paths.pilot_set)["companies"]}
    result = draw_set(source, seed, cfg, tm, n, ref, pilot_ids)
    for cid, copy in result["copies"].items():  # private: the cut-down register answers
        lib.write_json(source.store / "evidence" / f"{cid}.json", copy)
    set_file = {
        "version": 1,
        "seed": seed,
        **head,
        "drawn_at": lib.iso(now),
        "reference_date": ref.isoformat(),
        "window": result["window"],
        "quotas": result["quotas"],
        "frames": source.meta,
        "companies": result["companies"],
    }
    if args.pilot:
        lib.write_json(target, set_file | {"skips": result["skips"]})
    else:
        lib.write_json(target, set_file)
        lib.write_json(paths.set_skips, {"version": 1, "seed": seed, **result["skips"]})
        rows = audit_rows(seed, result["companies"], cfg)
        how = (
            "Open official_url (and also_open) for each row. Set agrees to true when the page "
            "shows the same status, insolvency and legal name as truth, else false with a "
            "note. Do not edit truth. Rows with agrees false are excluded and listed; more "
            f"than {cfg['audit']['max_disagreements']} among the A, B and C rows aborts the "
            "study."
        )
        lib.write_json(paths.audit, {"version": 1, "seed": seed, "instructions": how, "rows": rows})
    _print_set(result)
    print(f"wrote {paths.rel(target)}; set hash {lib.sha256_norm(target)}")
    if result["skips"]["shortfalls"]:
        print("WARNING: a cell could not be filled; see shortfalls. The draw is not repeated.")
    return 0


def cmd_truth2(args, paths: lib.Paths, client, now) -> int:
    cfg, tm = lib.read_json(paths.config), lib.read_json(paths.truth_map)
    if args.dry_run:
        source = Fixture(args.frames_dir or paths.fixtures / "frames", tm)
        seed = lib.sha256_text("dry-run")
        drawn = draw_set(source, seed, cfg, tm, lib.PILOT_COMPANIES // 3, source.reference_date)
        out = truth2(source, {"seed": seed, **drawn}, cfg, tm)
        print(
            json.dumps(
                [{k: r[k] for k in ("id", "changed", "why")} for r in out["companies"]], indent=1
            )
        )
        print("dry run: fixture frames, nothing written")
        return 0
    if not paths.set.is_file():
        raise Refused(f"{paths.rel(paths.set)} does not exist: nothing was drawn")
    set_file = lib.read_json(paths.set)
    if any(c["country"] == "GB" for c in set_file["companies"]):
        need_ch_key()
    source, client = _live(cfg, tm, None, client)
    out = truth2(source, set_file, cfg, tm)
    target = paths.report_dir(set_file["seed"]) / "truth2.json"
    lib.write_json(target, out)
    changed = [r["id"] for r in out["companies"] if r["changed"]]
    print(f"wrote {paths.rel(target)}; changed since the draw: {changed or 'none'}")
    return 0


def main(argv: list[str] | None = None, root: Path = lib.ROOT, client=None, now=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name, fn in (("probe", cmd_probe), ("draw", cmd_draw), ("truth2", cmd_truth2)):
        p = sub.add_parser(name)
        p.add_argument("--dry-run", action="store_true", help="no network, fixture frames")
        p.add_argument("--env-file", help="KEY=value file (default .env, then ~/.bosco/jobs.env)")
        p.add_argument("--frames-dir", type=Path, help="fixture frames for --dry-run")
        if name == "draw":
            p.add_argument("--pilot", action="store_true", help="6 companies, fixed pilot seed")
        p.set_defaults(fn=fn)
    args = ap.parse_args(argv)
    lib.utf8_stdio()
    paths = lib.Paths(root)
    if not args.dry_run:
        lib.apply_env(args.env_file, paths.root)
    try:
        return args.fn(args, paths, client, now or lib.now())
    except httpx.HTTPError as e:  # after the retries in fetch(): one line, not a traceback
        try:
            where = f" reading {e.request.url.copy_with(query=None)}"
        except RuntimeError:
            where = ""
        print(
            f"network error{where}: {type(e).__name__}: {e}\nNothing is lost: run the same "
            "command again when the connection is back.",
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
