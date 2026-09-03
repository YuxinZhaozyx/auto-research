#!/usr/bin/env python3
"""
verify_papers.py — Pre-search paper-existence verification helper.

Verifies that candidate papers found by literature-search skills actually exist
via 4-layer fallback (arXiv API → CrossRef DOI lookup → CrossRef bibliographic
title search → Semantic Scholar fuzzy title match). Title-only candidates are
resolved against CrossRef *before* S2: when the returned record's title matches
and an official DOI is found, the paper is verified via that DOI, and only
papers still unresolved fall through to Semantic Scholar. Designed to catch
LLM hallucination at search time, before fabricated references propagate
through downstream skills.

CLI:

  python3 verify_papers.py --input papers.json --output verified.json
      [--arxiv-batch-size 40]
      [--title-fuzzy-threshold 0.6]
      [--hallucination-warn-threshold 0.2]

Convenience entries (normalized to the same input schema internally):

  python3 verify_papers.py --arxiv-ids 2307.03172,2401.12345
  python3 verify_papers.py --titles-file titles.txt

Stdin/stdout supported via `-`:

  cat papers.json | python3 verify_papers.py --input - --output -

Input schema (papers.json):

  [
    {"id": "p1", "arxiv_id": "2307.03172", "doi": null, "title": "Lost in the Middle"},
    {"id": "p2", "arxiv_id": null, "doi": "10.1016/...", "title": "AgentAI"},
    {"id": "p3", "arxiv_id": null, "doi": null, "title": "Some Paper"}
  ]

Output schema (verified.json):

  {
    "verdict": "PASS | WARN | BLOCKED | ERROR",
    "hallucination_rate": 0.33,
    "pending_rate": 0.0,
    "warnings": ["high_hallucination_rate"],
    "papers": [
      {"id": "p1", "status": "verified",       "method": "arxiv",    "confidence": "high"},
      {"id": "p2", "status": "verified",       "method": "crossref", "confidence": "high"},
      {"id": "p3", "status": "verified",       "method": "crossref", "confidence": "high"},   # via CrossRef title search
      {"id": "p4", "status": "verified",       "method": "s2",       "confidence": "medium"},
      {"id": "p5", "status": "unverified",     "method": null,       "reason": "crossref_unverified_s2_unverified"},
      {"id": "p6", "status": "verify_pending", "method": null,       "reason": "crossref_verify_pending_s2_verify_pending"}
    ]
  }

Status semantics:

  verified        — at least one layer confirmed existence
  unverified      — all applicable layers ran cleanly and found no match
  verify_pending  — any layer hit transient failure (5xx, timeout, rate-limit) and
                    no earlier layer verified; do NOT count against hallucination rate
  error           — input malformed for this entry; rare

Top-level verdict:

  PASS    — hallucination_rate <= threshold AND no pending
  WARN    — hallucination_rate >  threshold OR any pending
  BLOCKED — input/output prerequisites missing
  ERROR   — tool itself crashed or output cannot be written

Email for CrossRef User-Agent: reads `CROSSREF_VERIFY_EMAIL` env, falls back to
`research@anonymous.local` (placeholder, not a real address). Set the env
to reduce CrossRef rate-limit risk:

  export CROSSREF_VERIFY_EMAIL="you@institution.edu"
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import re
import sys
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

# ──────────────────────────────────────────────────────────────────────────
# Constants
# ──────────────────────────────────────────────────────────────────────────

ARXIV_API = "https://export.arxiv.org/api/query"
CROSSREF_API = "https://api.crossref.org/works"
S2_API = "https://api.semanticscholar.org/graph/v1/paper/search"

DEFAULT_BATCH_SIZE = 40
DEFAULT_FUZZY_THRESHOLD = 0.6
DEFAULT_HALLUCINATION_WARN_THRESHOLD = 0.2

def _arxiv_user_agent() -> str:
    contact = os.environ.get("CROSSREF_VERIFY_EMAIL", "").strip()
    base = "verify-papers/1.0"
    return f"{base} (mailto:{contact})" if contact else base


ARXIV_VERSION_RE = re.compile(r"v\d+$")
TITLE_NORMALIZE_RE = re.compile(r"[^\w\s]", re.UNICODE)
WHITESPACE_RE = re.compile(r"\s+")


# ──────────────────────────────────────────────────────────────────────────
# Data shapes
# ──────────────────────────────────────────────────────────────────────────

@dataclass
class PaperInput:
    id: str
    arxiv_id: str | None = None
    doi: str | None = None
    title: str | None = None


@dataclass
class PaperResult:
    id: str
    status: str  # verified | unverified | verify_pending | error
    method: str | None = None  # arxiv | crossref | s2 | None
    confidence: str | None = None  # high | medium | low
    reason: str | None = None
    identifiers: dict[str, str] = field(default_factory=dict)


# ──────────────────────────────────────────────────────────────────────────
# Normalization
# ──────────────────────────────────────────────────────────────────────────

def normalize_arxiv_id(raw: str) -> tuple[str, str | None]:
    """Return (id_without_version, original_version_or_none)."""
    raw = raw.strip()
    m = ARXIV_VERSION_RE.search(raw)
    if m:
        return raw[: m.start()], m.group(0)
    return raw, None


def normalize_doi(raw: str) -> str:
    return raw.strip().lower().lstrip("https://doi.org/").lstrip("doi.org/")


def normalize_title(raw: str) -> str:
    """Lowercase + Unicode NFKD + strip punctuation + collapse whitespace."""
    t = unicodedata.normalize("NFKD", raw).lower()
    t = TITLE_NORMALIZE_RE.sub(" ", t)
    t = WHITESPACE_RE.sub(" ", t).strip()
    return t


def title_hash(normalized: str) -> str:
    return hashlib.sha1(normalized.encode("utf-8")).hexdigest()[:16]


# ──────────────────────────────────────────────────────────────────────────
# Retry helpers
# ──────────────────────────────────────────────────────────────────────────

def http_get(url: str, headers: dict[str, str] | None = None, timeout: int = 30) -> tuple[int, str | None]:
    """Return (status_code, body) or (status_code, None) on error. Status -1 = network error."""
    req = urllib.request.Request(url, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        return e.code, None
    except (urllib.error.URLError, TimeoutError, ConnectionError):
        return -1, None


def is_transient(status: int) -> bool:
    return status == -1 or status == 429 or 500 <= status < 600


def backoff(attempt: int) -> float:
    return min(2 ** attempt + random.uniform(0, 1), 30)


# ──────────────────────────────────────────────────────────────────────────
# Layer 1: arXiv batch verification
# ──────────────────────────────────────────────────────────────────────────

def verify_arxiv_batch(ids: list[str], batch_size: int = DEFAULT_BATCH_SIZE) -> dict[str, str]:
    """Return {arxiv_id: status} where status in {verified, unverified, verify_pending}."""
    if not ids:
        return {}
    result: dict[str, str] = {}
    for i in range(0, len(ids), batch_size):
        batch = ids[i : i + batch_size]
        result.update(_verify_arxiv_batch_with_retry(batch))
    return result


def _verify_arxiv_batch_with_retry(batch: list[str]) -> dict[str, str]:
    """3 retries with exponential backoff. On persistent failure split batch in half."""
    base_ids = [normalize_arxiv_id(x)[0] for x in batch]
    url = f"{ARXIV_API}?id_list={','.join(base_ids)}&max_results={len(base_ids)}"
    for attempt in range(3):
        status, body = http_get(url, headers={"User-Agent": _arxiv_user_agent()}, timeout=30)
        if status == 200 and body is not None:
            found = set()
            for bid in base_ids:
                if f"<id>http://arxiv.org/abs/{bid}" in body:
                    found.add(bid)
            return {
                orig: "verified" if normalize_arxiv_id(orig)[0] in found else "unverified"
                for orig in batch
            }
        if not is_transient(status):
            # 4xx (non-transient) — likely malformed query; mark whole batch unverified
            return {orig: "unverified" for orig in batch}
        time.sleep(backoff(attempt))
    # Persistent failure — split & retry
    if len(batch) > 1:
        mid = len(batch) // 2
        left = _verify_arxiv_batch_with_retry(batch[:mid])
        right = _verify_arxiv_batch_with_retry(batch[mid:])
        return {**left, **right}
    return {batch[0]: "verify_pending"}


# ──────────────────────────────────────────────────────────────────────────
# Layer 2: CrossRef DOI verification
# ──────────────────────────────────────────────────────────────────────────

def verify_doi(doi: str, user_email: str) -> str:
    """Return verified | unverified | verify_pending."""
    encoded = urllib.parse.quote(normalize_doi(doi), safe="/")
    url = f"{CROSSREF_API}/{encoded}"
    headers = {"User-Agent": f"verify-papers/1.0 (mailto:{user_email})"}
    for attempt in range(2):
        status, _ = http_get(url, headers=headers, timeout=15)
        if status == 200:
            return "verified"
        if status == 404:
            return "unverified"
        if not is_transient(status):
            return "unverified"
        time.sleep(backoff(attempt))
    return "verify_pending"


# ──────────────────────────────────────────────────────────────────────────
# Layer 3: CrossRef bibliographic title search (resolves an official DOI)
# ──────────────────────────────────────────────────────────────────────────

def verify_title_crossref(title: str, user_email: str, fuzzy_threshold: float) -> tuple[str, dict[str, str] | None]:
    """Search CrossRef by title (query.bibliographic) to resolve an official DOI.

    Runs before the S2 layer for title-only candidates: when a returned record's
    title matches the candidate within `fuzzy_threshold` (word overlap), the
    paper is verified via the record's official DOI. Returns
    (status, identifiers_dict_or_None) with status in {verified, unverified,
    verify_pending}.
    """
    normalized = normalize_title(title)
    if not normalized:
        return "unverified", None
    q = urllib.parse.quote(normalized[:300])
    url = f"{CROSSREF_API}?query.bibliographic={q}&rows=3&mailto={urllib.parse.quote(user_email)}"
    headers = {"User-Agent": f"verify-papers/1.0 (mailto:{user_email})"}
    for attempt in range(2):
        status, body = http_get(url, headers=headers, timeout=15)
        if status == 200 and body is not None:
            try:
                data = json.loads(body)
            except json.JSONDecodeError:
                return "verify_pending", None
            user_words = set(normalized.split())
            if not user_words:
                return "unverified", None
            for item in data.get("message", {}).get("items", []):
                cand_title = (item.get("title") or [""])[0]
                cand_words = set(normalize_title(cand_title).split())
                if not cand_words:
                    continue
                overlap = len(user_words & cand_words) / max(len(user_words), len(cand_words))
                if overlap >= fuzzy_threshold:
                    issued = item.get("issued", {}).get("date-parts") or [[None]]
                    return "verified", {
                        "doi": item.get("DOI", ""),
                        "crossref_title": cand_title,
                        "container_title": (item.get("container-title") or [""])[0],
                        "year": str(issued[0][0]) if issued[0][0] is not None else "",
                    }
            return "unverified", None
        if not is_transient(status):
            return "unverified", None
        time.sleep(backoff(attempt))
    return "verify_pending", None


# ──────────────────────────────────────────────────────────────────────────
# Layer 4: Semantic Scholar fuzzy title match
# ──────────────────────────────────────────────────────────────────────────

def verify_title_s2(title: str, fuzzy_threshold: float) -> tuple[str, dict[str, str] | None]:
    """Return (status, identifiers_dict_or_None)."""
    normalized = normalize_title(title)
    if not normalized:
        return "unverified", None
    q = urllib.parse.quote(normalized[:200])
    url = f"{S2_API}?query={q}&limit=3&fields=title,year,externalIds"
    for attempt in range(2):
        status, body = http_get(url, timeout=15)
        if status == 200 and body is not None:
            try:
                data = json.loads(body)
            except json.JSONDecodeError:
                return "verify_pending", None
            user_words = set(normalized.split())
            if not user_words:
                return "unverified", None
            for p in data.get("data", []):
                p_norm = normalize_title(p.get("title", ""))
                p_words = set(p_norm.split())
                if not p_words:
                    continue
                overlap = len(user_words & p_words) / max(len(user_words), len(p_words))
                if overlap >= fuzzy_threshold:
                    ext = p.get("externalIds", {}) or {}
                    return "verified", {
                        "s2_title": p.get("title", ""),
                        "arxiv_id": ext.get("ArXiv", ""),
                        "doi": ext.get("DOI", ""),
                    }
            return "unverified", None
        if status == 429:
            return "verify_pending", None
        if not is_transient(status):
            return "unverified", None
        time.sleep(backoff(attempt))
    return "verify_pending", None


# ──────────────────────────────────────────────────────────────────────────
# Orchestration
# ──────────────────────────────────────────────────────────────────────────

def verify_papers(
    papers: list[PaperInput],
    *,
    arxiv_batch_size: int,
    fuzzy_threshold: float,
    user_email: str,
) -> list[PaperResult]:
    """Run 3-layer verification."""
    now = time.time()

    results: dict[str, PaperResult] = {}
    to_verify_arxiv: dict[str, list[str]] = {}  # arxiv_id -> [paper_ids]
    to_verify_doi: list[PaperInput] = []
    to_verify_title: list[PaperInput] = []

    # Layer 1: arXiv batch
    if to_verify_arxiv:
        arxiv_results = verify_arxiv_batch(list(to_verify_arxiv.keys()), arxiv_batch_size)
        for base_id, paper_ids in to_verify_arxiv.items():
            status = arxiv_results.get(base_id, "verify_pending")
            for pid in paper_ids:
                results[pid] = PaperResult(
                    id=pid,
                    status=status,
                    method="arxiv" if status == "verified" else None,
                    confidence="high" if status == "verified" else None,
                    reason=None if status == "verified" else f"arxiv_{status}",
                    identifiers={"arxiv_id": base_id},
                )

    # Layer 2: CrossRef
    for p in to_verify_doi:
        status = verify_doi(p.doi or "", user_email)
        result = PaperResult(
            id=p.id,
            status=status,
            method="crossref" if status == "verified" else None,
            confidence="high" if status == "verified" else None,
            reason=None if status == "verified" else f"crossref_{status}",
            identifiers={"doi": normalize_doi(p.doi or "")},
        )
        # If unverified by CrossRef and we have a title, fall through to S2
        if status == "unverified" and p.title:
            s2_status, s2_ids = verify_title_s2(p.title, fuzzy_threshold)
            if s2_status == "verified":
                result = PaperResult(
                    id=p.id,
                    status="verified",
                    method="s2_fallback_from_doi",
                    confidence="medium",
                    identifiers={"doi": normalize_doi(p.doi or ""), **(s2_ids or {})},
                )
            elif s2_status == "verify_pending":
                result.status = "verify_pending"
                result.reason = "crossref_unverified_s2_pending"
        results[p.id] = result

    # Layer 3: CrossRef title search — resolve an official DOI before S2
    for p in to_verify_title:
        title = p.title or ""
        cr_status, cr_ids = verify_title_crossref(title, user_email, fuzzy_threshold)
        if cr_status == "verified":
            result = PaperResult(
                id=p.id,
                status="verified",
                method="crossref",
                confidence="high",
                identifiers=cr_ids or {},
            )
        else:
            # Layer 4: only papers CrossRef could not confirm go to S2
            s2_status, s2_ids = verify_title_s2(title, fuzzy_threshold)
            if s2_status == "verified":
                result = PaperResult(
                    id=p.id,
                    status="verified",
                    method="s2",
                    confidence="medium",
                    identifiers=s2_ids or {},
                )
            else:
                result = PaperResult(
                    id=p.id,
                    status="verify_pending" if "verify_pending" in (cr_status, s2_status) else "unverified",
                    method=None,
                    reason=f"crossref_{cr_status}_s2_{s2_status}",
                )
        results[p.id] = result

    return [results[p.id] for p in papers]


# ──────────────────────────────────────────────────────────────────────────
# CLI
# ──────────────────────────────────────────────────────────────────────────

def parse_input(args: argparse.Namespace) -> list[PaperInput]:
    if args.input:
        if args.input == "-":
            raw = sys.stdin.read()
        else:
            raw = Path(args.input).read_text(encoding="utf-8")
        data = json.loads(raw)
        return [PaperInput(**d) for d in data]
    if args.arxiv_ids:
        ids = [x.strip() for x in args.arxiv_ids.split(",") if x.strip()]
        return [PaperInput(id=f"arxiv-{i}", arxiv_id=x) for i, x in enumerate(ids)]
    if args.titles_file:
        path = sys.stdin if args.titles_file == "-" else open(args.titles_file, encoding="utf-8")
        try:
            titles = [line.strip() for line in path if line.strip()]
        finally:
            if path is not sys.stdin:
                path.close()
        return [PaperInput(id=f"title-{i}", title=t) for i, t in enumerate(titles)]
    raise SystemExit("error: provide --input, --arxiv-ids, or --titles-file")


def compute_verdict(results: list[PaperResult], threshold: float) -> tuple[str, dict[str, Any]]:
    terminal = [r for r in results if r.status in ("verified", "unverified")]
    pending = [r for r in results if r.status == "verify_pending"]
    errors = [r for r in results if r.status == "error"]
    unverified = [r for r in results if r.status == "unverified"]

    h_rate = (len(unverified) / len(terminal)) if terminal else 0.0
    p_rate = (len(pending) / len(results)) if results else 0.0

    warnings: list[str] = []
    if h_rate > threshold:
        warnings.append("high_hallucination_rate")
    if pending:
        warnings.append("transient_failures_present")
    if errors:
        warnings.append("malformed_inputs_present")

    if not results:
        verdict = "BLOCKED"
    elif errors and not terminal and not pending:
        verdict = "ERROR"
    elif warnings:
        verdict = "WARN"
    else:
        verdict = "PASS"

    return verdict, {
        "hallucination_rate": round(h_rate, 4),
        "pending_rate": round(p_rate, 4),
        "warnings": warnings,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--input", help="Path to papers.json, or - for stdin")
    ap.add_argument("--output", help="Path to verified.json, or - for stdout (default)")
    ap.add_argument("--arxiv-ids", help="Convenience: comma-separated arXiv IDs")
    ap.add_argument("--titles-file", help="Convenience: file with one title per line, or -")
    ap.add_argument("--arxiv-batch-size", type=int, default=DEFAULT_BATCH_SIZE)
    ap.add_argument("--title-fuzzy-threshold", type=float, default=DEFAULT_FUZZY_THRESHOLD)
    ap.add_argument(
        "--hallucination-warn-threshold",
        type=float,
        default=DEFAULT_HALLUCINATION_WARN_THRESHOLD,
    )
    args = ap.parse_args()

    try:
        papers = parse_input(args)
    except Exception as e:
        out = {
            "verdict": "BLOCKED",
            "hallucination_rate": 0.0,
            "pending_rate": 0.0,
            "warnings": ["input_unreadable"],
            "papers": [],
            "error": str(e),
        }
        print(json.dumps(out, indent=2, ensure_ascii=False))
        return 2

    user_email = os.environ.get("CROSSREF_VERIFY_EMAIL", "research@anonymous.local").strip()

    results = verify_papers(
        papers,
        arxiv_batch_size=args.arxiv_batch_size,
        fuzzy_threshold=args.title_fuzzy_threshold,
        user_email=user_email,
    )

    verdict, metrics = compute_verdict(results, args.hallucination_warn_threshold)
    output = {
        "verdict": verdict,
        **metrics,
        "papers": [asdict(r) for r in results],
    }

    payload = json.dumps(output, indent=2, ensure_ascii=False)
    if args.output and args.output != "-":
        Path(args.output).write_text(payload, encoding="utf-8")
    else:
        print(payload)
    return 0


if __name__ == "__main__":
    sys.exit(main())
