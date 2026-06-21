"""
report_store.py — Lưu & đọc LỊCH SỬ BÁO CÁO CUỐI NGÀY (tối đa 30 ngày) vào jsonblob.com.

Vì Streamlit Cloud xoá file khi reboot + dữ liệu Sapo đổi theo thời gian (qua ngày
không xem lại được số cũ) → chốt snapshot mỗi ngày vào 1 kho JSON ẩn danh.
URL kho đặt trong Streamlit secrets:
    [report_store]
    url = "https://jsonblob.com/api/jsonBlob/XXXX"
Dữ liệu: {"reports": {"2026-06-20": {"rep": {...}, "dv": {...}, "now": "..."}, ...}}
Chỉ giữ KEEP_DAYS ngày gần nhất (key ISO yyyy-mm-dd sort được).
"""
import json
from datetime import datetime, timedelta, timezone

import requests
import streamlit as st

_H = {"Content-Type": "application/json", "Accept": "application/json"}
KEEP_DAYS = 30


def _url():
    try:
        u = st.secrets["report_store"]["url"]
        return u if u and "jsonblob.com" in u else None
    except Exception:
        return None


def configured() -> bool:
    return bool(_url())


def today_iso() -> str:
    return (datetime.now(timezone.utc) + timedelta(hours=7)).strftime("%Y-%m-%d")


def _read_all():
    url = _url()
    if not url:
        return None
    try:
        r = requests.get(url, headers=_H, timeout=20)
        if r.status_code == 200:
            d = r.json()
            return d if isinstance(d, dict) else {"reports": {}}
    except Exception:
        pass
    return None


def _strip_rep(rep: dict) -> dict:
    """Bỏ field nặng / không serialize (set mã, list mã) — chỉ giữ phần để RENDER lại."""
    rep = dict(rep)
    for k in ("dong_goi_codes", "huy_goi_codes", "dong_goi_order_codes"):
        rep.pop(k, None)
    nk = rep.get("nhap_kho")
    if isinstance(nk, dict):
        nk = dict(nk)
        if nk.get("detail"):
            nk["detail"] = [{k: v for k, v in d.items() if k != "codes"} for d in nk["detail"]]
        rep["nhap_kho"] = nk
    return rep


def save_report(date_iso: str, rep: dict, dv, now_str: str):
    """Lưu snapshot báo cáo 1 ngày (ghi đè nếu đã có). Giữ 30 ngày gần nhất. Trả (ok, msg)."""
    url = _url()
    if not url:
        return False, "Chưa cấu hình kho lưu báo cáo."
    data = _read_all()
    if data is None:
        return False, "Không đọc được kho lưu trữ (mạng?)."
    reports = data.get("reports") or {}
    reports[date_iso] = {
        "rep": _strip_rep(rep),
        "dv": {"total": (dv or {}).get("total")},   # set 'match' không serialize → chỉ giữ total
        "now": now_str,
    }
    for old in sorted(reports.keys(), reverse=True)[KEEP_DAYS:]:   # prune > 30 ngày
        reports.pop(old, None)
    data["reports"] = reports
    try:
        r = requests.put(url, data=json.dumps(data, ensure_ascii=False), headers=_H, timeout=20)
        if r.status_code == 200:
            return True, f"Đã lưu báo cáo ngày {date_iso}."
        return False, f"Lỗi lưu ({r.status_code})."
    except Exception as e:
        return False, f"Lỗi kết nối: {e}"


def list_dates() -> list:
    """Danh sách ngày đã lưu (ISO yyyy-mm-dd, mới → cũ)."""
    data = _read_all()
    if not data:
        return []
    return sorted((data.get("reports") or {}).keys(), reverse=True)


def load_report(date_iso: str):
    """Đọc snapshot 1 ngày → dict {rep, dv, now} hoặc None."""
    data = _read_all()
    if not data:
        return None
    return (data.get("reports") or {}).get(date_iso)
