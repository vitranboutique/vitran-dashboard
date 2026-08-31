"""Quet cac bo du lieu don tra o GitHub Actions va day snapshot len Gist."""
from __future__ import annotations

import json
import os
import random
import sys
import time
import unicodedata
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


def _note_is_concluded(note: str) -> bool:
    """Only final standardized outcomes close a return complaint."""
    prefix = str(note or "").split("|", 1)[0]
    compact = "".join(
        ch for ch in unicodedata.normalize("NFKD", prefix).encode("ascii", "ignore").decode().upper()
        if ch.isalnum()
    )
    if "CHOQUYETTOAN" in compact or "CHUAQUYETTOAN" in compact:
        return False
    return any(token in compact for token in (
        "KHONGCANKN", "KHONGCANKHIEUNAI", "HETHAN", "THANG", "THUA", "HUY",
    ))


def _detail_record(payload) -> dict:
    if not isinstance(payload, dict):
        return {}
    row = payload.get("order_return") or payload.get("return") or payload
    return row if isinstance(row, dict) else {}


def enrich_closed_return_details(in_progress: dict, fetch_json, max_checks: int = 200) -> dict:
    """Confirm unresolved active returns against SAPO's authoritative detail endpoint.

    SAPO's list endpoint can keep a recently closed return as ``returning``. Checking
    only the existing CẦN KN rows misses young returns, because they have not reached
    the seven-day threshold yet. The background job checks unresolved active rows and
    copies newly closed records into ``canceled_detail`` for the app to classify.
    """
    if not isinstance(in_progress, dict):
        return {"checked": 0, "closed": 0, "errors": 0, "capped": False}

    detail_rows = list(in_progress.get("detail") or [])
    candidates = []
    seen_ids = set()
    for row in sorted(detail_rows, key=lambda item: str(item.get("created_on") or ""), reverse=True):
        return_id = str(row.get("sapo_return_id") or "").strip()
        if not return_id or return_id in seen_ids or _note_is_concluded(row.get("note")):
            continue
        seen_ids.add(return_id)
        candidates.append(row)

    capped = len(candidates) > max_checks
    candidates = candidates[:max_checks]
    checked = closed = errors = 0
    closed_by_id = {}
    for row in candidates:
        return_id = str(row.get("sapo_return_id") or "").strip()
        try:
            record = _detail_record(fetch_json(f"/admin/order_returns/{return_id}.json"))
            checked += 1
        except Exception:
            errors += 1
            continue
        if not L.order_return_is_closed(record):
            continue
        closed += 1
        status = str(record.get("status") or "closed").strip() or "closed"
        closed_on = next((str(record.get(key) or "").strip() for key in (
            "closed_on", "closed_at", "cancelled_on", "canceled_on",
            "cancelled_at", "canceled_at",
        ) if str(record.get(key) or "").strip()), "")
        closed_by_id[return_id] = {
            "return_status": status,
            "is_closed": True,
            "is_canceled": status.lower() in ("canceled", "cancelled"),
            "canceled_on": closed_on,
            "_snapshot_closed_verified": True,
        }

    if not closed_by_id:
        return {"checked": checked, "closed": closed, "errors": errors, "capped": capped}

    row_by_id = {}
    for section in ("detail", "all_detail", "canceled_detail"):
        rows = in_progress.get(section) or []
        for row in rows:
            return_id = str(row.get("sapo_return_id") or "").strip()
            if return_id in closed_by_id:
                row.update(closed_by_id[return_id])
                row_by_id.setdefault(return_id, row)

    canceled_rows = in_progress.setdefault("canceled_detail", [])
    existing_ids = {str(row.get("sapo_return_id") or "").strip() for row in canceled_rows}
    for return_id, flags in closed_by_id.items():
        if return_id in existing_ids:
            continue
        source = row_by_id.get(return_id)
        if not source:
            continue
        added = dict(source)
        added.update(flags)
        added["_location"] = "SAPO đã đóng"
        added["reason"] = (
            "SAPO đã đóng phiếu; chưa có ghi chú kết luận chuẩn — cần khiếu nại"
        )
        added["need_kn"] = False
        canceled_rows.append(added)
        existing_ids.add(return_id)
    canceled_rows.sort(key=lambda row: str(row.get("created_on") or ""), reverse=True)
    return {"checked": checked, "closed": closed, "errors": errors, "capped": capped}


def main() -> None:
    fetch_json = make_fetch_json(build_session())
    now_vn = datetime.now(timezone.utc) + timedelta(hours=7)
    daily = L.get_daily_report(fetch_json, target_date=now_vn.date())
    week_summary = L.get_week_summary(fetch_json, days=30)
    picking = L.get_picking(fetch_json)
    in_progress = L.get_returns_in_progress(fetch_json)
    detail_check = enrich_closed_return_details(
        in_progress,
        fetch_json,
        max_checks=max(1, int(os.environ.get("RETURN_DETAIL_CHECK_LIMIT") or 200)),
    )
    in_progress["_detail_check"] = detail_check
    followup = L.get_returns_followup(fetch_json)
    restocked = L.get_restocked_returns_range(fetch_json, days=30)
    payload = {
        "at": now_vn.strftime("%H:%M %d/%m/%Y"),
        "at_epoch": int(time.time()),
        "daily_report_date": now_vn.date().isoformat(),
        "daily_report": daily,
        "week_summary_days": 30,
        "week_summary": week_summary,
        "picking": picking,
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
        f"picking={int((picking or {}).get('total') or 0)} "
        f"diag={(picking or {}).get('diagnostics') or {}} | "
        f"restocked={len(restocked)} | detail={len((in_progress or {}).get('detail') or [])} | "
        f"detail_checked={detail_check['checked']} closed={detail_check['closed']} "
        f"errors={detail_check['errors']}"
    )


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"Snapshot that bai: {exc}", file=sys.stderr)
        raise
