"""Shared helpers for benchmark 2 (docs/benchmark2/PROTOCOL.md). Standard library only.

Everything the four scripts must agree on lives here: where files are, how a file is hashed, how
the seed and the per-company keys are derived, how an answer is read and turned into a decision,
and how the pre-registration is checked. A reader who wants to recompute the published numbers
needs this file, tools/bench2_analyze.py and Python, nothing else.
"""

import hashlib
import json
import math
import os
import subprocess
import sys
import threading
import unicodedata
from datetime import UTC, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GROUPS = ("A", "B", "C")  # the headline groups; S is reported on its own
ARMS = ("web", "api", "memory")
SCRIPTS = ("lib", "sample", "prereg", "run", "analyze")
PILOT_COMPANIES = 6


class Paths:
    """Every file of the study, relative to one root (the repo; a temp folder in tests)."""

    def __init__(self, root: Path = ROOT):
        self.root = Path(root)
        self.data = self.root / "data" / "benchmark2"
        self.docs = self.root / "docs" / "benchmark2"
        self.reports = self.root / "reports" / "benchmark2"
        self.storage = self.root / "storage" / "benchmark2"  # ignored by git: private
        self.fixtures = self.root / "tests" / "fixtures" / "bench2"
        self.config = self.data / "config.json"
        self.truth_map = self.data / "truth_map.json"
        self.frames = self.data / "frames.json"
        self.prereg = self.data / "prereg.json"
        self.pilot_set = self.data / "pilot_set.json"
        self.set = self.data / "set.json"
        self.set_skips = self.data / "set_skips.json"
        self.audit = self.data / "audit.json"
        self.protocol = self.docs / "PROTOCOL.md"
        self.pilot_journal = self.storage / "pilot" / "runs.jsonl"

    def private(self, seed: str) -> Path:
        return self.storage / seed[:8]

    def journal(self, seed: str) -> Path:
        return self.private(seed) / "runs.jsonl"

    def report_dir(self, seed: str) -> Path:
        return self.reports / seed[:8]

    def rel(self, path: Path) -> str:
        return Path(path).resolve().relative_to(self.root.resolve()).as_posix()


# --- small file helpers ---------------------------------------------------------------------------


