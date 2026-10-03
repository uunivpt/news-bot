from __future__ import annotations

import base64
import json
import os
import shutil
import socket
import subprocess
import tempfile
import time
import urllib.request
from pathlib import Path

import requests
import websocket

FPS = 60
DURATION = 18.0
WIDTH = 1080
HEIGHT = 1920
CDP_TIMEOUT = float(os.getenv("PH_CDP_TIMEOUT", "30"))


def _find_browser():
    for name in (
        os.getenv("CHROMIUM_BIN", "").strip(),
        os.getenv("CHROME_BIN", "").strip(),
        "chromium",
        "chromium-browser",
        "google-chrome",
        "google-chrome-stable",
    ):
        if name and (Path(name).exists() if "/" in name else shutil.which(name)):
            return name
    return None


def _free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _data_uri(url):
    if not url:
        return None
    value = str(url)
    if not value.startswith(("http://", "https://")):
        local = Path(value)
        if local.exists() and local.is_file():
            try:
                import mimetypes
                mime = mimetypes.guess_type(str(local))[0] or "image/jpeg"
                return "data:" + mime + ";base64," + base64.b64encode(local.read_bytes()).decode()
            except Exception:
                return None
        return value
    try:
        response = requests.get(
            str(url),
            timeout=15,
            headers={"User-Agent": "PoliticsHub/1.0"},
        )
        response.raise_for_status()
        mime = (response.headers.get("content-type") or "image/jpeg").split(";", 1)[0]
        if not mime.startswith("image/"):
            return None
        return "data:" + mime + ";base64," + base64.b64encode(response.content).decode()
    except Exception:
        return None


def _cdp(ws, counter, method, params=None, timeout=None):
    counter[0] += 1
    ident = counter[0]
    old_timeout = ws.gettimeout()
    ws.settimeout(timeout or CDP_TIMEOUT)
    try:
        ws.send(json.dumps({"id": ident, "method": method, "params": params or {}}))
        while True:
            message = json.loads(ws.recv())
            if message.get("id") != ident:
                continue
            if "error" in message:
                raise RuntimeError(f"CDP {method} failed: {message['error']}")
            return message.get("result", {})
    finally:
        ws.settimeout(old_timeout)


