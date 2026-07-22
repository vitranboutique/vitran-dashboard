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
_FROZEN_SUMMARIES_KEY = "frozen_daily_summaries"


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


def _now_vn():
    return datetime.now(timezone.utc) + timedelta(hours=7)


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


def _codes_of(row):
    return [str(c).strip() for c in (row or {}).get("codes", []) if str(c).strip()]


def _intv(row, key):
    try:
        return int((row or {}).get(key) or 0)
    except Exception:
        return 0


def _scale_count(value, old_n, new_n):
    try:
        value = int(value or 0)
    except Exception:
        value = 0
    if not (old_n and new_n and value):
        return 0
    return int(round(value * new_n / old_n))


def _trim_duplicate_codes(row, new_codes, old_code_count):
    """Trả row đã giảm số đơn khi cùng một mã bị lưu trong nhiều đợt."""
    out = dict(row or {})
    old_codes = _codes_of(out)
    old_n = int(out.get("so_don") or old_code_count or 0)
    new_n = len(new_codes)
    out["codes"] = list(new_codes)
    groups = out.get("code_groups") or []
    if old_codes and isinstance(groups, list):
        by_code = {}
        for idx, code in enumerate(old_codes):
            if idx < len(groups) and groups[idx]:
                by_code[code] = groups[idx]
        if by_code:
            out["code_groups"] = [by_code.get(code, [code]) for code in new_codes]
    out["so_don"] = new_n
    if old_n and new_n != old_n:
        out["so_sp"] = _scale_count(out.get("so_sp"), old_n, new_n)
        out["ht_don"] = min(_intv(out, "ht_don"), new_n)
        out["th_don"] = max(0, new_n - _intv(out, "ht_don"))
        out["so_cu"] = min(_intv(out, "so_cu"), new_n)
        out["dedup_note"] = f"Đã bỏ {max(0, old_code_count - new_n)} mã trùng"
    return out


def dedupe_logs(rows):
    """Khử trùng lịch sử phiếu nhặt.

    Ưu tiên khử theo mã đơn/vận đơn trong `codes`; nếu dòng cũ không có codes
    thì chỉ khử dòng trùng y hệt theo ngày/giờ/số đơn/số SP.
    """
    out, seen_exact, seen_codes, seen_no_code = [], set(), set(), set()
    dup_orders = 0
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        codes = _codes_of(row)
        exact = (
            row.get("ngay"), str(row.get("gio", "")), _intv(row, "so_don"),
            _intv(row, "so_sp"), tuple(sorted(codes)),
        )
        if exact in seen_exact:
            dup_orders += _intv(row, "so_don") or len(codes)
            continue
        seen_exact.add(exact)
        if codes:
            new_codes = []
            for code in codes:
                if code in seen_codes:
                    continue
                seen_codes.add(code)
                new_codes.append(code)
            if not new_codes:
                dup_orders += _intv(row, "so_don") or len(codes)
                continue
            if len(new_codes) < len(codes):
                dup_orders += len(codes) - len(new_codes)
                out.append(_trim_duplicate_codes(row, new_codes, len(codes)))
            else:
                out.append(dict(row))
            continue
        no_code_key = (row.get("ngay"), str(row.get("gio", "")), _intv(row, "so_don"), _intv(row, "so_sp"))
        if no_code_key in seen_no_code:
            dup_orders += _intv(row, "so_don")
            continue
        seen_no_code.add(no_code_key)
        out.append(dict(row))
    return out, dup_orders


def summarize_logs(rows):
    clean, dup_orders = dedupe_logs(rows)
    return {
        "rows": clean,
        "so_don": sum(_intv(r, "so_don") for r in clean),
        "so_sp": sum(_intv(r, "so_sp") for r in clean),
        "dup_orders": dup_orders,
    }


def _write_all(data) -> bool:
    gid = _resolve_gid()
    if not gid:
        return False
    try:
        body = {"files": {_FILE: {"content": json.dumps(data, ensure_ascii=False)}}}
        r = requests.patch(f"{_API}/gists/{gid}", headers=_hdr(), data=json.dumps(body), timeout=20)
        return r.status_code == 200
    except Exception:
        return False


def _apply_frozen_counts(summary, frozen):
    out = dict(summary or {})
    if isinstance(frozen, dict):
        out["so_don"] = _intv(frozen, "so_don")
        out["so_sp"] = _intv(frozen, "so_sp")
        out["counts_frozen"] = True
        out["frozen_at"] = frozen.get("frozen_at") or ""
    return out


