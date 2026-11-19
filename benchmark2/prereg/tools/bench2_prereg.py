"""Benchmark 2 pre-registration: freeze the bundle, verify it, export the public files.

    uv run python tools/bench2_prereg.py freeze --round-time 2026-11-14T12:00:00Z --api-commit <sha>
    uv run python tools/bench2_prereg.py verify
    uv run python tools/bench2_prereg.py export

freeze writes data/benchmark2/prereg.json: a hash of every frozen file (protocol, settings,
mapping table, probe result, the five scripts, the tests), the group size worked out from the
pilot's cost, the drand round of the given time, and the bundle hash over all of that. The seed
of the draw is sha256(bundle hash : randomness of that round), so nothing in the bundle can be
changed after the round without changing the seed.

verify recomputes everything from the files on disk and exits 1 on any difference. A reader with
the public bundle can run it. Neither freeze nor verify uses the network.

export writes the public copy of the runs under reports/benchmark2/<seed8>/. The private journal
keeps the model's full text, the search queries and the API's full response; the public file
keeps the parsed answers, URLs, counts, costs and the API's checks, and a hash of what was left
out.
"""

import argparse
import json
import shutil
import sys
from datetime import UTC, timedelta
from pathlib import Path

import bench2_lib as lib

REMOVED = ("final_text", "search_queries")  # per attempt; api.body goes too
ATTRIBUTION = [
    "Contains public sector information licensed under the Open Government Licence v3.0 "
    "(Companies House; UK Sanctions List, FCDO).",
    "Contains Irish Public Sector Data licensed under a Creative Commons Attribution 4.0 "
    "International (CC BY 4.0) licence (Companies Registration Office, Company Records).",
    "Enterprise Register of Latvia (Uzņēmumu reģistrs) open data, CC0 1.0.",
    "e-Business Register (RIK) open data, CC BY 4.0 (only when Estonia is part of the set).",
    "OFAC SDN List: US Treasury, a US government work; no endorsement by OFAC implied.",
    "EU data: European Commission, Consolidated list of persons, groups and entities subject to "
    "EU financial sanctions; reformatted for matching, names as published. Only the Official "
    "Journal of the EU is authentic.",
    "Randomness: the drand quicknet beacon (League of Entropy).",
]


class Refused(SystemExit):
    """The freeze or export cannot be made as the protocol asks; nothing was written."""


# --- freeze ---------------------------------------------------------------------------------------


def freeze_checks(paths: lib.Paths, cfg: dict, round_time, now) -> tuple[list[str], dict]:
    """(reasons to refuse, the numbers worked out so far). All reasons are collected, so the
    owner sees the whole list at once."""
    why, out = [], {}
    hours = cfg["windows"]["freeze_to_round_min_hours"]
    if round_time < now + timedelta(hours=hours):
        why.append(f"the round time must be at least {hours} h away, so the bundle is public first")
    for name, price in cfg["prices"].items():
        if isinstance(price, dict) and not (price.get("checked") and price.get("source")):
            why.append(f"price {name}: fill in source and checked in config.json")
    tm = lib.read_json(paths.truth_map)
    gate = cfg["ee_licence_confirmed"]["checked"]
    countries = [c for c, v in cfg["countries"].items() if not v.get("needs") or gate]
    out["countries"] = countries
    drand = dict(cfg["drand"])
    if not paths.frames.is_file():
        why.append(f"{paths.rel(paths.frames)} is missing: run bench2_sample.py probe")
    else:
        frames = lib.read_json(paths.frames)
        for cc in countries:
            src = (frames.get("sources") or {}).get(cc) or {}
            if not src.get("reachable"):
                why.append(f"probe: {cc} was not reachable")
            missing = sorted(
                s for s in src.get("status", {}) if s not in tm["countries"][cc]["status"]
            )
            if missing:
                why.append(f"truth_map.json has no entry for {cc} status: {', '.join(missing)}")
        if not ((frames.get("sanctions") or {}).get("lists") or {}).get("reachable"):
            why.append("probe: the sanctions lists were not reachable")
        seen = frames.get("drand") or {}
        if not seen.get("reachable"):
            why.append("probe: the drand beacon was not reachable")
        else:
            for k, name in (
                ("chain_hash", "chain_hash"),
                ("genesis_time", "genesis_time"),
                ("period", "period"),
            ):
                if str(seen.get(k)) != str(drand[name]):
                    why.append(f"drand {name}: config says {drand[name]}, the beacon {seen.get(k)}")
    out["drand"] = {k: drand[k] for k in ("beacon", "chain_hash", "genesis_time", "period")}
    out["round"] = lib.round_for(round_time, int(drand["genesis_time"]), int(drand["period"]))
    pilot = lib.read_journal(paths.pilot_journal)
    means = lib.mean_cost_per_run(pilot)
    if not all(arm in means for arm in lib.ARMS):
        why.append(f"no pilot journal with all three arms at {paths.rel(paths.pilot_journal)}")
        means = {a: cfg["estimates_usd_per_run"][a] for a in lib.ARMS} | means
        out["pilot"] = {"measured": False}
    else:
        out["pilot"] = {"measured": True, "journal_sha256": lib.sha256_norm(paths.pilot_journal)}
    out["pilot"]["mean_usd_per_run"] = {a: round(means[a], 5) for a in lib.ARMS}
    out["projected_usd"], size = lib.group_size_rule(cfg, out["pilot"]["mean_usd_per_run"])
    if size is not None:
        out["group_size"] = size
    else:
        why.append(
            f"no group size fits ${cfg['projected_max_usd']}: {out['projected_usd']}. "
            "The study is not run on this budget."
        )
    return why, out


