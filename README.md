# היום בקיצור — a personal daily newspaper

A Hebrew, right-to-left daily paper, generated from sources I choose and read in
the morning. Not an aggregator: a human picks every story, every fact is checked
against the article itself, and the paper is written fresh.

* **Front page** — `index.html`, always the newest edition
* **Archive** — every past edition, kept forever
* **Search** — full-text across everything published
* **Learning** — a topic a day, each with its own explained page, simulator and quiz

---

## The daily loop

```
ישיבת מערכת  →  deep research (external)  →  בנה את העיתון  →  build → verify
 agent proposes        you, hours later          agent writes
```

The agent **never picks the content**. It proposes; I choose. Decisions are
persisted to `data/plans/YYYY-MM-DD.plan.json`, because the meeting and the
build are usually hours apart. An edition is always dated **tomorrow**.

Full procedure: **[`docs/RUNBOOK.md`](docs/RUNBOOK.md)**.

## Quick start

```powershell
.\scripts\setup.ps1                              # venv + deps
$env:PYTHONIOENCODING = "utf-8"                  # required for Hebrew output
.\.venv\Scripts\python.exe scripts\build_site.py # validate, then render everything
.\.venv\Scripts\python.exe -m pytest -q          # 36 regression tests
```

Then serve the folder and open `index.html`:

```powershell
.\.venv\Scripts\python.exe -m http.server 8787
```

## Layout

```
data/editions/    one JSON per edition - the source of truth for a paper
data/topics/      one JSON per learning topic (explanation, simulator, quiz)
data/plans/       editorial decisions + what was fact-checked, per edition
data/research/    the research PDF bound to each edition
data/research/bank/  undated researches waiting for a future edition
data/ledger.json  editorial memory: printed, and proposed-but-not-used
templates/        Jinja2: edition, topic, archive, search, catalog
assets/css/       the whole visual design
scripts/          build_site, validate, fetch_news, ledger, weather, research_bank
docs/             SPEC (contract) · RUNBOOK (procedure) · BKM (why) · VISUAL_SPEC
editions/ learn/  generated output - committed, so the site is servable as-is
```

## The research bank

Deep research is run externally and handed in as a PDF. Anything ready for a
*future* day goes in `data/research/bank/` under any filename:

```powershell
.\.venv\Scripts\python.exe scripts\research_bank.py            # what's available
.\.venv\Scripts\python.exe scripts\research_bank.py use <id> 2026-09-02
```

A banked research is undated; `use` binds it to an edition and stops it being
offered again. The editorial meeting checks the bank before proposing new
topics, so a ready research becomes tomorrow's lead with no waiting.

## How it avoids regressing

Prose in a doc rots. The rules that matter are executable:

* **`scripts/validate.py`** — a machine-enforced subset of `docs/SPEC.md`.
  `build_site.py` runs it first and **refuses to publish** on any violation.
* **`tests/test_newspaper.py`** — one test per bug actually hit.

**Every improvement ends with a validator rule or a test, not just a paragraph.**

What is enforced today: no story printed twice (ever), every printed brief traced
to a plan entry with a `verified` note, the ledger closed after publishing,
figures citing real data, weather fetched rather than written, quiz answers in
range and explained, Hebrew search matching at word starts, no placeholder text,
and no mojibake or BOM — see `docs/RUNBOOK.md` §5.

## Rules that don't bend

1. **Never print an unverified fact.** Fetch the article; the headline is not the
   story. This caught a real one: an aggregator said Nvidia was buying Hugging
   Face for $13B; the article said **$12.9B**, **not finalized**, single-sourced.
2. **Facts aren't copyrightable, prose is.** Every brief is written fresh.
3. **Never fabricate an ambient detail** — the weather is fetched from Open-Meteo
   or the previous reading stands.
4. **No paid API in the loop.** Deep research is run externally and handed in as
   a PDF.
5. **Secrets live in `.env`**, never in the repo.
