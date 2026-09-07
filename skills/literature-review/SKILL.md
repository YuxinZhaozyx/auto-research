---
name: literature-review
description: Search and analyze research papers, find related work, summarize key ideas. Use when user says "find papers", "related work", "literature review", "what does this paper say", or needs to understand academic papers.
argument-hint: "[paper-topic-or-url]"
allowed-tools: Bash(*), Read, Glob, Grep, WebSearch, WebFetch, Write, Agent, mcp__zotero__*
---

# Research Literature Review

Research topic: $ARGUMENTS

## Constants

- **PAPER_LIBRARY** — Local directory containing user's paper collection (PDFs). Check these paths in order:
  1. `literature/` in the current project directory
  2. Custom path specified by user in `CLAUDE.md` / `AGENTS.md` under `## Paper Library` 
- **MAX_LOCAL_PAPERS = 20** — Maximum number of local PDFs to scan (read first 3 pages each). If more are found, prioritize by filename relevance to the topic.
- **SOURCES = `all`** — Which literature sources to search. Options: `zotero`, `local`, `web`, `semantic-scholar`, `all`. Full source table and selection rules: see `## Data Sources` below.

> 💡 Overrides:
> - `/literature-review "topic" — paper library: ~/my_papers/` — custom local PDF path
> - `/literature-review "topic" — sources: zotero, local` — only search Zotero + local PDFs
> - `/literature-review "topic" — sources: web` — only search the web (skip all local)
> - `/literature-review "topic" — sources: web, semantic-scholar` — also search Semantic Scholar for published venue papers (IEEE, ACM, etc.)

## Data Sources

This skill checks multiple sources **in priority order**. All are optional — if a source is not configured or not requested, skip it silently.

Do not search for papers on arXiv unless explicitly stated.

### Source Selection

Parse `$ARGUMENTS` for a `— sources:` directive:
- **If `— sources:` is specified**: Only search the listed sources (comma-separated). Valid values: `zotero`, `local`, `web`, `semantic-scholar`, `all`.
- **If not specified**: Default to `all` — search every available source in priority order.

Examples:
```
/literature-review "diffusion models"                                    → all (default)
/literature-review "diffusion models" — sources: all                     → all (default)
/literature-review "diffusion models" — sources: zotero                  → Zotero only
/literature-review "diffusion models" — sources: zotero, web             → Zotero + web
/literature-review "diffusion models" — sources: local                   → local PDFs only
/literature-review "topic" — sources: web, semantic-scholar              → web + semantic-scholar API (IEEE/ACM venue papers)
```

### Source Table

| Priority | Source | ID | How to detect | What it provides |
|----------|--------|----|---------------|-----------------|
| 1 | **Zotero** (via MCP) | `zotero` | Try calling any `mcp__zotero__*` tool — if unavailable, skip | Collections, tags, annotations, PDF highlights, BibTeX, semantic search |
| 2 | **Local PDFs** | `local` | `Glob: literature/**/*.pdf` (in current project directory) | Raw PDF content (first 3 pages) |
| 3 | **Semantic Scholar API** | `semantic-scholar` | `scripts/semantic_scholar_fetch.py` (in current skill directory) | Published venue papers (IEEE, ACM, Springer) with structured metadata: citation counts, venue info, TLDR. |
| 4 | **Web search** | `web` | Always available (WebSearch) | Semantic Scholar, Google Scholar, Springer, IEEExplore |

> **Graceful degradation**: If no MCP servers are configured, the skill works exactly as before (local PDFs + web search). Zotero is pure additions.

## Workflow

### Step 0a: Search Zotero Library (if available)

**Skip this step entirely if Zotero MCP is not configured.**

Try calling a Zotero MCP tool (e.g., search). If it succeeds:

1. **Search by topic**: Use the Zotero search tool to find papers matching the research topic
2. **Read collections**: Check if the user has a relevant collection/folder for this topic
3. **Extract annotations**: For highly relevant papers, pull PDF highlights and notes — these represent what the user found important
4. **Export BibTeX**: Get citation data for relevant papers
5. **Compile results**: For each relevant Zotero entry, extract:
   - Title, authors, year, venue
   - User's annotations/highlights (if any)
   - Tags the user assigned
   - Which collection it belongs to

