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
| nature.com | **406 for the article, the PDF and the Wayback copy** — blocked, rejected as a source |
| Times of Israel, Davar, Haaretz | **403 to fetching** — verify the story elsewhere and link the source you actually read |
| openai.com | **403 to fetching** — fall back to their RSS `summary`, it's authoritative |
| Hacker News | high noise, weight 0.7 |

**Stories age out of the recency window between fetches.** A story proposed
fifteen minutes earlier fell out of the 48h window before the build; the window
was widened to 96h to recover it. If a chosen story vanishes, widen, don't drop.

**A blocked source is not a source.** `validate.py::BLOCKED_DOMAINS` refuses a
brief that cites one, because the paper's whole claim is that every fact was
checked against the article. When the chosen item sits behind a block, find an
outlet you can actually read, verify there, and link that. Record the original
in the plan's `companion_url` so the substitution is visible later. This is how
the Nature piece on the Nepal collapse was replaced with New Scientist, which
turned out to carry a materially better-sourced version of the story.

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

## 9. Deep research is a shaky source, not a forbidden one

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

### Verify what you print, cut the rest

The trust document produced 66 claims. Demanding two independent checks on all
of them made sealing so expensive that the real temptation became skipping the
gate, which is the single outcome this whole system exists to prevent. A gate
that is too costly to use is not a gate.

So a claim marked `cut` no longer needs verifying: it is not going to appear
in print. `cut-unverified` closes a document honestly by cutting everything
that never got a second check, and `printable` lists what an article may
actually rest on. The seal now reports both numbers, and the trust document
sealed at 25 claims cleared and 41 cut.

### 2026-09-05: the seal stopped being mandatory

Everything above still describes what deep research does wrong. What changed is
what the paper does about it.

`validate.check_research_sealed` was supposed to enforce the three-pass rule. It
was keyed on an edition field, `research`, that no edition ever set, so across
eight editions **it never ran once**. Every deep-research lead this paper has
printed went out unsealed. The gate was not protecting anything, it was
describing a protection that did not exist, which is worse than having none: it
let the rule read as enforced in the docs while the actual defence was one
person reading carefully.

The section above already predicted this. "A gate that is too costly to use is
not a gate." Two adversarial passes over 60 to 90 claims is roughly a full extra
session per lead, for a paper with one reader.

So the standing rule is now:

- **Deep research is trusted as a source.** Not as gospel, but as good enough to
  build a lead on without sealing it first.
- **What the lead actually prints is still spot-checked at its own source.** Not
  every claim in the document. The claims that reach the page.
- **That check is recorded** in the plan's `lead.verified`, exactly as briefs
  record theirs. `check_plan` fails an edition whose lead cites research with no
  such note. The day the rule was added it caught two plans, one of them the
  edition that had shipped the night before.

`verify_research.py` is kept, and is still worth running on a document you have
a specific reason to distrust: one leaning on trade associations, or one making
a historical claim that sounds too tidy. It is a tool now, not a toll gate.

**Do not read this as permission to print from a research document unread.**
The spot-check is what caught the trap in the metacognition lead, where the
document itself says "אין לייחס לה טענות כגון אקרמן הראתה ש-ChatGPT יוצר אשליית
הבנה", the exact sentence the obvious version of that story wanted to write. The
seal would not have caught it. Reading the source did.

This is not a loophole. Cutting does not launder an unchecked claim into
print, it removes it from what may be used, and there is a test that says so.
Write only from the cleared claims.

### A real quote from the wrong document defeats the quote rule

This is the most important limitation found so far, and it is a hole in the
method rather than in the code.

On its third batch, pass B reversed a series of its own earlier, correct
verdicts. It called the Ipsos interpersonal-trust figures false by fetching
the Ipsos *Global Trustworthiness Index*, a different survey by the same
pollster. It called the 2024 Gallup media figures false by fetching the *2023*
Gallup poll. It declared the KPMG 2025 AI study "actually from 2023" and its
fieldwork dates "fabricated", while pasting a quote that reads "(2025) ... A
global study 2025", contradicting its own verdict.

Every one of those checks carried a real URL and a genuine verbatim quote, so
every one passed the mechanical gate. The quote requirement stops a model
answering from memory. It does **not** stop a model reading the wrong page
with total confidence.

