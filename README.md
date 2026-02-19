# pdf-layout-translator

Low-cost API-first PDF translator using OpenRouter for OCR + translation.

## What this MVP does
- Upload a PDF and create async translation jobs
- Extracts text blocks from text-based PDFs
- Falls back to model-based OCR for scanned pages
- Translates blocks with a low-cost model (`flash-lite` default)
- Rebuilds translated PDF with block-level placement
- Exposes job status and download endpoints
- Includes Telegram bot adapter

## API
- `GET /health`
- `GET /version`
- `POST /v1/jobs` (multipart file + source_lang + target_lang)
- `GET /v1/jobs/{job_id}`
- `GET /v1/jobs/{job_id}/download`

## Quickstart
```bash
cp .env.example .env
python -m venv .venv
source .venv/bin/activate
pip install -e .[dev]
python scripts/init_db.py
uvicorn pdf_translator.api.main:app --reload --port 8900
```

## Telegram bot
```bash
export TELEGRAM_BOT_TOKEN=...
python -m pdf_translator.bot.telegram_bot
```

## Notes
- This is an MVP focused on low-cost operation.
- Layout preservation is block-based and not perfect for all complex PDFs.
- For better quality, configure fallback model for low-confidence chunks.
