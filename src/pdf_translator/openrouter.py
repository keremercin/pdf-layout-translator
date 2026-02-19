import base64
import json
import time

import httpx

from pdf_translator.config import settings


class OpenRouterError(RuntimeError):
    pass


class OCRParseError(OpenRouterError):
    pass


class OCRTimeoutError(OpenRouterError):
    pass


class TranslateTimeoutError(OpenRouterError):
    pass


class OpenRouterClient:
    def __init__(self) -> None:
        self.base_url = settings.openrouter_base_url.rstrip("/")
        self.api_key = settings.openrouter_api_key

    def _headers(self) -> dict:
        if not self.api_key:
            raise OpenRouterError("OPENROUTER_API_KEY is not set")
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    def _post_chat(self, body: dict, timeout_sec: int, timeout_exc: type[Exception]) -> dict:
        last_err: Exception | None = None
        for attempt in range(3):
            try:
                with httpx.Client(timeout=timeout_sec) as client:
                    r = client.post(f"{self.base_url}/chat/completions", headers=self._headers(), json=body)
                    r.raise_for_status()
                    return r.json()
            except httpx.TimeoutException as exc:
                last_err = timeout_exc(str(exc))
            except httpx.HTTPStatusError as exc:
                code = exc.response.status_code
                if code in {429, 500, 502, 503, 504}:
                    last_err = OpenRouterError(f"transient_http_{code}")
                else:
                    raise OpenRouterError(f"http_{code}: {exc.response.text}") from exc
            except Exception as exc:
                last_err = OpenRouterError(str(exc))

            time.sleep(0.6 * (attempt + 1))

        assert last_err is not None
        raise last_err

    def translate_text(self, text: str, source_lang: str, target_lang: str, model: str | None = None) -> str:
        model = model or settings.openrouter_translate_model
        prompt = (
            f"Translate from {source_lang} to {target_lang}. "
            "Preserve meaning, numbers, symbols and line intent. "
            "Return only translated text.\n\n"
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
        data = self._post_chat(body, timeout_sec=settings.translate_timeout_sec, timeout_exc=TranslateTimeoutError)
        return data["choices"][0]["message"]["content"].strip()

    def ocr_page(self, image_bytes: bytes, source_lang: str, model: str | None = None) -> list[dict]:
        model = model or settings.openrouter_ocr_model
        b64 = base64.b64encode(image_bytes).decode("utf-8")
        prompt = (
            "Extract text blocks and return strict JSON array. "
            "Each item must have text,x0,y0,x1,y1,confidence. No prose."
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
        data = self._post_chat(body, timeout_sec=settings.ocr_timeout_sec, timeout_exc=OCRTimeoutError)
        content = data["choices"][0]["message"]["content"].strip()

        if content.startswith("```"):
            content = content.strip("`")
            if content.startswith("json"):
                content = content[4:].strip()

        try:
            parsed = json.loads(content)
        except json.JSONDecodeError as exc:
            raise OCRParseError(f"invalid_ocr_json: {content[:250]}") from exc

        if not isinstance(parsed, list):
            raise OCRParseError("ocr_response_not_list")
        return parsed