def read_json(path: Path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def write_json(path: Path, obj) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(obj, indent=2, ensure_ascii=False) + "\n"
    with path.open("w", encoding="utf-8", newline="\n") as f:  # LF on Windows too
        f.write(text)


def write_text(path: Path, text: str) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as f:
        f.write(text)


def utf8_stdio() -> None:
    """Print UTF-8 whatever the console's code page is. A Windows console or a redirected output
    may use cp1252, which cannot print a Latvian or Estonian company name and would crash the
    one-shot draw right after it ran. Called first in every script's main()."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError, OSError):
            pass


def now() -> datetime:
    return datetime.now(UTC)


def iso(t: datetime) -> str:
    return t.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def parse_time(text: str) -> datetime:
    """An ISO time; a time without a zone is read as UTC."""
    t = datetime.fromisoformat(str(text).strip().replace("Z", "+00:00"))
    return t if t.tzinfo else t.replace(tzinfo=UTC)


def load_env(path: Path) -> dict[str, str]:
    """KEY=value lines, as tools/run_local_jobs.py reads them. Values are never printed."""
    out = {}
    path = Path(path)
    if path.is_file():
        for line in path.read_text("utf-8-sig").splitlines():
            key, sep, value = line.partition("=")
            if sep and not key.strip().startswith("#") and value.strip():
                out[key.strip()] = value.strip().strip('"').strip("'")
    return out


def apply_env(env_file: str | None, root: Path = ROOT) -> str | None:
    """Put the keys of the env file into this process, without replacing what is already set.
    Looks at --env-file, else .env in the root, else ~/.bosco/jobs.env. Returns the file used."""
    candidates = [Path(env_file)] if env_file else [root / ".env", Path.home() / ".bosco/jobs.env"]
    for path in candidates:
        if path.is_file():
            for k, v in load_env(path).items():
                os.environ.setdefault(k, v)
            return str(path)
    return None


# --- hashes, seed, keys ---------------------------------------------------------------------------


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_text(text: str) -> str:
    return sha256_bytes(text.encode("utf-8"))


def sha256_norm(path: Path) -> str:
    """SHA-256 of the file with CRLF turned into LF, so a Windows checkout hashes the same."""
    return sha256_bytes(Path(path).read_bytes().replace(b"\r\n", b"\n"))


def seed(bundle_hash: str, randomness_hex: str) -> str:
    return sha256_text(f"{bundle_hash}:{randomness_hex}")


def key(seed_hex: str, *parts: str) -> str:
    """The one ranking function: company keys, UK dates, run order, arm order, bootstrap seed."""
    return sha256_text("|".join([seed_hex, *map(str, parts)]))


def round_for(t: datetime, genesis: int, period: int) -> int:
    """The first beacon round emitted at or after `t` (round 1 is emitted at genesis)."""
    secs = max(0, math.ceil(t.timestamp()) - genesis)
    return (secs + period - 1) // period + 1


def round_time(rnd: int, genesis: int, period: int) -> datetime:
    return datetime.fromtimestamp(genesis + (rnd - 1) * period, UTC)


# --- journal --------------------------------------------------------------------------------------


class Journal:
    """Append-only JSON lines. Each line is flushed and synced before the call returns, so a
    crash loses at most the attempt in flight, and a restart continues from what is on disk."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def append(self, obj: dict) -> None:
        line = json.dumps(obj, ensure_ascii=False, separators=(",", ":"))
        with self._lock, self.path.open("a", encoding="utf-8", newline="\n") as f:
            f.write(line + "\n")
            f.flush()
            os.fsync(f.fileno())

    def read(self) -> list[dict]:
        return read_journal(self.path)


def read_journal(path: Path) -> list[dict]:
    """All lines of a journal. A cut-off last line (a crash mid-write) is dropped; a broken line
    anywhere else is an error, because it would silently lose a run."""
    path = Path(path)
    if not path.is_file():
        return []
    lines = [x for x in path.read_text(encoding="utf-8").split("\n") if x.strip()]
    out = []
    for i, line in enumerate(lines):
        try:
            out.append(json.loads(line))
        except ValueError:
            if i != len(lines) - 1:
                raise ValueError(f"{path}: line {i + 1} is not JSON") from None
            print(f"WARNING: {path}: the last line is cut off and was ignored", file=sys.stderr)
    return out


def attempts_by_run(lines: list[dict]) -> dict[str, list[dict]]:
    runs: dict[str, list[dict]] = {}
    for x in lines:
        if x.get("run_id") and "attempt" in x:
            runs.setdefault(x["run_id"], []).append(x)
    return runs


def run_state(attempts: list[dict], max_attempts: int) -> str:
    """valid: an attempt gave a readable answer. failed: every allowed attempt was invalid.
    open: not started or not finished (a restart continues it)."""
    if any(a.get("valid") for a in attempts):
        return "valid"
    return "failed" if len(attempts) >= max_attempts else "open"


def run_id(company_id: str, arm: str, replicate: int) -> str:
    return f"{company_id}|{arm}|r{replicate}"


def paid(x: dict) -> bool:
    """A journal line that carries money: an attempt, or a product call whose attempt was then
    stopped by a fault of the model API (type attempt_aborted, charged but not an attempt)."""
    return "attempt" in x or x.get("type") == "attempt_aborted"


def spent_usd(lines: list[dict]) -> float:
    return sum(float((x.get("usd") or {}).get("total") or 0) for x in lines if paid(x))


def mean_cost_per_run(lines: list[dict]) -> dict[str, float]:
    """Dollars per run for each arm, every attempt counted: {arm: mean}. From a pilot journal."""
    total: dict[str, float] = {}
    runs: dict[str, set] = {}
    for x in lines:
        if x.get("run_id") and paid(x):
            arm = x["run_id"].split("|")[1]
            total[arm] = total.get(arm, 0.0) + float((x.get("usd") or {}).get("total") or 0)
            if "attempt" in x:
                runs.setdefault(arm, set()).add(x["run_id"])
    return {arm: total[arm] / len(runs[arm]) for arm in sorted(total) if runs.get(arm)}


def projected_usd(group_size: int, s_max: int, per_run: dict[str, float]) -> float:
    """Main-run cost at a group size: every company gets two Web runs, two API runs and one
    Memory run; group S is counted at its cap."""
    companies = 3 * group_size + s_max
    return companies * (2 * per_run["web"] + 2 * per_run["api"] + per_run["memory"])


def group_size_rule(cfg: dict, per_run: dict[str, float]) -> tuple[dict[str, float], int | None]:
    """(projected cost per group size, the largest size that fits; None = none fits). Protocol
    section 9. The freeze uses it, and verify recomputes it from the frozen pilot means."""
    s_max = int(cfg["group_s_max"])
    projected = {str(n): round(projected_usd(n, s_max, per_run), 2) for n in cfg["group_sizes"]}
    fits = [n for n in cfg["group_sizes"] if projected[str(n)] <= cfg["projected_max_usd"]]
    return projected, (max(fits) if fits else None)


# --- answers and decisions ------------------------------------------------------------------------


def parse_answer(text: str | None) -> dict | None:
    """The last complete JSON object in the text that has a "status" key, else None. Objects may
    hold nested objects; an object inside another one is not looked at on its own."""
    text = text or ""
    dec = json.JSONDecoder()
    found, i = None, text.find("{")
    while i != -1:
        try:
            obj, end = dec.raw_decode(text, i)
        except ValueError:
            i = text.find("{", i + 1)
            continue
        if isinstance(obj, dict) and "status" in obj:
            found = obj
        i = text.find("{", end)
    return found


def verdicts(answer: dict | None) -> dict:
    """What the answer decides: register and sanctions, each problem, clear or none."""
    a = answer if isinstance(answer, dict) else {}
    status = str(a.get("status") or "").strip().lower()
    insolvent, sanctioned = a.get("insolvent"), a.get("sanctioned")
    if status in ("winding_up", "dissolved") or insolvent is True:
        register = "problem"
    elif status == "active" and insolvent is False:
        register = "clear"
    else:
        register = "none"
    sanctions = "problem" if sanctioned is True else "clear" if sanctioned is False else "none"
    return {"register": register, "sanctions": sanctions}


def correct(group: str, v: dict) -> bool:
    """The right decision (protocol section 7). A needs both all-clears; B and C need the
    register problem; S needs the sanctions problem."""
    if group == "A":
        return v["register"] == "clear" and v["sanctions"] == "clear"
    if group in ("B", "C"):
        return v["register"] == "problem"
    return v["sanctions"] == "problem"


def outcome(group: str, v: dict) -> str:
    if group == "A":
        if v["register"] == "problem" or v["sanctions"] == "problem":
            return "false_alarm"
        return "cleared" if correct("A", v) else "no_verdict"
    side = v["register"] if group in ("B", "C") else v["sanctions"]
    return {"problem": "caught", "clear": "false_all_clear", "none": "no_verdict"}[side]


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """Wilson score interval for k of n, as shares."""
    if n == 0:
        return (0.0, 1.0)
    p = k / n
    centre = p + z * z / (2 * n)
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    denom = 1 + z * z / n
    return (max(0.0, (centre - half) / denom), min(1.0, (centre + half) / denom))


def normalise_name(name: str | None, tokens: list[str]) -> str:
    """A name for comparing a register entry with a sanctions listing: no accents, case or
    punctuation, and without the legal-form words in `tokens` (which may be phrases)."""

    def flat(s: str) -> str:
        s = unicodedata.normalize("NFKD", s or "")
        s = "".join(c for c in s if not unicodedata.combining(c)).casefold()
        return " ".join("".join(c if c.isalnum() else " " for c in s).split())

    text = f" {flat(name)} "
    for t in sorted({flat(t) for t in tokens if flat(t)}, key=len, reverse=True):
        text = text.replace(f" {t} ", " ")
    return " ".join(text.split())


def cost(usage: dict, prices: dict) -> dict:
    """List-price dollars of one attempt's model usage: {"model": tokens, "search": searches}."""

    def p(name: str) -> float:
        return float(prices[name]["value"])

    tokens = (
        usage.get("input_tokens", 0) * p("input")
        + usage.get("cache_creation_input_tokens", 0) * p("input") * p("cache_write_multiplier")
        + usage.get("cache_read_input_tokens", 0) * p("cache_read")
        + usage.get("output_tokens", 0) * p("output")
    )
    return {
        "model": round(tokens / 1e6, 6),
        "search": round(usage.get("web_searches", 0) * p("search"), 6),
    }


# --- git ------------------------------------------------------------------------------------------


def git(root: Path, *args: str) -> str:
    r = subprocess.run(
        ["git", *args], cwd=root, capture_output=True, text=True, encoding="utf-8", check=False
    )
    if r.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)}: {r.stderr.strip()[:300]}")
    return r.stdout.strip()


