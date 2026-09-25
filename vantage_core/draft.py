"""Authorized custom authoring — scan their artifacts → draft Core contracts.

Partners grant a local repo, tests, and/or a one-shot ingest export
(or ``grant`` / ``draft --grant`` snapshots). We propose 3–5 *custom*
``runtimeai.contract/v1`` paths from *their* strings.
They Accept / Skip / Refine.

Auto-write = no Accept + continuous bar sync — not us.
Grant snapshot (API key / PAT) ≠ auto-write.
"""

from __future__ import annotations

import json
import os
import re
import shutil
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from vantage_core.ingest_priors import PRIORS

CONTRACT_SCHEMA = "runtimeai.contract/v1"
MANIFEST_SCHEMA = "runtimeai.draft_manifest/v1"
MANIFEST_NAME = "draft_manifest.json"
DEFAULT_DRAFTS_DIR = "contracts_drafts"
DEFAULT_CONTRACTS_DIR = "contracts"
DEFAULT_SUITE = "suites/starter.suite.yaml"

SKIP_DIRS = frozenset(
    {
        ".git",
        ".hg",
        ".svn",
        ".venv",
        "venv",
        "node_modules",
        "dist",
        "build",
        "coverage",
        "__pycache__",
        ".mypy_cache",
        ".pytest_cache",
        ".tox",
        ".next",
        "vendor",
        "site-packages",
        ".cursor",
        ".idea",
        "eggs",
        ".eggs",
        # App local data / PHI — never grant or draft from these (e.g. beatit/data/patients)
        "data",
        "uploads",
        "patients",
    }
)
SKIP_SUFFIXES = frozenset(
    {
        ".pyc",
        ".pyo",
        ".so",
        ".dylib",
        ".woff",
        ".woff2",
        ".png",
        ".jpg",
        ".jpeg",
        ".gif",
        ".webp",
        ".ico",
        ".pdf",
        ".zip",
        ".gz",
        ".whl",
        ".lock",
        ".min.js",
        ".map",
        ".svg",
    }
)
SKIP_NAMES = frozenset(
    {
        "package-lock.json",
        "yarn.lock",
        "pnpm-lock.yaml",
        "poetry.lock",
        "Cargo.lock",
        "go.sum",
        "Gemfile.lock",
        ".env",
        ".env.local",
        ".env.production",
    }
)
CODE_SUFFIXES = frozenset(
    {
        ".py",
        ".ts",
        ".tsx",
        ".js",
        ".jsx",
        ".mjs",
        ".cjs",
        ".go",
        ".rs",
        ".rb",
        ".java",
        ".kt",
        ".swift",
        ".php",
        ".md",
        ".html",
        ".vue",
        ".svelte",
    }
)
TEST_NAME_RE = re.compile(
    r"(^test_.*\.py$|.*_test\.py$|.*\.test\.(ts|tsx|js|jsx)$|.*_test\.go$|.*\.spec\.(ts|tsx|js)$)",
    re.I,
)
LLM_SITE_RE = re.compile(
    r"chat\.completions|ChatCompletion|from openai import|import openai|"
    r"\bOpenAI\b|\banthropic\b|\bAnthropic\b|\bopenrouter\b|\bOpenRouter\b|"
    r"\bollama\b|OPENROUTER_MODEL|OPENAI_MODEL|ANTHROPIC_MODEL|"
    r"OPENROUTER_API_KEY|openai\.chat|\bllm\.complete\b|\.complete\(\s*['\"`]",
    re.I,
)
POLICY_NAME_RE = re.compile(
    r"(?:^|_)("
    r"SYSTEM(?:_PROMPT)?|system_prompt|SOURCE_ATTRIBUTION\w*|PALLIATIVE\w*|"
    r"POLICY\w*|PROMPT\w*|RETAIN\w*|PLANNER\w*|EXCLUSION\w*"
    r")(?:_|$)",
)
# Named consts built as 'a' + 'b' + 'c' (common in front-end system prompts)
CONCAT_MORE_RE = re.compile(r"""\s*\+\s*(?P<q>'''|\"\"\"|`|'|\")""")
COMPLETE_FIRST_ARG_RE = re.compile(
    r"""\.complete\(\s*(?P<q>'|\"|`)""",
)
NAMED_STRING_RE = re.compile(
    r"^[ \t]*(?:export\s+)?(?:(?:const|let|var|final)\s+)?"
    r"(?P<name>[A-Z][A-Z0-9_]{2,}|system_prompt|SYSTEM_PROMPT|SYSTEM)"
    r"(?:\s*:\s*[^=\n]+?)?"
    r"\s*[:=]\s*"
    r"(?P<q>'''|\"\"\"|`|'|\")",
    re.M,
)
SYSTEM_PROP_RE = re.compile(
    r"""(?:role\s*[:=]\s*['\"]system['\"].{0,80}|system\s*[:=]\s*)(?P<q>'''|\"\"\"|`|'|\")""",
    re.I | re.S,
)
ASSERT_RE = re.compile(
    r"""(?:assert\s+|assertIn\(|\.toContain\(|\.toHaveText\(|\.includes\(|t\.Contains\()"""
    r"""\s*(['\"])(?P<lit>(?:\\.|(?!\1).){2,120})\1""",
)
NEVER_RE = re.compile(
    r"(?:never (?:use|mention|say|include|write)|do not (?:use|mention|say)|"
    r"must not (?:use|mention|say)|ABSOLUTE EXCLUSION[:\s]+)"
    r"(?P<body>[^\n.]{3,160})",
    re.I,
)
REQUIRED_TOKEN_RE = re.compile(
    r"(\[SOURCE:[^\]]+\]|\[PLANNER:[^\]]+\]|\[RET(?:AIN)?[^\]]*\]|"
    r"DOC-[A-Z0-9]+|POL-[A-Z0-9]+)",
)
SECRET_RE = re.compile(
    r"(sk-or-[A-Za-z0-9_-]{8,}|sk-ant-[A-Za-z0-9_-]{8,}|"
    r"sk-[A-Za-z0-9]{20,}|Bearer\s+[A-Za-z0-9._\-]+)",
    re.I,
)
# Prefix literals in startsWith('sk-or-') helpers — never ship into drafts
SECRET_PREFIX_RE = re.compile(r"(?i)sk-(?:or|ant)-")
ENV_ASSIGN_RE = re.compile(
    r"(?i)(?:api[_-]?key|secret|token|password|passwd)\s*[:=]\s*\S+"
)
KEY_HELPER_NAME_RE = re.compile(
    r"(api[-_]?key|auth[-_]?token|credentials?|secret[-_]?store)",
    re.I,
)
LIBRARY_IDS = (
    "de_sql_optimization_v1",
    "healthcare_prior_auth_v1",
    "healthcare_scheduling_ops_v1",
    "fintech_kyc_compliance_v1",
    "de_pipeline_incident_v1",
    "support_escalation_v1",
)
REFUSE_AWARE_TOPICS = (
    "stage iv",
    "stage 4",
    "stage iv.",
    "metastasis",
    "metastases",
    "tumor",
    "tumour",
    "cancer",
    "oncology",
)
ABSOLUTE_EXCLUSION_OK = (
    "palliative",
    "hospice",
    "comfort care",
    "end-of-life",
    "end of life",
)
MAX_FILE_BYTES = 200_000
MAX_SYSTEM_CHARS = 2200
MAX_PATHS = 5
MIN_LITERAL = 4

