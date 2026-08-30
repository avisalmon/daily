# היום בקיצור — Content Specification

> Status: **ACTIVE** (phase 1). Companion to `docs/VISUAL_SPEC.md`, which governs
> the look. This document governs *what goes in the paper and how it gets there*.

## 1. Purpose

A personal daily newspaper in Hebrew. One human editor (the user), one AI
production desk (the agent). It is not an automated news aggregator — every
edition is the result of an editorial decision made by a person.

**Language:** Hebrew throughout, RTL. Source links may point to English pages.

## 2. The two commands

Producing an edition takes **two separate invocations**, with the user's own
research happening in between. They must not be merged — the gap between them
may be hours, and may cross sessions.

```
  ┌─ 1. "בוא נעשה ישיבת מערכת"  ──────────────────────────┐
  │    agent proposes → user chooses → plan written to disk │
  └─────────────────────────────────────────────────────────┘
                          ↓
             user runs deep research externally
             (NotebookLM / Gemini) → exports PDF
                          ↓
  ┌─ 2. "בנה את העיתון"  ────────────────────────────────┐
  │    agent reads plan + PDF → writes edition JSON → builds │
  │    → commits and pushes, dated ahead and held back        │
  └──────────────────────────────────────────────────────────┘
                          ↓
             midnight, Asia/Jerusalem: GitHub Actions
             rebuilds and the edition becomes the front page
```

Because step 2 may run in a fresh session, **step 1's output must be persisted
to a file.** Nothing may live only in conversation.

There is no third command for publishing. Committing is safe because the build
holds a dated-ahead edition back (§8), so step 2 ends with a push and the paper
appears on its own morning without anyone being awake.

## 3. Command 1 — Editorial meeting

**Trigger:** the user says something like *"בוא נעשה ישיבת מערכת"* /
*"let's have an editorial meeting"*.

The agent fetches from `config/sources.yaml` and presents three groups of
proposals. The user chooses from each.

### 3.1 AI & technology news

- Fetch all active feeds; keep items from the **last 48 hours**.
- Deduplicate — the same story from three outlets is one candidate.
- Present **10–15 candidates**, each as: Hebrew one-line description, source
  name, publication time, link.
- Order by interest, not recency. Prefer primary sources (an OpenAI
  announcement beats three outlets reporting it).
- The user selects **5–10** to run as briefs.

### 3.2 Deep research topic (lead story)

- Propose **3–5 topics** suitable for a substantial main article.
- Draw from Israel news, science, technology, economics — wider than AI.
- Each proposal states: the topic, why it matters now, and the question the
  research should answer.
- A good topic has genuine depth and a real question. Not "מה חדש ב-AI".
- The user picks one (or supplies their own), then runs the research
  themselves and returns a PDF.

### 3.3 Learning topic

- Propose **3–5** "מה זה…" topics at high-school level.
- Any field — science, technology, economics, history.
- Bias toward topics that are **visually explainable**, since phase 2 adds
  diagrams and a simulator.
- The user picks one.

### 3.4 Output of the meeting

The agent writes `data/plans/YYYY-MM-DD.plan.json`, where the date is the
**edition date** (see §6):

```jsonc
{
  "edition_date": "2026-08-30",
  "decided_at": "2026-08-29T14:40:00+03:00",
  "lead": {
    "topic": "...",              // chosen research topic
    "question": "...",           // what the research must answer
    "research_pdf": null         // filled in at build time
  },
  "briefs": [
    { "title_he": "...", "url": "...", "source": "...", "published": "..." }
  ],
  "learning": {
    "topic": "...",              // e.g. "מה זה אלגוריתם"
    "why": "..."                 // one line on why it was chosen
  }
}
```

## 4. Command 2 — Build the edition

**Preconditions:** the plan file exists, and a research PDF is present in
`data/research/` named `YYYY-MM-DD-slug.pdf` matching the edition date.

The agent extracts the PDF text, writes `data/editions/YYYY-MM-DD.json`, and
runs `scripts/build_site.py`.

### 4.1 Lead story — the deep research

- A Hebrew **summary written by the agent** from the PDF text. Not a machine
  translation, not a copy-paste of the PDF's own summary.
- Length: roughly 400–700 words.
- Structure: headline, standfirst, body with subheadings.
- Must end with a link to the full research (see §5).
- If the extracted text looks garbled (see §7), **stop and report** — do not
  write a story from broken input.

### 4.2 Briefs — 5–10 short items

- One short Hebrew paragraph each, 2–4 sentences.
- **Written in the agent's own words.** Never copy sentences or paragraphs from
  the source. Facts are not copyrightable; prose is.
- Each carries a link to the original and the source name.
- Where the source is English, the brief is still Hebrew.

### 4.3 Learning topic of the day

- **Phase 1:** a short paragraph in the paper (roughly 100–150 words)
  explaining the topic. No dedicated page yet.
- **Phase 2:** the paragraph gains a "לקריאה מורחבת" link to a standalone
  interactive page. See §8.

## 5. The research PDF

**Decision:** the research PDF **is published** alongside the edition.

This reverses the earlier note in `data/research/README.md`. Rationale: a lead
story that cites research the reader cannot open is weak, and the research is
the user's own work product.

- Input lives at `data/research/YYYY-MM-DD-slug.pdf` (gitignored).
- The build copies it to `research/YYYY-MM-DD.pdf` in the published site.
- The lead story links there.

## 6. Site structure — history, search, catalog

The site is static. Nothing below requires a server.

