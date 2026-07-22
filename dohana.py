"""
dohana.py — Lấy VIDEO ĐÓNG HÀNG từ Dohana (dhn.io.vn) qua Partner API.

API v2 (keyset CURSOR): GET https://openapi.dhn.io.vn/dpm/v1/partner/v2/video/search  (header x-api-key)
  params: cursor (ISO timestamp bản ghi cuối trang trước), limit (≤1000), type (package/inbound/outbound/prepare), orderCode, status[]
  response: {data:[...], nextCursor, hasNextPage, pageSize}
Mỗi video: orderCode (= mã vận đơn), type, createdAt, slug, duration, status, tagId, user...
Domain cũ be/backend.dhn.io.vn (page/limit, "Legacy") NGƯNG sau 17/08/2026 → đã chuyển openapi.dhn.io.vn + cursor.
Key đặt trong Streamlit secrets:  [dohana]\n  x_api_key = "..."
"""
from collections import Counter
from datetime import datetime, timedelta, timezone
import time
import threading
import unicodedata

import requests
import streamlit as st

_API_ROOT = "https://openapi.dhn.io.vn/dpm/v1"
_BASE = f"{_API_ROOT}/partner/v2/video/search"
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


def _video_slug(v):
    """Return the public Dohana tracking slug if the API includes one."""
    for k in ("slug", "videoSlug", "video_slug", "trackingSlug", "tracking_slug"):
        s = str((v or {}).get(k) or "").strip()
        if s:
            return s
    return ""