_ACTIONS = frozenset({"list", "show", "accept", "skip", "refine"})


@dataclass
class ExtractedString:
    name: str
    value: str
    path: Path
    kind: str = "policy"  # policy | system | opening


@dataclass
class TestOracle:
    path: Path
    literal: str
    line: int


@dataclass
class LlmSite:
    path: Path
    line: int
    snippet: str


@dataclass
class ScanResult:
    root: Path
    prefix: str
    llm_sites: list[LlmSite] = field(default_factory=list)
    strings: list[ExtractedString] = field(default_factory=list)
    oracles: list[TestOracle] = field(default_factory=list)
    files_scanned: int = 0


@dataclass
class DraftProposal:
    id: str
    slug: str
    name: str
    system: str
    opening: str
    checks: list[dict[str, Any]]
    sources: list[str]
    quiet_miss: str
    confidence: float
    refuse_aware_note: str = ""
    prior_hint: str = ""
    status: str = "draft"

    def as_manifest_row(self, filename: str) -> dict[str, Any]:
        return {
            "id": self.id,
            "slug": self.slug,
            "file": filename,
            "name": self.name,
            "sources": self.sources,
            "quiet_miss": self.quiet_miss,
            "confidence": round(self.confidence, 3),
            "status": self.status,
        }


def redact_secrets(text: str) -> str:
    """Strip API keys / secret assignments. Never copy .env contents."""
    out = SECRET_RE.sub("[REDACTED]", text)
    out = ENV_ASSIGN_RE.sub("[REDACTED]", out)
    # Key-prefix detectors (startsWith('sk-or-')) must not land in contracts
    out = SECRET_PREFIX_RE.sub("[REDACTED]", out)
    return out


def _is_key_helper_file(path: Path) -> bool:
    """Credential helpers are not critical-path policy."""
    return bool(KEY_HELPER_NAME_RE.search(path.name))


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _slug(text: str, *, fallback: str = "path") -> str:
    s = re.sub(r"[^a-z0-9]+", "_", (text or "").lower()).strip("_")
    s = re.sub(r"_+", "_", s)[:48].strip("_")
    return s or fallback


def _repo_prefix(root: Path) -> str:
    name = _slug(root.name, fallback="app")
    if name in {"src", "lib", "app", "code", "repo"}:
        parent = _slug(root.parent.name, fallback="app")
        if parent not in {"src", "lib", "desktop", "users"}:
            name = parent
    if name.startswith("team"):
        return name
    return name or "app"


def _rel(path: Path, root: Path) -> str:
    try:
        return str(path.resolve().relative_to(root.resolve()))
    except ValueError:
        return path.name


def _should_skip_dir(name: str) -> bool:
    return name in SKIP_DIRS or name.startswith(".")


def _is_probably_minified(path: Path) -> bool:
    n = path.name.lower()
    return n.endswith(".min.js") or n.endswith(".min.css") or ".min." in n


def _is_test_file(path: Path) -> bool:
    return bool(TEST_NAME_RE.match(path.name))


def _test_constrains_model(path: Path, text: str) -> bool:
    blob = f"{path.name}\n{text[:4000]}".lower()
    if "healthz" in path.name.lower() or "health_check" in path.name.lower():
        return False
    hints = (
        "llm",
        "model",
        "prompt",
        "golden",
        "agent",
        "openai",
        "anthropic",
        "openrouter",
        "completion",
        "system prompt",
        "chat.completions",
    )
    return any(h in blob for h in hints)


def iter_scan_files(root: Path, *, extra_tests: Path | None = None) -> list[Path]:
    """Deterministic file walk. Skip VCS, deps, minified, secrets, lockfiles."""
    out: list[Path] = []
    roots = [root]
    if extra_tests is not None:
        extra = extra_tests.expanduser().resolve()
        if extra.exists() and extra not in roots:
            roots.append(extra)

    for base in roots:
        if base.is_file():
            out.append(base)
            continue
        if not base.is_dir():
            continue
        for dirpath, dirnames, filenames in os.walk(base):
            dirnames[:] = sorted(d for d in dirnames if not _should_skip_dir(d))
            for name in sorted(filenames):
                if name in SKIP_NAMES or name.startswith(".env"):
                    continue
                path = Path(dirpath) / name
                suf = path.suffix.lower()
                if suf in SKIP_SUFFIXES or _is_probably_minified(path):
                    continue
                if suf not in CODE_SUFFIXES and not _is_test_file(path):
                    continue
                try:
                    if path.stat().st_size > MAX_FILE_BYTES:
                        continue
                except OSError:
                    continue
                out.append(path)
    # stable unique
    seen: set[Path] = set()
    unique: list[Path] = []
    for p in out:
        r = p.resolve()
        if r in seen:
            continue
        seen.add(r)
        unique.append(p)
    return unique


def _close_quote(text: str, start: int, q: str) -> str:
    if q in ("'''", '"""'):
        end = text.find(q, start)
        if end < 0:
            return text[start : start + MAX_SYSTEM_CHARS]
        return text[start:end]
    if q == "`":
        end = text.find("`", start)
        if end < 0:
            return text[start : start + MAX_SYSTEM_CHARS]
        return text[start:end]
    # single-char quotes — stop at unescaped
    i = start
    while i < len(text):
        ch = text[i]
        if ch == "\\" and i + 1 < len(text):
            i += 2
            continue
        if ch == q:
            return text[start:i]
        if ch == "\n" and q in ("'", '"'):
            return text[start:i]
        i += 1
    return text[start : start + MAX_SYSTEM_CHARS]


