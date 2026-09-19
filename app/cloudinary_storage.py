from __future__ import annotations
import os
from pathlib import Path
import requests
from time import sleep

def upload_video(path:str)->str|None:
    cloud=os.getenv("CLOUDINARY_CLOUD_NAME",""); preset=os.getenv("CLOUDINARY_UPLOAD_PRESET","")
    if not cloud or not preset:return None
    url=f"https://api.cloudinary.com/v1_1/{cloud}/video/upload"
    # Mobile Wi-Fi/DNS can briefly drop while the worker is running.
    # Retry transient connection/DNS failures without rebuilding the Reel.
    last_error = None
    for attempt, delay in enumerate((0, 5, 15, 30), start=1):
        if delay:
            sleep(delay)
        try:
            with open(path,"rb") as f:
                r=requests.post(
                    url,
                    data={"upload_preset":preset},
                    files={"file":(Path(path).name,f,"video/mp4")},
                    timeout=120,
                )
            r.raise_for_status()
            return r.json().get("secure_url")
        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as exc:
            last_error = exc
            print(f"Cloudinary upload connection attempt {attempt}/4 failed; retrying: {exc}")
            continue
    if last_error:
        raise last_error
    return None