def render_html_reel(news, output_path, audio_path=None, template_path=None):
    template = Path(
        template_path
        or os.getenv(
            "POLITICSHUB_REEL_TEMPLATE",
            "app/templates/politicshub_reel_18s.html",
        )
    )
    if not template.exists():
        raise FileNotFoundError(f"PoliticsHub HTML template not found: {template}")

    browser = _find_browser()
    if not browser:
        raise RuntimeError("Chromium/Chrome is required for the HTML Reel renderer")

    item = dict(news)
    item["headline"] = str(item.get("headline") or item.get("title") or "Latest news update")
    item["category"] = str(item.get("category") or "News")
    item["date"] = str(item.get("date") or "")
    item["location"] = str(item.get("location") or "")
    item["source"] = str(item.get("source") or item.get("source_name") or "")
    item["summary"] = str(item.get("summary") or "")
    item["cta"] = str(item.get("cta") or "Follow for daily politics & world updates")
    item["img"] = _data_uri(item.get("img") or item.get("image_url"))
    item.pop("image_url", None)

    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)

    work = Path(tempfile.mkdtemp(prefix="politicshub_reel_"))
    frames = work / "frames"
    frames.mkdir()
    silent = work / "silent.mp4"
    profile = work / "chrome-profile"
    port = _free_port()

    process = None
    ws = None

    try:
        process = subprocess.Popen(
            [
                browser,
                "--headless=new",
                "--disable-gpu",
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--hide-scrollbars",
                "--mute-audio",
                "--remote-allow-origins=*",
                "--run-all-compositor-stages-before-draw",
                "--disable-background-timer-throttling",
                "--disable-renderer-backgrounding",
                "--disable-backgrounding-occluded-windows",
                f"--window-size={WIDTH},{HEIGHT}",
                f"--remote-debugging-port={port}",
                f"--user-data-dir={profile}",
                "about:blank",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

        deadline = time.time() + 20
        debugger_url = None
        while time.time() < deadline:
            try:
                debugger_url = requests.get(
                    f"http://127.0.0.1:{port}/json",
                    timeout=2,
                ).json()
                if debugger_url:
                    break
            except Exception:
                time.sleep(0.1)

        if not debugger_url:
            raise RuntimeError("Chromium DevTools endpoint did not start")

        page = next(
            (entry for entry in debugger_url if entry.get("type") == "page"),
            None,
        )
        if not page or not page.get("webSocketDebuggerUrl"):
            raise RuntimeError("Chromium page target was not available")

        ws = websocket.create_connection(
            page["webSocketDebuggerUrl"],
            timeout=CDP_TIMEOUT,
            origin="http://localhost",
        )
        counter = [0]

        _cdp(ws, counter, "Page.enable")
        _cdp(ws, counter, "Runtime.enable")
        _cdp(
            ws,
            counter,
            "Emulation.setDeviceMetricsOverride",
            {
                "width": WIDTH,
                "height": HEIGHT,
                "deviceScaleFactor": 1,
                "mobile": True,
            },
        )

        file_url = template.resolve().as_uri()
        try:
            _cdp(
                ws,
                counter,
                "Page.navigate",
                {"url": file_url},
                timeout=10,
            )
        except RuntimeError as exc:
            if "ERR_ABORTED" not in str(exc):
                raise

        ready_deadline = time.time() + 15
        while time.time() < ready_deadline:
            result = _cdp(
                ws,
                counter,
                "Runtime.evaluate",
                {
                    "expression": "Boolean(document.getElementById('st') && window.PH)",
                    "returnByValue": True,
                },
                timeout=5,
            )
            if result.get("result", {}).get("value"):
                break
            time.sleep(0.1)
        else:
            raise RuntimeError("PoliticsHub HTML template did not initialize")

        payload = json.dumps(item, ensure_ascii=False)
        _cdp(
            ws,
            counter,
            "Runtime.evaluate",
            {
                "expression": f"window.__PH_NEWS={json.dumps(payload)}; "
                "window.PH.load(JSON.parse(window.__PH_NEWS));"
            },
        )

        # The HTML template also contains a browser-only preview toolbar (#ui).
        # Never capture that editor UI in a production Reel. The stage itself is
        # 1080x1920 and the renderer now captures at native resolution, so the stage
        # fills the complete viewport with no scaling or surrounding page layout.
        _cdp(
            ws,
            counter,
            "Runtime.evaluate",
            {
                "expression": """
                    (() => {
                        const body = document.body;
                        const html = document.documentElement;
                        const wrap = document.getElementById('w');
                        const stage = document.getElementById('st');
                        const ui = document.getElementById('ui');
                        if (!body || !html || !wrap || !stage) throw new Error('Reel stage not found');
                        if (ui) ui.style.display = 'none';
                        html.style.width = '1080px';
                        html.style.height = '1920px';
                        html.style.overflow = 'hidden';
                        body.style.width = '1080px';
                        body.style.height = '1920px';
                        body.style.margin = '0';
                        body.style.padding = '0';
                        body.style.display = 'block';
                        body.style.overflow = 'hidden';
                        body.style.background = '#050506';
                        wrap.style.width = '1080px';
                        wrap.style.height = '1920px';
                        wrap.style.margin = '0';
                        wrap.style.boxShadow = 'none';
                        wrap.style.overflow = 'hidden';
                        stage.style.transformOrigin = '0 0';
                        stage.style.transform = 'scale(1)';
                        stage.style.left = '0';
                        stage.style.top = '0';
                        return true;
                    })()
                """,
                "returnByValue": True,
            },
        )
        _cdp(
            ws,
            counter,
            "Runtime.evaluate",
            {
                "expression": """
                    (document.fonts && document.fonts.ready)
                      ? document.fonts.ready.then(() => true)
                      : Promise.resolve(true)
                """,
                "awaitPromise": True,
            },
            timeout=15,
        )
        _cdp(
            ws,
            counter,
            "Runtime.evaluate",
            {"expression": "window.PH.load(JSON.parse(window.__PH_NEWS)); window.PH.stop(); window.PH.render(0);"},
        )

        total_frames = int(round(DURATION * FPS))
        print(f"Capturing {total_frames} frames from the current HTML template...")

        for index in range(total_frames):
            timestamp = index / FPS
            expression = (
                "(function(){"
                "window.PH.render(" + f"{timestamp:.6f}" + ");"
                "return true;"
                "})()"
            )
            _cdp(
                ws,
                counter,
                "Runtime.evaluate",
                {"expression": expression},
                timeout=10,
            )
            shot = _cdp(
                ws,
                counter,
                "Page.captureScreenshot",
                {
                    "format": "jpeg",
                    "quality": 95,
                    "captureBeyondViewport": False,
                    "fromSurface": True,
                },
                timeout=10,
            )
            data = shot.get("data")
            if not data:
                raise RuntimeError(f"Chromium returned no screenshot at frame {index}")
            (frames / f"f{index:05d}.jpg").write_bytes(base64.b64decode(data))

            if index and index % 90 == 0:
                print(f"Captured {index}/{total_frames} frames")

        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-framerate",
                str(FPS),
                "-i",
                str(frames / "f%05d.jpg"),
                "-t",
                f"{DURATION:.6f}",
                "-vf",
                f"fps={FPS}",
                "-c:v",
                "libx264",
                "-preset",
                "medium",
                "-crf",
                "16",
                "-pix_fmt",
                "yuv420p",
                "-an",
                str(silent),
            ],
            check=True,
        )

        if audio_path and Path(audio_path).exists():
            subprocess.run(
                [
                    "ffmpeg",
                    "-y",
                    "-i",
                    str(silent),
                    "-i",
                    str(audio_path),
                    "-map",
                    "0:v:0",
                    "-map",
                    "1:a:0",
                    "-c:v",
                    "copy",
                    "-c:a",
                    "aac",
                    "-b:a",
                    "128k",
                    "-shortest",
                    "-t",
                    f"{DURATION:.6f}",
                    "-movflags",
                    "+faststart",
                    str(output),
                ],
                check=True,
            )
        else:
            subprocess.run(
                [
                    "ffmpeg",
                    "-y",
                    "-i",
                    str(silent),
                    "-t",
                    f"{DURATION:.6f}",
                    "-movflags",
                    "+faststart",
                    "-c",
                    "copy",
                    str(output),
                ],
                check=True,
            )

        probe = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration:stream=width,height,pix_fmt",
                "-of",
                "json",
                str(output),
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        info = json.loads(probe.stdout)
        duration = float(info["format"]["duration"])
        video = next(
            stream for stream in info["streams"] if stream.get("width")
        )
        if abs(duration - DURATION) > 0.15:
            raise RuntimeError(f"HTML Reel duration is {duration:.3f}s, expected 18.000s")
        if video.get("width") != 1080 or video.get("height") != 1920:
            raise RuntimeError(
                f"HTML Reel resolution is {video.get('width')}x{video.get('height')}, expected 1080x1920"
            )
        if video.get("pix_fmt") not in {"yuv420p", "yuvj420p"}:
            raise RuntimeError(f"HTML Reel pixel format is {video.get('pix_fmt')}")

        print(f"HTML Reel PASS: {duration:.3f}s, 1080x1920, {video.get('pix_fmt')}")
        return str(output)

    finally:
        if ws is not None:
            try:
                ws.close()
            except Exception:
                pass
        if process is not None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
        shutil.rmtree(work, ignore_errors=True)