def _unescape_js_fragment(raw: str) -> str:
    """Turn source fragments ('…\\n' + '…') into readable policy text."""
    out = raw.replace("\\n", "\n").replace("\\t", "\t").replace("\\'", "'").replace('\\"', '"')
    out = out.replace("\\`", "`")
    return out


def _read_string_literal_chain(text: str, start: int, q: str) -> tuple[str, int]:
    """Read one quoted literal and any immediate + '…' concatenations."""
    parts: list[str] = []
    frag = _close_quote(text, start, q)
    parts.append(frag)
    pos = start + len(frag) + len(q)
    while True:
        m = CONCAT_MORE_RE.match(text, pos)
        if not m:
            break
        q2 = m.group("q")
        next_start = m.end()
        frag2 = _close_quote(text, next_start, q2)
        parts.append(frag2)
        pos = next_start + len(frag2) + len(q2)
        if sum(len(p) for p in parts) >= MAX_SYSTEM_CHARS:
            break
    joined = _unescape_js_fragment("".join(parts))
    return joined[:MAX_SYSTEM_CHARS], pos


def _looks_like_agent_policy(text: str) -> bool:
    low = (text or "").lower()
    if len(low) < 40:
        return False
    cues = (
        "you are",
        "you help",
        "never ",
        "must not",
        "do not ",
        "json only",
        "[source:",
        "[planner:",
        "absolute exclusion",
        "return json",
        "system prompt",
        "study agent",
        "research assistant",
    )
    return any(c in low for c in cues)


def _extract_named_strings(path: Path, text: str) -> list[ExtractedString]:
    found: list[ExtractedString] = []
    seen: set[str] = set()

    def _keep(name: str, value: str, kind: str) -> None:
        key = re.sub(r"\s+", " ", value)[:120]
        if key in seen:
            return
        seen.add(key)
        found.append(ExtractedString(name=name, value=value, path=path, kind=kind))

    for m in NAMED_STRING_RE.finditer(text):
        name = m.group("name")
        if not POLICY_NAME_RE.search(name) and name not in {"SYSTEM", "SYSTEM_PROMPT", "system_prompt"}:
            # Keep long ALL_CAPS policy-looking names
            if not (name.isupper() and len(name) >= 6):
                continue
        q = m.group("q")
        raw, _ = _read_string_literal_chain(text, m.end(), q)
        value = redact_secrets(raw).strip()
        if len(value) < 24:
            continue
        kind = "system" if "system" in name.lower() or "prompt" in name.lower() else "policy"
        _keep(name, value, kind)
    for m in SYSTEM_PROP_RE.finditer(text):
        q = m.group("q")
        raw, _ = _read_string_literal_chain(text, m.end(), q)
        value = redact_secrets(raw).strip()
        if len(value) < 40:
            continue
        _keep("system", value, "system")
    for m in COMPLETE_FIRST_ARG_RE.finditer(text):
        q = m.group("q")
        raw, _ = _read_string_literal_chain(text, m.end(), q)
        value = redact_secrets(raw).strip()
        if len(value) < 40 or not _looks_like_agent_policy(value):
            continue
        _keep("system", value, "system")
    return found


def _extract_oracles(path: Path, text: str) -> list[TestOracle]:
    out: list[TestOracle] = []
    if not _test_constrains_model(path, text):
        return out
    for m in ASSERT_RE.finditer(text):
        lit = m.group("lit").encode("utf-8").decode("unicode_escape", errors="replace")
        lit = redact_secrets(lit).strip()
        if len(lit) < MIN_LITERAL:
            continue
        if SECRET_RE.search(lit):
            continue
        line = text[: m.start()].count("\n") + 1
        out.append(TestOracle(path=path, literal=lit, line=line))
    return out


def scan_repo(
    root: str | Path,
    *,
    tests: str | Path | None = None,
) -> ScanResult:
    """Walk an authorized local tree. No remotes."""
    base = Path(root).expanduser().resolve()
    extra = Path(tests).expanduser().resolve() if tests else None
    result = ScanResult(root=base, prefix=_repo_prefix(base))
    for path in iter_scan_files(base, extra_tests=extra):
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        result.files_scanned += 1
        if LLM_SITE_RE.search(text):
            line = 1
            for i, row in enumerate(text.splitlines(), start=1):
                if LLM_SITE_RE.search(row):
                    line = i
                    break
            result.llm_sites.append(
                LlmSite(path=path, line=line, snippet=redact_secrets(text[max(0, text.find("\n")) :][:180]))
            )
        result.strings.extend(_extract_named_strings(path, text))
        if _is_test_file(path):
            result.oracles.extend(_extract_oracles(path, text))
    return result


def _truncate_system(text: str) -> str:
    t = redact_secrets(text).strip()
    if len(t) <= MAX_SYSTEM_CHARS:
        return t
    return t[: MAX_SYSTEM_CHARS - 1].rstrip() + "…"


def _prior_hint_for(text: str) -> str:
    blob = text.lower()
    best = ""
    for prior in PRIORS:
        dets = prior.get("detectors") or {}
        pats = list(dets.get("user_any") or []) + list(dets.get("assistant_any") or [])
        hits = 0
        for pat in pats:
            try:
                if re.search(pat, blob, re.I):
                    hits += 1
            except re.error:
                continue
        if hits and (not best or hits > 1):
            best = str(prior.get("approach") or "")
    return best


def _refuse_aware_none_of(phrase: str, policy: str) -> bool:
    """Return True if this none_of would false-hard-fail a competent refusal."""
    p = phrase.strip().lower()
    if any(ok in p for ok in ABSOLUTE_EXCLUSION_OK):
        return False
    pol = policy.lower()
    looks_refuse = any(
        tok in pol for tok in ("do not invent", "don't invent", "never state", "not a substitute", "refuse")
    )
    if looks_refuse and any(p == t or p.startswith(t) for t in REFUSE_AWARE_TOPICS):
        return True
    return False


