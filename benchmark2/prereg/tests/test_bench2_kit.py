"""Shared helpers for the benchmark 2 tests (no tests in this file): a temporary copy of the
frozen files with its own git history, a scripted model client, and a mock of the registers that
serves the invented companies of tests/fixtures/bench2/frames in the shapes the real ones use."""

import base64
import copy
import io
import json
import shutil
import subprocess
import sys
import zipfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import httpx

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))
import bench2_analyze as analyze  # noqa: E402, F401  (re-exported for the tests)
import bench2_lib as lib  # noqa: E402
import bench2_prereg as prereg  # noqa: E402
import bench2_run as run  # noqa: E402, F401  (re-exported for the tests)
import bench2_sample as sample  # noqa: E402

FRAMES = REPO / "tests" / "fixtures" / "bench2" / "frames"
NOW = datetime(2026, 11, 12, 10, 0, tzinfo=UTC)
ROUND_TIME = NOW + timedelta(hours=30)
SIGNATURE = "ab" * 48
PROBE_COMPANY = lib.read_json(REPO / "data/benchmark2/config.json")["uk_frame"]["probe_company"]


def git(root: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=root, check=True, capture_output=True)


def commit(root: Path, message: str = "x") -> None:
    git(root, "add", "-A")
    git(root, "-c", "user.name=t", "-c", "user.email=t@example.com", "commit", "-qm", message)


def make_root(tmp_path: Path, prices_checked: bool = True) -> lib.Paths:
    """A copy of everything the pre-registration hashes, in its own git repository."""
    root = tmp_path / "repo"
    for rel in (
        "data/benchmark2/config.json",
        "data/benchmark2/truth_map.json",
        "docs/benchmark2/PROTOCOL.md",
    ):
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(REPO / rel, root / rel)
    for pattern, folder in (("bench2_*.py", "tools"), ("test_bench2_*.py", "tests")):
        (root / folder).mkdir(exist_ok=True)
        for f in (REPO / folder).glob(pattern):
            # LF copy: on a CRLF checkout the tests' own LF->CRLF edit would otherwise make \r\r\n
            (root / folder / f.name).write_bytes(f.read_bytes().replace(b"\r\n", b"\n"))
    shutil.copytree(REPO / "tests/fixtures/bench2", root / "tests/fixtures/bench2")
    (root / ".gitignore").write_text("storage/\n", encoding="utf-8")
    paths = lib.Paths(root)
    if prices_checked:
        cfg = lib.read_json(paths.config)
        for price in cfg["prices"].values():
            if isinstance(price, dict):
                price |= {"source": "https://example.com/pricing", "checked": "2026-11-12"}
        lib.write_json(paths.config, cfg)
    git(root, "init", "-q")
    commit(root, "bundle")
    return paths


def write_frames(paths: lib.Paths) -> None:
    """A probe result made from the fixture frames, with the beacon as config.json states it."""
    cfg, tm = lib.read_json(paths.config), lib.read_json(paths.truth_map)
    out = sample.probe(sample.Fixture(FRAMES, tm), cfg, tm, None)
    out["probed_at"] = lib.iso(NOW)  # frames.json is in the bundle: a fixed time, a fixed seed
    d = cfg["drand"]
    out["drand"] = {
        "reachable": True,
        "chain_hash": d["chain_hash"],
        "genesis_time": d["genesis_time"],
        "period": d["period"],
    }
    lib.write_json(paths.frames, out)


def write_pilot_journal(paths: lib.Paths, web=0.15, api=0.07, memory=0.01) -> None:
    journal = lib.Journal(paths.pilot_journal)
    for arm, usd in (("web", web), ("api", api), ("memory", memory)):
        for n in range(2):
            journal.append(
                {
                    "v": 1,
                    "run_id": f"gb-0000000{n}|{arm}|r0",
                    "attempt": 1,
                    "valid": True,
                    "usd": {"total": usd},
                }
            )


def complete_truth_map(paths: lib.Paths) -> None:
    """What the owner does after the probe: the fixture's Irish "receivership" gets an entry."""
    tm = lib.read_json(paths.truth_map)
    tm["countries"]["IE"]["status"].setdefault("receivership", {"skip": "status_not_mapped"})
    lib.write_json(paths.truth_map, tm)


def freeze(paths: lib.Paths, now=NOW, round_time=ROUND_TIME) -> dict:
    complete_truth_map(paths)
    write_frames(paths)
    write_pilot_journal(paths)
    args = ["freeze", "--round-time", lib.iso(round_time), "--api-commit", "abc1234"]
    assert prereg.main(args, root=paths.root, now=now) == 0
    commit(paths.root, "freeze")
    return lib.read_json(paths.prereg)


