from __future__ import annotations
import os
import requests


def dispatch_worker() -> dict:
    # Admin actions must dispatch the dedicated Instagram worker, never the news-only workflow.
    token = (os.getenv("WORKFLOW_TOKEN", "").strip() or os.getenv("GITHUB_WORKFLOW_TOKEN", "").strip())
    if not token:
        return {"ok": False, "configured": False, "queued": True, "error": "No GitHub workflow token is configured in Vercel; the action remains queued for the scheduled Instagram worker."}

    owner = os.getenv("GITHUB_REPO_OWNER", "uunivpt").strip()
    repo = os.getenv("GITHUB_REPO_NAME", "news-bot").strip()
    workflow = os.getenv("GITHUB_WORKFLOW_FILE", "instagram-publisher.yml").strip()
    ref = os.getenv("GITHUB_WORKFLOW_REF", "main").strip()
    url = f"https://api.github.com/repos/{owner}/{repo}/actions/workflows/{workflow}/dispatches"
    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "X-GitHub-Api-Version": "2022-11-28",
        "Content-Type": "application/json",
    }
    try:
        response = requests.post(url, headers=headers, json={"ref": ref}, timeout=8)
        if response.status_code in (200, 201, 204):
            return {"ok": True, "configured": True, "queued": False, "status_code": response.status_code}
        try:
            body = response.json()
            detail = body.get("message") or "GitHub rejected workflow dispatch"
        except Exception:
            detail = f"GitHub returned HTTP {response.status_code}"
        return {"ok": False, "configured": True, "queued": True, "status_code": response.status_code, "error": detail}
    except requests.RequestException as exc:
        return {"ok": False, "configured": True, "queued": True, "error": f"GitHub dispatch request failed: {exc}"}
