# RUNBOOK — producing an edition

The daily procedure. **`docs/SPEC.md` says what must be true; this says what to
do; `docs/BKM.md` says why.** If those three ever disagree, SPEC wins.

---

## Where each kind of rule lives

Put a new rule in exactly one place. Duplicating it guarantees drift.

| Kind of rule | Home | Enforced by |
|---|---|---|
| What must be true of an edition | `docs/SPEC.md` | `scripts/validate.py` |
| How the paper must sound | `AGENTS.md` (Voice) | `scripts/style.py` |
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

**First check the bank** — you may already have one ready:

```powershell
.\.venv\Scripts\python.exe scripts\research_bank.py
```

`data/research/bank/` holds undated researches for future days. Drop PDFs there
any time, under any filename. If tomorrow's lead comes from the bank, claim it:

```powershell
.\.venv\Scripts\python.exe scripts\research_bank.py use <id> YYYY-MM-DD
```

Otherwise run the research externally (NotebookLM / Gemini / ChatGPT) and drop
the PDF in:

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
topic page, publishes the research PDF, and fetches weather for Haifa once per
paper-day.

**An edition dated ahead is held back.** You are writing tomorrow's paper, so
the normal result is that the build reports the new edition as held back and
leaves the front page showing today's. That is correct — commit it anyway. See
SPEC §8. To read it before its day:

```powershell
.\.venv\Scripts\python.exe scripts\build_site.py --include-future   # preview only
.\.venv\Scripts\python.exe scripts\build_site.py                    # withdraw again
```

Never commit the output of `--include-future`. Rebuild without the flag first.

Afterwards, close the editorial loop:

```powershell
.\.venv\Scripts\python.exe scripts\record_edition.py YYYY-MM-DD --proposed data\_news_cache.json
.\.venv\Scripts\python.exe scripts\ledger.py
```

## 3a. Podcast

Optional, and only worth it when the research is good. Two steps with a read in
between, exactly like the meeting and the build.

```powershell
# draft the script from the research, then stop
.\.venv\Scripts\python.exe scripts\podcast.py --date YYYY-MM-DD --source data\research\bank\slug.md

# read data/podcasts/YYYY-MM-DD.script.md, edit it, then check it for free
.\.venv\Scripts\python.exe scripts\podcast.py --date YYYY-MM-DD --dry-run

# record it, archive it, and drop old local episodes
.\.venv\Scripts\python.exe scripts\podcast.py --date YYYY-MM-DD --speak --upload --prune
```

`--speak` writes `audio/YYYY-MM-DD.mp3`, adds the `podcast` block to the edition
JSON, and the build renders the player. Rebuild after recording.

`--prune` keeps the newest 30 episodes in the repository and drops the rest. It
never deletes a file the release archive does not already hold, and it records
the archive URL in the edition JSON first, so an old episode keeps playing from
the release. If you see `! keeping <file>: not in the release yet`, run
`--upload` for that date before pruning again.

Read the script before spending money on it. The style rules are enforced and
will refuse a script with a voice tell, but they cannot catch a claim the
research does not support, and that is the failure that matters.

## 3b. Publish

Committing is now the whole of publishing, and it is safe: the edition is dated
ahead, so pushing it does not put it in front of a reader. This is the last step
of command 2 - there is no third command to remember.

```powershell
git add -A
git commit -F <message-file>   # PowerShell has no heredoc; never use <<EOF
git push origin main
git ls-remote origin main      # the only trustworthy check - see BKM §5
```

At midnight Jerusalem, the hourly `publish` workflow rebuilds on GitHub's
machines and promotes the edition. Nothing on this machine needs to be running,
awake, or even switched on.

If the push itself was the last thing to change the repo, that same workflow
runs immediately as a check. It is green when the paper is publishable and it
refuses to commit anything if `validate.py`, the build or the tests fail.

## 4. Before calling it done

- [ ] Every brief **fetched and read** — never written from the RSS headline
- [ ] Numbers match the article, not the headline
- [ ] Each brief in our own words, with a working source link
- [ ] `verified` note recorded per item in the plan
- [ ] Lead figure built from **real numbers**, with its source cited
- [ ] `python scripts\validate.py` passes
- [ ] `pytest -q` green
- [ ] Built **without** `--include-future` as the last build before committing
- [ ] Opened in a browser: index, archive, search (Hebrew **and** Latin term),
      learn, the topic page, and one archived edition
