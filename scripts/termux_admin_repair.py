"""Repair missing admin modules/static files after a partial Git sparse download.

Uses only the Python standard library. No Git clone, database access, secrets,
and never overwrites an existing file.
"""
from __future__ import annotations
import ast
from collections import deque
from pathlib import Path
import os
import tempfile
import time
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
RAW = "https://raw.githubusercontent.com/uunivpt/news-bot/main/"
STATIC = (
    "public/admin/index.html",
    "public/admin.js",
    "public/assets/admin-room.css",
    "public/assets/admin-telemetry.js",
    "public/favicon.svg",
)
MANDATORY = ("app/__init__.py", "api/index.py", "scripts/mobile_editorial_approve.py")

def restore(path: str) -> Path:
    dest = ROOT / path
    if dest.is_file() and dest.stat().st_size:
        return dest
    if dest.exists():
        raise RuntimeError(f"Refusing to overwrite: {path}")
    dest.parent.mkdir(parents=True, exist_ok=True)
    for attempt in range(3):
        try:
            with urlopen(Request(RAW + path, headers={"User-Agent":"PoliticsHub-Termux-Admin-Repair/1"}), timeout=20) as response:
                data = response.read(6 * 1024 * 1024)
            if not data:
                raise RuntimeError(f"Empty download: {path}")
            fd, temp = tempfile.mkstemp(prefix=".admin-repair-", dir=dest.parent)
            try:
                with os.fdopen(fd, "wb") as out:
                    out.write(data)
                os.replace(temp, dest)
            finally:
                if os.path.exists(temp):
                    os.unlink(temp)
            print("RESTORED:", path, flush=True)
            return dest
        except Exception as exc:
            if attempt >= 2:
                raise RuntimeError(f"Unable to download {path}: {type(exc).__name__}") from exc
            time.sleep(1)
    return dest

def module_file(module: str):
    if module == "app":
        return "app/__init__.py"
    if module.startswith(("app.", "api.")):
        return module.replace(".", "/") + ".py"
    return None

def dependencies(module: str, source: str):
    package = module.rpartition(".")[0]
    for node in ast.walk(ast.parse(source, filename=module)):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if module_file(alias.name):
                    yield alias.name
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                parts = module.split(".")[:-node.level]
                target = ".".join(parts + ([node.module] if node.module else []))
            else:
                target = node.module or ""
            if module_file(target):
                yield target
            if target in {"app", "api"}:
                for alias in node.names:
                    if alias.name != "*":
                        yield target + "." + alias.name

def repair():
    for file in MANDATORY + STATIC:
        restore(file)
    queue = deque(["api.index"])
    seen = set()
    while queue:
        module = queue.popleft()
        if module in seen:
            continue
        seen.add(module)
        target = module_file(module)
        if not target:
            continue
        path = restore(target)
        for dep in dependencies(module, path.read_text(encoding="utf-8")):
            if dep not in seen:
                queue.append(dep)
    print("ADMIN SOURCE REPAIR COMPLETE; PostgreSQL unchanged", flush=True)

if __name__ == "__main__":
    repair()
