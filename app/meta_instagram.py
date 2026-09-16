"""Official Meta/Instagram Graph API publishing for Reels."""
from __future__ import annotations
import os, time
import requests


def _cfg():
    token=os.getenv("META_ACCESS_TOKEN","")
    account=os.getenv("META_INSTAGRAM_ACCOUNT_ID","")
    version=os.getenv("META_API_VERSION","v23.0")
    return token,account,version


def publish_reel(video_url: str, caption: str) -> dict:
    token,account,version=_cfg()
    if not token or not account:
        raise RuntimeError("Instagram is not configured. Add META_ACCESS_TOKEN and META_INSTAGRAM_ACCOUNT_ID.")
    base=f"https://graph.facebook.com/{version}"
    r=requests.post(f"{base}/{account}/media",data={"media_type":"REELS","video_url":video_url,"caption":caption,"access_token":token},timeout=30)
    r.raise_for_status(); container=r.json()["id"]
    for _ in range(24):
        s=requests.get(f"{base}/{container}",params={"fields":"status_code,status","access_token":token},timeout=20); s.raise_for_status(); data=s.json()
        if data.get("status_code")=="FINISHED": break
        if data.get("status_code")=="ERROR": raise RuntimeError(f"Instagram container failed: {data}")
        time.sleep(5)
    else: raise TimeoutError("Instagram media container did not finish in time")
    p=requests.post(f"{base}/{account}/media_publish",data={"creation_id":container,"access_token":token},timeout=30); p.raise_for_status()
    return p.json()