def cmd_freeze(args, paths: lib.Paths, now) -> int:
    cfg = lib.read_json(paths.config)
    round_time = lib.parse_time(args.round_time)
    why, got = freeze_checks(paths, cfg, round_time, now)
    if paths.set.exists():
        why.append(
            f"{paths.rel(paths.set)} exists: the draw was made; a new attempt needs new files"
        )
    if not args.api_commit and not args.dry_run and sys.stdin.isatty():
        args.api_commit = input("Commit of counterparty-check that is deployed now: ").strip()
    if not args.api_commit:
        why.append("--api-commit: give the commit of counterparty-check that is deployed now")
    missing = [paths.rel(p) for p in lib.manifest_files(paths) if not p.is_file()]
    why += [f"missing frozen file: {m}" for m in missing]
    if args.dry_run or why:
        print(json.dumps(got, indent=2))
    if why and not args.dry_run:
        raise Refused("freeze refused:\n  " + "\n  ".join(why))
    # Everything the draw and the group size depend on goes into the hashed settings: the
    # freeze time (it sets the reference date of group C's 24-month window) and the pilot's
    # figures. verify checks that they agree with each other and with the round time.
    settings = {
        "frozen_at": lib.iso(now),
        "reference_date": now.astimezone(UTC).date().isoformat(),
        "round_time": lib.iso(round_time),
        "round": got["round"],
        "group_size": got.get("group_size"),
        "api_commit": args.api_commit,
        "countries": got["countries"],
        "pilot": got["pilot"],
        "projected_usd": got["projected_usd"],
    }
    man = {} if missing else lib.manifest(paths, settings)
    pre = {
        "version": 1,
        "frozen_at": lib.iso(now),
        "settings": settings,
        "drand": got["drand"],
        "pilot": got["pilot"],
        "projected_usd": got["projected_usd"],
        "prices": cfg["prices"],
        "caps": cfg["caps"],
        "config_hash": lib.sha256_norm(paths.config),
        "manifest": man,
        "bundle_hash": lib.bundle_hash(man),
    }
    if args.dry_run:
        print(
            f"would freeze round {settings['round']} ({settings['round_time']}), group size "
            f"{settings['group_size']}, {len(man)} files, bundle hash {pre['bundle_hash']}"
        )
        for w in why:
            print(f"would refuse: {w}")
        print("dry run: nothing written")
        return 0
    lib.write_json(paths.prereg, pre)
    print(
        f"wrote {paths.rel(paths.prereg)}\nbundle hash {pre['bundle_hash']}\n"
        f"round {settings['round']} at {settings['round_time']}, group size "
        f"{settings['group_size']}\nNow commit, publish the bundle and its hash, and make a "
        "web-archive capture before the round."
    )
    return 0


# --- verify ---------------------------------------------------------------------------------------


def cmd_verify(args, paths: lib.Paths, now) -> int:
    problems = lib.verify_prereg(paths)
    if not problems and paths.set.is_file():
        pre, s = lib.read_json(paths.prereg), lib.read_json(paths.set)
        if s.get("bundle_hash") != pre["bundle_hash"]:
            problems.append("set.json was drawn from another bundle hash")
        elif s.get("seed") != lib.seed(pre["bundle_hash"], s["drand"]["randomness"]):
            problems.append("the seed in set.json is not sha256(bundle hash : randomness)")
        elif s["drand"]["round"] != pre["settings"]["round"]:
            problems.append("set.json used another beacon round than the frozen one")
    for p in problems:
        print(f"DIFFERS: {p}")
    if not problems:
        pre = lib.read_json(paths.prereg)
        print(
            f"verified: {len(pre['manifest'])} entries, bundle hash {pre['bundle_hash']}, round "
            f"{pre['settings']['round']} at {pre['settings']['round_time']}"
        )
    return 1 if problems else 0


# --- export ---------------------------------------------------------------------------------------


def public_line(line: dict) -> dict:
    """A journal line without the model's text, the search queries and the API's full body.
    Hashes of what was removed stay, so the private file can later be shown to match."""
    if "attempt" not in line:
        return line
    out = {k: v for k, v in line.items() if k not in REMOVED}
    out["final_text_sha256"] = lib.sha256_text(line.get("final_text") or "")
    queries = line.get("search_queries") or []
    out["search_queries_count"] = len(queries)
    out["search_queries_sha256"] = lib.sha256_text(json.dumps(queries, ensure_ascii=False))
    if isinstance(line.get("api"), dict):
        api = {k: v for k, v in line["api"].items() if k != "body"}
        # the officers check names people in its detail text: keep its verdict, drop the text
        api["checks"] = [
            c | ({"detail": None} if "people" in str(c.get("check")) else {})
            for c in api.get("checks") or []
        ]
        out["api"] = api
    return out


