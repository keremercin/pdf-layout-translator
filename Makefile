.PHONY: install init-db cleanup run-api run-bot test lint smoke-model

install:
	python -m venv .venv && . .venv/bin/activate && python -m pip install -e .[dev]

init-db:
	python scripts/init_db.py

cleanup:
	python scripts/cleanup_expired.py

run-api:
	uvicorn pdf_translator.api.main:app --reload --port 8900

run-bot:
	python -m pdf_translator.bot.telegram_bot

test:
	pytest -s

lint:
	ruff check src tests scripts

smoke-model:
	python scripts/smoke_pdf_model.py
