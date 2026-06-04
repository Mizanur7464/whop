"""Download buyer PDFs from Google Drive URLs in .env into data/docs/."""

from __future__ import annotations

import re
import sys
from pathlib import Path

import httpx
from dotenv import load_dotenv
import os

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")

DRIVE_ID_RE = re.compile(r"/d/([a-zA-Z0-9_-]+)")

MAPPING = {
    "DOC_URL_TERMS": "terms_and_conditions.pdf",
    "DOC_URL_ONBOARDING_VANTAGE": "vantage_onboarding.pdf",
    "DOC_URL_ONBOARDING_PREMIER": "premier_onboarding.pdf",
    "DOC_URL_COPYTRADING_VANTAGE": "vantage_copytrading.pdf",
    "DOC_URL_COPYTRADING_PREMIER": "premier_copytrading.pdf",
}


def drive_file_id(url: str) -> str | None:
    m = DRIVE_ID_RE.search(url.strip())
    return m.group(1) if m else None


def download(file_id: str, dest: Path) -> None:
    url = f"https://drive.google.com/uc?export=download&id={file_id}"
    with httpx.Client(follow_redirects=True, timeout=120.0) as client:
        r = client.get(url)
        r.raise_for_status()
        dest.write_bytes(r.content)
    size = dest.stat().st_size
    if size < 10_000:
        raise RuntimeError(f"Download too small ({size} bytes) — check sharing on Drive")


def main() -> int:
    out_dir = ROOT / "data" / "docs"
    out_dir.mkdir(parents=True, exist_ok=True)
    ok = 0
    for env_key, filename in MAPPING.items():
        url = os.getenv(env_key, "").strip()
        if not url:
            print(f"SKIP {env_key}: not set in .env")
            continue
        file_id = drive_file_id(url)
        if not file_id:
            print(f"FAIL {env_key}: could not parse Google Drive file id")
            continue
        dest = out_dir / filename
        try:
            download(file_id, dest)
            print(f"OK   {filename} ({dest.stat().st_size:,} bytes)")
            ok += 1
        except Exception as e:
            print(f"FAIL {filename}: {e}")
    print(f"\nSynced {ok}/{len(MAPPING)} files to {out_dir}")
    return 0 if ok == len(MAPPING) else 1


if __name__ == "__main__":
    sys.exit(main())
