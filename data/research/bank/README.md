# בנק המחקרים / The research bank

Deep researches waiting for an edition. **Drop PDFs here with any filename** —
no date, no naming convention. This is the pool of ready leads.

```powershell
.\.venv\Scripts\python.exe scripts\research_bank.py          # what's in the bank
.\.venv\Scripts\python.exe scripts\research_bank.py show <id># preview the text
.\.venv\Scripts\python.exe scripts\research_bank.py use <id> 2026-09-02
```

## Why undated

A file in `data/research/` is named `YYYY-MM-DD-slug.pdf` — it is bound to one
edition. A research in the bank isn't bound to anything yet. It becomes dated
only when you pick it at an editorial meeting, and `use` copies it into place
under the name the build expects.

So: **`bank/` is the pool, `data/research/` is the queue.**

## What the scan records

Reading each PDF once, into `data/research/bank.json`:

| Field | Why |
|---|---|
| `title` | first substantial line — usually right, editable by hand |
| `pages`, `words` | is this a real research or a two-page note? |
| `language` | `he` or `en`, detected from the text |
| `extractable` | **`false` means a scanned PDF** — it cannot be summarized |
| `preview` | first ~320 chars, enough to recognize it |
| `used_in` | the edition that consumed it, or `null` |
| `notes` | yours. The scan never overwrites it |

Re-running `scan` is safe: existing entries keep their metadata, so a title you
corrected or a note you wrote stays.

## Rules

- **The PDFs are gitignored; `bank.json` is committed.** The index is the record
  of what we hold and what we published from. If a file disappears the entry is
  flagged `missing` rather than deleted — publication history must survive.
- A research is used **once**. `use` refuses to claim an item twice.
- **Check `extractable` before promising a lead.** A scanned PDF has no text
  layer and would need OCR.
- Hebrew PDFs extract with varying quality depending on the producing tool.
  Always eyeball `show <id>` before it becomes an edition.
