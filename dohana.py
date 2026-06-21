"""
dohana.py — Lấy VIDEO ĐÓNG HÀNG từ Dohana (dhn.io.vn) qua Partner API.

API: GET https://backend.dhn.io.vn/dpm/v1/partner/video/search  (header x-api-key)
  params: page, limit, type (package=đóng hàng / outbound / inbound), orderCode, status
Mỗi video: orderCode (= mã vận đơn), type, createdAt, slug, duration, status...
Key đặt trong Streamlit secrets:  [dohana]\n  x_api_key = "..."
"""
from collections import Counter
from datetime import datetime, timedelta, timezone

import requests
import streamlit as st

_BASE = "https://backend.dhn.io.vn/dpm/v1/partner/video/search"


def _key():
    try:
        k = st.secrets["dohana"]["x_api_key"]
        return k or None
    except Exception:
        return None


def configured() -> bool:
    return bool(_key())


def _vnd(iso):
    s = str(iso).replace("Z", "").split(".")[0]
    try:
        return (datetime.fromisoformat(s) + timedelta(hours=7)).date()
    except Exception:
        return None


def _fetch_videos(typ: str, cutoff_date, max_pages: int):
    """Lấy video theo type, lùi (page 0 = MỚI NHẤT) tới khi createdAt < cutoff_date. Khử trùng id."""
    key = _key()
    if not key:
        return None
    headers = {"x-api-key": key}
    vids = []
    for p in range(0, max_pages):        # ⚠️ 0-INDEXED: page=0 = MỚI NHẤT
        try:
            r = requests.get(_BASE, params={"page": p, "limit": 100, "type": typ},
                             headers=headers, timeout=20)
            rows = r.json().get("data", []) if r.status_code == 200 else []
        except Exception:
            break
        if not rows:
            break
        vids += rows
        last = _vnd(rows[-1].get("createdAt"))
        if last and last < cutoff_date:
            break
    return list({v.get("id"): v for v in vids}.values())


def _in_window(v, lo, hi):
    d = _vnd(v.get("createdAt"))
    return d is not None and lo <= d <= hi


def inbound_videos(days_match: int = 3, max_pages: int = 25, target_date=None):
    """Video KHUI HÀNG (type=inbound). target_date=None → hôm nay; truyền ngày cũ để xem lại.
    Trả {total(ngày đó), count(Counter mã cửa sổ), match(set mã), today_codes(mã ngày đó), dup}."""
    today = (datetime.now(timezone.utc) + timedelta(hours=7)).date()
    tdate = target_date or today
    cutoff = tdate - timedelta(days=days_match - 1)
    vids = _fetch_videos("inbound", cutoff, max_pages)
    if vids is None:
        return None
    win = [v for v in vids if _in_window(v, cutoff, tdate)]
    cnt = Counter(v.get("orderCode") for v in win if v.get("orderCode"))
    today_codes = {v.get("orderCode") for v in vids
                   if v.get("orderCode") and _vnd(v.get("createdAt")) == tdate}
    return {
        "total": sum(1 for v in vids if _vnd(v.get("createdAt")) == tdate),
        "count": dict(cnt),
        "match": set(cnt),
        "today_codes": today_codes,
        "dup": {k: v for k, v in cnt.items() if v >= 2},
    }


def today_package_videos(days_match: int = 3, max_pages: int = 25, target_date=None):
    """Video ĐÓNG HÀNG (type=package). target_date=None → hôm nay; truyền ngày cũ để xem lại.
    'match' gồm mã video cửa sổ [tdate-days_match+1 .. tdate] để khớp cả đơn SÓT (quay hôm trước)."""
    today = (datetime.now(timezone.utc) + timedelta(hours=7)).date()
    tdate = target_date or today
    cutoff = tdate - timedelta(days=days_match - 1)
    vids = _fetch_videos("package", cutoff, max_pages)
    if vids is None:
        return None
    day_vids = [v for v in vids if _vnd(v.get("createdAt")) == tdate]
    codes = Counter(v.get("orderCode") for v in day_vids if v.get("orderCode"))
    return {
        "total": len(day_vids),
        "codes": dict(codes),
        "dup": {k: v for k, v in codes.items() if v >= 2},
        "match": {v.get("orderCode") for v in vids
                  if v.get("orderCode") and _in_window(v, cutoff, tdate)},
    }
