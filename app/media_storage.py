from __future__ import annotations
import os
from pathlib import Path
from urllib.parse import quote
from urllib.request import Request, urlopen


def public_video_url(local_path: str) -> str | None:
    """Return a public URL for a generated media file.

    The worker cannot expose its filesystem to Instagram. Set PUBLIC_MEDIA_BASE_URL
    when a separate public media host is used, or MEDIA_URL_<filename> for testing.
    """
    base=os.getenv("PUBLIC_MEDIA_BASE_URL","").rstrip("/")
    if not base: return None
    return f"{base}/{quote(Path(local_path).name)}"


def download_to(path: str, url: str) -> str:
    Path(path).parent.mkdir(parents=True,exist_ok=True)
    req=Request(url,headers={"User-Agent":"NewsDeskBot/1.0"})
    with urlopen(req,timeout=20) as r: Path(path).write_bytes(r.read())
    return path