def _freeze_closed_summaries(data, summaries):
    """Khóa số A4 từ 23:59 mỗi ngày; các ngày trước luôn giữ số đã khóa."""
    if not isinstance(data, dict):
        return summaries
    frozen = data.setdefault(_FROZEN_SUMMARIES_KEY, {})
    if not isinstance(frozen, dict):
        frozen = {}
        data[_FROZEN_SUMMARIES_KEY] = frozen
    now_vn = _now_vn()
    today = now_vn.strftime("%Y-%m-%d")
    reached_daily_cutoff = (now_vn.hour, now_vn.minute) >= (23, 59)
    changed = False
    for day, summary in (summaries or {}).items():
        day_key = str(day or "")
        is_closed = day_key < today or (day_key == today and reached_daily_cutoff)
        if not is_closed or day in frozen:
            continue
        frozen[day] = {
            "so_don": _intv(summary, "so_don"),
            "so_sp": _intv(summary, "so_sp"),
            "frozen_at": today,
        }
        changed = True
    if changed:
        _write_all(data)
    return {
        day: _apply_frozen_counts(summary, frozen.get(day))
        for day, summary in (summaries or {}).items()
    }


def summaries_by_date():
    data = _read_all()
    groups = {}
    for row in (data or {}).get("logs", []):
        day = row.get("ngay")
        if day:
            groups.setdefault(day, []).append(row)
    summaries = {day: summarize_logs(rows) for day, rows in groups.items()}
    return _freeze_closed_summaries(data, summaries)


def log_batch(payload: dict):
    """Ghi 1 lượt in phiếu (đọc gist → thêm dòng → ghi lại). Trả (ok, msg)."""
    gid = _resolve_gid()
    if not gid:
        return False, "Chưa cấu hình GitHub token (kho lưu)."
    data = _read_all()
    if data is None:
        return False, "Không đọc được gist (token/mạng?)."
    logs = data.setdefault("logs", [])
    day = (payload or {}).get("ngay")
    existing_rows = [r for r in logs if r.get("ngay") == day]
    existing_codes = set()
    for r in existing_rows:
        existing_codes.update(_codes_of(r))
    payload_codes = _codes_of(payload)
    if payload_codes:
        new_codes = [c for c in payload_codes if c not in existing_codes]
        if not new_codes:
            return True, "Đợt này đã có trong lịch sử, không lưu trùng."
        if len(new_codes) < len(payload_codes):
            payload = _trim_duplicate_codes(payload, new_codes, len(payload_codes))
    else:
        exact = ((payload or {}).get("ngay"), str((payload or {}).get("gio", "")),
                 _intv(payload, "so_don"), _intv(payload, "so_sp"))
        for r in existing_rows:
            if (r.get("ngay"), str(r.get("gio", "")), _intv(r, "so_don"), _intv(r, "so_sp")) == exact:
                return True, "Đợt này đã có trong lịch sử, không lưu trùng."
    logs.append(payload)
    try:
        body = {"files": {_FILE: {"content": json.dumps(data, ensure_ascii=False)}}}
        r = requests.patch(f"{_API}/gists/{gid}", headers=_hdr(),
                           data=json.dumps(body), timeout=15)
        if r.status_code == 200:
            return True, "Đã lưu đợt in."
        return False, f"Lỗi lưu gist ({r.status_code})."
    except Exception as e:
        return False, f"Lỗi kết nối: {e}"