def head(root: Path) -> str:
    return git(root, "rev-parse", "HEAD")


def commit_of(root: Path, path: Path | str) -> str | None:
    """The last commit that changed the file; None when it was never committed."""
    return git(root, "log", "-1", "--format=%H", "--", str(path)) or None


def is_committed_clean(root: Path, paths: list) -> list[str]:
    """The paths that are not committed exactly as they are on disk ([] = all fine)."""
    bad = []
    for path in paths:
        p = str(path)
        try:
            git(root, "ls-files", "--error-unmatch", "--", p)
            if git(root, "status", "--porcelain", "--", p):
                bad.append(p)
        except RuntimeError:
            bad.append(p)
    return bad


# --- pre-registration -----------------------------------------------------------------------------


def manifest_files(paths: Paths) -> list[Path]:
    """The frozen bundle: protocol, settings, mapping table, probe result, scripts and tests."""
    tools, tests = paths.root / "tools", paths.root / "tests"
    files = [paths.protocol, paths.config, paths.truth_map, paths.frames]
    files += [tools / f"bench2_{name}.py" for name in SCRIPTS]
    files += sorted(tests.glob("test_bench2_*.py"))
    files += sorted(p for p in paths.fixtures.rglob("*") if p.is_file())
    return files


def settings_hash(settings: dict) -> str:
    return sha256_text(json.dumps(settings, sort_keys=True, ensure_ascii=False))


