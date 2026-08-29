# Agent guide — DailyDigest

## What this project is
A daily digest news creator. Pipeline: **fetch → normalize → dedup → filter → rank → summarize → render → deliver**.

## Ground rules
- Python 3.11+. Code lives in `src/dailydigest/`. Keep modules single-purpose.
- Never commit secrets. All keys come from `.env` (see `.env.example`).
- Never write generated artifacts into `src/`. Digests go to `output/digests/`.
- Config is data, not code: sources/topics/schedule live in `config/*.yaml`.
- Prompts live in `prompts/*.md`, not inline in Python.
- Add a test in `tests/` for every new processing rule.

## Commands
```powershell
.\scripts\setup.ps1              # venv + deps
python -m dailydigest --dry-run  # run pipeline without delivering
pytest -q                        # tests
```

## Open decisions (fill in when spec lands)
- [ ] Topics / audience
- [ ] Source list
- [ ] LLM provider (Azure OpenAI vs local Ollama)
- [ ] Delivery channel (email / file / Teams / WhatsApp)
- [ ] Schedule + trigger (Task Scheduler / GitHub Actions)
