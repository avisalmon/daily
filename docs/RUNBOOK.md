# RUNBOOK — producing an edition

The daily procedure. **`docs/SPEC.md` says what must be true; this says what to
do; `docs/BKM.md` says why.** If those three ever disagree, SPEC wins.

---

## Where each kind of rule lives

Put a new rule in exactly one place. Duplicating it guarantees drift.

| Kind of rule | Home | Enforced by |
|---|---|---|
| What must be true of an edition | `docs/SPEC.md` | `scripts/validate.py` |
| How to run the day | `docs/RUNBOOK.md` (this file) | the checklist in §4 |
| Why a rule exists, gotchas | `docs/BKM.md` | — |
| How it must look | `docs/VISUAL_SPEC.md` | `tests/test_newspaper.py` |
| Which sources we trust | `config/sources.yaml` | `scripts/fetch_news.py` |

---

## 1. Editorial meeting

> "בוא נעשה ישיבת מערכת"

The agent fetches candidates and proposes, in Hebrew:

1. **Latest AI/tech news** — a numbered list to choose from
2. **A deep-research topic** for the lead
3. **A learning topic** for the education slot

You choose. The agent writes the decisions to `data/plans/YYYY-MM-DD.plan.json`
**before doing anything else** — the meeting and the build can be hours or days
apart, and may cross sessions.

The edition is dated **tomorrow**.

## 2. You run the deep research

Externally (NotebookLM / Gemini / ChatGPT). Drop the PDF in:

```
data\research\YYYY-MM-DD-slug.pdf
```

The date must match the edition date. The PDF is published with the paper and
the lead links to it.

## 3. Build

> "בנה את העיתון"

```powershell
$env:PYTHONIOENCODING="utf-8"
.\.venv\Scripts\python.exe scripts\build_site.py
```

The build **validates first and refuses to publish** if anything fails. Then it
renders every edition, the archive, search, the learning catalog and every
topic page, publishes the research PDF, and fetches live weather for Haifa.

Afterwards, close the editorial loop:

```powershell
.\.venv\Scripts\python.exe scripts\record_edition.py YYYY-MM-DD --proposed data\_news_cache.json
.\.venv\Scripts\python.exe scripts\ledger.py
```

## 4. Before calling it done

- [ ] Every brief **fetched and read** — never written from the RSS headline
- [ ] Numbers match the article, not the headline
- [ ] Each brief in our own words, with a working source link
- [ ] `verified` note recorded per item in the plan
- [ ] Lead figure built from **real numbers**, with its source cited
- [ ] `python scripts\validate.py` passes
- [ ] `pytest -q` green
- [ ] Opened in a browser: index, archive, search (Hebrew **and** Latin term),
      learn, the topic page, and one archived edition
- [ ] Checked at ≤700px

---

## 5. The anti-regression rule

**Every improvement ends with a validator rule or a test — not just a
paragraph.** A lesson that lives only in prose will be forgotten.

When something goes wrong, ask which layer should have caught it:

| The problem is… | Add it to |
|---|---|
| Wrong or missing data in an edition | `scripts/validate.py` |
| Wrong behaviour in code | `tests/test_newspaper.py` |
| A judgement call a human must make | the checklist in §4 |
| Background on why | `docs/BKM.md` |

Then write the rule down in `docs/SPEC.md` if it is part of the contract.

### What is enforced today

`scripts/validate.py` refuses to publish when:
- a required edition field is missing, or the date disagrees with the filename
- the lead has no headline, source or URL
- the lead links to a research PDF that is not on disk
- a figure has no source, no bars, or a non-numeric value
- a brief is missing a field, or its URL is not absolute
- a URL repeats inside an edition, or was already printed in an earlier one
- the almanac has no `source` (weather must be measured, never written by hand)
- a learning topic has no `title`/`summary`, or its slug has no topic file
- a quiz has fewer than 3 questions, an out-of-range answer, or an unexplained one
- anything contains placeholder text or mojibake

`pytest` additionally covers: Hebrew word-start search (plurals must not
false-match), ledger URL normalization, no story printed twice, weather code
coverage, the compound-interest numbers quoted in the article, CSS brace
balance, dead CSS classes, missing local assets, and that the build runs clean.

---

## 6. Hard-won rules

- **Never run PowerShell string operations on a file containing Hebrew.** Use
  the editor tools. `Get-Content -Raw` reads UTF-8 as ANSI and `Set-Content`
  writes the damage back. Recovery recipe: `docs/BKM.md` §5.
- **`Out-File -Encoding utf8` adds a BOM** in Windows PowerShell, which breaks
  Python source files. A test now checks for this.
- **Always `$env:PYTHONIOENCODING="utf-8"`** before Python that prints Hebrew.
- **Never fabricate an ambient detail.** Weather is fetched; if the fetch fails,
  the printed value stands.
- **Facts aren't copyrightable, prose is.** Write every brief fresh.
