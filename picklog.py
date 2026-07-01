"""
picklog.py — Ghi & đọc LỊCH SỬ IN PHIẾU NHẶT (qua dashboard) vào GitHub Gist.

Gist KHÔNG bao giờ tự xóa (khác jsonblob ẩn danh hay chết) → bền vĩnh viễn.
Cấu hình trong Streamlit secrets — CHỈ cần 1 token (gist tự tìm/tạo theo tên file):
    [picklog]
    github_token = "ghp_xxx"     # Personal Access Token, quyền: gist
    # gist_id = "..."            # (tuỳ chọn) chỉ định gist cố định; bỏ trống = tự tìm/tạo

Dữ liệu trong gist (file vitran_picklog.json):
    {"logs": [ {ngay, gio, so_don, so_sp, so_sku, ht_don, th_don}, ... ]}
"""
import json
from datetime import datetime, timedelta, timezone

import requests
import streamlit as st

_API = "https://api.github.com"
_FILE = "vitran_picklog.json"      # tên file trong gist (dùng để tự tìm gist)
_GID_CACHE = None                  # nhớ gist_id trong phiên để khỏi list lại mỗi lần


def _token():
    try:
        t = st.secrets["picklog"]["github_token"]
        return t or None
    except Exception:
        return None


def _hdr():
    return {"Authorization": f"Bearer {_token()}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28"}


def configured() -> bool:
    return bool(_token())


def _today_vn() -> str:
    return (datetime.now(timezone.utc) + timedelta(hours=7)).strftime("%Y-%m-%d")


def _explicit_gid():
    try:
        g = st.secrets["picklog"]["gist_id"]
        return g or None
    except Exception:
        return None


def _resolve_gid():
    """Trả gist_id để dùng. Ưu tiên gist_id khai trong secrets; nếu không, TỰ TÌM
    gist chứa file _FILE; chưa có thì TẠO mới (secret). Cache trong phiên."""
    global _GID_CACHE
    if _GID_CACHE:
        return _GID_CACHE
    gid = _explicit_gid()
    if gid:
        _GID_CACHE = gid
        return gid
    if not _token():
        return None
    try:                                   # tìm trong các gist của user theo tên file
        for page in range(1, 6):
            r = requests.get(f"{_API}/gists", headers=_hdr(),
                             params={"per_page": 100, "page": page}, timeout=15)
            if r.status_code != 200:
                break
            rows = r.json()
            if not rows:
                break
            for g in rows:
                if _FILE in (g.get("files") or {}):
                    _GID_CACHE = g.get("id")
                    return _GID_CACHE
            if len(rows) < 100:
                break
    except Exception:
        pass
    try:                                   # chưa có → tạo gist mới (secret)
        body = {"description": "VITRAN dashboard picklog (ĐỪNG XOÁ)",
                "public": False,
                "files": {_FILE: {"content": json.dumps({"logs": []}, ensure_ascii=False)}}}
        r = requests.post(f"{_API}/gists", headers=_hdr(),
                          data=json.dumps(body), timeout=15)
        if r.status_code in (200, 201):
            _GID_CACHE = r.json().get("id")
            return _GID_CACHE
    except Exception:
        pass
    return None


def _read_all():
    gid = _resolve_gid()
    if not gid:
        return None
    try:
        r = requests.get(f"{_API}/gists/{gid}", headers=_hdr(), timeout=15)
        if r.status_code == 200:
            f = (r.json().get("files") or {}).get(_FILE) or {}
            content = f.get("content") or ""
            if f.get("truncated") and f.get("raw_url"):   # file lớn → GitHub cắt, lấy bản đầy đủ
                rr = requests.get(f["raw_url"], headers=_hdr(), timeout=15)
                if rr.status_code == 200:
                    content = rr.text
            if not content:
                return {"logs": []}
            d = json.loads(content)
            return d if isinstance(d, dict) else {"logs": []}
    except Exception:
        pass
    return None


def log_batch(payload: dict):
    """Ghi 1 lượt in phiếu (đọc gist → thêm dòng → ghi lại). Trả (ok, msg)."""
    gid = _resolve_gid()
    if not gid:
        return False, "Chưa cấu hình GitHub token (kho lưu)."
    data = _read_all()
    if data is None:
        return False, "Không đọc được gist (token/mạng?)."
    data.setdefault("logs", []).append(payload)
    try:
        body = {"files": {_FILE: {"content": json.dumps(data, ensure_ascii=False)}}}
        r = requests.patch(f"{_API}/gists/{gid}", headers=_hdr(),
                           data=json.dumps(body), timeout=15)
        if r.status_code == 200:
            return True, "Đã lưu đợt in."
        return False, f"Lỗi lưu gist ({r.status_code})."
    except Exception as e:
        return False, f"Lỗi kết nối: {e}"


def read_today() -> list:
    """Các lượt in phiếu HÔM NAY."""
    return read_date(_today_vn())


def read_date(day_iso: str) -> list:
    """Các lượt in phiếu của 1 NGÀY (yyyy-mm-dd)."""
    data = _read_all()
    if not data:
        return []
    return [r for r in data.get("logs", []) if r.get("ngay") == day_iso]


# ─── ĐƠN CÓ TAG DOHANA (tráo/đã dùng/trả thiếu/hư hỏng/đóng thiếu SP) ───
# Tích luỹ dần qua các lần fetch 3 lần/ngày → vượt giới hạn API Dohana (không lo 1 lần bị 429).
# Lưu cùng gist với picklog, file riêng. Mỗi mục: {code, tag_id, type(inbound/package), recorded, first_seen}.
_DFILE = "vitran_dohana_tags.json"


def _read_gist_file(fname):
    gid = _resolve_gid()
    if not gid:
        return None
    try:
        r = requests.get(f"{_API}/gists/{gid}", headers=_hdr(), timeout=15)
        if r.status_code == 200:
            f = (r.json().get("files") or {}).get(fname) or {}
            content = f.get("content") or ""
            if f.get("truncated") and f.get("raw_url"):
                rr = requests.get(f["raw_url"], headers=_hdr(), timeout=15)
                if rr.status_code == 200:
                    content = rr.text
            if content:
                d = json.loads(content)
                return d if isinstance(d, dict) else None
    except Exception:
        pass
    return None


def read_dohana_tags() -> list:
    """Toàn bộ đơn có tag Dohana đã tích luỹ."""
    d = _read_gist_file(_DFILE)
    return (d or {}).get("tags", []) if d else []


def merge_dohana_tags(new_list) -> list:
    """Gộp tag mới (từ fetch) vào kho, khử trùng theo (code, type). Trả TOÀN BỘ danh sách tích luỹ."""
    gid = _resolve_gid()
    cur = read_dohana_tags()
    if not gid:
        return cur
    seen = {(t.get("code"), t.get("type")) for t in cur}
    today = _today_vn()
    added = False
    for t in (new_list or []):
        c, ty = t.get("code"), t.get("type")
        if c and (c, ty) not in seen:
            cur.append({"code": c, "tag_id": t.get("tag_id"), "type": ty,
                        "recorded": t.get("recorded"), "first_seen": today})
            seen.add((c, ty))
            added = True
    if added:
        try:
            body = {"files": {_DFILE: {"content": json.dumps({"tags": cur}, ensure_ascii=False)}}}
            requests.patch(f"{_API}/gists/{gid}", headers=_hdr(), data=json.dumps(body), timeout=15)
        except Exception:
            pass
    return cur
