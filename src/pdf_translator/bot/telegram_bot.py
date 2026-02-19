import asyncio
import tempfile
from pathlib import Path

import httpx
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters

from pdf_translator.config import settings


PRICING_TEXT = (
    "Pricing (manual credit packs):\n"
    "- Starter: 100 pages\n"
    "- Growth: 350 pages\n"
    "- Pro: 1200 pages\n\n"
    "Use /buy to get payment instructions."
)


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


async def _get_balance(telegram_user_id: int) -> dict:
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.get(f"{settings.api_base_url}/v1/credits/{telegram_user_id}")
        r.raise_for_status()
        return r.json()["data"]["balance"]


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "Welcome to PDF Layout Translator.\n"
        "Supported language pairs: tr,en or en,tr\n"
        "Send PDF with caption like: en,tr\n\n"
        "Commands: /balance /pricing /buy /status <job_id>"
    )


async def balance(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_user:
        return
    bal = await _get_balance(update.effective_user.id)
    await update.message.reply_text(
        f"Credits:\nAvailable: {bal['available_credits']}\nReserved: {bal['reserved_credits']}"
    )


async def pricing(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(PRICING_TEXT)


async def buy(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_user:
        return
    ref_code = f"STARS-{update.effective_user.id}-{int(asyncio.get_event_loop().time())}"
    await update.message.reply_text(
        "Manual payment flow (MVP):\n"
        "1) Send Stars payment to the configured bot/admin channel\n"
        "2) Share this reference code to admin\n"
        f"Reference: {ref_code}\n"
        "3) Credits will be granted manually"
    )


async def status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        await update.message.reply_text("Usage: /status <job_id>")
        return

    job_id = context.args[0]
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.get(f"{settings.api_base_url}/v1/jobs/{job_id}")

    if r.status_code == 404:
        await update.message.reply_text("Job not found")
        return
    r.raise_for_status()
    data = r.json()["data"]
    await update.message.reply_text(
        f"Job {job_id}\nStatus: {data['status']}\nPages: {data['pages_processed']}/{data['pages_total']}"
    )


async def handle_pdf(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.message.document or not update.effective_user:
        return

    caption = (update.message.caption or "en,tr").strip().lower()
    parts = [x.strip() for x in caption.split(",")]
    if len(parts) != 2 or parts[0] not in {"tr", "en"} or parts[1] not in {"tr", "en"} or parts[0] == parts[1]:
        await update.message.reply_text("Caption must be tr,en or en,tr")
        return

    source_lang, target_lang = parts
    tg_file = await update.message.document.get_file()

    with tempfile.TemporaryDirectory() as td:
        local_in = Path(td) / update.message.document.file_name
        await tg_file.download_to_drive(custom_path=str(local_in))

        await update.message.reply_text("Creating translation job...")

        async with httpx.AsyncClient(timeout=120) as client:
            files = {"file": (local_in.name, local_in.read_bytes(), "application/pdf")}
            data = {
                "source_lang": source_lang,
                "target_lang": target_lang,
                "telegram_user_id": str(update.effective_user.id),
            }
            r = await client.post(f"{settings.api_base_url}/v1/jobs", files=files, data=data)

        if r.status_code in {402, 403}:
            await update.message.reply_text("Insufficient credits. Use /buy and /balance")
            return
        if r.status_code >= 400:
            await update.message.reply_text(f"Job create failed: {r.text[:300]}")
            return

        job = r.json()["data"]
        await update.message.reply_text(f"Job created: {job['job_id']} ({job['pages_total']} pages)")

        final_job = await _poll_job(job["job_id"])
        if final_job["status"] == "failed":
            await update.message.reply_text(
                f"Job failed: {final_job.get('failure_reason_code', 'UNKNOWN')} / {final_job.get('error', '')}"
            )
            return

        async with httpx.AsyncClient(timeout=120) as client:
            dr = await client.get(
                f"{settings.api_base_url}/v1/jobs/{job['job_id']}/download",
                params={"telegram_user_id": update.effective_user.id},
            )
            dr.raise_for_status()
            out_path = Path(td) / f"{job['job_id']}.translated.pdf"
            out_path.write_bytes(dr.content)

        await update.message.reply_document(document=out_path.open("rb"), filename=out_path.name)


def main() -> None:
    if not settings.telegram_bot_token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is not set")

    app = Application.builder().token(settings.telegram_bot_token).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("balance", balance))
    app.add_handler(CommandHandler("pricing", pricing))
    app.add_handler(CommandHandler("buy", buy))
    app.add_handler(CommandHandler("status", status))
    app.add_handler(MessageHandler(filters.Document.PDF, handle_pdf))
    app.run_polling()


if __name__ == "__main__":
    main()