Two defences follow from this:

- **A checker reversing itself is a red flag, not a correction.** `add_check`
  now keeps the superseded check, records the reversal, and prints a warning
  naming both URLs. Importing that batch blindly would have overwritten good
  checks with bad ones while looking like progress.
- **Watch for right-source-wrong-edition.** Annual reports and repeat surveys
  are the trap: the same pollster, the same title, the wrong year. When a
  check contradicts an earlier one, compare the two URLs before believing
  either.

Coverage also decays. Pass B did 6 useful claims, then 21, then a batch that
was mostly wrong. Push a checker for volume and quality falls off a cliff
rather than degrading gently.

### Most disputes are about precision, not facts

The trust document produced four disputes, and in two of them **both checkers
fetched the same page and quoted the same sentence, then disagreed about what
it meant**. The document called a Pew survey a "Feb 2023 survey" when the
fieldwork ran 12-18 December 2022 and February was merely the publication
date. It reported that 85% of leaders "reported lower trust in employee
productivity" when the source says they find it "challenging to have
confidence that employees are being productive".

Neither is a factual error in the arithmetic sense, and a lenient checker
waves both through. Both are still wrong to print: one misdates a survey, the
other rewrites the question that was actually asked. Attributing a survey to
its publication date, or restating its question in livelier words, is an
error and not a paraphrase.

This is where the mandatory quote earns its keep a second time. Because the
quote is stored in the ledger, a disagreement can be settled by reading the
evidence already collected, without re-fetching anything and without asking a
third model to guess.

### The percentages were right and the labels were wrong

The most dangerous errors in the trust document were not invented numbers.
63 to 56 and 49 to 62 were both exactly correct. What was wrong was the year,
2023 instead of 2024, and the metric: those figures track whether people
*perceive AI as trustworthy*, not whether they are *willing to trust* it,
which fell 52 to 43 instead. A number that survives a smell test while
describing a different quantity is far more likely to reach print than an
obvious fabrication. Check the year, the metric and the sample, not just the
digits.

### Write the ledger atomically

An import failed mid-write with OSError 22 on Windows, most likely a scanner
holding the file. Because `save()` wrote in place, that could have truncated a
ledger representing hours of checking and a paid research run. It now writes a
temporary file and replaces it, so the ledger is always either the old version
or the new one.

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
---

## 10. A rule that cannot fire is worse than no rule

The lesson of `check_research_sealed` (§9) generalises, and it is the most
expensive kind of mistake this project can make, because it is invisible.

The function was correct. Its logic was right, it was tested, and the tests
passed. It was gated on `ed.get("research")`, a field no edition ever set, so it
returned on its first line every single time. For eight editions the docs said
deep research was gated and it was not.

**A passing test proves the function works, not that it runs.** Those two tests
called the function directly with a hand-built fixture. Nothing checked that the
production path ever reached it.

So, when you add a validator rule:

1. **Run it against the real data and confirm it FAILS first.** If a new rule
   passes immediately on eight editions of real content, be suspicious. It has
   probably found nothing because it is looking nowhere. The `lead.verified`
   rule that replaced the seal caught two real plans the minute it was written,
   including the edition that had shipped the night before. That failure was the
   evidence the rule was wired up.
2. **Test the real data as well as a fixture.** Every fixture test wants a
   sibling that walks `data/editions/*.json` and asserts the same thing. See
   `test_every_lead_citing_research_records_what_was_checked`.
3. **Delete a guard you decide not to enforce.** Leaving it in place is not a
   neutral act. It makes the next reader, including you in three weeks, believe
   in a protection that is not there. `test_the_dead_seal_gate_is_gone` exists
   so the corpse cannot walk back in.

## 11. Templates drift away from data, silently

Everything the reader sees goes through Jinja, and Jinja does not raise on a
missing key. `{{ edition.podcast.src }}` where the key is actually `file`
renders an empty string and the page ships looking fine.

Two live examples, both found in one session:

**The podcast player never worked.** `podcast.py` wrote `podcast.file`,
`validate.py` checked `podcast.file`, and the template read `podcast.src`. Three
places, two spellings. Any recorded episode would have rendered no player at all
and reported nothing. It went unnoticed only because every episode so far has
been a link.

