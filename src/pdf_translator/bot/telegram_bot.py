import asyncio
import tempfile
from pathlib import Path

import httpx
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters

from pdf_translator.config import settings


async def _poll_job(job_id: str) -> dict:
    async with httpx.AsyncClient(timeout=30) as client:
        for _ in range(120):
            r = await client.get(f"{settings.api_base_url}/v1/jobs/{job_id}")
            r.raise_for_status()
            data = r.json()["data"]
            if data["status"] in {"completed", "failed"}:
                return data
            await asyncio.sleep(2)
    raise RuntimeError("Job timeout")


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "Send me a PDF document with caption format: source_lang,target_lang\n"
        "Example: en,tr"
    )


async def handle_pdf(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.message.document:
        return

    caption = (update.message.caption or "en,tr").strip()
    parts = [x.strip() for x in caption.split(",")]
    if len(parts) != 2:
        await update.message.reply_text("Caption must be: source_lang,target_lang (example: en,tr)")
        return

    source_lang, target_lang = parts
    tg_file = await update.message.document.get_file()

    with tempfile.TemporaryDirectory() as td:
        local_in = Path(td) / update.message.document.file_name
        await tg_file.download_to_drive(custom_path=str(local_in))

        await update.message.reply_text("Uploading and creating translation job...")

        async with httpx.AsyncClient(timeout=120) as client:
            files = {"file": (local_in.name, local_in.read_bytes(), "application/pdf")}
            data = {"source_lang": source_lang, "target_lang": target_lang}
            r = await client.post(f"{settings.api_base_url}/v1/jobs", files=files, data=data)
            r.raise_for_status()
            job = r.json()["data"]

        await update.message.reply_text(f"Job created: {job['job_id']}. Processing...")
        final_job = await _poll_job(job["job_id"])

        if final_job["status"] == "failed":
            await update.message.reply_text(f"Job failed: {final_job.get('error', 'unknown error')}")
            return

        async with httpx.AsyncClient(timeout=120) as client:
            dr = await client.get(f"{settings.api_base_url}/v1/jobs/{job['job_id']}/download")
            dr.raise_for_status()
            out_path = Path(td) / f"{job['job_id']}.translated.pdf"
            out_path.write_bytes(dr.content)

        await update.message.reply_document(document=out_path.open("rb"), filename=out_path.name)


def main() -> None:
    if not settings.telegram_bot_token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is not set")

    app = Application.builder().token(settings.telegram_bot_token).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.Document.PDF, handle_pdf))
    app.run_polling()


if __name__ == "__main__":
    main()
