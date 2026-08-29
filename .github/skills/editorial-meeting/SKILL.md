---
name: editorial-meeting
description: Run the editorial meeting for היום בקיצור - fetch fresh news from the source catalog and present three groups of proposals (AI/tech briefs, a deep-research lead topic, a learning topic) for the user to choose from, then persist the decisions to a plan file. TRIGGER - user says "ישיבת מערכת", "editorial meeting", "בוא נעשה ישיבת מערכת", "let's have an editorial meeting", "מה יש היום", "propose topics", "what's in tomorrow's paper".
---

# Editorial meeting

Command 1 of 2 in the edition workflow. See `docs/SPEC.md` §3 for the contract.
This skill **only decides and records**. It never builds an edition.

## Before you start

Read `docs/SPEC.md` §3 and §6. The edition being planned is **tomorrow's**.

## Step 1 — Fetch

Read `config/sources.yaml` and fetch every source. Fetch in **one batch**, not
sequentially.

```powershell
.\.venv\Scripts\python.exe scripts\fetch_news.py --hours 48
```

Rules:
- Keep items from the last **48 hours**. On a quiet day widen the window
  rather than padding the paper with weak items.
- Deduplicate: the same story from three outlets is **one** candidate. Prefer
  the primary source (an OpenAI post beats three outlets reporting it).
- If a feed fails, report it and continue. Do not abort the meeting. If a feed
  fails repeatedly, say so — its `verified` date in the catalog is stale.

## Step 2 — Present three groups

All proposals in **Hebrew**. Present all three groups in one message so the
user can decide in a single pass.

### א. חדשות AI וטכנולוגיה
10–15 candidates. Each: one-line Hebrew description, source, publication time,
link. Order by **interest, not recency**. The user picks 5–10.

### ב. נושא למחקר עומק (כתבה ראשית)
3–5 topics. Wider than AI — Israel, science, technology, economics. Each states
the topic, why it matters now, and **the question the research should answer**.
A good topic has a real question; "מה חדש ב-AI" is not one.

### ג. נושא ללימוד
3–5 "מה זה…" topics at high-school level. Bias toward **visually explainable**
topics — phase 2 adds diagrams and a simulator.

## Step 3 — Persist

Once the user has chosen, write `data/plans/YYYY-MM-DD.plan.json` using the
edition date. Schema is in `docs/SPEC.md` §3.4.

**This step is mandatory.** The build may run hours later in a fresh session;
decisions held only in conversation are lost.

Then tell the user:
1. The plan file path.
2. The research question they're taking to NotebookLM/Gemini.
3. Where the PDF goes: `data/research/YYYY-MM-DD-slug.pdf`.

## Do not

- Do not build the edition. That is command 2.
- Do not choose on the user's behalf. This paper exists because a human picks.
- Do not run any paid API. The meeting is free — fetching and reading only.