def _forbidden_from_policy(policy: str) -> list[tuple[str, bool]]:
    """(phrase, hard_fail) from absolute exclusions / never-lines."""
    out: list[tuple[str, bool]] = []
    for m in NEVER_RE.finditer(policy):
        body = m.group("body")
        # split on commas / or
        parts = re.split(r",|/| or ", body)
        for part in parts:
            phrase = re.sub(r"[^a-z0-9 \-']+", " ", part.lower()).strip()
            phrase = re.sub(r"\s+", " ", phrase)
            # drop leading verbs leftover
            phrase = re.sub(r"^(use |mention |say |include |write )", "", phrase).strip()
            if len(phrase) < 4 or len(phrase) > 48:
                continue
            if _refuse_aware_none_of(phrase, policy):
                continue
            hard = any(ok in phrase for ok in ABSOLUTE_EXCLUSION_OK)
            out.append((phrase, hard))
    # explicit palliative-style constants
    low = policy.lower()
    for tok in ABSOLUTE_EXCLUSION_OK:
        if tok in low:
            out.append((tok, True))
    # de-dupe
    seen: set[str] = set()
    uniq: list[tuple[str, bool]] = []
    for phrase, hard in out:
        if phrase in seen:
            continue
        seen.add(phrase)
        uniq.append((phrase, hard))
    return uniq[:6]


def _required_tokens(*texts: str) -> list[str]:
    found: list[str] = []
    seen: set[str] = set()
    for text in texts:
        for m in REQUIRED_TOKEN_RE.finditer(text or ""):
            tok = m.group(0).strip()
            key = tok.lower()
            if key in seen:
                continue
            seen.add(key)
            found.append(tok)
    return found[:8]


def _synthetic_opening(system: str, oracles: list[str], sources: list[str]) -> str:
    facts = _required_tokens(system, *oracles)
    bits = []
    if facts:
        bits.append("Use only these facts from the authorized artifacts:")
        for f in facts[:5]:
            bits.append(f"- {f}")
    else:
        excerpt = re.sub(r"\s+", " ", system)[:220].strip()
        if excerpt:
            bits.append(f"Follow the policy slice already present in {sources[0] if sources else 'the repo'}.")
            bits.append(f"Policy excerpt: {excerpt}")
        else:
            bits.append("Exercise the critical path described in the authorized repo files.")
    bits.append("Do not invent identifiers, staging, or citations that are not in the granted text.")
    return "\n".join(bits)


def _safe_contract_id(prefix: str, slug: str, source_blob: str) -> str:
    cid = f"{prefix}.{slug}_v1"
    blob = source_blob.lower()
    for lib in LIBRARY_IDS:
        if lib in cid.lower() and lib not in blob:
            cid = f"{prefix}.custom_{slug}_v1"
            break
        if cid.lower().endswith(lib) and lib not in blob:
            cid = f"{prefix}.custom_{slug}_v1"
            break
    # never emit a bare library id
    if cid in LIBRARY_IDS or cid.split(".", 1)[-1] in LIBRARY_IDS:
        if cid not in blob and cid.split(".", 1)[-1] not in blob:
            cid = f"{prefix}.authored_{slug}_v1"
    return cid


def _score_candidate(
    *,
    policy: str,
    oracles: list[str],
    has_llm: bool,
    ingest_boost: float,
) -> float:
    score = 0.2
    low = policy.lower()
    if any(w in low for w in ("never", "must", "mandatory", "absolute", "exclusion", "do not")):
        score += 0.35
    if _looks_like_agent_policy(policy):
        score += 0.15
    # Prefer full prompts over first-line scraps / HTML chrome
    if len(policy) >= 200:
        score += 0.1
    if len(policy) >= 600:
        score += 0.05
    if oracles:
        score += min(0.3, 0.08 * len(oracles))
    if has_llm:
        score += 0.1
    if _required_tokens(policy, *oracles):
        score += 0.15
    score += min(0.2, ingest_boost)
    # Demote markup / README / client-wrapper scraps
    if low.count("<") > 8 or low.startswith("# ") or "import openai" in low[:200]:
        score -= 0.25
    return min(0.99, max(0.05, score))


