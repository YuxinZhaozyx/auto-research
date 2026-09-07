---
name: idea-discovery
description: Generate and rank research ideas given a broad direction. Use when user says "找idea", "brainstorm ideas", "generate research ideas", "what can we work on", or wants to explore a research area for publishable directions.
argument-hint: "[research-direction]"
allowed-tools: Bash(*), Read, Write, Edit, Grep, Glob, WebSearch, WebFetch, Skill
---

# Idea Discovery Skill

Orchestrate a complete idea discovery workflow for: **$ARGUMENTS**

## Workflow

### Phase 1: Literature Survey

Invoke `/literature-review` to map the research landscape. 

**What this does:**
1. **Build a landscape map**:
   - Group papers by sub-direction / approach
   - Identify what has been tried and what hasn't
   - Note recurring limitations mentioned in "Future Work" sections
   - Flag any open problems explicitly stated by multiple papers
2. **Identify structural gaps**:
   - Methods that work in domain A but haven't been tried in domain B
   - Contradictory findings between papers (opportunity for resolution)
   - Assumptions that everyone makes but nobody has tested
   - Scaling regimes that haven't been explored
   - Diagnostic questions that nobody has asked
3. Output a literature summary

### Phase 2: Idea Generation

Create a subagent for divergent thinking. **do not inline the full landscape + gaps prompt** once it stops being tiny. Write the full brainstorming request to
`idea/.temp/idea_brainstorm_bundle.md`, then keep the subagent prompt short:

```
prompt: |
  Read the idea-generation bundle at <absolute path to idea_brainstorm_bundle.md> and follow all instructions in it.
```

Bundle contents:

```
    You are a senior ML researcher brainstorming research ideas.

    Research direction: [user's direction]

    Here is the current landscape:
    [write the Phase-1 landscape map into this bundle file]

    Key gaps identified:
    [write the Phase-1 gap summary into this bundle file]

    Generate 8-12 concrete research ideas. For each idea:
    1. One-sentence summary
    2. Core hypothesis (what you expect to find and why)
    3. Minimum viable experiment (what's the cheapest way to test this?)
    4. Expected contribution type: empirical finding / new method / theoretical result / diagnostic
    5. Highlights (2-3 sentences)
    6. Risk level: LOW (likely works) / MEDIUM (50-50) / HIGH (speculative)
    7. Risk (Possible reasons for failure)
    8. Estimated effort: days / weeks / months
    9. Feasibility (compute, data, implementation estimates)

    Prioritize ideas that are:
    - Testable with moderate compute (8x RTX 3090 or less)
    - Likely to produce a clear positive OR negative result (both are publishable)
    - Simple at the core: one mechanism, few moving parts — an idea a colleague could restate after hearing it once. If the novelty only appears once a second module or an extra gate is added, that is packaging, not novelty.
    - Aware of the 10-15 papers above — awareness, not avoidance. Differentiation is the novelty check's job later, not a constraint on brainstorming.

    "Apply X to Y" is legitimate when the application would reveal something non-obvious — judge it by what it reveals, not by the template. A direct, well-executed attack on a central problem is a valid idea when nobody has executed it well; do not steer around crowded areas — proximity to strong work is a sign the problem matters, not that it is taken.

    Be genuinely creative: surprising connections, inverted assumptions, questions nobody thought to ask. Creativity is a new angle on a problem that matters — not an obscure corner nobody visits, and not extra modules stacked until something looks new. Generate first, filter later — the filters come after you, and they are strict enough. A bold, creative idea with a named risk beats a hedged, complicated one with none. A great idea is one where the answer matters regardless of which way it goes.
```

### Phase 3: Novelty Verification

For each top idea, run a thorough novelty check:

```
/novelty-check "[top idea 1 description]"
/novelty-check "[top idea 2 description]"
```

**What this does:**
- Identify closest existing work and differentiation points

### Phase 4: Final Report

Finalize `idea/summary/IDEA_REPORT.md` with all accumulated information:

```markdown
# Idea Discovery Report

**Direction**: $ARGUMENTS
**Date**: [today]

## Landscape Summary
[from Phase 1, 3-5 paragraphs on the current state of the field]

## Ranked Ideas
[from Phase 2, updated with Phase 3-4 results]

### 🏆 Idea 1: [title] — RECOMMENDED
- **Method (what we actually do)**: [2–4 concrete steps in plain language — what we build / train / run. No jargon, no claim-IDs, no hypothesis yet. Lead with this so the reader grasps the approach first.]
- **Hypothesis**: [one sentence]
- **Minimum experiment**: [concrete description]
- **Expected outcome**: [what success/failure looks like]
- **Novelty**: X/10 — CONFIRMED (closest: [paper], differentiation: [what's different])
- **Feasibility**: [compute, data, implementation estimates]
- **Highlights**:
  1. [highlight1]
  2. [highlight2]
- **Risk Level**: LOW/MEDIUM/HIGH
- **Risk**:
  1. [risk1]
  2. [riks2]
- **Contribution type**: empirical / method / theory / diagnostic
- **Reviewer score**: X/10
- **Reviewer's likely objection**: [strongest counterargument]
- **Why we should do this**: [1-2 sentences]

### Idea 2: [title] — BACKUP
...

## Eliminated Ideas
[ideas killed at each phase, with reasons]

| Idea | Reason eliminated |
|------|-------------------|
| ... | Already done by [paper] |
| ... | Requires > 1 week GPU time |
| ... | Result wouldn't be interesting either way |

```
