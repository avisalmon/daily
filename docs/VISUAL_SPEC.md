# DailyDigest — Visual Specification (LOCKED)

**Status: APPROVED 2026-08-27.** This document is the contract for how every edition looks.
Content decisions live in `docs/SPEC.md`. This file governs *presentation only*.

> **Change control:** Do not alter the design tokens, layout structure, or module set below
> without explicit approval. Bug fixes (broken layout, accessibility, responsive defects) are
> always allowed. New *content* never requires a design change — it requires a new field in the
> edition schema, which must be added to §6 here first.

---

## 1. Concept

A classic broadsheet newspaper rendered for the screen. Warm paper stock, hairline rules,
high-contrast serif display type, generous column structure. It should read as a *published
edition*, not as a feed or a dashboard. Restraint over decoration: the only color is one
editorial red used sparingly.

---

## 2. Design tokens

Canonical source: `assets/css/newspaper.css` `:root`. Never hardcode these values elsewhere.

### Color

| Token | Value | Use |
|---|---|---|
| `--ink` | `#16130f` | Body text, headlines |
| `--ink-soft` | `#4a443c` | Summaries, standfirst, secondary text |
| `--ink-faint` | `#857d72` | Bylines, meta, captions |
| `--rule` | `#d8d1c4` | Hairline column and list rules |
| `--rule-dark` | `#16130f` | Heavy section and masthead rules |
| `--paper` | `#f7f4ec` | Page background |
| `--paper-alt` | `#efe9dc` | Tinted panels (opinion, almanac, current archive row) |
| `--accent` | `#8c1c13` | Editorial red — kicker, drop cap, hover, current edition |
| `--accent-2` | `#1c4b73` | Link blue — original-source links only |

The page carries a faint two-layer radial dot texture to simulate newsprint. Keep it.

### Type

| Token | Stack | Use |
|---|---|---|
| `--serif` | Playfair Display | Masthead, all headlines, pull-quotes, drop cap, almanac temperature |
| `--body` | Spectral | Body copy, standfirst, summaries, briefs |
| `--sans` | Inter | Kickers, section labels, meta, bylines, dateline, colophon, archive |

Rules:
- Base body: **17px / 1.62**.
- Every sans element is uppercase with wide letter-spacing (`.13em`–`.34em`) and small (10.5–13px).
- Headlines use negative letter-spacing (`-.01em` to `-.02em`) and tight leading (≤1.14).
- Display sizes are fluid via `clamp()`. Do not replace with fixed sizes.
- Fonts load from Google Fonts with local serif fallbacks; the page must remain legible offline.

### Measure

Max content width **1380px**. Main column + **300px** sticky right rail, **34px** gutter.

---

## 3. Page anatomy

Fixed order. Sections may be omitted when data is absent, never reordered.

```
[ archive banner ]          only on non-latest editions
masthead
  ├─ meta strip             place · edition no. · price
  ├─ title                  "The Daily Digest" ("Daily" italic light)
  ├─ tagline
  ├─ double rule
  └─ dateline strip         date · sections · story + read count
paper (2-col grid)
  ├─ main
  │   ├─ lead story         text left (1.35fr) / art right (1fr)
  │   ├─ grid sections      repeating: section head + 3-col story grid
  │   └─ opinion strip      tinted, 2-up, portrait + pull-quote
  └─ rail (sticky)
      ├─ In Brief           numbered list
      ├─ Past Editions      archive, current row highlighted
      ├─ Almanac            place / temperature / conditions
      └─ Quote of the Day
colophon                    double-rule footer
```

### Module rules

- **Lead story** — one per edition, mandatory. Kicker, headline, italic standfirst, body
  paragraphs with a red drop cap on the first, byline with source link, art with caption.
- **Story grid** — 3 columns, zero gap, separated by hairline rules; first/last column lose
  outer padding. A story flagged `wide: true` spans 2 columns and gets a larger headline and a
  21:9 crop.
- **Opinion strip** — exactly 2 items, tinted panel, circular grayscale portraits.
- **Rail** — sticky at 20px. Each module has an uppercase head over a 2px rule.
- **Archive** — every edition ever published, newest first, scrollable at 340px, current
  edition highlighted in accent red.
- **Archive banner** — dark bar on any edition that is not the latest, linking back to today.

### Imagery

All art is desaturated (`grayscale(.35)`–`grayscale(1)`) with slight added contrast and a
hairline border. Aspect ratios are fixed: lead **3:2**, standard story **16:10**, wide story
**21:9**, portrait **1:1** circular. Placeholder art is generated locally as SVG engravings by
`scripts/build_site.py` — no external image requests.

#### Raster lead art (`lead.image`)

The lead may carry one real image, served from `assets/img/` in this repository.
It renders as `.leadart`: the image inside a hairline border and linked to the
full-size file, then a caption under a thin rule with the credit beneath it.

Three rules, all enforced by `scripts/validate.py`:

- **Never hotlinked.** The `src` must be a repo-relative path that exists on
  disk. A remote URL leaks readers to another host and rots when that host
  moves.