| Page | Contents |
|---|---|
| `index.html` | Always the newest edition |
| `editions/YYYY-MM-DD.html` | Every edition, kept forever |
| `archive.html` | Full history, grouped by month, with headline and research link |
| `search.html` | Client-side search over every article ever published |
| `learn.html` | Growing catalog of learning topics |
| `research/YYYY-MM-DD.pdf` | Published research behind each lead |

**Nothing is ever deleted.** Every edition is re-rendered on every build, so a
design change propagates to the whole archive.

### 6.1 Search

`assets/search-index.json` is generated at build time — one document per lead
story, per grid story, and per learning topic, carrying title, body text, date,
source and a link. The page fetches it and filters in the browser.

**Hebrew matching is word-start, not substring.** Hebrew plurals end in `-ים`,
so a naive substring search for `מים` ("water") also matches `אלגוריתמים`
("algorithms"). Terms must therefore match the start of a word, optionally
after one of the single-letter prefixes `ו ה ב כ ל מ ש` so that `המים` still
finds `מים`. Prefix search still works: `רופ` finds `רופא`.

Search matches the text as written. Brand names written in Latin (`Anthropic`)
will not be found by their Hebrew spelling.

### 6.2 Learning catalog

`learn.html` lists every learning topic ever published, newest first, each
linking to its edition. When phase 2 lands, an entry gains a link to its
standalone interactive page; until then it is marked "עמוד מורחב — בקרוב".

## 7. The editorial ledger

`data/ledger.json` is editorial memory, and is committed to git.

- **`published`** — every item ever printed. These are filtered out of future
  editorial meetings automatically, so a story can never run twice.
- **`proposed`** — candidates shown at a meeting but not chosen, with a
  `times_proposed` counter. They stay in the pool and can resurface later.

URLs are normalized (tracking parameters stripped, `www.` and trailing slashes
removed) so the same story matches across variants.

```powershell
python scripts\record_edition.py 2026-08-30 --proposed data\_news_cache.json
python scripts\ledger.py          # summary of what has been printed
```

## 8. Dates

The edition produced is **tomorrow's** — the paper is read in the morning.

A meeting held on 2026-08-29 produces edition `2026-08-30`. Plan file, edition
JSON, research PDF and published page all use that same date.

### 8.1 An edition is written the evening before and published on its own day

The site is public the moment it is committed, so writing tomorrow's paper
tonight must not put tomorrow's paper in front of a reader tonight.

`build_site.py` therefore **refuses to publish an edition dated ahead of the
current day in Asia/Jerusalem**. An edition that is not yet due:

- gets no page under `editions/`,
- does not become `index.html`,
- is absent from the archive rail, the search index and the learning catalog,
- keeps its research PDF and its learning page unpublished.

If any of those were published by an earlier run, the next build **withdraws
them**. Committing a not-yet-due edition is safe and is the normal workflow.

`index.html` always shows the newest edition **that is due** — not the newest
edition on disk.

### 8.2 Who promotes it at midnight

`.github/workflows/publish.yml` runs on GitHub's machines every hour, rebuilds,
and commits only if the rebuild changed something. On the 23 quiet hours it is a
no-op; on the hour the date rolls over it promotes the edition. This needs no
machine of yours to be switched on.

It is hourly rather than a single midnight cron because Jerusalem shifts between
UTC+2 and UTC+3, and because GitHub's scheduler is often late and sometimes
skips a run. Letting the build decide what is due removes both problems.

**The build must be byte-stable across runs**, or the job commits every hour.
`test_build_is_reproducible` enforces this. The live weather fetch broke the
rule once and is now pinned to press time: one reading per paper-day.

### 8.3 Previewing an edition before its day

```powershell
.\.venv\Scripts\python.exe scripts\build_site.py --include-future
```

This renders held-back editions so you can read them locally. **Its output must
never be committed** — it publishes tomorrow's paper today. Rebuild without the
flag to withdraw it again. Three tests fail if a preview build is committed, so
CI will refuse to push one.

## 9. Known risks

- **Hebrew PDF extraction is unreliable.** RTL text can extract reversed or
  with broken glyph mapping depending on the producing tool. Extracted text is
  eyeballed before use; garbled input halts the build.
- **Scanned PDFs extract nothing.** Text-based PDFs only.
- **Feeds rot.** `config/sources.yaml` records a `verified` date per feed.
  Calcalist is already rejected (403).
- **48-hour windows go empty** on quiet days. Widen the window rather than
  padding the paper with weak items.

## 10. Phase 2 — the learning page (not yet built)

Deferred by decision until the newspaper works end to end.

Target: a standalone HTML page per learning topic containing (1) an explanation
with diagrams and illustrations, (2) an interactive simulator, (3) a quiz.

Open questions, to resolve when phase 2 starts:

- Simulators do not generalize — a simulator for *מה זה אלגוריתם* shares
  nothing with one for *מה זה DNA*. Bespoke per topic, or a small library of
  archetypes (chart / step-through / parameter-slider) that topics are fitted
  to?
- The page needs its own visual spec: RTL, mobile-first, self-contained JS.
- Pages accumulate and will need an archive index of their own.

## 11. Non-goals

- **Not autonomous.** The agent never publishes an edition without the user
  choosing its contents.
- **Not a general aggregator.** A curated personal paper, not full coverage.
- **The agent does not run the deep research.** The user does, externally.
- **No paid API in the loop** for phase 1. Research is done by the user; the
  agent writes from the PDF. Azure remains available for artwork.
- **No scraping of authenticated services.** No ChatGPT, Gemini or NotebookLM
  private endpoints, ever.

