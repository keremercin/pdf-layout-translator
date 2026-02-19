import base64
import json

import httpx

from pdf_translator.config import settings


class OpenRouterClient:
    def __init__(self) -> None:
        self.base_url = settings.openrouter_base_url.rstrip("/")
        self.api_key = settings.openrouter_api_key

    def _headers(self) -> dict:
        if not self.api_key:
            raise RuntimeError("OPENROUTER_API_KEY is not set")
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    def translate_text(self, text: str, source_lang: str, target_lang: str, model: str | None = None) -> str:
        model = model or settings.openrouter_translate_model
        prompt = (
            f"Translate the text from {source_lang} to {target_lang}. "
            "Preserve meaning, numbers, special symbols, and inline structure. "
            "Return only translated text without commentary.\n\n"
            f"TEXT:\n{text}"
        )
        body = {
            "model": model,
            "messages": [
                {"role": "system", "content": "You are a high-precision translator."},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0,
        }
        with httpx.Client(timeout=90) as client:
            r = client.post(f"{self.base_url}/chat/completions", headers=self._headers(), json=body)
            r.raise_for_status()
            data = r.json()
        return data["choices"][0]["message"]["content"].strip()

    def ocr_page(self, image_bytes: bytes, source_lang: str, model: str | None = None) -> list[dict]:
        model = model or settings.openrouter_ocr_model
        b64 = base64.b64encode(image_bytes).decode("utf-8")
        prompt = (
            "Extract readable text blocks from this page image and return strict JSON array only. "
            "Each item must have: text, x0, y0, x1, y1, confidence. "
            "Coordinates must be in image pixel space."
        )
        body = {
            "model": model,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": f"Source language hint: {source_lang}. {prompt}"},
                        {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}},
                    ],
                }
            ],
            "temperature": 0,
        }
        with httpx.Client(timeout=120) as client:
            r = client.post(f"{self.base_url}/chat/completions", headers=self._headers(), json=body)
            r.raise_for_status()
            data = r.json()
        content = data["choices"][0]["message"]["content"].strip()
        if content.startswith("```"):
            content = content.strip("`")
            if content.startswith("json"):
                content = content[4:].strip()
        parsed = json.loads(content)
        if not isinstance(parsed, list):
            raise ValueError("OCR response is not a list")
        return parsed
