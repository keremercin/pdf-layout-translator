# pdf-layout-translator

Low-cost Telegram-first PDF translator using configurable provider models for OCR + translation.

## Scope (MVP S1)
- Channel: Telegram-only
- Language pairs: `tr,en` and `en,tr`
- Model policy: provider-selectable (`openai` or `openrouter`)
- Billing: credits with manual Stars verification
- Retention: 24-hour cleanup

## API
- `GET /health`
- `GET /version`
- `POST /v1/jobs` (multipart: file, source_lang, target_lang, telegram_user_id)
- `GET /v1/jobs/{job_id}`
- `GET /v1/jobs/{job_id}/download?telegram_user_id=...`
- `GET /v1/credits/{telegram_user_id}`
- `POST /v1/admin/credits/grant` (Header: `x-admin-token`)
- `GET /v1/admin/jobs/stats` (Header: `x-admin-token`)

## Quickstart
```bash
cp .env.example .env
python -m venv .venv
source .venv/bin/activate
pip install -e .[dev]
python scripts/init_db.py
uvicorn pdf_translator.api.main:app --reload --port 8900
```

For OpenAI-first testing:
- `MODEL_PROVIDER=openai`
- `OPENAI_API_KEY=...`
- Suggested starter models: `OPENAI_TRANSLATE_MODEL=gpt-4.1-mini`, `OPENAI_OCR_MODEL=gpt-4.1-mini`

## OpenAI presets
- `./.env.openai.min-cost`: lower cost (`translate=gpt-4.1-nano`, `ocr=gpt-4.1-mini`)
- `./.env.openai.balanced`: safer quality baseline (`translate=gpt-4.1-mini`, `ocr=gpt-4.1-mini`)
- `./.env.local`: put only your secret key here (`OPENAI_API_KEY=...`), this file is git-ignored

Usage:
```bash
cp .env.openai.balanced .env   # or .env.openai.min-cost
cp .env.local.example .env.local
# edit .env.local and set OPENAI_API_KEY
```

## Pre-Telegram model smoke test
Run model-level PDF validation (text-layer + scanned-like):
```bash
make smoke-model
```
This command creates sample PDFs under `data/smoke/`, opens jobs through the API app, waits for completion, and saves translated outputs under `outputs/`.

## Single fixed reference PDF (always use this)
Reference test file:
- `data/fixtures/reference_english.pdf`
- Source: `https://arxiv.org/pdf/1706.03762.pdf`

Run fixed-file smoke:
```bash
make smoke-reference
```
Output file:
- `outputs/reference_english_en_tr.translated.pdf`

Tuning (same reference PDF, faster loops):
- `SMOKE_REFERENCE_PAGES=5` (default, first 5 pages)
- `SMOKE_REFERENCE_PAGES=15` (full file)
- `SMOKE_REFERENCE_TIMEOUT_SEC=420`

## Candidate benchmark (our engine vs external tools)
Run a quick layout benchmark on first 2 pages:
```bash
python scripts/benchmark_layout_candidates.py
```
Expected candidate paths:
- `outputs/reference_english_en_tr.translated.pdf`
- `outputs/bench_pdf2zh/reference_english-mono.pdf`
- `outputs/bench_pdf2zh_babeldoc/reference_english.tr.mono.pdf`

## Telegram bot
```bash
export TELEGRAM_BOT_TOKEN=...
python -m pdf_translator.bot.telegram_bot
```

## Credits and manual payment flow
1. User checks `/pricing`
2. User requests `/buy` and receives reference code
3. Admin verifies Stars payment externally
4. Admin grants credits via `POST /v1/admin/credits/grant`

## Cleanup
Run periodic cleanup (cron):
```bash
python scripts/cleanup_expired.py
```

## Notes
- Page limit per job: 150
- File size limit: 80MB
- Layout preservation is block-based (best effort)