def beacon(rnd: int) -> dict:
    sig = bytes.fromhex(SIGNATURE)
    return {"round": rnd, "randomness": lib.sha256_bytes(sig), "signature": SIGNATURE}


def drawn_root(tmp_path: Path, audited: bool = True) -> lib.Paths:
    """Frozen, drawn and committed: the fixture companies as set.json, with a seed that
    recomputes from the bundle hash, and an audit file filled in."""
    paths = make_root(tmp_path)
    pre = freeze(paths)
    fixture = lib.read_json(paths.fixtures / "set.json")
    rand = beacon(pre["settings"]["round"])
    seed = lib.seed(pre["bundle_hash"], rand["randomness"])
    drawn_at = ROUND_TIME + timedelta(hours=1)
    lib.write_json(
        paths.set,
        fixture
        | {
            "seed": seed,
            "bundle_hash": pre["bundle_hash"],
            "freeze_commit": lib.commit_of(paths.root, paths.prereg),
            "drand": rand | {"fetched_at": lib.iso(drawn_at)},
            "drawn_at": lib.iso(drawn_at),
        },
    )
    rows = [
        {"id": c["id"], "group": c["group"], "agrees": True if audited else None, "note": ""}
        for c in fixture["companies"]
    ]
    lib.write_json(paths.audit, {"version": 1, "seed": seed, "rows": rows})
    commit(paths.root, "set")
    return paths


# --- a scripted model client ----------------------------------------------------------------------


class Block(SimpleNamespace):
    def model_dump(self):
        return copy.deepcopy(vars(self))


def text(t: str, citations=None) -> Block:
    return Block(type="text", text=t, citations=citations)


def server_use(name: str, **inp) -> Block:
    return Block(type="server_tool_use", id=f"srv_{name}", name=name, input=inp)


def search_result(*urls: str) -> Block:
    content = [{"type": "web_search_result", "url": u, "title": "t"} for u in urls]
    return Block(type="web_search_tool_result", tool_use_id="srv_web_search", content=content)


def search_error(code: str) -> Block:
    content = {"type": "web_search_tool_result_error", "error_code": code}
    return Block(type="web_search_tool_result", tool_use_id="srv_web_search", content=content)


def fetch_result(url: str) -> Block:
    content = {"type": "web_fetch_result", "url": url, "content": {"type": "document"}}
    return Block(type="web_fetch_tool_result", tool_use_id="srv_web_fetch", content=content)


def tool_use(tool_id: str, name: str) -> Block:
    return Block(type="tool_use", id=tool_id, name=name, input={})


def usage(inp=1000, out=100, searches=0, fetches=0, cache_read=0):
    tools = SimpleNamespace(web_search_requests=searches, web_fetch_requests=fetches)
    return SimpleNamespace(
        input_tokens=inp,
        output_tokens=out,
        cache_read_input_tokens=cache_read,
        cache_creation_input_tokens=0,
        server_tool_use=tools,
    )


def reply(blocks, stop="end_turn", use=None):
    blocks = [text(blocks)] if isinstance(blocks, str) else blocks
    return SimpleNamespace(
        content=blocks, stop_reason=stop, usage=use or usage(), _request_id="req_test"
    )


ANSWER = '{"status": "active", "insolvent": false, "sanctioned": false, "sanctions_lists": []}'


class FakeClient:
    """Replies in call order (an exception instance is raised); when they run out, `default`
    answers every further call. Records each request as it was at the time of the call."""

    def __init__(self, replies=(), default=None):
        self.replies, self.default, self.calls = list(replies), default, []
        self.messages = self

    def create(self, **kw):
        self.calls.append(kw | {"messages": list(kw["messages"])})
        got = self.replies.pop(0) if self.replies else self.default
        if got is None:
            raise AssertionError("the model was called more often than scripted")
        if isinstance(got, Exception):
            raise got
        return got(kw) if callable(got) else got


