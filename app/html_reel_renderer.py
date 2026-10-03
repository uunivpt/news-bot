from __future__ import annotations
import base64, json, os, socket, subprocess, tempfile, time, urllib.request
from pathlib import Path
import requests, websocket

CAPTURE_WIDTH, CAPTURE_HEIGHT, FPS, DURATION = 540, 960, 30, 18.0
CDP_TIMEOUT = float(os.getenv("PH_CDP_TIMEOUT", "30"))

def _find_browser():
    import shutil
    for c in (os.getenv("CHROMIUM_BIN","").strip(), os.getenv("CHROME_BIN","").strip(),
              "chromium","chromium-browser","google-chrome","google-chrome-stable"):
        if c and (Path(c).exists() if "/" in c else shutil.which(c)):
            return c
    return None

def _free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1",0))
        return s.getsockname()[1]

def _data_uri(url):
    if not url or not str(url).startswith(("http://","https://")):
        return url
    try:
        r=requests.get(str(url),timeout=15,headers={"User-Agent":"PoliticsHub/1.0"})
        r.raise_for_status()
        mime=(r.headers.get("content-type") or "image/jpeg").split(";",1)[0]
        return f"data:{mime};base64,"+base64.b64encode(r.content).decode() if mime.startswith("image/") else None
    except Exception:
        return None

def _cdp(ws,counter,method,params=None,timeout=None):
    counter[0]+=1
    ident=counter[0]
    old_timeout=ws.gettimeout()
    ws.settimeout(timeout or CDP_TIMEOUT)
    try:
        ws.send(json.dumps({"id":ident,"method":method,"params":params or {}}))
        while True:
            msg=json.loads(ws.recv())
            if msg.get("id")==ident:
                if "error" in msg:
                    raise RuntimeError(f"CDP {method} failed: {msg['error']}")
                return msg.get("result",{})
    finally:
        ws.settimeout(old_timeout)

def _read_stream(ws,counter,handle):
    chunks=[]
    while True:
        result=_cdp(ws,counter,"IO.read",{"handle":handle,"size":1024*1024},timeout=60)
        data=result.get("data","")
        if data:
            chunks.append(base64.b64decode(data) if result.get("base64Encoded") else data.encode())
        if result.get("eof"):
            break
    try:
        _cdp(ws,counter,"IO.close",{"handle":handle},timeout=10)
    except Exception:
        pass
    return b"".join(chunks)

