from __future__ import annotations
import os
from pathlib import Path
import requests

def upload_video(path:str)->str|None:
    cloud=os.getenv("CLOUDINARY_CLOUD_NAME",""); preset=os.getenv("CLOUDINARY_UPLOAD_PRESET","")
    if not cloud or not preset:return None
    url=f"https://api.cloudinary.com/v1_1/{cloud}/video/upload"
    with open(path,"rb") as f:
        r=requests.post(url,data={"upload_preset":preset},files={"file":(Path(path).name,f,"video/mp4")},timeout=120)
    r.raise_for_status(); return r.json().get("secure_url")
