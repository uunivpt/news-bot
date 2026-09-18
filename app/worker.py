from __future__ import annotations
import os
import requests


def dispatch_worker() -> dict:
    token = os.getenv("GITHUB_WORKFLOW_TOKEN", "").strip()
    if not token:
        return {"ok": False, "configured": False, "error": "GITHUB_WORKFLOW_TOKEN is not configured"}

    owner = os.getenv("GITHUB_REPO_OWNER", "uunivpt").strip()
    repo = os.getenv("GITHUB_REPO_NAME", "news-bot").strip()
    workflow = os.getenv("GITHUB_WORKFLOW_FILE", "instagram.yml").strip()
    ref = os.getenv("GITHUB_WORKFLOW_REF", "main").strip()
    url = f"https://api.github.com/repos/{owner}/{repo}/actions/workflows/{workflow}/dispatches"
    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "X-GitHub-Api-Version": "2026-03-10",
        "Content-Type": "application/json",
    }
    try:
        response = requests.post(url, headers=headers, json={"ref": ref}, timeout=8)
        if response.status_code in (200, 201, 204):
            return {"ok": True, "configured": True, "status_code": response.status_code}
        try:
            body = response.json()
            detail = body.get("message") or "GitHub rejected workflow dispatch"
        except Exception:
            detail = f"GitHub returned HTTP {response.status_code}"
        return {"ok": False, "configured": True, "status_code": response.status_code, "error": detail}
    except requests.RequestException as exc:
        return {"ok": False, "configured": True, "error": f"GitHub dispatch request failed: {exc}"}