def render_html_reel(news, output_path, audio_path=None, template_path=None):
    template=Path(template_path or os.getenv("POLITICSHUB_REEL_TEMPLATE","app/templates/politicshub_reel_18s.html"))
    if not template.exists():
        raise FileNotFoundError(f"PoliticsHub HTML template not found: {template}")
    browser=_find_browser()
    if not browser:
        raise RuntimeError("Chromium/Chrome is required for the PoliticsHub HTML Reel renderer")

    item=dict(news)
    item["headline"]=str(item.get("headline") or item.get("title") or "Latest news update")
    item["category"]=str(item.get("category") or "News")
    item["date"]=str(item.get("date") or "")
    item["location"]=str(item.get("location") or "")
    item["source"]=str(item.get("source") or item.get("source_name") or "")
    item["summary"]=str(item.get("summary") or "")
    item["cta"]=str(item.get("cta") or "Follow for daily politics & world updates")
    item["img"]=_data_uri(item.get("img") or item.get("image_url"))
    item.pop("image_url",None)

    out=Path(output_path)
    out.parent.mkdir(parents=True,exist_ok=True)
    work=Path(tempfile.mkdtemp(prefix="ph_html_reel_"))
    recording=work/"recording.webm"
    silent=work/"video.mp4"
    profile=work/"chrome-profile"
    port=_free_port()
    proc=ws=None

    try:
        proc=subprocess.Popen([
            browser,"--headless=new","--disable-gpu","--no-sandbox","--disable-dev-shm-usage",
            "--hide-scrollbars","--mute-audio","--remote-allow-origins=*",
            "--run-all-compositor-stages-before-draw",
            f"--remote-debugging-port={port}",f"--user-data-dir={profile}","about:blank"
        ],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)

        deadline=time.time()+15
        ws_url=None
        while time.time()<deadline:
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/json",timeout=1) as r:
                    tabs=json.loads(r.read())
                if tabs:
                    ws_url=tabs[0]["webSocketDebuggerUrl"]
                    break
            except Exception:
                time.sleep(.1)
        if not ws_url:
            raise RuntimeError("Could not connect to Chromium DevTools")

        ws=websocket.create_connection(ws_url,timeout=CDP_TIMEOUT)
        counter=[0]
        _cdp(ws,counter,"Page.enable")
        _cdp(ws,counter,"Runtime.enable")
        _cdp(ws,counter,"Emulation.setDeviceMetricsOverride",{
            "width":CAPTURE_WIDTH,"height":CAPTURE_HEIGHT,"deviceScaleFactor":1,
            "mobile":False,"screenWidth":CAPTURE_WIDTH,"screenHeight":CAPTURE_HEIGHT
        })

        payload=json.dumps(item,ensure_ascii=False)
        _cdp(ws,counter,"Page.addScriptToEvaluateOnNewDocument",{"source":f"window.__PH_NEWS={payload};"})
        nav=_cdp(ws,counter,"Page.navigate",{"url":template.resolve().as_uri()})
        if nav.get("errorText"):
            raise RuntimeError(f"Template navigation failed: {nav['errorText']}")
        time.sleep(1)

        _cdp(ws,counter,"Runtime.evaluate",{"expression":
            "document.body.style.background='#050506';"
            "document.body.style.margin='0';"
            "document.body.style.display='block';"
            "document.getElementById('ui').style.display='none';"
            "document.getElementById('w').style.width='540px';"
            "document.getElementById('w').style.height='960px';"
            "document.getElementById('w').style.boxShadow='none';"
            "document.getElementById('st').style.transform='scale(0.5');"
            "window.PH.load(window.__PH_NEWS);"
            "window.T=0;window.pl=true;window.last=performance.now();"
            "window.PH.render(0);true"
        })
        _cdp(ws,counter,"Runtime.evaluate",{
            "expression":"document.fonts&&document.fonts.ready?document.fonts.ready.then(()=>true):true",
            "awaitPromise":True
        })
        # Fonts can resolve after the first build; rebuild once before recording.
        _cdp(ws,counter,"Runtime.evaluate",{"expression":
            "window.PH.load(window.__PH_NEWS);window.T=0;window.last=performance.now();window.PH.render(0);true"
        })

        try:
            start=_cdp(ws,counter,"Page.startScreenRecording",{
                "format":"webm","frameRate":FPS,"maxWidth":CAPTURE_WIDTH,"maxHeight":CAPTURE_HEIGHT
            },timeout=15)
        except Exception as exc:
            raise RuntimeError(f"Chromium screen recording is unavailable: {exc}") from exc

        # The page's own requestAnimationFrame loop drives the motion graphics in real time.
        # Record slightly beyond 18s, then trim to an exact 18.000s with FFmpeg.
        time.sleep(DURATION+0.35)
        stop=_cdp(ws,counter,"Page.stopScreenRecording",{},timeout=30)
        handle=stop.get("stream") or start.get("stream")
        if not handle:
            raise RuntimeError(f"Chromium screen recording returned no stream: {stop}")
        recording.write_bytes(_read_stream(ws,counter,handle))
        if recording.stat().st_size<1024:
            raise RuntimeError("Chromium screen recording returned an empty stream")

        subprocess.run([
            "ffmpeg","-y","-i",str(recording),
            "-t",str(DURATION),"-vf","scale=1080:1920:flags=lanczos",
            "-r",str(FPS),"-c:v","libx264","-preset","veryfast","-crf","18",
            "-pix_fmt","yuv420p","-an","-movflags","+faststart",str(silent)
        ],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)

        if audio_path:
            subprocess.run([
                "ffmpeg","-y","-i",str(silent),"-stream_loop","-1","-i",str(audio_path),
                "-map","0:v:0","-map","1:a:0","-t",str(DURATION),
                "-c:v","copy","-c:a","aac","-b:a","128k","-ar","48000","-ac","2",
                "-movflags","+faststart",str(out)
            ],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        else:
            silent.replace(out)
        return str(out)
    finally:
        if ws:
            try: ws.close()
            except Exception: pass
        if proc:
            proc.terminate()
            try: proc.wait(timeout=3)
            except Exception: proc.kill()