def log_batches(payloads: list):
    """Ghi NHIỀU đợt trong 1 lần (đọc gist 1 lần → append → patch 1 lần) → nhanh, đỡ rate-limit.
    Khử trùng theo (ngay, gio, so_don): đợt đã có thì BỎ QUA — nhưng nếu payload có so_cu mà đợt cũ
    chưa có thì CẬP NHẬT so_cu (để bổ sung cột Cũ về sau). Trả (ok, added, updated, skipped, msg)."""
    gid = _resolve_gid()
    if not gid:
        return False, 0, 0, 0, "Chưa cấu hình GitHub token (kho lưu)."
    data = _read_all()
    if data is None:
        return False, 0, 0, 0, "Không đọc được gist (token/mạng?)."
    logs = data.setdefault("logs", [])
    existing = {}
    existing_codes_by_day = {}
    for r in logs:
        existing[(r.get("ngay"), str(r.get("gio", "")), int(r.get("so_don") or 0))] = r
        day = r.get("ngay")
        if day:
            existing_codes_by_day.setdefault(day, set()).update(_codes_of(r))
    added = updated = skipped = 0
    for p in (payloads or []):
        key = (p.get("ngay"), str(p.get("gio", "")), int(p.get("so_don") or 0))
        codes = _codes_of(p)
        if codes:
            seen_codes = existing_codes_by_day.setdefault(p.get("ngay"), set())
            new_codes = [c for c in codes if c not in seen_codes]
            if not new_codes:
                skipped += 1
                continue
            if len(new_codes) < len(codes):
                p = _trim_duplicate_codes(p, new_codes, len(codes))
                key = (p.get("ngay"), str(p.get("gio", "")), int(p.get("so_don") or 0))
            seen_codes.update(new_codes)
        old = existing.get(key)
        if old is not None:
            if int(p.get("so_cu") or 0) and not int(old.get("so_cu") or 0):
                old["so_cu"] = int(p.get("so_cu") or 0)
                updated += 1
            else:
                skipped += 1
            continue
        logs.append(p)
        existing[key] = p
        added += 1
    if not (added or updated):
        return True, 0, 0, skipped, "Không có đợt mới (tất cả đã có)."
    try:
        body = {"files": {_FILE: {"content": json.dumps(data, ensure_ascii=False)}}}
        r = requests.patch(f"{_API}/gists/{gid}", headers=_hdr(), data=json.dumps(body), timeout=25)
        if r.status_code == 200:
            return True, added, updated, skipped, "OK"
        return False, 0, 0, skipped, f"Lỗi lưu gist ({r.status_code})."
    except Exception as e:
        return False, 0, 0, skipped, f"Lỗi kết nối: {e}"


def delete_log(ngay, gio, so_don, so_sp=None):
    """XÓA 1 đợt phiếu nhặt khớp (ngay, gio, so_don[, so_sp]) — xóa ĐÚNG 1 dòng đầu khớp.
    Trả (ok, msg). Chỉ gọi cho tài khoản admin/chủ shop."""
    gid = _resolve_gid()
    if not gid:
        return False, "Chưa cấu hình GitHub token (kho lưu)."
    data = _read_all()
    if data is None:
        return False, "Không đọc được gist (token/mạng?)."
    logs = data.get("logs", [])
    _sd = int(so_don or 0)
    idx = None
    for i, r in enumerate(logs):
        if (r.get("ngay") == ngay and str(r.get("gio", "")) == str(gio)
                and int(r.get("so_don") or 0) == _sd
                and (so_sp is None or int(r.get("so_sp") or 0) == int(so_sp or 0))):
            idx = i
            break
    if idx is None:
        return False, "Không tìm thấy đợt cần xóa (có thể đã xóa rồi)."
    removed = logs.pop(idx)
    try:
        body = {"files": {_FILE: {"content": json.dumps(data, ensure_ascii=False)}}}
        r = requests.patch(f"{_API}/gists/{gid}", headers=_hdr(), data=json.dumps(body), timeout=20)
        if r.status_code == 200:
            return True, f"Đã xóa đợt {removed.get('gio', '')} — {removed.get('so_don', 0)} đơn."
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
    rows = [r for r in data.get("logs", []) if r.get("ngay") == day_iso]
    return summarize_logs(rows)["rows"]


def read_date_summary(day_iso: str) -> dict:
    """Tổng phiếu nhặt trong ngày sau khi khử trùng."""
    data = _read_all()
    if not data:
        return {"rows": [], "so_don": 0, "so_sp": 0, "dup_orders": 0}
    rows = [r for r in data.get("logs", []) if r.get("ngay") == day_iso]
    summaries = _freeze_closed_summaries(data, {day_iso: summarize_logs(rows)})
    return summaries.get(day_iso) or {"rows": [], "so_don": 0, "so_sp": 0, "dup_orders": 0}


# ─── LỊCH SỬ LƯU TTKH (mỗi lần ghi Sapo) — LƯU BỀN ĐỂ THỐNG KÊ THEO NGÀY ───
_TTKH_FILE = "vitran_ttkh_log.json"