def _ingest_boosts(ingest: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not ingest:
        return []
    return list(ingest.get("suggestions") or [])


def _ingest_overlap(text: str, suggestions: list[dict[str, Any]]) -> float:
    """Boost when a trace failure/opening overlaps *their* policy tokens."""
    if not suggestions:
        return 0.0
    blob = text.lower()
    policy_tokens = {t.lower() for t in _required_tokens(text)}
    for tok in (
        "[source:",
        "[planner:",
        "palliative",
        "hospice",
        "doc-",
        "refuse",
        "escalate",
        "cite",
    ):
        if tok in blob:
            policy_tokens.add(tok)
    boost = 0.0
    for s in suggestions:
        sev = str(s.get("severity") or "").lower()
        quote = str(s.get("suggested_opening") or s.get("reason") or "")
        quote_l = quote.lower()
        if quote and quote[:40].lower() in blob:
            boost += 0.12
        # Trace text overlaps their policy token → accuracy signal
        if policy_tokens and any(tok in quote_l for tok in policy_tokens if len(tok) >= 4):
            boost += 0.18
        if sev in {"critical", "high"}:
            boost += 0.05
        if s.get("failure_count"):
            try:
                if int(s.get("failure_count") or 0) > 0:
                    boost += 0.08
            except (TypeError, ValueError):
                pass
    return boost


def _opening_from_ingest(system: str, suggestions: list[dict[str, Any]]) -> str | None:
    """Prefer a real trace opening that hits their policy over a synthetic one."""
    if not suggestions:
        return None
    blob = system.lower()
    tokens = {t.lower() for t in _required_tokens(system)}
    for tok in ("[source:", "[planner:", "palliative", "doc-", "ssn", "escalate"):
        if tok in blob:
            tokens.add(tok)
    best = None
    best_score = 0
    for s in suggestions:
        opening = str(s.get("suggested_opening") or "").strip()
        if not opening or len(opening) < 8:
            continue
        low = opening.lower()
        score = 0
        for tok in tokens:
            if len(tok) >= 4 and tok in low:
                score += 2
        if str(s.get("severity") or "").lower() in {"critical", "high"}:
            score += 1
        try:
            if int(s.get("failure_count") or 0) > 0:
                score += 1
        except (TypeError, ValueError):
            pass
        if score > best_score:
            best_score = score
            best = opening
    if best and best_score > 0:
        if not best.lower().startswith("user:"):
            return f"User: {best}" if len(best) < 400 else f"User: {best[:397]}…"
        return best
    return None


def propose_paths(
    scan: ScanResult,
    *,
    ingest: dict[str, Any] | None = None,
    limit: int = MAX_PATHS,
) -> list[DraftProposal]:
    """Rank 3–5 custom paths. Identity comes from their strings, not library IDs."""
    suggestions = _ingest_boosts(ingest)
    llm_files = {_rel(s.path, scan.root) for s in scan.llm_sites}

    clusters: list[DraftProposal] = []
    used_slugs: set[str] = set()

    def add_proposal(
        *,
        title: str,
        system: str,
        sources: list[str],
        oracles: list[str],
        extra_any: list[str] | None = None,
    ) -> None:
        slug = _slug(title)
        if slug in used_slugs:
            slug = _slug(f"{title}_{len(used_slugs)+1}")
        used_slugs.add(slug)
        blob = system + " " + " ".join(oracles)
        cid = _safe_contract_id(scan.prefix, slug, blob)
        checks: list[dict[str, Any]] = []
        tokens = list(dict.fromkeys((extra_any or []) + _required_tokens(system, *oracles)))
        if tokens:
            checks.append(
                {
                    "id": "holds_their_literals",
                    "any_of": tokens[:6],
                    "points": 5,
                }
            )
        elif oracles:
            checks.append(
                {
                    "id": "holds_test_oracle",
                    "any_of": oracles[:4],
                    "points": 5,
                }
            )
        none_items: list[str] = []
        hard_none: list[str] = []
        for phrase, hard in _forbidden_from_policy(system):
            if hard:
                hard_none.append(phrase)
            else:
                none_items.append(phrase)
        if hard_none:
            checks.append(
                {
                    "id": "absolute_exclusion",
                    "none_of": hard_none[:6],
                    "hard_fail": True,
                    "points": 5,
                }
            )
        if none_items:
            checks.append(
                {
                    "id": "must_not_dump",
                    "none_of": none_items[:6],
                    "points": 5,
                }
            )
        if not checks:
            checks.append(
                {
                    "id": "must_hold",
                    "any_of": ["cannot", "won't", "policy"],
                    "points": 5,
                }
            )
        opening = _synthetic_opening(system, oracles, sources)
        # Prefer a test literal that looks like a user utterance
        for lit in oracles:
            if " " in lit and len(lit) > 12:
                opening = lit if lit.lower().startswith(("user:", "case ", "patient")) else (
                    f"User: {lit}" if len(lit) < 80 else opening
                )
                if lit.lower().startswith(("user:", "case ", "patient")):
                    opening = lit
                break
        # Prefer a trace opening that overlaps their policy tokens
        ingest_opening = _opening_from_ingest(system, suggestions)
        if ingest_opening:
            opening = ingest_opening
        quiet = _quiet_miss(system, oracles)
        has_llm = any(src in llm_files for src in sources)
        conf = _score_candidate(
            policy=system,
            oracles=oracles,
            has_llm=has_llm,
            ingest_boost=_ingest_overlap(blob, suggestions),
        )
        note = ""
        if any(_refuse_aware_none_of(t, system) for t in REFUSE_AWARE_TOPICS):
            note = (
                "Refuse-aware: none_of skips topic names a competent agent may say "
                "while refusing (e.g. 'stage iv'); prefer positive evidence + dump phrases."
            )
        clusters.append(
            DraftProposal(
                id=cid,
                slug=slug,
                name=_human_name(title, scan.prefix),
                system=_truncate_system(system),
                opening=redact_secrets(opening),
                checks=checks,
                sources=sources,
                quiet_miss=quiet,
                confidence=conf,
                refuse_aware_note=note,
                prior_hint=_prior_hint_for(system),
            )
        )

    # 1. Named policy / system strings
    for item in scan.strings:
        if _is_key_helper_file(item.path):
            continue
        if not _looks_like_agent_policy(item.value) and len(item.value) < 120:
            continue
        src = _rel(item.path, scan.root)
        nearby = [
            o.literal
            for o in scan.oracles
            if o.path.parent == item.path.parent or o.path.stem.split("_")[0] in item.path.stem
        ]
        # also match oracles whose literal appears in this policy
        for o in scan.oracles:
            if o.literal.lower() in item.value.lower() and o.literal not in nearby:
                nearby.append(o.literal)
        add_proposal(
            title=item.name.lower().replace("rules", "").replace("prompt", "prompt"),
            system=item.value,
            sources=[src],
            oracles=nearby[:6],
        )

    # 2. LLM files without a named string already captured
    covered = {s for p in clusters for s in p.sources}
    for site in scan.llm_sites:
        src = _rel(site.path, scan.root)
        if src in covered:
            continue
        if _is_key_helper_file(site.path):
            continue
        try:
            text = site.path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        extracted = _extract_named_strings(site.path, text)
        # Prefer the longest agent-looking extract over file head scrap
        agentish = [e for e in extracted if _looks_like_agent_policy(e.value)]
        if agentish:
            system = max(agentish, key=lambda e: len(e.value)).value
        elif extracted:
            system = max(extracted, key=lambda e: len(e.value)).value
        else:
            system = redact_secrets(text[:800])
        # Skip credential plumbing / client wrappers / README chrome
        low = system.lower()
        if "startswith" in low and ("sk-or" in low or "sk-ant" in low or "[redacted]" in low):
            if "you are" not in low and "[source:" not in low and "policy" not in low:
                continue
        stem = site.path.name.lower()
        if stem in {"readme.md", "llm.ts", "llm.js", "llm.py", "openrouter_client.py"}:
            if not _looks_like_agent_policy(system):
                continue
        if not _looks_like_agent_policy(system) and (
            site.path.suffix.lower() in {".html", ".md"} or "import openai" in text[:400].lower()
        ):
            continue
        oracles = [o.literal for o in scan.oracles if o.path.parent == site.path.parent]
        add_proposal(
            title=site.path.stem,
            system=system,
            sources=[src],
            oracles=oracles[:6],
        )

    # 3. Orphan test oracles grouped by file
    oracle_used = {lit.lower() for p in clusters for c in p.checks for lit in (c.get("any_of") or [])}
    by_file: dict[Path, list[TestOracle]] = {}
    for o in scan.oracles:
        if o.literal.lower() in oracle_used:
            continue
        by_file.setdefault(o.path, []).append(o)
    for path, group in by_file.items():
        lits = [g.literal for g in group[:6]]
        add_proposal(
            title=path.stem.replace("test_", "").replace("_test", ""),
            system=(
                "You are the production agent under test. "
                "Honor the assertions in the granted test file. "
                + " Required evidence: "
                + ", ".join(lits[:4])
            ),
            sources=[_rel(path, scan.root)],
            oracles=lits,
            extra_any=lits[:4],
        )

    # Rank + cap
    clusters.sort(key=lambda p: (-p.confidence, p.id))
    # drop duplicate ids / duplicate system bodies
    uniq: list[DraftProposal] = []
    seen_ids: set[str] = set()
    seen_bodies: set[str] = set()
    for p in clusters:
        if p.id in seen_ids:
            continue
        body_key = re.sub(r"\s+", " ", p.system)[:120]
        if body_key in seen_bodies:
            continue
        seen_bodies.add(body_key)
        # never keep a library id unless it appeared in their text
        tail = p.id.split(".", 1)[-1]
        blob = (p.system + p.opening).lower()
        if tail in LIBRARY_IDS and tail not in blob:
            continue
        seen_ids.add(p.id)
        uniq.append(p)
        if len(uniq) >= limit:
            break

    # If ingest-only (no repo hits), draft custom ids from export openings
    if not uniq and suggestions:
        for s in suggestions[:limit]:
            opening = str(s.get("suggested_opening") or s.get("reason") or "User: (quiet miss from export)")
            slug = _slug(str(s.get("slug") or s.get("name") or "ingest_path"))
            cid = _safe_contract_id(scan.prefix, slug, opening)
            hint_checks = list(s.get("check_hints") or [])
            uniq.append(
                DraftProposal(
                    id=cid,
                    slug=slug,
                    name=str(s.get("name") or slug),
                    system=(
                        "You are the customer's production agent under test. "
                        "Follow their real policies. Prefer refuse / escalate / cite over guessing."
                    ),
                    opening=redact_secrets(opening),
                    checks=hint_checks
                    or [{"id": "must_hold", "any_of": ["cannot", "won't", "policy"], "points": 5}],
                    sources=["ingest-export"],
                    quiet_miss=str(s.get("reason") or "export-suggested quiet miss"),
                    confidence=float(s.get("confidence") or 0.4),
                    prior_hint=str(s.get("approach") or ""),
                )
            )
    return uniq


def _human_name(title: str, prefix: str) -> str:
    words = _slug(title).replace("_", " ").strip()
    label = words[:60] or "critical path"
    return f"{prefix} — {label}"


def _quiet_miss(system: str, oracles: list[str]) -> str:
    low = system.lower()
    if "palliative" in low or "hospice" in low:
        return "names palliative / hospice when the policy forbids it"
    if "[source:" in low or "source attribution" in low:
        return "clinical or policy claim without the required source tag"
    if "stage" in low and ("invent" in low or "never state" in low):
        return "invented staging without a document source"
    if oracles:
        return f"drops required evidence ({oracles[0][:48]})"
    if "escalate" in low:
        return "guesses instead of escalating"
    return "quiet miss on a hard constraint in their policy text"


def render_draft_yaml(proposal: DraftProposal) -> str:
    """Partner-editable contract. Status stays draft until Accept."""
    src = ", ".join(proposal.sources) or "(scan)"
    lines = [
        "# status: draft",
        f"# Sources: {src}",
        f"# Quiet miss: {proposal.quiet_miss}",
        f"# Confidence: {proposal.confidence:.2f}",
    ]
    if proposal.prior_hint:
        lines.append(f"# Fallback approach hint (not path identity): {proposal.prior_hint[:160]}")
    if proposal.refuse_aware_note:
        lines.append(f"# {proposal.refuse_aware_note}")
    lines += [
        "# Approve in Control Center (Accept) or: vantage-core draft accept " + proposal.id,
        "schema: runtimeai.contract/v1",
        f"id: {proposal.id}",
        f'name: "{proposal.name.replace(chr(34), chr(39))}"',
        "mode: custom",
        "fail_under: 7.0",
        "turns: 1",
        "model: openai/gpt-4o-mini",
        "",
        "agent:",
        "  system: |",
    ]
    for row in (proposal.system or "Follow the granted policy.").splitlines() or [""]:
        lines.append(f"    {row}" if row else "    ")
    lines.append("  opening: |")
    for row in (proposal.opening or "User: …").splitlines() or [""]:
        lines.append(f"    {row}" if row else "    ")
    lines.append("")
    lines.append("scorer:")
    lines.append("  kind: hard_checks")
    lines.append("  checks:")
    for ch in proposal.checks:
        lines.append(f"    - id: {ch.get('id') or 'check'}")
        if ch.get("any_of"):
            lines.append(f"      any_of: {json.dumps(list(ch['any_of']), ensure_ascii=False)}")
        if ch.get("none_of"):
            lines.append(f"      none_of: {json.dumps(list(ch['none_of']), ensure_ascii=False)}")
        if ch.get("hard_fail"):
            lines.append("      hard_fail: true")
        lines.append(f"      points: {int(ch.get('points') or 5)}")
    lines.append("")
    body = redact_secrets("\n".join(lines))
    # Final belt: never ship key-prefix literals into partner contracts
    if "sk-or-" in body.lower() or "sk-ant-" in body.lower():
        body = SECRET_PREFIX_RE.sub("[REDACTED]", body)
    return body


def drafts_dir(path: str | Path | None = None) -> Path:
    p = Path(path or DEFAULT_DRAFTS_DIR).expanduser()
    return p.resolve() if p.is_absolute() else (Path.cwd() / p).resolve()


def manifest_path(directory: str | Path) -> Path:
    return Path(directory) / MANIFEST_NAME


def load_manifest(directory: str | Path) -> dict[str, Any]:
    path = manifest_path(directory)
    if not path.is_file():
        return {"schema": MANIFEST_SCHEMA, "drafts": []}
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        return {"schema": MANIFEST_SCHEMA, "drafts": []}
    data.setdefault("drafts", [])
    return data


def write_manifest(directory: str | Path, payload: dict[str, Any]) -> Path:
    dest = Path(directory)
    dest.mkdir(parents=True, exist_ok=True)
    path = manifest_path(dest)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


def write_drafts(
    proposals: list[DraftProposal],
    out_dir: str | Path,
    *,
    force: bool = False,
    repo: str | Path | None = None,
) -> dict[str, Any]:
    dest = Path(out_dir).expanduser().resolve()
    dest.mkdir(parents=True, exist_ok=True)
    existing = load_manifest(dest) if (dest / MANIFEST_NAME).is_file() else None
    status_by_id: dict[str, str] = {}
    if existing:
        for row in existing.get("drafts") or []:
            if isinstance(row, dict) and row.get("id"):
                status_by_id[str(row["id"])] = str(row.get("status") or "draft")

    written: list[Path] = []
    rows: list[dict[str, Any]] = []
    for p in proposals:
        fname = f"{p.slug}.draft.yaml"
        path = dest / fname
        if path.exists() and not force:
            # keep file; still list it
            rows.append(p.as_manifest_row(fname))
            continue
        path.write_text(render_draft_yaml(p), encoding="utf-8")
        written.append(path)
        row = p.as_manifest_row(fname)
        if p.id in status_by_id and status_by_id[p.id] in {"accepted", "skipped"} and not force:
            row["status"] = status_by_id[p.id]
        rows.append(row)

    payload = {
        "schema": MANIFEST_SCHEMA,
        "generated_at": _now_iso(),
        "repo": str(Path(repo).resolve()) if repo else None,
        "drafts": rows,
        "suggested_suite": {
            "id": f"{(proposals[0].id.split('.')[0] if proposals else 'app')}.release_paths_v1",
            "paths": [f"../contracts/{r['slug']}.yaml" for r in rows],
        },
        "claim": (
            "Custom drafts from authorized local artifacts. "
            "Accept required. Not a generic library suite. Not OAuth."
        ),
    }
    write_manifest(dest, payload)
    readme = dest / "README_DRAFTS.md"
    if not readme.exists() or force:
        readme.write_text(
            "# Custom drafts — Accept in Control Center\n\n"
            "These YAML files were **drafted from artifacts you authorized** "
            "(repo / tests / ingest export).\n"
            "Ids are custom (`app.*` / `team.*`), not Vantage library scenarios.\n\n"
            "**Accept** copies a draft into `contracts/` and appends it to the suite.\n"
            "**Skip** drops it. **Refine** opens the YAML.\n\n"
            "Approve is one Accept — not a blank YAML page. "
            "Auto-write still means no human ownership + live OAuth; we do **not** do that.\n"
            "Static `center.html` export shows copy-commands; "
            "`vantage-core center --serve` runs Accept against this directory.\n",
            encoding="utf-8",
        )
    payload["written"] = [str(p) for p in written]
    return payload


def analyze_and_draft(
    repo: str | Path = ".",
    *,
    ingest: str | Path | None = None,
    tests: str | Path | None = None,
    write_dir: str | Path = DEFAULT_DRAFTS_DIR,
    suite: str | Path | None = None,
    force: bool = False,
    limit: int = MAX_PATHS,
) -> dict[str, Any]:
    """Scan + propose + write. Optional ingest JSON is one input, not the identity."""
    root = Path(repo).expanduser().resolve()
    if not root.exists():
        raise FileNotFoundError(f"repo not found: {root}")
    scan = scan_repo(root, tests=tests)
    ingest_payload = None
    if ingest:
        from vantage_core.ingest import analyze_export, load_export

        ingest_payload = analyze_export(load_export(ingest), limit=limit)
    proposals = propose_paths(scan, ingest=ingest_payload, limit=limit)
    out = drafts_dir(write_dir)
    manifest = write_drafts(proposals, out, force=force, repo=root)
    suite_note = None
    if suite:
        sp = Path(suite)
        suite_note = str(sp)
    return {
        "repo": str(root),
        "files_scanned": scan.files_scanned,
        "llm_sites": len(scan.llm_sites),
        "drafts": manifest.get("drafts") or [],
        "written": manifest.get("written") or [],
        "manifest": str(manifest_path(out)),
        "drafts_dir": str(out),
        "suite": suite_note,
        "claim": manifest.get("claim"),
    }


def list_drafts(directory: str | Path | None = None) -> list[dict[str, Any]]:
    man = load_manifest(drafts_dir(directory))
    return [d for d in (man.get("drafts") or []) if isinstance(d, dict)]


def _find_row(directory: Path, draft_id: str) -> dict[str, Any]:
    for row in list_drafts(directory):
        if str(row.get("id") or "") == draft_id or str(row.get("slug") or "") == draft_id:
            return row
        if str(row.get("file") or "") == draft_id:
            return row
    raise FileNotFoundError(f"draft not found: {draft_id}")


def show_draft(draft_id: str, *, directory: str | Path | None = None) -> tuple[dict[str, Any], str]:
    dest = drafts_dir(directory)
    row = _find_row(dest, draft_id)
    path = dest / str(row.get("file") or "")
    if not path.is_file():
        raise FileNotFoundError(f"draft YAML missing: {path}")
    return row, path.read_text(encoding="utf-8")


def _set_status(directory: Path, draft_id: str, status: str) -> dict[str, Any]:
    man = load_manifest(directory)
    found = None
    for row in man.get("drafts") or []:
        if not isinstance(row, dict):
            continue
        if str(row.get("id") or "") == draft_id or str(row.get("slug") or "") == draft_id:
            row["status"] = status
            found = row
            break
    if found is None:
        raise FileNotFoundError(f"draft not found: {draft_id}")
    write_manifest(directory, man)
    return found


def _mark_accepted_header(yaml_text: str) -> str:
    if yaml_text.lstrip().startswith("# status: draft"):
        return yaml_text.replace("# status: draft", "# status: accepted", 1)
    if "status: draft" in yaml_text[:400]:
        return yaml_text.replace("status: draft", "status: accepted", 1)
    return "# status: accepted\n" + yaml_text


def append_suite_path(
    suite_path: Path,
    contract_rel: str,
    *,
    why: str = "",
    contract_id: str | None = None,
) -> None:
    """Create or append a suite path entry. Idempotent on contract filename."""
    name = Path(contract_rel).name
    if suite_path.is_file():
        text = suite_path.read_text(encoding="utf-8")
        if name in text or contract_rel in text:
            return
        if re.search(r"(?m)^paths:\s*$", text):
            extra = f"  - {contract_rel}"
            if why:
                extra += f'\n    why: "{why.replace(chr(34), chr(39))}"'
            text = re.sub(r"(?m)^paths:\s*$", f"paths:\n{extra}", text, count=1)
        else:
            extra = f"\n  - {contract_rel}"
            if why:
                extra += f'\n    why: "{why.replace(chr(34), chr(39))}"'
            text = text.rstrip() + extra + "\n"
        suite_path.write_text(text if text.endswith("\n") else text + "\n", encoding="utf-8")
        return

    suite_path.parent.mkdir(parents=True, exist_ok=True)
    sid = (contract_id or "team.release_paths_v1").split(".")[0] + ".release_paths_v1"
    why_line = f'\n    why: "{why.replace(chr(34), chr(39))}"' if why else ""
    body = (
        "schema: runtimeai.suite/v1\n"
        f"id: {sid}\n"
        'name: "Release critical paths"\n'
        "fail_policy: all_must_pass\n"
        "paths:\n"
        f"  - {contract_rel}{why_line}\n"
    )
    suite_path.write_text(body, encoding="utf-8")


def accept_draft(
    draft_id: str,
    *,
    drafts: str | Path | None = None,
    into: str | Path = DEFAULT_CONTRACTS_DIR,
    suite: str | Path = DEFAULT_SUITE,
    ci: bool = False,
    root: str | Path | None = None,
) -> dict[str, Any]:
    """Copy draft → contracts/, append suite, optional CI stub for the accepted suite."""
    base = Path(root).expanduser().resolve() if root else Path.cwd()
    ddir = drafts_dir(drafts)
    row = _find_row(ddir, draft_id)
    src = ddir / str(row["file"])
    if not src.is_file():
        raise FileNotFoundError(f"draft YAML missing: {src}")
    contracts = Path(into).expanduser()
    if not contracts.is_absolute():
        contracts = (base / contracts).resolve()
    contracts.mkdir(parents=True, exist_ok=True)
    dest = contracts / f"{row.get('slug') or src.stem.replace('.draft', '')}.yaml"
    dest.write_text(_mark_accepted_header(src.read_text(encoding="utf-8")), encoding="utf-8")

    suite_path = Path(suite).expanduser()
    if not suite_path.is_absolute():
        suite_path = (base / suite_path).resolve()
    try:
        rel = os.path.relpath(dest, suite_path.parent)
    except ValueError:
        rel = str(dest)
    # prefer ../contracts/foo.yaml style
    if not rel.startswith("."):
        rel = f"../contracts/{dest.name}" if dest.parent.name == "contracts" else rel
    append_suite_path(
        suite_path,
        rel.replace("\\", "/"),
        why=str(row.get("quiet_miss") or row.get("name") or ""),
        contract_id=str(row.get("id") or ""),
    )
    _set_status(ddir, str(row.get("id") or draft_id), "accepted")

    ci_path = None
    if ci:
        from vantage_core.ci_stub import default_stub_path, write_stub

        try:
            rel_suite = os.path.relpath(suite_path, base).replace("\\", "/")
        except ValueError:
            rel_suite = str(suite_path)
        dest_ci = base / default_stub_path("github")
        try:
            ci_path = str(write_stub("github", dest_ci, force=True, suite=rel_suite))
        except TypeError:
            ci_path = str(write_stub("github", dest_ci, force=True))
    return {
        "id": row.get("id"),
        "contract": str(dest),
        "suite": str(suite_path),
        "ci": ci_path,
        "status": "accepted",
    }


def skip_draft(draft_id: str, *, drafts: str | Path | None = None) -> dict[str, Any]:
    ddir = drafts_dir(drafts)
    row = _set_status(ddir, draft_id, "skipped")
    return {"id": row.get("id"), "status": "skipped"}


def refine_draft_path(draft_id: str, *, drafts: str | Path | None = None) -> Path:
    dest = drafts_dir(drafts)
    row = _find_row(dest, draft_id)
    path = dest / str(row.get("file") or "")
    if not path.is_file():
        raise FileNotFoundError(f"draft YAML missing: {path}")
    return path


def load_center_drafts(directory: str | Path | None = None) -> list[dict[str, Any]]:
    """Rows for Author next — pending drafts only (not accepted/skipped)."""
    rows = []
    for row in list_drafts(directory):
        status = str(row.get("status") or "draft")
        if status in {"accepted", "skipped"}:
            continue
        rows.append(row)
    return rows


def packaged_demo_drafts_dir() -> Path:
    return Path(__file__).resolve().parent / "demo_fixtures" / "authorized_draft"


def seed_demo_authorized_drafts(work: str | Path, *, force: bool = True) -> Path:
    """Copy the wheel's fake authorized-repo draft pack into a demo workdir."""
    src = packaged_demo_drafts_dir()
    dest = Path(work).expanduser().resolve() / DEFAULT_DRAFTS_DIR
    dest.mkdir(parents=True, exist_ok=True)
    if src.is_dir():
        for path in src.iterdir():
            if path.is_file():
                target = dest / path.name
                if force or not target.exists():
                    shutil.copy2(path, target)
    return dest


def format_draft_report(result: dict[str, Any]) -> str:
    lines = [
        "Authorized custom draft — scan → 3–5 paths from *their* artifacts",
        f"repo     {result.get('repo')}",
        f"scanned  {result.get('files_scanned')} file(s)  ·  llm sites {result.get('llm_sites')}",
        f"drafts   {result.get('drafts_dir')}",
    ]
    drafts = result.get("drafts") or []
    if not drafts:
        lines.append("No custom paths found. Grant a repo with policy strings / model tests, or pass --ingest.")
        lines.append("Fallback: vantage-core init --guided")
        return "\n".join(lines)
    lines.append(f"propose  {len(drafts)} custom path(s) (not a library suite):")
    for i, d in enumerate(drafts, start=1):
        lines.append(f"  {i}. {d.get('id')}  — {d.get('name')}")
        lines.append(
            f"     confidence={d.get('confidence')}  sources={', '.join(d.get('sources') or []) or '—'}"
        )
        if d.get("quiet_miss"):
            lines.append(f"     quiet miss: {d.get('quiet_miss')}")
    lines.append("")
    lines.append("Next: Accept in Control Center, or:")
    lines.append("  vantage-core draft list")
    lines.append("  vantage-core draft accept <draft_id>")
    lines.append("  vantage-core center --serve   # Accept / Skip / Refine against this directory")
    lines.append("")
    lines.append(str(result.get("claim") or ""))
    return "\n".join(lines)


def is_draft_action(token: str | None) -> bool:
    return str(token or "").strip().lower() in _ACTIONS
