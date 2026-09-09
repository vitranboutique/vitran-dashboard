"""sapo_cache.py — KHO ĐỆM đơn hàng / đơn hoàn + ĐỒNG BỘ TĂNG DẦN.

Vì sao có file này (Sapo cảnh báo 08/09/2026):
    "Ứng dụng phía KH đang gọi API quét TOÀN BỘ dữ liệu đơn hàng và đơn hoàn từ trước đến nay,
     lặp lại nhiều lần… gây tốn tài nguyên hệ thống → kỹ thuật đã chặn một số IP."

Cách cũ: mỗi lượt quét nền phân trang `orders.json` / `order_returns.json` TỪ ĐẦU (tới 240 trang,
hàng chục nghìn bản ghi) dù dữ liệu thay đổi trong ngày chỉ vài trăm dòng.

Cách mới (đúng như Sapo hướng dẫn): giữ một BẢN SAO trên Gist, mỗi lượt chỉ hỏi phần MỚI/ĐỔI:
    GET /admin/orders/search.json?modified_on_min=…&modified_on_max=…
    GET /admin/order_returns/search.json?modified_on_min=…&modified_on_max=…
rồi ghi đè các bản ghi đó vào kho. Báo cáo đọc từ kho, KHÔNG quét lại lịch sử nữa.

Kho nén gzip+base64 để vừa Gist (bản ghi đơn hàng rất nặng).
"""
from __future__ import annotations

import base64
import gzip
import json
import os
import time
from datetime import datetime, timedelta, timezone

import requests

# picklog kéo theo streamlit — trên GitHub Actions KHÔNG có streamlit, nên chỉ import khi
# chạy trong app; ngoài runner thì đọc/ghi Gist trực tiếp bằng requests + GITHUB_TOKEN.
try:
    import picklog  # type: ignore
except Exception:          # ModuleNotFoundError: streamlit (runner) hoặc lỗi khác
    picklog = None

_API = "https://api.github.com"
_ANCHOR_FILE = "vitran_picklog.json"     # gist chứa file này là kho chung của app
_GID_CACHE = ""


def _token() -> str:
    return os.environ.get("GITHUB_TOKEN") or os.environ.get("GIST_TOKEN") or ""


def _hdr() -> dict:
    return {"Authorization": f"Bearer {_token()}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28"}


def _gid() -> str:
    """Tìm gist chứa kho chung (cache trong phiên)."""
    global _GID_CACHE
    if _GID_CACHE:
        return _GID_CACHE
    if not _token():
        return ""
    for page in range(1, 6):
        r = requests.get(f"{_API}/gists", headers=_hdr(),
                         params={"per_page": 100, "page": page}, timeout=30)
        r.raise_for_status()
        rows = r.json()
        if not rows:
            break
        for g in rows:
            if _ANCHOR_FILE in (g.get("files") or {}):
                _GID_CACHE = str(g.get("id") or "")
                return _GID_CACHE
    return ""


def _read_file(fname, _tries: int = 3):
    """Đọc 1 file trong kho. THỬ LẠI vài lượt: đọc hụt 1 mảnh là kho bị THIẾU NGÀY mà
    không ai biết, rồi báo cáo lại đi quét thẳng Sapo cả tháng (từng xảy ra 09/09/2026)."""
    for _i in range(max(1, int(_tries))):
        d = _read_file_once(fname)
        if d is not None:
            return d
        if _i + 1 < _tries:
            time.sleep(1.5 * (_i + 1))
    return None


def _read_file_once(fname):
    if picklog is not None and getattr(picklog, "configured", lambda: False)():
        return picklog._read_gist_file(fname)
    gid = _gid()
    if not gid:
        return None
    r = requests.get(f"{_API}/gists/{gid}", headers=_hdr(), timeout=30)
    if r.status_code != 200:
        return None
    f = (r.json().get("files") or {}).get(fname) or {}
    content = f.get("content") or ""
    if f.get("truncated") and f.get("raw_url"):      # file lớn → tải bản raw
        rr = requests.get(f["raw_url"], headers=_hdr(), timeout=60)
        if rr.status_code == 200:
            content = rr.text
    try:
        d = json.loads(content) if content else None
        return d if isinstance(d, dict) else None
    except Exception:
        return None