**A topic can name a simulator the template has never heard of.** `topic.html.j2`
dispatches on the literal string `compound-interest` inside a Jinja `if`.
A typo, or a new type with no branch, renders the section heading and its intro
with nothing underneath. Valid JSON, valid HTML, empty page.

The guards, both now in `test_newspaper.py`:

- `test_podcast_key_matches_what_the_recorder_writes` reads all three files and
  fails if they stop agreeing on the key.
- `test_e_topic_simulator_and_diagrams_are_rendered` walks every topic and every
  section, and fails if any `sim.type` or `diagram.type` has no branch in the
  template.

**The general rule: when data names something the template must dispatch on, a
test walks the data and asserts the template can handle every value.** Grep for
the literal, do not trust that it is there.

## 12. Rehearse a time-gated publish, do not reason about it

The paper publishes itself at midnight by rebuilding hourly and comparing the
edition date against `paper_today()`. Reading that code and concluding it will
work is not the same as knowing.

Monkeypatch the clock and run the real build:

```python
import build_site, datetime
build_site.paper_today = lambda: datetime.date(2026, 9, 6)
build_site.build(include_future=False)
```

Then assert on the output: the front page is the new edition, its headline is
there, the learning topic entered the catalog, yesterday moved to the archive
rail. This is not the same as `--include-future`, which only proves the edition
*can* render. It proves the promotion happens.

**Rebuild plainly afterwards.** The rehearsal leaves a future edition sitting in
`index.html`, and committing that publishes the paper a day early. `pytest` will
catch it, but do not rely on that.

## 13. Compute a number before you print it

The `e` learning page states what the limit gives at n=12 and n=365, what ten
terms of the series give, and where 63.2% and 36.8% come from. Every one of
those was calculated in Python first, and several first guesses were wrong: the
draft claimed seven terms gave six digits of accuracy. It gives four. Ten terms
gives six.

A reader cannot catch this. There is no source to check it against, because the
paper is the source. So the numbers are pinned in
`test_e_topic_matches_the_numbers_it_prints`, which recomputes each one and
asserts the string still appears on the page. Change the page, the test tells
you which number you broke.

The same applies to any figure the paper derives rather than quotes.

## 14. A borrowed image needs a credit more than a caption

The paper draws its own diagrams as SVG, so for eight editions there was no way
to print a raster image and no rules about it. The first one, a NotebookLM
infographic, needed rules written from scratch.

What `validate.py` now enforces on `lead.image`:

- **Local only.** The `src` must exist in the repository. Hotlinking sends your
  readers to another host and breaks when that host reorganises.
- **`alt`, `caption`, `credit`, `width`, `height` all required.** The credit is
  the load-bearing one: a raster image in this paper is by definition somebody
  else's work.
- **Say what the image asserts that the research does not.** That infographic
  has an 80% gauge that corresponds to no measurement in the source. The credit
  says so. An image can make a claim the article never makes, and a reader will
  believe the picture.

Aspect ratio is the documented exception: an infographic keeps its native shape,
because cropping one to the standard 3:2 destroys information.

## 15. The repository is published, not just the site

The commit that added sections 10 to 14 turned the Pages deployment red. Nothing
was wrong with the paper. `publish` was green, `validate`, `style` and 118 tests
all passed, and the built HTML was correct.

GitHub Pages was running Jekyll over the whole repository, and Jekyll renders
Liquid before markdown. Section 11 quotes a Jinja tag:

    { % if topic.sim.type == 'compound-interest' % }

Jinja and Liquid share that syntax. Liquid read it as a real tag, found no
matching `endif`, and refused to build. Backticks do not help, because Liquid
runs before the fence is understood. The error pointed at the last line of the
file, not the offending one.

The fix is `.nojekyll` at the repository root. This site is pre-built static
HTML; Jekyll had no business touching it and was only ever a chance to corrupt
something. `test_nojekyll_exists` keeps the file there.

Two things generalise:

- **Everything in the repository is published, including the documentation.** A
  file you think of as a note to yourself is an input to a build.
- **A green workflow is not a green deploy.** `publish` and `pages-build-deployment`
  are separate runs. Check both, `gh run list --limit 3` shows them side by side.


