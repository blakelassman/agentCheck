"""Gemini transport for instruction scans, independent judges, and revisions."""
import json
import os
import re
from time import perf_counter
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class GeminiClient:
    is_mock = False

    def __init__(self, key=None, model=None):
        self.key = key if key is not None else os.environ.get("GEMINI_API_KEY", "")
        self.model = model if model is not None else os.environ.get("GEMINI_MODEL", "")

    @property
    def ready(self):
        return bool(self.key and re.fullmatch(r"[A-Za-z0-9._-]{1,120}", self.model))

    def generate(self, instructions, user_input, *, json_output=False, purpose="candidate", version=1):
        if not self.ready:
            raise ValueError("Configure a Gemini API key and model in Connection setup before running a live scan.")
        config = {"maxOutputTokens": 8192 if purpose in ("refine", "plan") else 4096}
        if json_output:
            config["responseMimeType"] = "application/json"
        body = {"systemInstruction": {"parts": [{"text": instructions}]},
                "contents": [{"role": "user", "parts": [{"text": user_input}]}],
                "generationConfig": config}
        request = Request(f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent",
                          data=json.dumps(body).encode(), method="POST",
                          headers={"Content-Type": "application/json", "x-goog-api-key": self.key})
        started = perf_counter()
        try:
            with urlopen(request, timeout=90) as response:
                data = json.load(response)
            candidates = data.get("candidates", [])
            parts = candidates[0].get("content", {}).get("parts", []) if candidates else []
            text = "".join(p.get("text", "") for p in parts if not p.get("thought"))
            result = {"text": text, "model": self.model, "latency_ms": round((perf_counter()-started)*1000)}
            finish = candidates[0].get("finishReason") if candidates else None
            if not text.strip() or finish not in (None, "STOP"):
                result["error"] = "The model response was empty, blocked or incomplete. Partial output is retained."
            return result
        except HTTPError as error:
            raise ValueError(f"Gemini returned HTTP {error.code}. Check the model, credentials, quota and account access.") from None
        except (URLError, TimeoutError, OSError):
            raise ValueError("Gemini connection failed or timed out.") from None
        except (ValueError, TypeError, AttributeError, IndexError):
            raise ValueError("Gemini returned an unexpected response format.") from None
