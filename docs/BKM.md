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

## 9. Deep research is a map, not a source

`o3-deep-research` writes beautifully and cites every sentence. That is exactly
what makes it dangerous. A citation next to a sentence means the model found
that sentence somewhere, not that it is true.

Measured on the first real run (history of ice cream, 30 minutes, 86 web
searches, 132K tokens): **91 citations across only 7 unique domains.** The two
heaviest were `idfa.org`, the dairy industry trade association, and a content
farm. No academic or primary sources. It searched broadly and cited narrowly.

It printed two well-known legends as fact:

- Catherine de Medici bringing sorbet to France in 1533. It cited the Wikipedia
  article that debunks this **18 times** and reproduced the myth anyway.
- Soft serve invented in 1939 by Dairy Queen. The real rival claims are Carvel
  1936 and McCullough 1938, and there is no uncontested first.

It also garbled a Chinese term and contradicted itself on a date: 550 BC in one
paragraph, 400 BCE in another, about the same structures.

### The three-pass rule

```
1. research   scripts/deep_research.py            -> raw document
2. pass A     one model, source-anchored          -> a check per claim
3. pass B     a DIFFERENT model, adversarial      -> a second check
4. seal       scripts/verify_research.py seal     -> printable, or not
```

**Both passes must be source-anchored, not model-anchored.** This is the whole
trick. A second model asked "is this true?" from memory will confirm the Medici
myth, because that myth saturates training data. That is the same error twice,
and it *feels* like corroboration. So a check only counts if it carries a URL
**and a verbatim quote from that URL**. No quote, no check. `verify_research.py`
enforces this and rejects a check whose quote is under 20 characters.

The point of the second model is that it fails *differently*, and it only fails
differently if it is forced to go and read something. When it was, it beat pass
A twice: it fetched Chinese Wikipedia to show that su shan is a real Tang-era
dish but had been conflated with a separate one, and it found Nancy Johnson's
actual 1843 patent, a primary source neither the research nor pass A reached.

Give pass B the adversarial framing explicitly. It was told the domain
concentration, that idfa.org is a trade group, and that food history is full of
charming myths. A neutral "please check this" prompt would not have produced
the same scrutiny.

### What agreement and disagreement mean

Two checkers agreeing gives a verdict. Two checkers disagreeing gives
`disputed`, which is not a failure of the process but the point of it: it marks
where a human must decide. On the ice cream run the two passes agreed on both
myths and split three ways, on Persia, Charles I, and the 1692 cookbook author.
All three splits were real ambiguities in the historical record.

A claim is printable only when two *different* checkers agree and both showed
evidence. Everything else is cut, or printed openly as a legend, which is
usually the better story anyway.

### Give the token ceiling far more headroom than looks sane

Reasoning tokens are charged against `max_output_tokens`, and on a hard
question they are nearly all of it. The first "trust in the AI era" run spent
**44,352 of its 46,678 output tokens on reasoning**, hit the 50,000 ceiling,
and stopped *before writing a single word*: 17 minutes and 167K tokens for an
empty result. Nothing warns you in advance, and the run is not resumable.

The ceiling is a cap, not a budget. Raising it costs nothing unless it is
actually used, while setting it too low costs you the entire run. The floor is
now 150,000.

Note this interacts with the standing brief: demanding twelve domains, a
disputed-claims section and a source assessment makes the model think harder,
so a better prompt raises the token ceiling you need.

### Do not use deep research to test connectivity

A one-word "ping" probe ran to completion at 34 searches and 51,870 tokens. It
cannot be made lazy, and a trivial question costs about as much as a real one.
Test the plumbing with `--status` against an existing run instead.

### The client must survive a network blip

A momentary DNS failure killed a submit with a raw traceback. The job is half
an hour long and lives server-side, so losing the client is a pure own goal.
`_call` retries transient errors with backoff, and on giving up it prints the
run id and how to reattach. HTTP errors are still fatal, because a 401 will
not fix itself by waiting.

### Claim ids must be content-derived

The first version of `verify_research.py` numbered claims by position. Changing
the extractor shifted every sentence by one, and previously recorded checks
**silently reattached to the wrong claims**: a check quoting Charles I ended up
filed against the Catherine de Medici claim. Ids are now a hash of the claim
text, so a claim keeps its identity and a reworded claim correctly becomes a
new, unchecked one.
