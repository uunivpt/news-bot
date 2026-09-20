from __future__ import annotations
import os
from pathlib import Path
import requests
from time import sleep

def _deterministic_url(cloud: str, public_id: str, suffix: str = ".mp4") -> str:
    return f"https://res.cloudinary.com/{cloud}/video/upload/{public_id}{suffix}"

def upload_video(path:str, public_id:str|None=None)->str|None:
    cloud=os.getenv("CLOUDINARY_CLOUD_NAME",""); preset=os.getenv("CLOUDINARY_UPLOAD_PRESET","")
    if not cloud or not preset:\n        raise RuntimeError(f"Cloudinary configuration missing: cloud_name={bool(cloud)} upload_preset={bool(preset)}")
    url=f"https://api.cloudinary.com/v1_1/{cloud}/video/upload"
    # A stable public_id makes retries idempotent. If the first upload succeeded
    # but the response was lost, reuse the existing public delivery URL instead
    # of creating another Cloudinary asset.
    deterministic_url = _deterministic_url(cloud, public_id) if public_id else None
    if deterministic_url:
        try:
            probe=requests.head(deterministic_url, timeout=15, allow_redirects=True)
            if probe.ok:
                print(f"Reusing existing Cloudinary Reel: {deterministic_url}")
                return deterministic_url
        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout):
            pass
    last_error = None
    for attempt, delay in enumerate((0, 5, 15, 30), start=1):
        if delay:
            sleep(delay)
        try:
            data={"upload_preset":preset}
            if public_id:
                data["public_id"]=public_id
            with open(path,"rb") as f:
                r=requests.post(
                    url,
                    data=data,
                    files={"file":(Path(path).name,f,"video/mp4")},
                    timeout=120,
                )
            if r.ok:
                return r.json().get("secure_url") or deterministic_url
            # Unsigned uploads cannot overwrite an existing public_id. If the
            # asset already exists, the deterministic delivery URL is exactly
            # what we need and no second asset should be created.
            try:
                payload=r.json()
            except ValueError:
                payload={}
            message=str((payload.get("error") or {}).get("message") or r.text or "")
            if deterministic_url and r.status_code in (400,409) and any(
                token in message.lower() for token in ("already exists","already exists with","duplicate","public id")
            ):
                print(f"Reusing existing Cloudinary Reel after duplicate response: {deterministic_url}")
                return deterministic_url
            r.raise_for_status()
        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as exc:
            last_error = exc
            print(f"Cloudinary upload connection attempt {attempt}/4 failed; retrying: {exc}")
            continue
    if last_error:
        raise last_error
    return None
