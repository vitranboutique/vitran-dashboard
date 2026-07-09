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
_TAG_CACHE = {"ts": 0.0, "map": {}}


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


def _valid_tag_text(x, tag_id=""):
    s = str(x or "").strip()
    if not s or s == str(tag_id or "").strip():
        return ""
    if s in ("⚠️ Có tag", "Có tag"):
        return ""
    if len(s) == 36 and s.count("-") == 4:
        return ""
    if s.lower() in ("none", "null", "false"):
        return ""
    return s


def _raw_tag_name(v):
    """Cố đọc tên tag nếu Partner API có field phụ; nếu không có thì trả rỗng."""
    tid = v.get("tagId") or v.get("tag_id")
    for k in ("tagName", "tag_name", "tagLabel", "tag_label", "tagTitle", "tag_title"):
        got = _valid_tag_text(v.get(k), tid)
        if got:
            return got
    for k in ("tag", "tagInfo", "tag_info", "videoTag", "video_tag"):
        obj = v.get(k)
        if isinstance(obj, dict):
            for kk in ("name", "title", "label", "text"):
                got = _valid_tag_text(obj.get(kk), tid)
                if got:
                    return got
        else:
            got = _valid_tag_text(obj, tid)
            if got:
                return got
    tags = v.get("tags")
    if isinstance(tags, list):
        names = []
        for obj in tags:
            if isinstance(obj, dict):
                got = next((_valid_tag_text(obj.get(kk), tid)
                            for kk in ("name", "title", "label", "text") if _valid_tag_text(obj.get(kk), tid)), "")
            else:
                got = _valid_tag_text(obj, tid)
            if got:
                names.append(got)
        if names:
            return " · ".join(names)
    return ""


def _flatten_tags_payload(payload):
    if isinstance(payload, list):
        return payload
    if not isinstance(payload, dict):
        return []
    for k in ("data", "items", "rows", "results", "tags"):
        v = payload.get(k)
        if isinstance(v, list):
            return v
        if isinstance(v, dict):
            got = _flatten_tags_payload(v)
            if got:
                return got
    return []


def _extract_tag_pair(row):
    if not isinstance(row, dict):
        return None, None
    tid = next((row.get(k) for k in ("id", "_id", "tagId", "tag_id", "uuid", "value") if row.get(k)), None)
    name = next((_valid_tag_text(row.get(k), tid)
                 for k in ("name", "title", "label", "text", "tagName", "tag_name") if _valid_tag_text(row.get(k), tid)), "")
    return (str(tid).strip(), name) if tid and name else (None, None)


def _fetch_tag_names():
    """Đọc danh sách tag DHN để map tagId -> tên tag (UI DHN dùng API /tag)."""
    now = time.monotonic()
    if now - float(_TAG_CACHE.get("ts") or 0) < 3600:
        return dict(_TAG_CACHE.get("map") or {})
    key = _key()
    out = {}
    if key:
        headers = {"x-api-key": key}
        urls = [
            "https://backend.dhn.io.vn/dpm/v1/partner/tag",
            "https://backend.dhn.io.vn/dpm/v1/partner/tags",
            "https://backend.dhn.io.vn/dpm/v1/tag",
            "https://be.dhn.io.vn/dpm/v1/tag",
        ]
        for url in urls:
            try:
                _throttle()
                r = requests.get(url, headers=headers, timeout=15)
                if r.status_code != 200:
                    continue
                for row in _flatten_tags_payload(r.json()):
                    tid, name = _extract_tag_pair(row)
                    if tid and name:
                        out[tid] = name
                if out:
                    break
            except Exception:
                pass
    _TAG_CACHE["ts"], _TAG_CACHE["map"] = now, out
    return dict(out)


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
                    "tag_name": _raw_tag_name(v),
                    "staff": ((v.get("user") or {}).get("firstName") or "").strip()})
    return out


# tagId (UUID) -> TÊN TAG trên app đóng hàng. Partner API CHỈ trả tagId, KHÔNG trả tên tag,
# nên phải map thủ công. Bổ sung/sửa tên trong Streamlit secrets (không cần đổi code):
#   [dohana.tags]
#   "2380d014-46be-4a1b-a549-a6dac57904d8" = "Khách tráo!"
_TAG_NAMES = {
    "2380d014-46be-4a1b-a549-a6dac57904d8": "Khách tráo!",
}


def _tag_name(tag_id, fallback=""):
    """Trả tên tag để hiển thị. Chưa map được tagId thì hiện rõ id để không còn chung chung."""
    fb = _valid_tag_text(fallback, tag_id)
    if fb:
        return fb
    if not tag_id:
        return ""
    _tid = str(tag_id).strip()
    try:
        ov = dict(st.secrets["dohana"]["tags"])
        if _tid in ov and ov[_tid]:
            return ov[_tid]
    except Exception:
        pass
    if _tid in _TAG_NAMES:
        return _TAG_NAMES[_tid]
    api_tags = _fetch_tag_names()
    if _tid in api_tags:
        return api_tags[_tid]
    return f"⚠️ Tag chưa map tên (id {_tid[:8]})"


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
        # Dohana giới hạn 10 req/s (xác nhận từ Dohana). _throttle() giữ ~3/s → thừa dưới 10/s.
        # 429 → thử lại TỐI ĐA 1 lần (ít đấm lại để key đang bị phạt hồi nhanh; kho lưu phục vụ đọc).
        for _try in range(2):
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
            "tag": _tag_name(v.get("tagId"), _raw_tag_name(v)),
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