> 📚 Zotero annotations are gold — they show what the user personally highlighted as important, which is far more valuable than generic summaries.

### Step 0b: Scan Local Paper Library

Before searching online, check if the user already has relevant papers locally:

1. **Locate library**: Check PAPER_LIBRARY paths for PDF files (in current project directory)
   ```
   Glob: literature/**/*.pdf
   ```

2. **De-duplicate against Zotero**: If Step 0a found papers, skip any local PDFs already covered by Zotero results (match by filename or title).

3. **Filter by relevance**: Match filenames and first-page content against the research topic. Skip clearly unrelated papers.

4. **Summarize relevant papers**: For each relevant local PDF (up to MAX_LOCAL_PAPERS):
   - Read first 3 pages (title, abstract, intro)
   - Extract: title, authors, year, core contribution, relevance to topic
   - Flag papers that are directly related vs tangentially related

5. **Build local knowledge base**: Compile summaries into a "papers you already have" section. This becomes the starting point — external search fills the gaps.

> 📚 If the user has a comprehensive local collection, the external search can be more targeted (focus on what's missing).
>
> ⚠️ **If all PAPER_LIBRARY paths miss, say so before moving on** — do not skip silently. A user whose PDFs live in a reference manager (Zotero, ...) otherwise assumes `— sources: all` covered them. Emit:
>
> `WARN: local contributed nothing — no PDFs found in literature/, or a configured paper library. To include yours, add a "## Paper Library" heading to CLAUDE.md / AGENTS.md followed by the directory path.`
>
> Then continue to Step 1.

### Step 1: Search (external)

**Semantic Scholar API search**:
Helper: `script/semantic_scholar_fetch.py` (in current skill directory).

```bash
# Search for published CS/Engineering papers with quality filters.
# Wrap with if/then/else so set -e doesn't abort the SKILL.
if [ -f .env ]; then set -a; source .env; set +a; fi
python scripts/semantic_scholar_fetch.py search "QUERY" --max 10 --fields-of-study "Computer Science,Engineering" --publication-types "JournalArticle,Conference" 2>&1
```

The interval between two requests of Semantic Scholar API must be at least 8 seconds.

**WebSearch**:
- Use WebSearch to find recent papers on the topic
- Check Semantic Scholar, Google Scholar, IEEExplore, Springer
- Focus on papers from last 2 years unless studying foundational work
- **De-duplicate**: Skip papers already found in Zotero or local library

### Step 1.5: Verify Candidate Papers (anti-hallucination, mandatory)

Before analysis, run pre-search verification on **all** candidate papers collected from Steps 0a-1 to filter out LLM-fabricated arXiv IDs / DOIs / titles.
Helper: `script/verify_papers.py` (in current skill directory).
If the helper is unresolved on this machine, the SKILL emits a fallback `verified_papers.json` tagging every candidate `[UNVERIFIED]` so downstream analysis proceeds with audit-visible degraded output rather than silently dropping candidates.

```bash
# 1. Emit candidates as JSON. Verification scratch lives under literature/.temp
mkdir -p literature/.temp
cat > literature/.temp/candidate_papers.json <<'JSON'
[
  {"id": "p1", "arxiv_id": "2307.03172", "doi": null, "title": "Lost in the Middle"},
  {"id": "p2", "arxiv_id": null, "doi": "10.1145/...", "title": "..."},
  {"id": "p3", "arxiv_id": null, "doi": null, "title": "Some Paper Title"}
]
JSON

# 2. Run 3-layer verification (arXiv batch → CrossRef → Semantic Scholar fuzzy).
#    Policy D1: when the helper is unresolved OR its invocation fails, emit
#    a degraded verified set tagging everything [UNVERIFIED] so the user
#    can audit search quality. If python itself is missing, we BLOCK
#    rather than hand-roll JSON in shell.
if [ -f .env ]; then set -a; source .env; set +a; fi
python script/verify_papers.py --input  literature/.temp/candidate_papers.json --output literature/.temp/verified_papers.json

python - <<'PY'
import json
cands = json.load(open('literature/.temp/candidate_papers.json'))
out = {
  'verdict': 'WARN',
  'reason_code': 'verify_papers_unavailable',
  'summary': 'verify_papers.py helper unresolved or invocation failed; all candidates tagged [UNVERIFIED] for audit visibility.',
  'papers': [dict(p, status='unverified', method='none') for p in cands],
}
with open('literature/.temp/verified_papers.json', 'w') as f:
  json.dump(out, f, indent=2)
PY

# 4. Read verdict + per-paper status from literature/.temp/verified_papers.json;
#    surface warnings to the user.
```

**Mandatory output rules**:

- Tag every paper in the analyzed list with its status: `✅ verified (via
  arxiv|crossref|s2)` or `⚠️ UNVERIFIED (reason)` or `… verify_pending`.
- **Never silently drop unverified papers** — keep them in the output with the
  `[UNVERIFIED]` marker so the user can audit the search quality.
- Never fabricate a DOI or arXiv ID from memory. If a field is unknown, leave
  it `null` in `candidate_papers.json` — the helper will fall through to title
  search.
- If the helper returns `WARN` with `high_hallucination_rate`, surface the
  warning verbatim and recommend re-running with narrower queries.
- For papers tagged `verify_pending`, do not promote them to `verified` —
  show the pending state to the user and retry on the next session.

### Step 2: Analyze Each Paper

> **Fan-out (Tier-aware).** Per-paper extraction is pure breadth — each paper
> is independent — so it parallelizes cleanly. **Tier 1** (Workflow): spawn
> one subagent per paper (or per small batch) to extract the fields
> below. **Tier 2** (Agent tool, no Workflow): the same per-paper subagents
> via the Agent tool. **Tier 3**: iterate sequentially. This follows the
> *extraction* shard schema
> — `{shard_id: "<paper-or-batch id>", entries: [{dedup_key: "<canonical
> arXiv-id / DOI / title-hash, already assigned upstream in Step 1.5>",
> problem, method, results, relevance, source, verification_status}]}`.

For **every** paper in `literature/.temp/verified_papers.json` (verified, unverified, `verify_pending`, and `error` alike — see Retention rule above), extract:
- **Problem**: What gap does it address?
- **Method**: Core technical contribution (1-2 sentences)
- **Results**: Key numbers/claims
- **Relevance**: How does it relate to our work?
- **Source**: Where we found it (Zotero/local/web) — helps user know what they already have vs what's new
- **Verification status** (one of):
  - `✅ verified (via arxiv|crossref|s2)`
  - `⚠️ UNVERIFIED (verification unavailable: helper unresolved or invocation failed)`
  - `⚠️ UNVERIFIED (searched: not found in any source)`
  - `… VERIFY_PENDING (transient API failure — retry next session)`
  - `❌ ERROR (malformed input: no arxiv, no DOI, no title)`

  Show the status in the analyzed table — never silently drop a paper because its status is anything other than `verified`.

### Step 3: Synthesize
- Group papers by approach/theme
- Identify consensus vs disagreements in the field
- Find gaps that our work could fill

### Step 4: Output
Present as a structured literature table:

```
| Paper | Venue | Method | Key Result | Relevance to Us | Source |
|-------|-------|--------|------------|-----------------|--------|
```

Plus a narrative summary of the landscape (3-5 paragraphs).

Save the structured literature table and related informations as a Report to a `REVIEW-[topic].md` in `literature/summary/` (in current project directory).

If Zotero BibTeX was exported, include a `references.bib` snippet for direct use in paper writing.

### Step 5: Save (if requested)
- Save paper PDFs to `literature/` (in current project directory)
- Update related work notes in project memory

## Key Rules
- Always include paper citations (authors, year, venue)
- Distinguish between peer-reviewed and preprints
- Be honest about limitations of each paper
- Note if a paper directly competes with or supports our approach
- **Never fail because a MCP server is not configured** — always fall back gracefully to the next data source
- Zotero tool may have different names depending on how the user configured the MCP server (e.g., `mcp__zotero__search` or `mcp__zotero-mcp__search_items`). Try the most common patterns and adapt.