def log_ttkh_batch(records: list) -> tuple:
    """Ghi 1 lượt lưu TTKH (nhiều dòng) vào gist. Mỗi record nên có:
    {ngay, gio, ma_don, sdt, ket_qua ('thanh_cong'|'that_bai'|'bo_qua'), chi_tiet}.
    Trả (ok, msg). Không bao giờ raise (an toàn cho luồng ghi Sapo)."""
    records = [r for r in (records or []) if r]
    if not records:
        return True, "Không có gì để lưu."
    gid = _resolve_gid()
    if not gid:
        return False, "Chưa cấu hình GitHub token (kho lưu)."
    data = _read_gist_file(_TTKH_FILE) or {"logs": []}
    if not isinstance(data, dict):
        data = {"logs": []}
    data.setdefault("logs", []).extend(records)
    ok = _write_gist_file(_TTKH_FILE, data)
    return (ok, "Đã lưu lịch sử TTKH." if ok else "Lỗi lưu gist lịch sử TTKH.")


def read_ttkh_logs() -> list:
    """Toàn bộ lịch sử lưu TTKH đã tích luỹ (list record). Rỗng nếu chưa có/chưa cấu hình."""
    d = _read_gist_file(_TTKH_FILE)
    return (d or {}).get("logs", []) if isinstance(d, dict) else []


# ─── ĐƠN "CHỜ TẠO KHÁCH": đã ghi được đơn nhưng phần KHÁCH HÀNG lỗi/thiếu ───
# Giữ để filter KHÔNG ẩn đơn (chưa đủ 2 nơi) cho tới khi tạo được khách.
_TTKH_PENDING_FILE = "vitran_ttkh_pending.json"


_TTKH_AUDIT_FILE = "vitran_ttkh_audit.json"


def save_ttkh_audit(data: dict) -> bool:
    """Lưu kết quả quét đối chiếu (đơn thiếu khách/địa chỉ text) để giữ qua tải lại."""
    try:
        return _write_gist_file(_TTKH_AUDIT_FILE, data or {})
    except Exception:
        return False


def read_ttkh_audit() -> dict:
    """Đọc kết quả quét gần nhất (None nếu chưa quét/chưa cấu hình)."""
    d = _read_gist_file(_TTKH_AUDIT_FILE)
    return d if isinstance(d, dict) else None


_CUST_AUDIT_FILE = "vitran_cust_audit.json"


def save_cust_audit(data: dict) -> bool:
    """Lưu kết quả quét KHÁCH HÀNG chưa chuẩn (phân nhóm) để giữ qua tải lại."""
    try:
        return _write_gist_file(_CUST_AUDIT_FILE, data or {})
    except Exception:
        return False


def read_cust_audit() -> dict:
    d = _read_gist_file(_CUST_AUDIT_FILE)
    return d if isinstance(d, dict) else None


def read_ttkh_pending() -> dict:
    """Map {order_id: {ma_don, sdt, ly_do, ts}} các đơn đã ghi nhưng CHƯA tạo được khách."""
    d = _read_gist_file(_TTKH_PENDING_FILE)
    p = (d or {}).get("pending", {}) if isinstance(d, dict) else {}
    return p if isinstance(p, dict) else {}


def update_ttkh_pending(add: dict = None, remove_ids: list = None) -> bool:
    """Thêm đơn lỗi khách vào / gỡ đơn đã tạo được khách ra khỏi danh sách chờ. An toàn."""
    if not (add or remove_ids):
        return True
    gid = _resolve_gid()
    if not gid:
        return False
    d = _read_gist_file(_TTKH_PENDING_FILE)
    pend = (d or {}).get("pending", {}) if isinstance(d, dict) else {}
    if not isinstance(pend, dict):
        pend = {}
    for oid in (remove_ids or []):
        pend.pop(str(oid), None)
    for oid, meta in (add or {}).items():
        pend[str(oid)] = meta
    return _write_gist_file(_TTKH_PENDING_FILE, {"pending": pend})


# ─── METADATA VIDEO DOHANA (đóng hàng + khui hàng) — LƯU CẢ NĂM ───
# Dohana chỉ giữ 30 ngày rồi XOÁ số liệu. Tích luỹ dần qua các lần fetch 3×/ngày vào GIST (không tự
# xoá) → cuối năm VẪN ĐỌC được: trạng thái · ngày quay · giờ · thời lượng · tag · link xem video. Khử trùng (code,type).
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
    """Toàn bộ metadata video Dohana đã tích luỹ: [{code,type,status,date,time,dur,tag_id,slug,link,first_seen}]."""
    d = _read_gist_file(_DFILE)
    return (d or {}).get("videos", []) if d else []


def _dohana_has_value(v) -> bool:
    return v is not None and str(v).strip() != ""


