# מחקרים נכנסים / Incoming research

Drop the ready-made deep-research PDF for an edition here.

## Naming

```
YYYY-MM-DD-slug.pdf
```

Example: `2026-08-29-ai-chip-export-rules.pdf`

The date prefix binds the research to an edition. `slug` is free-form and
only helps humans scan the folder.

## What happens to it

The PDF is the **source** for the lead story (`data/editions/YYYY-MM-DD.json`).
Text is extracted, then condensed into the edition's headline, standfirst and
body.

The build then **copies the PDF to `research/YYYY-MM-DD.pdf` in the published
site**, and the lead story links to it — a lead citing research the reader
can't open is weak. See `docs/SPEC.md` §5.

## Notes

- The file in *this* folder is the working input and is gitignored; the
  published copy under `research/` is the artifact.
- Text-based PDFs only. A scanned/image PDF needs OCR and will not extract.
- Hebrew PDFs: extraction quality depends on the producing tool. Always
  eyeball the extracted text before it becomes an edition.
