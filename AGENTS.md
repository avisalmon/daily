# Agent guide: היום בקיצור

A Hebrew, right-to-left daily newspaper. A human picks every story; the agent
proposes, verifies, writes and builds. Read `docs/RUNBOOK.md` before running a
day, and `docs/BKM.md` for why the rules exist.

## Voice: the paper must not read as machine-written

This is a hard rule, enforced by `scripts/style.py` and gated in the build.

**Never use an em dash (—).** It is the loudest AI tell there is. Hebrew prose
has commas, colons and full stops. Use them.

- `הרופא לא נעלם — הוא משנה תפקיד` becomes `הרופא לא נעלם. הוא משנה תפקיד`
- `מידע אישי — תוצאות בדיקות` becomes `מידע אישי: תוצאות בדיקות`
- An en dash is allowed **only tight, inside a range**: `2023–2026`, `פברואר–מרץ`.
  A spaced ` – ` is the same tell as an em dash.

**No emoji, ever.** Not in content, not in headings, not in the UI.

**No filler.** `חשוב לציין`, `בשורה התחתונה`, `בעידן שבו`, `אין ספק`,
`delve into`, `it's worth noting`, `game-changer`. If a sentence needs a
transition to justify itself, cut the sentence.

**No `לא רק X אלא גם Y`.** Say the thing.

**Write plainly.** Short sentences. Concrete nouns. A number instead of an
adjective. If a paragraph could describe any story, it describes none.

## Look: it is a newspaper, not an app

- **No cards.** No rounded corners, no drop shadows on content, no pill chips,
  no gradient buttons. Rules, rules and whitespace do the work.
- **No CTA buttons.** A link is a link: underlined text.
- Type and hierarchy carry the design. Colour is nearly absent by choice.
- The design contract is `docs/VISUAL_SPEC.md`. Do not invent components.

## Facts

- **Never print an unverified fact.** Fetch the article. The headline is not the
  story. Record what you checked in the plan's `verified` field.
- **Facts aren't copyrightable, prose is.** Write every brief fresh.
- **Never fabricate an ambient detail.** Weather is fetched or the last reading
  stands.
- Attribute reports as reports (`דיווח`), not as facts.

## Working rules

- Content is data: `data/editions/*.json`, `data/topics/*.json`. Templates
  render, they never invent.
- **Never run PowerShell string operations on a file containing Hebrew.**
  `Get-Content -Raw` reads UTF-8 as ANSI and `Set-Content` writes the damage
  back. Use the editor tools. Recovery recipe: `docs/BKM.md` §5.
- Always `$env:PYTHONIOENCODING="utf-8"` before Python that prints Hebrew.
- PowerShell has no `&&` or `||`. Use `;` and `if ($?) { }`.
- No paid API in the loop. Deep research is run externally, handed in as a PDF.
- Secrets live in `.env`, never in the repo.

## The anti-regression rule

**Every improvement ends with a validator rule or a test, not just a
paragraph.** A lesson that lives only in prose will regress.

| The problem is… | Add it to |
|---|---|
| Wrong data in an edition | `scripts/validate.py` |
| Wrong voice or styling | `scripts/style.py` |
| Wrong behaviour in code | `tests/test_newspaper.py` |
| A judgement a human must make | the checklist in `docs/RUNBOOK.md` §4 |

## Commands

```powershell
$env:PYTHONIOENCODING = "utf-8"
.\.venv\Scripts\python.exe scripts\build_site.py    # validates, then renders
.\.venv\Scripts\python.exe scripts\validate.py      # content contract
.\.venv\Scripts\python.exe scripts\style.py         # voice and tells
.\.venv\Scripts\python.exe scripts\research_bank.py # researches on hand
.\.venv\Scripts\python.exe -m pytest -q             # regression tests
```

## Known dead weight

`src/dailydigest/`, `config/digest.yaml`, `prompts/`, `templates/digest.*.j2`
and `output/` are scaffold from before the paper existed. Nothing in the real
pipeline imports them. Do not extend them; do not treat them as the
architecture.

## Deep research is a source, but a shaky one

scripts/deep_research.py produces a document that *looks* authoritative: a
citation on every sentence. The first real run cited only 7 domains across 91
citations, leaned on a dairy trade association and a content farm, and printed
the Catherine de Medici legend as fact while citing the article that debunks it
18 times.

It is still good enough to build a lead on. What is not optional is checking
the claims that actually reach the page.

- **Read the research document itself**, then go to where it got each fact,
  number, study or quote the article will print. The document is the map.
- **Look for what it tells you not to say.** A good brief carries its own
  warning, and the obvious version of the story is usually what it is warning
  about. That is what caught the ChatGPT attribution trap in the metacognition
  lead.
- **Write what you checked into the plan's `lead.verified`.** validate.py fails
  an edition whose lead cites research with no such note.
- The full two-pass seal (`verify_research.py`) is **no longer mandatory**. Run
  it when you have a specific reason to distrust a document. See BKM section 9
  and RUNBOOK section 7.
- Never run deep research to test connectivity. Use --status on an old run.