def _fill_missing_dohana_field(rec: dict, src: dict, key: str) -> bool:
    if _dohana_has_value(rec.get(key)) or not _dohana_has_value(src.get(key)):
        return False
    rec[key] = src.get(key)
    return True


def _lock_dohana_tag(rec: dict, tag_id, tag_name, today: str) -> bool:
    """Khóa tag đã từng thấy. Sau này Dohana gỡ/sửa tag cũng không làm mất dấu tag cũ."""
    if not tag_id:
        return False
    changed = False
    if not rec.get("locked_tag_id"):
        rec["locked_tag_id"] = tag_id
        rec["locked_tag_name"] = tag_name or rec.get("tag_name") or ""
        rec["tag_locked_at"] = rec.get("tag_locked_at") or today
        changed = True
    elif tag_name and not rec.get("locked_tag_name"):
        rec["locked_tag_name"] = tag_name
        changed = True
    if not rec.get("tag_id"):
        rec["tag_id"] = rec.get("locked_tag_id") or tag_id
        changed = True
    if (tag_name or rec.get("locked_tag_name")) and not rec.get("tag_name"):
        rec["tag_name"] = tag_name or rec.get("locked_tag_name")
        changed = True
    return changed


def merge_dohana_videos(new_list) -> list:
    """Gộp metadata video mới (từ fetch) vào kho, khử trùng (code,type).
    Fetch live có ``tag_observed=True`` là nguồn sự thật hiện tại: Dohana gỡ/đổi tag
    thì kho cũng phải gỡ/đổi. Bản dự phòng cũ không có cờ này sẽ không được xóa tag.
    Các field clip đã có (ngày/giờ/thời lượng/link) chỉ được bổ sung khi còn trống, không bị xóa bởi lần fetch sau."""
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
        tag_id = r.get("locked_tag_id") or r.get("tag_id")
        tag_name = r.get("locked_tag_name") or r.get("tag_name")
        tag_observed = r.get("tag_observed") is True
        old = idx.get((c, ty))
        if old is None:
            rec = {"code": c, "type": ty, "status": r.get("status"), "date": r.get("date"),
                   "time": r.get("time"), "dur": r.get("dur"), "tag_id": tag_id,
                   "tag_name": tag_name, "slug": r.get("slug"), "link": r.get("link"),
                   "staff": r.get("staff"), "first_seen": today}
            if not tag_observed:
                _lock_dohana_tag(rec, tag_id, tag_name, today)
            cur.append(rec)
            idx[(c, ty)] = rec
            changed = True
        else:
            if tag_observed:
                # Live API xác nhận trạng thái tag hiện tại, kể cả xác nhận đã gỡ (None/rỗng).
                for key, value in (("tag_id", tag_id or ""), ("tag_name", tag_name or ""),
                                   ("locked_tag_id", ""), ("locked_tag_name", "")):
                    if old.get(key) != value:
                        old[key] = value
                        changed = True
                if old.get("tag_locked_at"):
                    old["tag_locked_at"] = ""
                    changed = True
            elif _lock_dohana_tag(old, tag_id, tag_name, today):
                changed = True
            if r.get("status") and old.get("status") != r.get("status"):
                old["status"] = r.get("status")
                changed = True
            for key in ("status", "date", "time", "dur", "staff", "slug", "link"):
                if _fill_missing_dohana_field(old, r, key):
                    changed = True
            if tag_name and not old.get("tag_name"):
                old["tag_name"] = tag_name
                changed = True
    if changed:
        try:
            body = {"files": {_DFILE: {"content": json.dumps({"videos": cur}, ensure_ascii=False)}}}
            requests.patch(f"{_API}/gists/{gid}", headers=_hdr(), data=json.dumps(body), timeout=15)
        except Exception:
            pass
    return cur


def clear_dohana_video_tag(code: str, video_type: str = "inbound") -> int:
    """Gỡ tag đã lưu nhầm của đúng một mã video; trả số record đã sửa."""
    code = str(code or "").strip()
    video_type = str(video_type or "").strip()
    if not code or not _resolve_gid():
        return 0
    cur = read_dohana_videos()
    changed = 0
    for rec in cur:
        if str(rec.get("code") or "").strip() != code:
            continue
        if video_type and str(rec.get("type") or "").strip() != video_type:
            continue
        had_tag = any(rec.get(k) for k in ("tag_id", "tag_name", "locked_tag_id",
                                           "locked_tag_name", "tag_locked_at"))
        for key in ("tag_id", "tag_name", "locked_tag_id", "locked_tag_name", "tag_locked_at"):
            rec[key] = ""
        rec["tag_corrected_at"] = _today_vn()
        if had_tag:
            changed += 1
    if changed and _write_gist_file(_DFILE, {"videos": cur}):
        return changed
    return 0