def _video_link(v):
    """Build a stable Dohana video URL from direct URL fields or the video slug."""
    for k in ("url", "link", "videoUrl", "video_url", "trackingUrl", "tracking_url"):
        s = str((v or {}).get(k) or "").strip()
        if s.startswith(("http://", "https://")):
            return s
    slug = _video_slug(v)
    if not slug:
        return ""
    if slug.startswith(("http://", "https://")):
        return slug
    slug = slug.lstrip("/")
    if slug.startswith("tracking/"):
        return f"https://dhn.io.vn/{slug}"
    return f"https://dhn.io.vn/tracking/{slug}"


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
            f"{_API_ROOT}/partner/tag",
            f"{_API_ROOT}/partner/tags",
            f"{_API_ROOT}/tag",
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
    {code, type, status, date(VN yyyy-mm-dd), time(VN HH:MM:SS), dur(giây), tag_id, slug, link}."""
    seen, out, idx = set(), [], {}
    for v in sorted(vids, key=lambda x: str(x.get("createdAt") or ""), reverse=True):
        oc = v.get("orderCode")
        if not oc:
            continue
        tag_id = v.get("tagId")
        tag_name = _raw_tag_name(v)
        if oc in seen:
            rec = idx.get(oc) or {}
            # Nếu mã này có clip/tag cũ hơn, vẫn giữ tag để kho không bỏ sót tranh chấp.
            if tag_id and not rec.get("tag_id"):
                rec["tag_id"] = tag_id
            if tag_name and not rec.get("tag_name"):
                rec["tag_name"] = tag_name
            slug = _video_slug(v)
            link = _video_link(v)
            if slug and not rec.get("slug"):
                rec["slug"] = slug
            if link and not rec.get("link"):
                rec["link"] = link
            continue
        seen.add(oc)
        dur = v.get("duration")
        rec = {"code": oc, "type": typ, "status": v.get("status"),
               "date": str(_vnd(v.get("createdAt")) or ""),
               "time": _vn_time(v.get("createdAt")),
               "dur": int(dur) if isinstance(dur, (int, float)) else None,
               "tag_id": tag_id,
               "tag_name": tag_name,
               "slug": _video_slug(v),
               "link": _video_link(v),
               "staff": ((v.get("user") or {}).get("firstName") or "").strip()}
        out.append(rec)
        idx[oc] = rec
    return out


def _active_video(v):
    s = str((v or {}).get("status") or "").strip().lower()
    if not s:
        return True
    compact = "".join(ch for ch in unicodedata.normalize("NFKD", s) if not unicodedata.combining(ch))
    compact = "".join(ch for ch in compact.upper() if ch.isalnum())
    return not any(token in compact for token in ("DELETED", "REMOVED", "DAXOA", "XOA"))


# tagId (UUID) -> TÊN TAG trên app đóng hàng. Partner API CHỈ trả tagId, KHÔNG trả tên tag,
# nên phải map thủ công. Bổ sung/sửa tên trong Streamlit secrets (không cần đổi code):
#   [dohana.tags]
#   "2380d014-46be-4a1b-a549-a6dac57904d8" = "Khách tráo!"
_TAG_NAMES = {
    # Lấy trực tiếp từ Dohana /dpm/v1/tag (UUID → tên nhãn video đóng/khui hàng).
    "0768ccc3-871c-4070-afe5-68865e0ca10d": "Đóng thiếu 2 sp",
    "c781dc26-5d67-4b18-b80e-c7dca1d57d82": "Đóng thiếu 1 sp",
    "4c975c2c-7707-433f-8b07-e84b26a3e610": "Đóng thiếu sp",
    "8b5216a5-727b-4f74-9f03-6e0531bf6cfb": "Đóng sai sp",
    "2380d014-46be-4a1b-a549-a6dac57904d8": "Khách tráo hàng",
    "1b2b16bb-7dea-41e8-9af9-257a16a5ffab": "Trả hàng thiếu",
    "45433c95-4b29-49a7-a981-69f559f2f0eb": "Đã sử dụng",
    "5b863771-0b22-4bcd-9922-472b9790862c": "Hàng hư hỏng",
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
_RATE_LOCK = threading.Lock()
_COOLDOWN_UNTIL = [0.0]


def _throttle(min_gap=1.1):
    """Giãn nhịp TOÀN TIẾN TRÌNH, kể cả nhiều session/luồng Streamlit cùng tải."""
    with _RATE_LOCK:
        now = time.monotonic()
        wait_for = max(
            0.0,
            min_gap - (now - _LAST_REQ[0]),
            _COOLDOWN_UNTIL[0] - now,
        )
        if wait_for:
            time.sleep(wait_for)
        _LAST_REQ[0] = time.monotonic()


def _note_rate_limit(seconds=60.0):
    """Đặt thời gian nghỉ dùng chung khi bất kỳ request nào nhận 429."""
    try:
        seconds = max(30.0, min(float(seconds or 60.0), 120.0))
    except Exception:
        seconds = 60.0
    with _RATE_LOCK:
        _COOLDOWN_UNTIL[0] = max(_COOLDOWN_UNTIL[0], time.monotonic() + seconds)


def _fetch_videos(typ: str, cutoff_date, max_pages: int):
    """Lấy video theo type bằng cursor tới khi createdAt < cutoff_date. Khử trùng id."""
    key = _key()
    if not key:
        return None
    headers = {"x-api-key": key}
    vids = []
    cursor = None
    seen_cursors = set()
    # p=custom tránh giới hạn mặc định 30 ngày khi app cần đồng bộ 35 ngày.
    # Lấy dư một ngày UTC; kết quả cuối vẫn được lọc theo ngày Việt Nam.
    from_iso = f"{cutoff_date - timedelta(days=1)}T00:00:00Z"
    # Dùng thời điểm hiện tại (thay vì 00:00 ngày mai cố định cả ngày) để URL request
    # thay đổi theo mỗi lần refresh, tránh lớp cache phía Dohana trả snapshot cũ nhiều giờ.
    to_iso = (datetime.now(timezone.utc) + timedelta(minutes=1)).isoformat(
        timespec="seconds"
    ).replace("+00:00", "Z")
    for page_no in range(max_pages):
        rows = None
        payload = {}
        # Gặp 429 thì dừng ngay và nghỉ dài; gọi lại tức thời chỉ kéo dài thời gian khóa key.
        for _try in range(1):
            _throttle()
            try:
                params = {"limit": 1000, "type": typ, "p": "custom",
                          "from": from_iso, "to": to_iso}
                if cursor:
                    params["cursor"] = cursor
                r = requests.get(_BASE, params=params,
                                 headers=headers, timeout=20)
            except Exception:
                break
            if r.status_code == 429:
                _note_rate_limit(r.headers.get("Retry-After") or 60)
                break
            if r.status_code == 200:
                payload = r.json() or {}
                rows = payload.get("data", [])
            break                        # thành công / lỗi khác → thoát vòng thử lại
        if rows is None:                 # 429 / lỗi mạng
            if page_no == 0:             # trang ĐẦU fail → Dohana KHÔNG sẵn sàng → trả None
                return None              # dùng kho dự phòng, chờ hết cooldown rồi thử lại
            break                        # trang sau: giữ video đã lấy
        if not rows:
            break
        vids += rows
        last = _vnd(rows[-1].get("createdAt"))
        if last and last < cutoff_date:
            break
        next_cursor = payload.get("nextCursor")
        if not payload.get("hasNextPage") or not next_cursor or next_cursor in seen_cursors:
            break
        seen_cursors.add(next_cursor)
        cursor = next_cursor
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
    active_vids = [v for v in vids if _active_video(v)]
    win = [v for v in active_vids if _in_window(v, cutoff, tdate)]
    cnt = Counter(v.get("orderCode") for v in win if v.get("orderCode"))
    today_codes = {v.get("orderCode") for v in active_vids
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
            "slug": _video_slug(v),
            "link": _video_link(v),
            "staff": ((v.get("user") or {}).get("firstName") or "").strip(),   # NV quay clip
        }
    return {
        "total": sum(1 for v in active_vids if _vnd(v.get("createdAt")) == tdate),
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
    active_vids = [v for v in vids if _active_video(v)]
    day_vids = [v for v in active_vids if _vnd(v.get("createdAt")) == tdate]
    codes = Counter(v.get("orderCode") for v in day_vids if v.get("orderCode"))
    return {
        "total": len(day_vids),
        "codes": dict(codes),
        "dup": {k: v for k, v in codes.items() if v >= 2},
        "match": {v.get("orderCode") for v in active_vids
                  if v.get("orderCode") and _in_window(v, cutoff, tdate)},
        # METADATA MỌI video đóng hàng (lưu cả năm): trạng thái·ngày·giờ·thời lượng·tag.
        # Đơn CÓ tag (đóng thiếu SP) → mục KHÔNG CẦN KN.
        "records": _records_from(vids, "package"),
    }