- [ ] Checked at ≤700px
- [ ] After pushing, the run of `publish` on GitHub is green

---

## 5. The anti-regression rule

**Every improvement ends with a validator rule or a test — not just a
paragraph.** A lesson that lives only in prose will be forgotten.

When something goes wrong, ask which layer should have caught it:

| The problem is… | Add it to |
|---|---|
| Wrong or missing data in an edition | `scripts/validate.py` |
| The paper sounding machine-written | `scripts/style.py` |
| Wrong behaviour in code | `tests/test_newspaper.py` |
| A judgement call a human must make | the checklist in §4 |
| Background on why | `docs/BKM.md` |

Then write the rule down in `docs/SPEC.md` if it is part of the contract.

### Voice, enforced

`scripts/style.py` refuses to publish content containing:

- an **em dash** (`—`), the loudest AI tell there is, or a **spaced en dash**.
  A tight en dash inside a range (`2023–2026`, `פברואר–מרץ`) is correct and allowed
- an **emoji** or decorative symbol, anywhere
- an **arrow glyph** in prose (allowed in a chart axis label)
- **filler phrases**: `חשוב לציין`, `בשורה התחתונה`, `בעידן שבו`, `אין ספק`,
  `delve into`, `it's worth noting`, `game-changer`
- the **`לא רק X אלא גם Y`** construction

Look is checked too: `test_no_card_styling_in_css` fails on any rounded corner,
because this is a newspaper and not an app.

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
- an edition declares a podcast under the wrong filename, or one that is neither
  on disk nor in the release archive
- anything contains placeholder text or mojibake

`pytest` additionally covers: Hebrew word-start search (plurals must not
false-match), ledger URL normalization, no story printed twice, weather code
coverage, the compound-interest numbers quoted in the article, CSS brace
balance, dead CSS classes, missing local assets, podcast script parsing and
chunking, that a pruned episode still validates and still renders, the local
audio retention window, and that the build runs clean.

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

## 7. Deep research, when you use it

Optional and expensive. About 30 minutes and 130K tokens per question, so decide
it is worth it before starting. Never run it to test connectivity.

```powershell
python scripts\deep_research.py "your question"     # ~30 min, files into the bank
python scripts\deep_research.py --status resp_...   # cheap plumbing check
```

Auth is your own Azure AD identity. Just `az login`. There is no key to fetch,
and `az cognitiveservices account keys list -g rg-modelon-westus` will fail
because that resource is in a subscription we cannot see. That is expected.

**What comes back is not printable.** It is a map of what to check. Run the
three passes before any of it reaches the paper:

```powershell
python scripts\verify_research.py extract <doc-id>

# generate the adversarial prompt for a checker, then hand it to a sub-agent
python scripts\verify_research.py brief <doc-id> --for <model>

# record a whole pass at once from the JSON it returns
python scripts\verify_research.py import <doc-id> --by <model> --file findings.json

# obvious calls: confirmed to print, false to cut, disputed left to you
python scripts\verify_research.py auto-disposition <doc-id>

# close honestly: anything that never got a second check is cut, not printed
python scripts\verify_research.py cut-unverified <doc-id>
python scripts\verify_research.py printable <doc-id>
python scripts\verify_research.py seal <doc-id>
```

Pass B must be a different model family and must be told to *falsify*, not to
review. Tell it the document's weaknesses up front: which domains dominate,
which of them are trade groups or content farms, and that the subject area is
prone to myths. A neutral "please check this" gets a neutral rubber stamp.

Both passes must fetch and quote. A check without a verbatim quote is refused,
because a model answering from memory reproduces exactly the myths you are
trying to catch.

**Verify what you print and cut the rest.** A 66-claim document will not get
two checks on every sentence, and a gate too expensive to use is not a gate.
`cut-unverified` removes the unchecked claims from what may be written, which
is honest; it does not pretend they were verified.

**Watch for a checker reversing itself.** The tool prints a warning naming both
URLs when this happens. It usually means the second pass fetched the wrong
document: a different survey by the same pollster, or last year's edition of
the same annual report. A real quote from the wrong page passes every
mechanical check, so this is the one thing you must judge yourself.

Then decide what to do with what survived:

- `confirmed` by both, print it
- `disputed`, either drop it or print it openly as a disputed story
- `false`, cut it, or print it as a legend and say so, which is often the
  better piece anyway

`validate.py` refuses to build an edition whose `research` points at an unsealed
document, so this cannot be skipped by accident.