def has_key(obj, names: tuple) -> bool:
    if isinstance(obj, dict):
        return any(k in names or has_key(v, names) for k, v in obj.items())
    return isinstance(obj, list) and any(has_key(v, names) for v in obj)


def public_jsonl(lines: list[dict]) -> str:
    out = [public_line(x) for x in lines]
    if any(has_key(x, (*REMOVED, "people", "body")) for x in out):
        raise Refused("export stopped: a public line still holds text, queries, a body or people")
    return "".join(json.dumps(x, ensure_ascii=False, separators=(",", ":")) + "\n" for x in out)


def readme(seed: str, files: list[str]) -> str:
    listing = "\n".join(f"- `{f}`" for f in sorted(files))
    folder = f"reports/benchmark2/{seed[:8]}"
    notes = "\n".join(f"- {a}" for a in ATTRIBUTION)
    return f"""# Counterparty-check benchmark 2: public files of draw {seed[:8]}

A vendor benchmark by Bosco Labs. The protocol, the scripts and the frozen settings are in the
repository this folder belongs to (`docs/benchmark2/PROTOCOL.md`, `tools/bench2_*.py`,
`data/benchmark2/`). Seed: `{seed}`.

## Files

{listing}

`runs_public.jsonl` is the run journal without the model's full text, the search queries and the
API's full response; each line carries a hash of what was left out. Company names are published
as the registers show them. Nothing else about persons is stored or published: no officers, no
addresses, no insolvency practitioners.

## Recompute the report

    python tools/bench2_prereg.py verify
    python tools/bench2_analyze.py --dry-run --journal {folder}/runs_public.jsonl

The second command needs only Python and the files named above.

## Sources and attribution

{notes}

The answer key was read from these official sources by `tools/bench2_sample.py`; it is a copy
of public register facts on the fetch dates given in `set.json` and `truth2.json`, not legal
advice, and registers change daily.
"""


def cmd_export(args, paths: lib.Paths, now) -> int:
    set_path = paths.set
    journal_path = None
    if not set_path.is_file():
        if not args.dry_run:
            raise Refused(f"{paths.rel(paths.set)} does not exist: nothing to export")
        set_path, journal_path = paths.fixtures / "set.json", paths.fixtures / "runs.jsonl"
        print("no set.json yet: showing the export on the test fixture")
    seed = lib.read_json(set_path)["seed"]
    out = paths.report_dir(seed)
    lines = lib.read_journal(journal_path or paths.journal(seed))
    if not lines and not args.dry_run:
        raise Refused(f"no journal at {paths.journal(seed)}")
    texts = {"runs_public.jsonl": public_jsonl(lines)}
    if pilot := lib.read_journal(paths.pilot_journal):
        texts["pilot_runs_public.jsonl"] = public_jsonl(pilot)
    copies = {
        "set.json": set_path,
        "set_skips.json": paths.set_skips,
        "audit.json": paths.audit,
        "prereg.json": paths.prereg,
        "pilot_set.json": paths.pilot_set,
        "CHANGES.md": paths.docs / "CHANGES.md",
    }
    copies = {name: p for name, p in copies.items() if p.is_file()}
    made = ["truth2.json", "report.md", "report.json"]  # written there by the other scripts
    absent = [m for m in made if not (out / m).is_file()]
    files = [*texts, *copies, *[m for m in made if m not in absent], "README.md"]
    texts["README.md"] = readme(seed, files)
    if args.dry_run:
        print(f"would write to {paths.rel(out)}: {', '.join(sorted(files))}")
        print(f"{len(lines)} journal lines; first public line:")
        print(texts["runs_public.jsonl"].split("\n")[0][:600])
        print("dry run: nothing written")
        return 0
    for name, text in texts.items():
        lib.write_text(out / name, text)
    for name, src in copies.items():
        shutil.copyfile(src, out / name)
    print(f"wrote {len(files)} files to {paths.rel(out)}")
    if absent:
        print(f"NOT there yet (run truth2 and analyze first): {', '.join(absent)}")
    return 0


def main(argv: list[str] | None = None, root: Path = lib.ROOT, now=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name, fn in (("freeze", cmd_freeze), ("verify", cmd_verify), ("export", cmd_export)):
        p = sub.add_parser(name)
        p.add_argument("--dry-run", action="store_true", help="print, write nothing")
        p.add_argument("--env-file", help="accepted for symmetry; this script needs no keys")
        if name == "freeze":
            p.add_argument("--round-time", required=True, help="UTC, e.g. 2026-11-14T12:00:00Z")
            p.add_argument("--api-commit", help="commit of counterparty-check deployed now")
        p.set_defaults(fn=fn)
    args = ap.parse_args(argv)
    lib.utf8_stdio()
    return args.fn(args, lib.Paths(root), now or lib.now())


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