def _write_file(fname, data) -> bool:
    if picklog is not None and getattr(picklog, "configured", lambda: False)():
        return bool(picklog._write_gist_file(fname, data))
    gid = _gid()
    if not gid:
        return False
    body = {"files": {fname: {"content": json.dumps(data, ensure_ascii=False)}}}
    r = requests.patch(f"{_API}/gists/{gid}", headers=_hdr(), data=json.dumps(body), timeout=120)
    return r.status_code == 200

ORDERS_FILE = "vitran_cache_orders.json"
RETURNS_FILE = "vitran_cache_returns.json"

# Giữ bao nhiêu ngày trong kho (theo created_on). Đơn hàng nặng nên giữ ngắn hơn;
# đơn hoàn cần cả năm cho bảng Cần KN.
ORDERS_KEEP_DAYS = int(os.environ.get("CACHE_ORDER_DAYS") or 120)  # phủ báo cáo ngày, tổng hợp 30 ngày VÀ dự đoán SX 3 tháng
RETURNS_KEEP_DAYS = int(os.environ.get("CACHE_RETURN_DAYS") or 400)
# Lùi lại vài phút mỗi lần đồng bộ để không lọt bản ghi sửa ngay lúc giao thời.
OVERLAP_MIN = 10
PAGE = 250


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _iso_z(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _pack(rows: dict, synced_until: str) -> dict:
    raw = json.dumps(rows, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return {
        "synced_until": synced_until,
        "count": len(rows),
        "at": (_now_utc() + timedelta(hours=7)).strftime("%H:%M %d/%m/%Y"),
        "raw_kb": len(raw) // 1024,
        "gz": base64.b64encode(gzip.compress(raw, 6)).decode("ascii"),
    }


def _unpack(blob) -> tuple[dict, str]:
    if not isinstance(blob, dict):
        return {}, ""
    gz = blob.get("gz")
    if not gz:
        return {}, ""
    try:
        rows = json.loads(gzip.decompress(base64.b64decode(gz)).decode("utf-8"))
        return (rows if isinstance(rows, dict) else {}), str(blob.get("synced_until") or "")
    except Exception:
        return {}, ""


def _orders_shard(month: str) -> str:
    """Đơn hàng nhiều gấp ~5 lần phiếu trả → chia kho theo THÁNG cho vừa Gist."""
    return f"vitran_cache_orders_{month}.json"


def _months_back(n_days: int) -> list[str]:
    out, d = [], _now_utc()
    while True:
        m = d.strftime("%Y-%m")
        if m not in out:
            out.append(m)
        d -= timedelta(days=28)
        if (_now_utc() - d).days > n_days + 31:
            break
    return out


def load(kind: str) -> tuple[dict, str]:
    """kind = 'orders' | 'returns' → ({id: record}, synced_until)."""
    if kind != "orders":
        return _unpack(_read_file(RETURNS_FILE))
    rows, synced = {}, ""
    for m in _months_back(ORDERS_KEEP_DAYS):
        part, at = _unpack(_read_file(_orders_shard(m)))
        rows.update(part)
        if at > synced:
            synced = at
    return rows, synced


def save(kind: str, rows: dict, synced_until: str) -> bool:
    if kind != "orders":
        return bool(_write_file(RETURNS_FILE, _pack(rows, synced_until)))
    by_month: dict[str, dict] = {}
    for rid, r in rows.items():
        by_month.setdefault(str((r or {}).get("created_on") or "")[:7] or "unknown", {})[rid] = r
    ok = True
    for m, part in by_month.items():
        if not _write_file(_orders_shard(m), _pack(part, synced_until)):
            ok = False
    return ok


def _prune(rows: dict, keep_days: int) -> int:
    """Bỏ bản ghi quá cũ theo created_on để kho không phình mãi."""
    lo = (_now_utc() - timedelta(days=keep_days)).strftime("%Y-%m-%d")
    drop = [k for k, v in rows.items() if str((v or {}).get("created_on") or "")[:10] < lo]
    for k in drop:
        rows.pop(k, None)
    return len(drop)


def sync(kind: str, fetch_json, *, backfill_days: int | None = None, max_pages: int = 60,
         log=print) -> dict:
    """Đồng bộ TĂNG DẦN 1 loại dữ liệu. Kho trống → nạp lần đầu theo backfill_days.

    Trả về {"new": n, "total": n, "pages": n, "from": iso, "to": iso}."""
    path = "/admin/orders/search.json" if kind == "orders" else "/admin/order_returns/search.json"
    key = "orders" if kind == "orders" else "order_returns"
    keep = ORDERS_KEEP_DAYS if kind == "orders" else RETURNS_KEEP_DAYS
    rows, synced_until = load(kind)

    now = _now_utc()
    if backfill_days:      # nêu rõ số ngày = ÉP nạp lại phạm vi đó (mở rộng kho), kể cả khi
        synced_until = ""  # kho đã có dữ liệu — dùng khi tăng số ngày giữ.
    if synced_until:
        try:
            start = datetime.strptime(synced_until, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        except Exception:
            start = now - timedelta(days=2)
        start -= timedelta(minutes=OVERLAP_MIN)
    else:
        start = now - timedelta(days=int(backfill_days if backfill_days is not None else keep))
        log(f"  [{kind}] kho TRỐNG → nạp lần đầu {(now - start).days} ngày")

    _min, _max = _iso_z(start), _iso_z(now)
    new_rows, pages = 0, 0
    for p in range(1, max_pages + 1):
        chunk = (fetch_json(path, limit=PAGE, page=p,
                            modified_on_min=_min, modified_on_max=_max) or {}).get(key) or []
        pages += 1
        for r in chunk:
            rid = str((r or {}).get("id") or "")
            if rid:
                rows[rid] = r
                new_rows += 1
        if len(chunk) < PAGE:
            break
    dropped = _prune(rows, keep)
    ok = save(kind, rows, _max)
    log(f"  [{kind}] {new_rows} bản ghi mới/đổi · {pages} trang · kho {len(rows)} "
        f"(bỏ {dropped} quá {keep} ngày) · lưu {'OK' if ok else 'LỖI'}")
    return {"new": new_rows, "total": len(rows), "pages": pages, "from": _min, "to": _max, "saved": ok}


# ── ĐỌC BÁO CÁO TỪ KHO ĐỆM ─────────────────────────────────────────────────────────────
# Giữ nguyên toàn bộ logic trong sapo_logic (2.700 dòng) bằng cách thay hàm gọi API: các
# lệnh phân trang orders.json / order_returns.json sẽ được phục vụ TỪ KHO, không ra Sapo.
# Lệnh khác (lấy 1 đơn, ghi chú…) vẫn đi thẳng API thật.
def _day(v) -> str:
    """'2026-09-01T00:00:00+07:00' → '2026-09-01' (so sánh theo NGÀY cho chắc múi giờ)."""
    return str(v or "")[:10]


def _out_of_range(params, cache_from: str, allow_unbounded: bool) -> bool:
    """Câu hỏi vượt quá phạm vi kho → phải ra API thật, không được trả số thiếu.

    allow_unbounded=True (đơn hoàn): kho giữ hơn 1 năm, mà mọi báo cáo đơn hoàn chỉ tính
    trong NĂM NAY nên hỏi không kèm mốc ngày vẫn phục vụ được từ kho.
    allow_unbounded=False (đơn hàng): kho chỉ giữ ít ngày → hỏi trống mốc là muốn cả lịch sử."""
    if not cache_from:
        return True
    cmin = _day(params.get("created_on_min"))
    if not cmin:
        return not allow_unbounded
    return cmin < cache_from


def make_cached_fetch_json(real_fetch, *, log=print):
    orders, o_at = load("orders")
    returns, r_at = load("returns")
    o_list = sorted(orders.values(), key=lambda r: int((r or {}).get("id") or 0), reverse=True)
    r_list = sorted(returns.values(), key=lambda r: int((r or {}).get("id") or 0), reverse=True)
    # PHẠM VI kho: ngày cũ nhất đang giữ. Ai hỏi cũ hơn mốc này mà mình vẫn trả từ kho là
    # trả THIẾU số mà không ai biết → phải đẩy sang API thật.
    o_from = min((_day(r.get("created_on")) for r in o_list if r.get("created_on")), default="")
    r_from = min((_day(r.get("created_on")) for r in r_list if r.get("created_on")), default="")
    log(f"  kho đệm: {len(o_list)} đơn (từ {o_from}, đồng bộ tới {o_at}) · "
        f"{len(r_list)} phiếu trả (từ {r_from}, tới {r_at})")

    def _filter(rows, params):
        st = str(params.get("status") or "").lower()
        cmin, cmax = _day(params.get("created_on_min")), _day(params.get("created_on_max"))
        out = []
        for r in rows:
            if st and str((r or {}).get("status") or "").lower() != st:
                continue
            d = _day((r or {}).get("created_on"))
            if cmin and d < cmin:
                continue
            if cmax and d > cmax:
                continue
            out.append(r)
        return out

    def fetch(path, **params):
        if path == "/admin/orders.json":
            # ĐƠN ĐANG MỞ (cần nhặt) luôn hỏi thẳng Sapo: chỉ vài chục đơn = 1 request, mà
            # kho chỉ giữ ngần ấy ngày nên đơn mở lâu ngày có thể lọt — NV giao hàng theo bảng
            # này, thiếu 1 đơn là thiếu 1 kiện, không đánh đổi được.
            if str(params.get("status") or "").lower() == "open":
                return real_fetch(path, **params)
            if _out_of_range(params, o_from, False):
                return real_fetch(path, **params)
            rows, key = _filter(o_list, params), "orders"
        elif path == "/admin/order_returns.json":
            if _out_of_range(params, r_from, True):
                return real_fetch(path, **params)
            rows, key = _filter(r_list, params), "order_returns"
        else:
            return real_fetch(path, **params)
        limit = max(1, int(params.get("limit") or PAGE))
        page = max(1, int(params.get("page") or 1))
        return {key: rows[(page - 1) * limit: page * limit]}

    return fetch


# Kho phải phủ ít nhất ngần này ngày mới được tin. Đọc hụt vài mảnh → chỉ còn vài ngày,
# lúc đó mọi câu hỏi cũ hơn đều rơi ra API thật và quét lại cả tháng — thà nói thẳng
# "kho chưa đủ" để bên gọi biết đường.
MIN_ORDER_DAYS = 60


def cache_ready() -> tuple[bool, str]:
    """Kho đã có dữ liệu chưa (để quyết định dùng kho hay gọi Sapo như cũ)."""
    o, o_at = load("orders")
    r, r_at = load("returns")
    if not o or not r:
        return False, f"kho chưa đủ: {len(o)} đơn / {len(r)} phiếu trả"
    o_from = min((_day(x.get("created_on")) for x in o.values() if x.get("created_on")), default="")
    days = 0
    try:
        _f = datetime.strptime(o_from, "%Y-%m-%d").date()
        days = ((datetime.now(timezone.utc) + timedelta(hours=7)).date() - _f).days
    except Exception:
        days = 0
    info = (f"{len(o)} đơn (từ {o_from} = {days} ngày, tới {o_at}) · "
            f"{len(r)} phiếu trả (tới {r_at})")
    if days < MIN_ORDER_DAYS:
        return False, "PHỦ THIẾU NGÀY (đọc hụt mảnh kho?) — " + info
    return True, info