def api_client(handler=None, seen=None, row=None) -> httpx.Client:
    """The product's API: one row with checks and an officers section, unless `handler` says
    otherwise. Requests are appended to `seen`."""
    checks = [
        {
            "check": "register_status",
            "status": "pass",
            "detail": "Active.",
            "source": "register",
            "source_url": "https://register.example/1",
            "checked_at": "2026-11-15T09:00:00+00:00",
        }
    ]
    row = row or {"status": "checked", "checks": checks, "people": [{"name": "A Secret Officer"}]}

    def default(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/health":
            return httpx.Response(200, json={"ok": True, "version": "0.1.0"})
        return httpx.Response(200, json={"rows": [row], "count": 1, "charged_usd": 0.05})

    def serve(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(request)
        got = handler(request) if handler else None
        return got or default(request)

    return httpx.Client(transport=httpx.MockTransport(serve))


# --- a mock of the registers ----------------------------------------------------------------------


def _ckan(request: httpx.Request, rows: list[dict]) -> httpx.Response:
    q = request.url.params
    if "filters" in q:
        want = json.loads(q["filters"])
        rows = [r for r in rows if all(r.get(k) == v for k, v in want.items())]
    columns = list(rows[0]) if rows else []
    total = len(rows)
    start = int(q.get("offset", 0))
    page = rows[start : start + int(q.get("limit", 100))]
    if "fields" in q:
        names = q["fields"].split(",")
        page = [{k: r.get(k) for k in names} for r in page]
    result = {"records": page, "total": total, "fields": [{"id": c} for c in columns]}
    return httpx.Response(200, json={"success": True, "result": result})


class Registers:
    """httpx.MockTransport handler over the fixture frames. `seen` keeps every request."""

    def __init__(self, ch_key: str = "ch-test-key"):
        self.ch_key, self.seen, self.days = ch_key, [], []
        self.gb = lib.read_json(FRAMES / "gb.json")
        self.ie = lib.read_json(FRAMES / "ie.json")
        self.lv = lib.read_json(FRAMES / "lv.json")
        self.ee = lib.read_json(FRAMES / "ee.json")

    def client(self) -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(self), follow_redirects=True)

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.seen.append(request)
        host, path, q = request.url.host, request.url.path, request.url.params
        if host == "api.company-information.service.gov.uk":
            basic = "Basic " + base64.b64encode(f"{self.ch_key}:".encode()).decode()
            if request.headers.get("authorization") != basic:
                return httpx.Response(401, json={"error": "Invalid Authorization"})
            if path == "/advanced-search/companies":
                day = q["incorporated_from"]
                if day not in self.days:
                    self.days.append(day)
                lists, i = self.gb["any_day"], self.days.index(day)
                items = [
                    x | {"date_of_creation": day} for x in (lists[i] if i < len(lists) else [])
                ]
                if not items:
                    return httpx.Response(404, json={"error": "No companies found"})
                return httpx.Response(200, json={"hits": str(len(items)), "items": items})
            number = path.split("/")[2]
            if number == PROBE_COMPANY:  # the probe's fixed company: one with a case
                number = "09100003"
            company = self.gb["companies"].get(number)
            part = "insolvency" if path.endswith("/insolvency") else "profile"
            if not company or not company[part]:
                return httpx.Response(404, json={"errors": [{"error": "not-found"}]})
            return httpx.Response(200, json=company[part])
        if host == "opendata.cro.ie":
            return _ckan(request, self.ie)
        if host == "data.gov.lv":
            table = {
                sample.LV_REG: "register",
                sample.LV_LIQ: "liquidation",
                sample.LV_INS: "insolvency",
            }[q["resource_id"]]
            return _ckan(request, self.lv[table])
        if host == "avaandmed.ariregister.rik.ee":
            if path.endswith(".zip"):
                buf, names = io.StringIO(), list(self.ee[0])
                buf.write(";".join(names) + "\n")
                for r in self.ee:
                    buf.write(";".join(str(r[k]) for k in names) + "\n")
                z = io.BytesIO()
                with zipfile.ZipFile(z, "w") as f:
                    f.writestr("ettevotja_rekvisiidid__lihtandmed.csv", "﻿" + buf.getvalue())
                return httpx.Response(200, content=z.getvalue())
            link = "/sites/default/files/avaandmed/ettevotja_rekvisiidid__lihtandmed.csv.zip"
            return httpx.Response(200, text=f'<a href="{link}">basic data</a>')
        if host == "ariregister.rik.ee":
            hits = [
                {
                    "reg_code": int(r["ariregistri_kood"]),
                    "name": r["nimi"],
                    "status": r["ettevotja_staatus"],
                    "legal_form": "5",
                    "legal_address": "Tallinn, Näidise tn 1",
                }
                for r in self.ee
                if r["ariregistri_kood"] == q["q"]
            ]
            return httpx.Response(200, json={"status": "OK", "data": hits})
        for name, url in sample.LISTS.items():
            if host == httpx.URL(url).host:
                file = {"UK": "uk.xml", "OFAC SDN": "ofac.xml", "EU": "eu.xml"}[name]
                return httpx.Response(200, content=(FRAMES / file).read_bytes())
        if "drand" in host:
            if path.endswith("/info"):
                d = lib.read_json(REPO / "data/benchmark2/config.json")["drand"]
                return httpx.Response(
                    200,
                    json={
                        "hash": d["chain_hash"],
                        "period": d["period"],
                        "genesis_time": d["genesis_time"],
                        "schemeID": "bls-unchained-g1-rfc9380",
                    },
                )
            return httpx.Response(200, json=beacon(int(path.rsplit("/", 1)[1])))
        return httpx.Response(599, text=f"unexpected request: {request.url}")
