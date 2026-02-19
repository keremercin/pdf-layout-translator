.PHONY: install init-db run-api run-bot test lint

install:
	python -m venv .venv && . .venv/bin/activate && pip install -e .[dev]

init-db:
	python scripts/init_db.py

run-api:
	uvicorn pdf_translator.api.main:app --reload --port 8900

run-bot:
	python -m pdf_translator.bot.telegram_bot

test:
	pytest

lint:
	ruff check src tests scripts
