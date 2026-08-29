"""Quet cac bo du lieu don tra o GitHub Actions va day snapshot len Gist."""
from __future__ import annotations

import json
import os
import random
import sys
import time
from datetime import datetime, timedelta, timezone

import requests

import sapo_logic as L


BASE = "https://vitranboutiquehcm.mysapo.net"


def build_session() -> requests.Session:
    session = requests.Session()
    session.headers.update({"User-Agent": "Mozilla/5.0", "Accept": "application/json"})
    token = os.environ.get("SAPO_ACCESS_TOKEN") or os.environ.get("SAPO_TOKEN")
    cookie = os.environ.get("SAPO_COOKIE")
    key = os.environ.get("SAPO_API_KEY")
    secret = os.environ.get("SAPO_API_SECRET")
    if token:
        session.headers["X-Sapo-Access-Token"] = token
    elif cookie:
        session.headers["Cookie"] = cookie
    elif key and secret:
        session.auth = (key, secret)
    else:
        raise RuntimeError("Thieu credential Sapo cho workflow snapshot.")
    return session


def _is_cloudflare_block(response: requests.Response) -> bool:
    if response.status_code not in (403, 429, 503):
        return False
    head = (response.text or "")[:1600].lower()
    if "access_denied" in head or "access is denied" in head:
        return False
    return (
        "attention required" in head
        or "checking your browser" in head
        or "cf-error" in head
        or ("cloudflare" in head and "cdn-cgi" in head)
    )


def make_fetch_json(session: requests.Session):
    """Gioi han khoang 1.4 request/giay va retry 429 co Retry-After."""
    last_call = 0.0

    def fetch_json(path: str, **params):
        nonlocal last_call
        for attempt in range(5):
            elapsed = time.monotonic() - last_call
            gap = 0.68 + random.uniform(0, 0.10)
            if elapsed < gap:
                time.sleep(gap - elapsed)
            response = session.get(f"{BASE}{path}", params=params, timeout=40)
            last_call = time.monotonic()
            if _is_cloudflare_block(response):
                raise RuntimeError(
                    f"Cloudflare chan runner tai {path} (HTTP {response.status_code}); "
                    "giu snapshot cu va thu lai o lich sau."
                )
            if response.status_code != 429:
                response.raise_for_status()
                return response.json()
            if attempt == 4:
                response.raise_for_status()
            try:
                retry_after = float(response.headers.get("Retry-After") or 0)
            except Exception:
                retry_after = 0
            time.sleep(min(20.0, max(retry_after, 2.0 * (2**attempt))))
        raise RuntimeError(f"Khong lay duoc du lieu Sapo tai {path}.")

    return fetch_json


def push_to_gist(token: str, filename: str, data: dict) -> None:
    api = "https://api.github.com"
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    gist_id = ""
    for page in range(1, 6):
        response = requests.get(
            f"{api}/gists", headers=headers, params={"per_page": 100, "page": page}, timeout=30
        )
        response.raise_for_status()
        rows = response.json()
        if not rows:
            break
        for gist in rows:
            if "vitran_picklog.json" in (gist.get("files") or {}):
                gist_id = str(gist.get("id") or "")
                break
        if gist_id:
            break
    if not gist_id:
        raise RuntimeError("Khong tim thay Gist chua vitran_picklog.json.")
    response = requests.patch(
        f"{api}/gists/{gist_id}",
        headers=headers,
        data=json.dumps(
            {"files": {filename: {"content": json.dumps(data, ensure_ascii=False, default=str)}}}
        ),
        timeout=60,
    )
    response.raise_for_status()


def main() -> None:
    fetch_json = make_fetch_json(build_session())
    now_vn = datetime.now(timezone.utc) + timedelta(hours=7)
    daily = L.get_daily_report(fetch_json, target_date=now_vn.date())
    week_summary = L.get_week_summary(fetch_json, days=30)
    in_progress = L.get_returns_in_progress(fetch_json)
    followup = L.get_returns_followup(fetch_json)
    restocked = L.get_restocked_returns_range(fetch_json, days=30)
    payload = {
        "at": now_vn.strftime("%H:%M %d/%m/%Y"),
        "at_epoch": int(time.time()),
        "daily_report_date": now_vn.date().isoformat(),
        "daily_report": daily,
        "week_summary_days": 30,
        "week_summary": week_summary,
        "in_progress": in_progress,
        "followup": followup,
        "restocked": restocked,
        "restocked_days": 30,
    }
    gist_token = os.environ.get("GITHUB_TOKEN")
    if not gist_token:
        raise RuntimeError("Thieu GIST_TOKEN cho workflow snapshot.")
    push_to_gist(gist_token, "vitran_returns.json", payload)
    print(
        f"Snapshot {payload['at']} | daily={payload['daily_report_date']} | "
        f"week_days={len((week_summary or {}).get('days') or [])} | followup={len(followup)} | "
        f"restocked={len(restocked)} | detail={len((in_progress or {}).get('detail') or [])}"
    )


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"Snapshot that bai: {exc}", file=sys.stderr)
        raise
