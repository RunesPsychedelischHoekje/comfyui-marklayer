"""Minimal MarkLayer API client using only the standard library (no extra installs inside ComfyUI)."""
import json
import os
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

RAPIDAPI_HOST = "marklayer.p.rapidapi.com"
DEFAULT_URL = f"https://{RAPIDAPI_HOST}"
CONFIG_FILE = Path(__file__).parent / "config.json"
USER_AGENT = "comfyui-marklayer/1.0"


class MarkLayerError(Exception):
    pass


def load_settings() -> tuple[str, str]:
    """Return (api_key, base_url).

    The key never comes from a node widget: ComfyUI writes every widget value into the PNG
    metadata of each image it saves, so a key typed into the node would leak into every output.
    """
    key = os.environ.get("MARKLAYER_API_KEY", "").strip()
    url = os.environ.get("MARKLAYER_API_URL", "").strip()
    if CONFIG_FILE.exists():
        try:
            cfg = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise MarkLayerError(f"Could not read {CONFIG_FILE}: {exc}") from exc
        key = key or str(cfg.get("api_key", "")).strip()
        url = url or str(cfg.get("api_url", "")).strip()
    return key, (url or DEFAULT_URL).rstrip("/")


def _multipart(fields: dict[str, str], file_field: str, filename: str, data: bytes, mime: str) -> tuple[bytes, str]:
    boundary = uuid.uuid4().hex
    parts = []
    for name, value in fields.items():
        parts.append(
            f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode()
        )
    parts.append(
        f'--{boundary}\r\nContent-Disposition: form-data; name="{file_field}"; filename="{filename}"\r\n'
        f"Content-Type: {mime}\r\n\r\n".encode()
        + data
        + b"\r\n"
    )
    parts.append(f"--{boundary}--\r\n".encode())
    return b"".join(parts), f"multipart/form-data; boundary={boundary}"


def mark(image_png: bytes, *, kind: str, generator: str, output_format: str, quality: int,
         timeout: float = 120.0, retries: int = 3) -> tuple[bytes, dict[str, str]]:
    """POST /v1/mark. Returns (marked file bytes, response headers)."""
    key, base = load_settings()
    if not key and "rapidapi.com" in base:
        raise MarkLayerError(
            "No MarkLayer API key. Set the MARKLAYER_API_KEY environment variable, or copy "
            "config.example.json to config.json in the comfyui-marklayer folder and put your "
            "RapidAPI key in it. Get a key at https://rapidapi.com/RunesPsychedelischHoekje/api/marklayer"
        )
    fields = {"kind": kind, "format": output_format, "quality": str(quality)}
    if generator:
        fields["generator"] = generator
    body, ctype = _multipart(fields, "file", "comfyui.png", image_png, "image/png")
    headers = {"Content-Type": ctype, "User-Agent": USER_AGENT}
    if key:
        headers["X-RapidAPI-Key"] = key
        headers["X-RapidAPI-Host"] = RAPIDAPI_HOST

    delay = 2.0
    for attempt in range(retries + 1):
        req = urllib.request.Request(f"{base}/v1/mark", data=body, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read(), {k.lower(): v for k, v in resp.headers.items()}
        except urllib.error.HTTPError as exc:
            # 429 = plan rate limit, 503 = server busy: both are worth a short wait and retry.
            if exc.code in (429, 503) and attempt < retries:
                time.sleep(delay)
                delay *= 2
                continue
            raise MarkLayerError(_describe(exc)) from exc
        except urllib.error.URLError as exc:
            raise MarkLayerError(f"Could not reach MarkLayer at {base}: {exc.reason}") from exc
    raise MarkLayerError("MarkLayer stayed busy after several retries.")


def _describe(exc: urllib.error.HTTPError) -> str:
    try:
        payload = json.loads(exc.read().decode("utf-8", "replace"))
    except ValueError:
        payload = {}
    err = payload.get("error") if isinstance(payload, dict) else None
    detail = err.get("message") if isinstance(err, dict) else payload.get("message") if isinstance(payload, dict) else None
    hints = {
        401: "Your API key was rejected. Check MARKLAYER_API_KEY or config.json.",
        403: "Access denied. Check that you are subscribed to MarkLayer on RapidAPI and the key is right.",
        413: "Image too large for MarkLayer. Mark before upscaling, or downscale first.",
        429: "Rate limit or monthly quota reached for your RapidAPI plan.",
    }
    return f"MarkLayer error {exc.code}: {detail or hints.get(exc.code) or exc.reason}" + (
        f" ({hints[exc.code]})" if detail and exc.code in hints else ""
    )