def manifest(paths: Paths, settings: dict) -> dict[str, str]:
    """path -> hash. The numbers fixed at the freeze (round, group size, deployed API commit)
    enter as one more line, so the bundle hash, and with it the seed, covers them too."""
    out = {paths.rel(p): sha256_norm(p) for p in manifest_files(paths)}
    out["prereg:settings"] = settings_hash(settings)
    return out


def bundle_hash(man: dict[str, str]) -> str:
    return sha256_text("".join(f"{k}:{man[k]}\n" for k in sorted(man)))


def verify_prereg(paths: Paths) -> list[str]:
    """Every difference between prereg.json and the files on disk ([] = it verifies)."""
    if not paths.prereg.is_file():
        return [f"{paths.rel(paths.prereg)} does not exist: nothing was frozen"]
    pre = read_json(paths.prereg)
    problems = []
    missing = [paths.rel(p) for p in manifest_files(paths) if not p.is_file()]
    if missing:
        return [f"missing frozen file: {m}" for m in missing]
    have = manifest(paths, pre.get("settings") or {})
    frozen = pre.get("manifest") or {}
    for name in sorted(set(have) | set(frozen)):
        if have.get(name) != frozen.get(name):
            what = "changed" if name in have and name in frozen else "added or removed"
            problems.append(f"{what} since the freeze: {name}")
    if bundle_hash(frozen) != pre.get("bundle_hash"):
        problems.append("bundle_hash is not the hash of the manifest")
    if sha256_norm(paths.config) != pre.get("config_hash"):
        problems.append("config_hash differs from data/benchmark2/config.json")
    s, d = pre.get("settings") or {}, pre.get("drand") or {}
    try:
        want = round_for(parse_time(s["round_time"]), int(d["genesis_time"]), int(d["period"]))
        if want != s.get("round"):
            problems.append(f"round {s.get('round')} is not the round of {s['round_time']}: {want}")
    except (KeyError, ValueError, TypeError):
        problems.append("round_time or the beacon's genesis and period are missing")
    return problems + _verify_settings(paths, pre, s)


def _verify_settings(paths: Paths, pre: dict, s: dict) -> list[str]:
    """The numbers in the hashed settings agree with each other: the freeze came at least the
    required hours before the round, the draw's reference date is the freeze date, and the group
    size follows from the frozen pilot means by the rule of section 9."""
    problems = []
    cfg = read_json(paths.config)
    try:
        frozen, at = parse_time(s["frozen_at"]), parse_time(s["round_time"])
        hours = float(cfg["windows"]["freeze_to_round_min_hours"])
        if at - frozen < timedelta(hours=hours):
            problems.append(f"frozen_at {s['frozen_at']} is less than {hours:g} h before the round")
        if s.get("reference_date") != frozen.date().isoformat():
            problems.append("settings.reference_date is not the date of settings.frozen_at")
        if pre.get("frozen_at") not in (None, s["frozen_at"]):
            problems.append("frozen_at differs from settings.frozen_at")
    except (KeyError, ValueError, TypeError):
        problems.append("settings.frozen_at, reference_date or round_time is missing")
    pilot = s.get("pilot") or {}
    means = pilot.get("mean_usd_per_run") or {}
    if not all(arm in means for arm in ARMS):
        problems.append("settings.pilot.mean_usd_per_run is missing an arm")
    else:
        projected, size = group_size_rule(cfg, means)
        if projected != s.get("projected_usd") or size != s.get("group_size"):
            problems.append(
                f"group size {s.get('group_size')} does not follow from the pilot means "
                f"(the rule gives {size}, projected {projected})"
            )
    if pilot.get("journal_sha256") and paths.pilot_journal.is_file():
        if sha256_norm(paths.pilot_journal) != pilot["journal_sha256"]:
            problems.append("the pilot journal differs from the one the group size came from")
    return problems
