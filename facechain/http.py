"""Single HTTP entry point: shared session, honest user agent, bounded retries.

Every network call in facechain goes through here (and usually through cache.py on top),
so quotas, timeouts and offline mode have one place to live.
"""

from __future__ import annotations

import random
import re
import time
from collections.abc import Mapping
from typing import Any

import requests

USER_AGENT = "facechain/0.1 (+https://github.com/Vishal4742/facechain)"
BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/128.0 Safari/537.36"
)
RETRY_STATUS = {429, 500, 502, 503, 504}

SESSION = requests.Session()
SESSION.headers["User-Agent"] = USER_AGENT


SECRET_RE = re.compile(r"(api_key|token|jwt|authorization|key)=([^&\s'\"]+)", re.IGNORECASE)


def redact(text: str) -> str:
    """Strip credential-looking query values from any message that may reach a screen."""
    return SECRET_RE.sub(lambda m: f"{m.group(1)}=REDACTED", text)


class HttpError(RuntimeError):
    """Raised after retries are exhausted or on a non-retryable HTTP status."""

    def __init__(self, message: str) -> None:
        super().__init__(redact(message))


def request(
    method: str,
    url: str,
    *,
    params: Mapping[str, Any] | None = None,
    headers: Mapping[str, str] | None = None,
    data: Any = None,
    files: Any = None,
    json: Any = None,
    timeout: float = 20,
    retries: int = 3,
    stream: bool = False,
) -> requests.Response:
    """Send a request; retry with jittered backoff on 429/5xx/network errors only."""
    last_error: Exception | None = None
    for attempt in range(retries + 1):
        try:
            resp = SESSION.request(
                method,
                url,
                params=params,
                headers=headers,
                data=data,
                files=files,
                json=json,
                timeout=timeout,
                stream=stream,
            )
        except requests.RequestException as exc:  # DNS, timeout, connection reset
            last_error = exc
        else:
            if resp.status_code not in RETRY_STATUS:
                return resp
            last_error = HttpError(f"{method} {redact(url)} -> HTTP {resp.status_code}")
            retry_after = resp.headers.get("Retry-After")
            if retry_after and retry_after.isdigit():
                time.sleep(min(int(retry_after), 30))
                continue
        if attempt < retries:
            time.sleep(min(2**attempt, 8) + random.uniform(0, 0.5))
    raise HttpError(
        f"{method} {redact(url)} failed after {retries + 1} attempts: {redact(str(last_error))}"
    )


def get(url: str, **kwargs: Any) -> requests.Response:
    return request("GET", url, **kwargs)


def post(url: str, **kwargs: Any) -> requests.Response:
    return request("POST", url, **kwargs)


def download_bytes(
    url: str,
    *,
    max_bytes: int = 10 * 1024 * 1024,
    timeout: float = 8,
    referer: str | None = None,
    accept_prefix: str = "image/",
) -> bytes | None:
    """Fetch a media file with a browser UA. Returns None on any failure or non-media response."""
    headers = {"User-Agent": BROWSER_UA, "Accept": "image/avif,image/webp,image/*,*/*;q=0.8"}
    if referer:
        headers["Referer"] = referer
    try:
        resp = request("GET", url, headers=headers, timeout=timeout, retries=1, stream=True)
    except HttpError:
        return None
    if resp.status_code != 200:
        return None
    ctype = resp.headers.get("Content-Type", "")
    if accept_prefix and not ctype.startswith(accept_prefix):
        return None
    chunks: list[bytes] = []
    size = 0
    try:
        with resp:
            for chunk in resp.iter_content(chunk_size=65536):
                size += len(chunk)
                if size > max_bytes:
                    return None
                chunks.append(chunk)
    except requests.RequestException:
        return None
    return b"".join(chunks)
