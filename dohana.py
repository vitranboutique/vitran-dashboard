"""
dohana.py — Lấy VIDEO ĐÓNG HÀNG từ Dohana (dhn.io.vn) qua Partner API.

API: GET https://backend.dhn.io.vn/dpm/v1/partner/video/search  (header x-api-key)
  params: page, limit, type (package=đóng hàng / outbound / inbound), orderCode, status
Mỗi video: orderCode (= mã vận đơn), type, createdAt, slug, duration, status...
Key đặt trong Streamlit secrets:  [dohana]\n  x_api_key = "..."
"""
from collections import Counter
from datetime import datetime, timedelta, timezone
import time

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


def _vn_dt(iso):
    """createdAt -> giờ VN 'HH:MM:SS DD/MM' (KHỚP cột thời gian hiển thị trên app Dohana)."""
    s = str(iso).replace("Z", "").split(".")[0]
    try:
        return (datetime.fromisoformat(s) + timedelta(hours=7)).strftime("%H:%M:%S %d/%m")
    except Exception:
        return ""


def _vn_time(iso):
    """createdAt -> giờ VN 'HH:MM:SS'."""
    s = str(iso).replace("Z", "").split(".")[0]
    try:
        return (datetime.fromisoformat(s) + timedelta(hours=7)).strftime("%H:%M:%S")
    except Exception:
        return ""


def _records_from(vids, typ):
    """Metadata MỌI video (khử trùng theo mã, giữ bản MỚI NHẤT) để tích luỹ lưu cả năm —
    {code, type, status, date(VN yyyy-mm-dd), time(VN HH:MM:SS), dur(giây), tag_id}."""
    seen, out = set(), []
    for v in sorted(vids, key=lambda x: str(x.get("createdAt") or ""), reverse=True):
        oc = v.get("orderCode")
        if not oc or oc in seen:
            continue
        seen.add(oc)
        dur = v.get("duration")
        out.append({"code": oc, "type": typ, "status": v.get("status"),
                    "date": str(_vnd(v.get("createdAt")) or ""),
                    "time": _vn_time(v.get("createdAt")),
                    "dur": int(dur) if isinstance(dur, (int, float)) else None,
                    "tag_id": v.get("tagId"),
                    "staff": ((v.get("user") or {}).get("firstName") or "").strip()})
    return out


# tagId (UUID) -> TÊN TAG trên app đóng hàng. Partner API CHỈ trả tagId, KHÔNG trả tên tag,
# nên phải map thủ công. Bổ sung/sửa tên trong Streamlit secrets (không cần đổi code):
#   [dohana.tags]
#   "2380d014-46be-4a1b-a549-a6dac57904d8" = "Khách tráo!"
_TAG_NAMES = {
    "2380d014-46be-4a1b-a549-a6dac57904d8": "Khách tráo!",
}


def _tag_name(tag_id):
    """Trả tên tag để hiển thị. Chưa map được tagId -> '⚠️ Có tag' (nhân viên mở app xem)."""
    if not tag_id:
        return ""
    try:
        ov = dict(st.secrets["dohana"]["tags"])
        if tag_id in ov and ov[tag_id]:
            return ov[tag_id]
    except Exception:
        pass
    return _TAG_NAMES.get(tag_id) or "⚠️ Có tag"


_LAST_REQ = [0.0]   # mốc request Dohana gần nhất (dùng chung mọi call) — giữ nhịp ≤ 10 req/s


def _throttle(min_gap=0.34):
    """Giãn nhịp gọi Dohana (~3 req/s, dư an toàn dưới 10/s) → tránh bị phạt 429 tích luỹ."""
    dt = time.monotonic() - _LAST_REQ[0]
    if dt < min_gap:
        time.sleep(min_gap - dt)
    _LAST_REQ[0] = time.monotonic()


def _fetch_videos(typ: str, cutoff_date, max_pages: int):
    """Lấy video theo type, lùi (page 0 = MỚI NHẤT) tới khi createdAt < cutoff_date. Khử trùng id."""
    key = _key()
    if not key:
        return None
    headers = {"x-api-key": key}
    vids = []
    for p in range(0, max_pages):        # ⚠️ 0-INDEXED: page=0 = MỚI NHẤT
        rows = None
        # Dohana giới hạn 10 req/s (xác nhận từ Dohana). _throttle() giữ nhịp <10/s → hết 429.
        # 429 lẻ (do consumer khác) → thử lại, cửa sổ reset <1s.
        for _try in range(3):
            _throttle()
            try:
                r = requests.get(_BASE, params={"page": p, "limit": 100, "type": typ},
                                 headers=headers, timeout=20)
            except Exception:
                break
            if r.status_code == 429:
                time.sleep(min(float(r.headers.get("Retry-After") or 1), 3))
                continue
            if r.status_code == 200:
                rows = r.json().get("data", [])
            break                        # thành công / lỗi khác → thoát vòng thử lại
        if rows is None:                 # vẫn 429 sau 5 lần / lỗi mạng
            if p == 0:                   # trang ĐẦU fail → Dohana KHÔNG sẵn sàng → trả None
                return None              # (báo 'tạm không lấy được', KHÔNG nhầm '0 video')
            break                        # trang sau: giữ video đã lấy
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
    # meta theo mã đơn: thời lượng clip, giờ quay (createdAt), tag app đóng hàng.
    # Giữ video MỚI NHẤT cho mỗi mã (sort createdAt giảm dần → lần gặp đầu = mới nhất).
    meta = {}
    for v in sorted(win, key=lambda x: str(x.get("createdAt") or ""), reverse=True):
        oc = v.get("orderCode")
        if not oc or oc in meta:
            continue
        dur = v.get("duration")
        meta[oc] = {
            "dur": int(dur) if isinstance(dur, (int, float)) else None,
            "recorded": _vn_dt(v.get("createdAt")),
            "tag_id": v.get("tagId"),
            "tag": _tag_name(v.get("tagId")),
            "staff": ((v.get("user") or {}).get("firstName") or "").strip(),   # NV quay clip
        }
    return {
        "total": sum(1 for v in vids if _vnd(v.get("createdAt")) == tdate),
        "count": dict(cnt),
        "match": set(cnt),
        "today_codes": today_codes,
        "dup": {k: v for k, v in cnt.items() if v >= 2},
        "meta": meta,
        # METADATA MỌI video khui hàng (lưu cả năm): trạng thái·ngày·giờ·thời lượng·tag.
        # Đơn CÓ tag (tráo/đã dùng/trả thiếu/hư hỏng) → mục CẦN KN.
        "records": _records_from(vids, "inbound"),
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
        # METADATA MỌI video đóng hàng (lưu cả năm): trạng thái·ngày·giờ·thời lượng·tag.
        # Đơn CÓ tag (đóng thiếu SP) → mục KHÔNG CẦN KN.
        "records": _records_from(vids, "package"),
    }
