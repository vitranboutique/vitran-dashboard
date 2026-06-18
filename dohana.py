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


def today_package_videos(max_pages: int = 10):
    """Video ĐÓNG HÀNG (type=package) tạo HÔM NAY. Trả {total, codes:dict, dup:dict} hoặc None."""
    key = _key()
    if not key:
        return None
    today = (datetime.now(timezone.utc) + timedelta(hours=7)).date()
    headers = {"x-api-key": key}
    vids = []
    for p in range(0, max_pages):        # ⚠️ API phân trang 0-INDEXED: page=0 = MỚI NHẤT
        try:
            r = requests.get(_BASE, params={"page": p, "limit": 100, "type": "package"},
                             headers=headers, timeout=20)
            rows = r.json().get("data", []) if r.status_code == 200 else []
        except Exception:
            break
        if not rows:
            break
        vids += rows
        last = _vnd(rows[-1].get("createdAt"))     # đã sort giảm dần theo createdAt
        if last and last < today:
            break
    # khử trùng id (phòng phân trang chồng lấn)
    vids = list({v.get("id"): v for v in vids}.values())
    today_vids = [v for v in vids if _vnd(v.get("createdAt")) == today]
    codes = Counter(v.get("orderCode") for v in today_vids if v.get("orderCode"))
    return {
        "total": len(today_vids),
        "codes": dict(codes),
        "dup": {k: v for k, v in codes.items() if v >= 2},
    }
