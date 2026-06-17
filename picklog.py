"""
picklog.py — Ghi & đọc LỊCH SỬ IN PHIẾU NHẶT (qua dashboard) vào 1 kho JSON (jsonblob.com).

Kho lưu trữ ẩn danh (không cần Google/đăng nhập). URL kho đặt trong Streamlit secrets:
    [picklog]
    url = "https://jsonblob.com/api/jsonBlob/XXXX"
Dữ liệu trong kho: {"logs": [ {ngay, gio, so_don, so_sp, so_sku, ht_don, th_don}, ... ]}
"""
import json
from datetime import datetime, timedelta, timezone

import requests
import streamlit as st

_H = {"Content-Type": "application/json", "Accept": "application/json"}


def _url():
    try:
        u = st.secrets["picklog"]["url"]
        return u if u and "jsonblob.com" in u else None
    except Exception:
        return None


def configured() -> bool:
    return bool(_url())


def _today_vn() -> str:
    return (datetime.now(timezone.utc) + timedelta(hours=7)).strftime("%Y-%m-%d")


def _read_all():
    url = _url()
    if not url:
        return None
    try:
        r = requests.get(url, headers=_H, timeout=15)
        if r.status_code == 200:
            d = r.json()
            return d if isinstance(d, dict) else {"logs": []}
    except Exception:
        pass
    return None


def log_batch(payload: dict):
    """Ghi 1 lượt in phiếu (đọc kho → thêm dòng → ghi lại). Trả (ok, msg)."""
    url = _url()
    if not url:
        return False, "Chưa cấu hình kho lưu trữ."
    data = _read_all()
    if data is None:
        return False, "Không đọc được kho lưu trữ (mạng?)."
    data.setdefault("logs", []).append(payload)
    try:
        r = requests.put(url, data=json.dumps(data, ensure_ascii=False), headers=_H, timeout=15)
        if r.status_code == 200:
            return True, "Đã lưu đợt in."
        return False, f"Lỗi lưu ({r.status_code})."
    except Exception as e:
        return False, f"Lỗi kết nối: {e}"


def read_today() -> list:
    """Các lượt in phiếu HÔM NAY."""
    data = _read_all()
    if not data:
        return []
    today = _today_vn()
    return [r for r in data.get("logs", []) if r.get("ngay") == today]