# ───── ĐƠN NHẬP KHO NHƯNG KHÔNG CÓ VIDEO KHUI — lưu VĨNH VIỄN, KHÔNG mất khi Dohana xoá video ─────
# Đơn hoàn đã restock (Sapo) mà không khớp video khui (inbound) nào trong kho video đã lưu → nghi
# NV nhập kho nhầm / không quay clip. Sổ này TÍCH LUỸ, không tự xoá; video xuất hiện sau → tự đánh
# dấu resolved; admin có thể 'dismiss' (đã kiểm tra là ổn). Vì lưu riêng ở Gist nên Dohana purge
# video gốc cũng không làm mất bằng chứng.
_RESTOCK_NOVIDEO_FILE = "vitran_restock_novideo.json"


def read_restock_novideo() -> dict:
    """Sổ đơn đã nhập kho thiếu video khui. {items: {key: {...các field hiển thị + status...}}}.
    status: active (đang thiếu) · resolved (video hiện sau) · dismissed (admin bỏ qua)."""
    d = _read_gist_file(_RESTOCK_NOVIDEO_FILE)
    if isinstance(d, dict) and isinstance(d.get("items"), dict):
        return d
    return {"items": {}}


def write_restock_novideo(data) -> bool:
    if not isinstance(data, dict):
        data = {"items": {}}
    data.setdefault("items", {})
    return _write_gist_file(_RESTOCK_NOVIDEO_FILE, data)


def dismiss_restock_novideo(keys, reason="admin đã kiểm tra là ổn") -> bool:
    """Đánh dấu 1/nhiều đơn 'đã bỏ qua' → hết cảnh báo nhưng vẫn giữ trong sổ (audit)."""
    if isinstance(keys, str):
        keys = [keys]
    d = read_restock_novideo()
    items = d.get("items", {})
    today = _today_vn()
    hit = False
    for k in keys:
        if k in items:
            items[k]["status"] = "dismissed"
            items[k]["resolved_reason"] = reason
            items[k]["resolved_at"] = today
            hit = True
    return _write_gist_file(_RESTOCK_NOVIDEO_FILE, d) if hit else False


# ───── KHỚP TAY clip khui ↔ đơn hoàn — khi mã trên Dohana nhập THIẾU/SAI (vd clip "3Q" thay vì
# "GYXVRB3Q") mà KHÔNG sửa được trong app đóng hàng → admin tự khớp trong app vận hành. Lưu VĨNH VIỄN
# ở Gist, key theo mã đơn hoàn đã chuẩn hoá (caller tự chuẩn hoá bằng _ascii_code). ─────
_KHUI_MATCH_FILE = "vitran_khui_manual_match.json"


def read_khui_manual_match() -> list:
    """[{ret, clip, ret_raw, clip_raw, day, at}] — ret/clip đã chuẩn hoá sẵn (ascii-lower) bởi caller."""
    d = _read_gist_file(_KHUI_MATCH_FILE)
    if isinstance(d, dict) and isinstance(d.get("matches"), list):
        return d["matches"]
    return []


def add_khui_manual_match(entry: dict) -> bool:
    """Thêm/thay 1 cặp khớp tay. entry cần {ret, clip} (đã chuẩn hoá) + tuỳ chọn ret_raw/clip_raw/day/at.
    Cùng 1 mã đơn hoàn (ret) thì thay cặp cũ (1 đơn ↔ 1 clip)."""
    ret = str((entry or {}).get("ret") or "").strip()
    clip = str((entry or {}).get("clip") or "").strip()
    if not (ret and clip):
        return False
    matches = [m for m in read_khui_manual_match() if m.get("ret") != ret]
    row = dict(entry)
    row.setdefault("at", _today_vn())
    matches.append(row)
    return _write_gist_file(_KHUI_MATCH_FILE, {"matches": matches})


def remove_khui_manual_match(ret: str) -> bool:
    ret = str(ret or "").strip()
    matches = [m for m in read_khui_manual_match() if m.get("ret") != ret]
    return _write_gist_file(_KHUI_MATCH_FILE, {"matches": matches})
