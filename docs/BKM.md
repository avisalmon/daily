# BKM — running "היום בקיצור"

Best-known method for producing an edition, written after the first real
edition (2026-08-30) shipped end to end. Read this before running a paper.

---

## 1. The daily loop

```
  ישיבת מערכת  →  you run deep research  →  בנה את העיתון  →  build → verify
   (agent proposes)      (external, hours)      (agent writes)
```

Three rules that make it work:

1. **The agent never picks the content.** It proposes; you choose. Every
   edition traces back to an explicit decision of yours.
2. **The meeting and the build are separate commands.** Hours pass between
   them, often across sessions, so the decisions are persisted to
   `data/plans/YYYY-MM-DD.plan.json`. Never hold them in conversation only.
3. **An edition is dated tomorrow.** A meeting today produces tomorrow's
   paper. It is read in the morning.

---

## 2. Verify every fact before printing

This is the highest-value habit in the whole project, and it is not optional.

**Fetch the actual article. Never write a brief from the RSS headline.**

On the very first edition this caught a real error that would have been
printed:

> The aggregated headline said Nvidia was buying Hugging Face for **$13B**.
> The article said **$12.9B**, said the deal was **not finalized**, sourced it
> to a single outlet (The Information) with CNBC only confirming that talks
> existed, and noted **Salesforce had also bid**.

Everything except the number would have been lost. The brief was rewritten to
say "דיווח" (report), to give 12.9, and to name the sourcing.

Other things verification caught:

- **Headline framing ≠ article substance.** One outlet framed a court ruling
  about Anthropic in culture-war terms; the ruling was First Amendment
  retaliation. The brief was written from the outlet that described the
  substance.
- **Unconfirmed expansions stay unexpanded.** "MHS" was never confirmed to
  stand for anything specific, so the brief says "MHS" and nothing more.
- **Never fabricate an ambient detail.** The weather line is fetched from
  `wttr.in`. If it can't be fetched, it doesn't run.

Record what you checked, per item, in the plan's `verified` field. Future-you
needs to know the difference between "confirmed" and "assumed".

---

## 3. Write the briefs, don't copy them

Facts aren't copyrightable; prose is. Every brief is written fresh in Hebrew,
and links to the source. A brief that reads like a paste is a bug.

---

## 4. The ledger is what makes this sustainable

`data/ledger.json` is editorial memory and is committed to git.

- `published` — printed already, filtered out of future meetings automatically.
- `proposed` — shown but not chosen, with a `times_proposed` counter, so good
  stories you passed on can resurface instead of being lost.

Always close the loop after a build:

```powershell
python scripts\record_edition.py 2026-08-30 --proposed data\_news_cache.json
python scripts\ledger.py     # confirm the counts moved
```

**Verify the exclusion actually worked** by re-running the fetch — it should
report `already printed (skipped): N`. Matching is by normalized URL, not by
keyword, which is deliberate: "Hugging Face" correctly still appears for
genuinely different Hugging Face stories.

---

## 5. Environment hazards that cost real time

These are Windows/PowerShell specific and all of them have bitten this project.

**Never let PowerShell touch a file containing Hebrew.**
`Get-Content -Raw` reads UTF-8 as ANSI, and `Set-Content` then writes the
mojibake back. This silently corrupted the whole of `docs/SPEC.md` during this
project — every Hebrew word became `×ž×™×`. Use the `view`/`edit`/`grep` tools
instead, which are UTF-8 correct.

*If it does happen, it is recoverable* — the bytes are intact, just
double-encoded. Reverse it per character with cp1252, falling back to latin-1
for the five undefined bytes (`0x81 0x8D 0x8F 0x90 0x9D`):

```python
out = bytearray()
for c in text:
    try: out += c.encode('cp1252')
    except Exception: out.append(ord(c))   # ord(c) < 0x100
fixed = out.decode('utf-8')
```
Verify by counting Hebrew runs (`[\u0590-\u05FF]+`) before overwriting, and
always write the repair to a temp file first.

**`>` redirection writes UTF-16.** It produced
`UnicodeDecodeError: 0xff in position 0` on the next `json.load`. Use
`Out-File -Encoding utf8`, and read with `encoding='utf-8-sig'`.

**Set `$env:PYTHONIOENCODING="utf-8"`** before any Python that prints Hebrew.

**PowerShell has no `&&`, `||`, `?.`** — use `;` and `if ($?) { }`.

**pip's upgrade notice goes to stderr**, which surfaces as `NativeCommandError`
even on success. Confirm with a separate import check.

**The `create` tool refuses to overwrite.** Delete first.

---

## 6. Source quirks worth remembering

| Source | Behaviour |
|---|---|
| VentureBeat | `/category/ai/feed` works; **a trailing slash returns 308** |
| Calcalist | **403 even with a browser UA** — blocked, rejected as a source |
| openai.com | **403 to fetching** — fall back to their RSS `summary`, it's authoritative |
| Hacker News | high noise, weight 0.7 |

**Stories age out of the recency window between fetches.** A story proposed
fifteen minutes earlier fell out of the 48h window before the build; the window
was widened to 96h to recover it. If a chosen story vanishes, widen, don't drop.

---

## 7. Hebrew search is not substring search

Hebrew plurals end in `-ים`, so a substring search for `מים` ("water") also
matches `אלגוריתמים` ("algorithms") — it returned 9 results where 2 were
correct. Terms must match at a **word start**, allowing one leading prefix
letter from `ו ה ב כ ל מ ש` so `המים` still finds `מים`.

Search only matches text as written: `Anthropic` in Latin will not be found by
its Hebrew spelling.

---

## 8. Before you call an edition done

- [ ] Every brief fetched and fact-checked, with `verified` notes in the plan
- [ ] Numbers match the article, not the headline
- [ ] Briefs written in our own words, each with a working source link
- [ ] Research PDF published, lead links to it
- [ ] `record_edition.py` run, and re-fetch confirms the skip count
- [ ] `python scripts\build_site.py` clean, `pytest -q` green
- [ ] **Opened in a browser** — index, archive, search (try a Hebrew *and* a
      Latin term), learn, and one archived edition
- [ ] Checked at ≤700px for mobile