- **Always credited.** `alt`, `caption`, `credit`, `width` and `height` are all
  required. The paper draws its own diagrams as SVG, so a raster image is by
  definition somebody else's work, and the credit is what keeps that honest. If
  the image asserts a number the research does not support, say so in the
  credit.
- **Documented exception on aspect ratio.** The fixed ratios above do not apply.
  An infographic carries information in its layout, and cropping it to 3:2
  destroys some of that information, so it keeps its native ratio and the
  `width`/`height` attributes reserve the right space while it loads.

Desaturation still applies, at the light end (`grayscale(.35)`), so the image
sits in the paper rather than shouting over it.

```json
"image": {
  "src": "assets/img/2026-09-06-metacognition.webp",
  "width": 2000, "height": 1116,
  "alt": "...", "caption": "...", "credit": "..."
}
```

### Video

A story may carry an optional `video` object. It renders as a 16:9 frame inside the
article, between the headline and the summary, styled like a photograph: a hairline
border, no rounded corners, no shadow, no invented play button. The caption sits under
a thin rule in the sans face at 12.5px, with the credit in small caps.

```json
"video": {
  "youtube_id": "CHjdtTROPZg",
  "caption": "…",
  "credit": "Associated Press"
}
```

Rules, all of them binding:

- **YouTube only, embedded via `youtube-nocookie.com`.** No Facebook, Instagram or
  TikTok embeds — they require a tracking SDK and frequently fail to render.
- **The ID must be verified before it is printed**, by calling the YouTube oEmbed
  endpoint, which confirms the video exists, is embeddable, and returns the real
  publisher name for the credit. Never write an ID from memory or inference.
- **Prefer a news agency or newspaper** as publisher, for the same reason we prefer
  primary sources in text.
- `loading="lazy"` always, so a video never delays the front page.
- **Video does not print.** The `@media print` block hides the frame and keeps the
  caption.

---

## 4. Responsive behavior

| Breakpoint | Change |
|---|---|
| ≤1080px | Rail unsticks and moves below main content, separated by a heavy rule |
| ≤860px | Lead stacks to one column; story grid drops to 2 columns; opinion goes 1-up |
| ≤620px | Story grid drops to 1 column; wide stories become normal; padding tightens |
| `print` | Rail and banner hidden, background goes white |

---

## 5. Site architecture

```
data/editions/YYYY-MM-DD.json    one file per edition — the ONLY content input
templates/edition.html.j2        the layout (one template serves every page)
assets/css/newspaper.css         the entire visual design
assets/img/                      generated SVG placeholder art
scripts/build_site.py            renders all editions, then copies newest to index.html
index.html                       always the latest edition (base = "")
editions/YYYY-MM-DD.html         permanent archived pages (base = "../")
```

Invariants:
- **`index.html` is always the newest edition** and is fully regenerated on every build.
- **Archived editions are immutable in content** but re-rendered on every build so the archive
  list and design updates propagate to old pages.
- **Publishing a day = writing one JSON file and running the build.** Nothing else.
- Adding an edition must never require editing HTML, CSS, or the template.
- Relative asset paths come from the `base` variable — never hardcode `assets/...` in the
  template without it.

Build:
```powershell
.\.venv\Scripts\python.exe scripts\build_site.py
```

---

## 6. Edition data schema

`data/editions/YYYY-MM-DD.json`. Fields marked ✓ are required.

| Field | Type | Req | Notes |
|---|---|:--:|---|
| `date` | string | ✓ | `YYYY-MM-DD`, must match the filename |
| `date_long` | string | ✓ | e.g. `Thursday, 27 August 2026` |
| `number` | int | ✓ | Sequential edition number |
| `read_minutes` | int | ✓ | Shown in the dateline |
| `compiled_at` | string | ✓ | e.g. `07:30 IDT`, shown in the colophon |
| `sections` | string[] | ✓ | Section names listed in the dateline |
| `lead` | object | ✓ | See below |
| `grid` | object[] | ✓ | `{ name, stories[] }` — one entry per section block |
| `opinion` | object[] | | `{ quote, author, source, avatar }` — 2 items |
| `briefs` | object[] | | `{ text, url }` |
| `almanac` | object | | `{ place, temp, conditions }` |
| `quote` | object | | `{ text, author }` |

`lead`: `kicker`, `headline`, `standfirst`, `body` (string[] of paragraphs), `source`, `time`,
`url`, `image`, `caption` — all required.

`grid[].stories[]`: `headline`, `summary`, `source`, `time`, `url` required; `image`,
`wide` (bool) and `video` (`{ youtube_id, caption, credit }`) optional. See §3 *Video*
for the verification rule that governs `youtube_id`.

`story_count` is computed at build time — do not put it in the JSON.

Content rules:
- Use real Unicode characters (`·`, `°`, `&`), **never HTML entities** — output is autoescaped.
- Every story needs a working `url` back to its original source.
- Text is plain; no HTML markup inside JSON string values.

---

## 7. Editorial voice (visual consequences)

Headlines are declarative and sized to be read at a glance. Summaries are 1–2 sentences of
flat, factual prose. No emoji, no exclamation marks, no hype adjectives — the design assumes
sober copy and will look wrong without it.
