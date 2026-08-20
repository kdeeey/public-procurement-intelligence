import time
import hashlib
import os
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv()

BASE_URL = "https://www.marchespublics.gov.ma/"
RATE_LIMIT = float(os.getenv("SCRAPER_RATE_LIMIT_SECONDS", "2"))
USER_AGENT = os.getenv(
    "SCRAPER_USER_AGENT",
    "public-procurement-intelligence-bot (academic project)",
)
MAX_RETRIES = 3


class PMPPDownloader:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": USER_AGENT})
        self._last_request_time = 0.0

    def _wait(self):
        elapsed = time.time() - self._last_request_time
        if elapsed < RATE_LIMIT:
            time.sleep(RATE_LIMIT - elapsed)
        self._last_request_time = time.time()

    def get(self, url: str, **kwargs) -> requests.Response:
        self._wait()
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                resp = self.session.get(url, timeout=30, **kwargs)
                resp.raise_for_status()
                return resp
            except requests.RequestException as e:
                if attempt == MAX_RETRIES:
                    raise
                wait = 2 ** attempt
                print(f"[retry {attempt}/{MAX_RETRIES}] {e} — waiting {wait}s")
                time.sleep(wait)

    def post(self, url: str, data: dict, timeout: int = 120,
             retries: int = 4, **kwargs) -> requests.Response:
        """Rate-limited POST with retries.

        PRADO postbacks (pagination) carry the whole form and are noticeably
        slower than GETs — the portal stalls sporadically on deep pages, and a
        bare failure would abandon a whole listing walk.
        """
        last: Exception | None = None
        for attempt in range(1, retries + 1):
            self._wait()
            try:
                resp = self.session.post(url, data=data, timeout=timeout, **kwargs)
                resp.raise_for_status()
                return resp
            except requests.RequestException as e:
                last = e
                if attempt == retries:
                    raise
                wait = 2 ** attempt
                print(f"[post retry {attempt}/{retries}] {e} — waiting {wait}s")
                time.sleep(wait)
        raise RuntimeError(f"POST failed after {retries} attempts: {last}")

    def download_pdf(self, url: str, dest_dir: Path) -> Path | None:
        """Download a PDF and return its local path, or None if already exists."""
        resp = self.get(url)
        content_type = resp.headers.get("Content-Type", "")
        disposition = resp.headers.get("Content-Disposition", "")
        # PMMP serves PV/attribution PDFs as application/octet-stream with no .pdf
        # in the URL, so trust the %PDF magic bytes as well as the declared type.
        is_pdf = (
            "pdf" in content_type.lower()
            or url.lower().endswith(".pdf")
            or ".pdf" in disposition.lower()
            or resp.content[:4] == b"%PDF"
        )
        if not is_pdf:
            return None

        file_hash = hashlib.sha256(resp.content).hexdigest()
        dest = dest_dir / f"{file_hash}.pdf"
        if dest.exists():
            return dest  # already downloaded

        dest_dir.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(resp.content)
        return dest

    def build_url(self, page: str, extra_flags: list[str] | None = None, **params) -> str:
        from urllib.parse import urlencode
        qs = urlencode({"page": page, **params})
        flags = "&".join(extra_flags) if extra_flags else ""
        sep = "&" if flags else ""
        return f"{BASE_URL}index.php?{qs}{sep}{flags}"
