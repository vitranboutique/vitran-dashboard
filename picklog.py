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


# ─── METADATA VIDEO DOHANA (đóng hàng + khui hàng) — LƯU CẢ NĂM ───
# Dohana chỉ giữ 30 ngày rồi XOÁ số liệu. Tích luỹ dần qua các lần fetch 3×/ngày vào GIST (không tự
# xoá) → cuối năm VẪN ĐỌC được: trạng thái · ngày quay · giờ · thời lượng · tag. Khử trùng (code,type).
_DFILE = "vitran_dohana_videos.json"


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


def _write_gist_file(fname, data):
    """Ghi (PATCH) 1 file JSON vào gist. Trả True nếu OK."""
    gid = _resolve_gid()
    if not gid:
        return False
    try:
        body = {"files": {fname: {"content": json.dumps(data, ensure_ascii=False)}}}
        r = requests.patch(f"{_API}/gists/{gid}", headers=_hdr(), data=json.dumps(body), timeout=15)
        return r.status_code == 200
    except Exception:
        return False


def read_dohana_videos() -> list:
    """Toàn bộ metadata video Dohana đã tích luỹ: [{code,type,status,date,time,dur,tag_id,first_seen}]."""
    d = _read_gist_file(_DFILE)
    return (d or {}).get("videos", []) if d else []


def merge_dohana_videos(new_list) -> list:
    """Gộp metadata video mới (từ fetch) vào kho, khử trùng (code,type); cập nhật tag nếu gắn muộn.
    Trả TOÀN BỘ danh sách tích luỹ (lưu cả năm, không lo Dohana xoá sau 30 ngày)."""
    gid = _resolve_gid()
    cur = read_dohana_videos()
    if not gid:
        return cur
    idx = {(r.get("code"), r.get("type")): r for r in cur}
    today = _today_vn()
    changed = False
    for r in (new_list or []):
        c, ty = r.get("code"), r.get("type")
        if not c:
            continue
        old = idx.get((c, ty))
        if old is None:
            rec = {"code": c, "type": ty, "status": r.get("status"), "date": r.get("date"),
                   "time": r.get("time"), "dur": r.get("dur"), "tag_id": r.get("tag_id"),
                   "staff": r.get("staff"), "first_seen": today}
            cur.append(rec)
            idx[(c, ty)] = rec
            changed = True
        elif r.get("tag_id") and not old.get("tag_id"):   # tag gắn MUỘN (sau khi đã lưu) → cập nhật
            old["tag_id"] = r.get("tag_id")
            changed = True
    if changed:
        try:
            body = {"files": {_DFILE: {"content": json.dumps({"videos": cur}, ensure_ascii=False)}}}
            requests.patch(f"{_API}/gists/{gid}", headers=_hdr(), data=json.dumps(body), timeout=15)
        except Exception:
            pass
    return cur
