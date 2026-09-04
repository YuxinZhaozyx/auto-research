# auto-research

> Portable agent skills for automating academic research.

> ⚠️ **Work in progress** — skills, scripts, and interfaces may change without notice.

**English** | [简体中文](README.zh-CN.md)

---

## Overview

`auto-research` is a growing collection of portable **agent skills** that automate the tedious parts of academic research — searching papers, verifying they actually exist, extracting key ideas, and synthesizing a literature review. Each skill is a self-contained instruction file plus dependency-free helper scripts, loadable in Claude Code or any compatible harness.

Currently ships with:

- **`literature-review`** — a search → verify → analyze → synthesize pipeline. Pulls from Zotero (MCP), local PDFs, Semantic Scholar, and the web; runs a 4-layer anti-hallucination check on every candidate; and writes a structured review to `REVIEW.md`.

More skills are planned.

## Quick Start

```bash
git clone https://github.com/YuxinZhaozyx/auto-research.git
cd auto-research
cp .env.example .env   # then fill in the values (see Environment Variables below)
```

Requires Python 3.9+ and a skill-capable harness. Copy a skill folder into your harness's skills directory to make it available globally; otherwise keep it in your project repo and it's picked up automatically.

## Environment Variables

Copy `.env.example` to `.env` and fill in the values. Each variable:

| Variable | Required | Description |
|----------|----------|-------------|
| `SEMANTIC_SCHOLAR_API_KEY` | Recommended | Semantic Scholar API key. [Request one here](https://www.semanticscholar.org/product/api) — it must start with `s2k-`. Powers the Semantic Scholar search and verification. If unset, the skill degrades to the WebSearch tool for literature search. |
| `CROSSREF_VERIFY_EMAIL` | Recommended | Your institutional email, sent in the CrossRef `User-Agent`. Lowers the chance of being rate-limited. Falls back to a placeholder if unset. |
| `PYTHONIOENCODING` | — | Pinned to `utf-8` in `.env.example`; ensures non-ASCII metadata is handled correctly. Do not change. |
| `PYTHONUTF8` | — | Pinned to `1` in `.env.example`; enables Python's UTF-8 mode. Do not change. |

## Usage

### `literature-review`

Searches, verifies, analyzes, and synthesizes a literature review on a topic.

**How it works.** It searches multiple sources in priority order, then runs an anti-hallucination check on every candidate to filter out fabricated references before any analysis. Each surviving paper is analyzed for its problem, method, results, and relevance; the results are then grouped by theme to surface consensus, disagreements, and gaps your work could fill. Sources that aren't configured are skipped silently, so it always degrades gracefully.

```
/literature-review "diffusion models for image generation"
```

Narrow the sources with a `— sources:` directive (default `all`):

| Source | What it covers |
|--------|----------------|
| `zotero` | Your Zotero library via MCP (collections, tags, annotations, BibTeX) |
| `local` | PDFs in your project's `literature/` folder (first 3 pages each) |
| `semantic-scholar` | Published venue papers (IEEE, ACM, Springer) with citations and TLDR |
| `web` | Broad web search across scholarly sources |

```
/literature-review "topic" — sources: zotero, local
/literature-review "topic" — sources: web, semantic-scholar
```

Point to a custom local PDF path inline:

```
/literature-review "topic" — paper library: ~/my_papers/
```

**Zotero (optional).** The `zotero` source needs a Zotero MCP server. Install one (e.g. a community `zotero-mcp` package) and register it in your harness's MCP settings, pointing it at your library — either the local Zotero app (enable *Edit → Preferences → Advanced → General → "Allow other applications on this computer to communicate with Zotero"*) or a Zotero Web API key. The skill auto-detects available Zotero tools at run time; if none are present, `zotero` is simply skipped and the other sources take over.

Output is written to `literature/summary/REVIEW.md` — a literature table plus a narrative summary, with optional `references.bib`. Every paper is tagged with a verification status (`✅ verified` / `⚠️ UNVERIFIED` / `… VERIFY_PENDING`); unverified papers are never silently dropped, so you can audit search quality yourself.

## Acknowledgments

Some of the skills in this project are modified from [ARIS (Auto-claude-code-research-in-sleep)](https://github.com/wanshuiyin/Auto-claude-code-research-in-sleep) by wanshuiyin. See [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) for full attribution.

## License

[MIT License](LICENSE) — © 2026 Yuxin Zhao (YuxinZhaozyx).
