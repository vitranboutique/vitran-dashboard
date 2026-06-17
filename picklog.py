"""
picklog.py — Ghi & đọc LỊCH SỬ IN PHIẾU NHẶT (qua dashboard) vào Google Sheet.

Lưu qua 1 Google Apps Script Web App (không cần Service Account / Google Cloud).
URL web app đặt trong Streamlit secrets:  [picklog]\nurl = "https://script.google.com/macros/s/XXX/exec"
"""
from datetime import datetime, timedelta, timezone

import requests
import streamlit as st


def _url():
    try:
        u = st.secrets["picklog"]["url"]
        return u if u and "script.google.com" in u else None
    except Exception:
        return None


def configured() -> bool:
    return bool(_url())


def _today_vn() -> str:
    return (datetime.now(timezone.utc) + timedelta(hours=7)).strftime("%Y-%m-%d")


def log_batch(payload: dict):
    """Ghi 1 lượt in phiếu. Trả (ok: bool, msg: str)."""
    url = _url()
    if not url:
        return False, "Chưa cấu hình Google Sheet."
    try:
        r = requests.post(url, json={"action": "log", "data": payload}, timeout=20)
        if r.status_code == 200 and r.json().get("ok"):
            return True, "Đã lưu đợt in vào Google Sheet."
        return False, f"Lỗi phản hồi: {str(r.text)[:120]}"
    except Exception as e:
        return False, f"Lỗi kết nối Google Sheet: {e}"


def read_today() -> list:
    """Đọc các lượt in phiếu HÔM NAY (list dict). Rỗng nếu chưa cấu hình/lỗi."""
    url = _url()
    if not url:
        return []
    try:
        r = requests.get(url, params={"action": "today", "date": _today_vn()}, timeout=20)
        if r.status_code == 200:
            return r.json().get("rows", []) or []
    except Exception:
        pass
    return []
