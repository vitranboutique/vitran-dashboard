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
from datetime import datetime, timedelta, timezone

import picklog

ORDERS_FILE = "vitran_cache_orders.json"
RETURNS_FILE = "vitran_cache_returns.json"

# Giữ bao nhiêu ngày trong kho (theo created_on). Đơn hàng nặng nên giữ ngắn hơn;
# đơn hoàn cần cả năm cho bảng Cần KN.
ORDERS_KEEP_DAYS = int(os.environ.get("CACHE_ORDER_DAYS") or 60)
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


def load(kind: str) -> tuple[dict, str]:
    """kind = 'orders' | 'returns' → ({id: record}, synced_until)."""
    return _unpack(picklog._read_gist_file(ORDERS_FILE if kind == "orders" else RETURNS_FILE))


def save(kind: str, rows: dict, synced_until: str) -> bool:
    return bool(picklog._write_gist_file(ORDERS_FILE if kind == "orders" else RETURNS_FILE,
                                         _pack(rows, synced_until)))


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


def make_cached_fetch_json(real_fetch, *, log=print):
    orders, o_at = load("orders")
    returns, r_at = load("returns")
    o_list = sorted(orders.values(), key=lambda r: int((r or {}).get("id") or 0), reverse=True)
    r_list = sorted(returns.values(), key=lambda r: int((r or {}).get("id") or 0), reverse=True)
    log(f"  kho đệm: {len(o_list)} đơn (đồng bộ tới {o_at}) · {len(r_list)} phiếu trả (tới {r_at})")

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
            rows, key = _filter(o_list, params), "orders"
        elif path == "/admin/order_returns.json":
            rows, key = _filter(r_list, params), "order_returns"
        else:
            return real_fetch(path, **params)
        limit = max(1, int(params.get("limit") or PAGE))
        page = max(1, int(params.get("page") or 1))
        return {key: rows[(page - 1) * limit: page * limit]}

    return fetch


def cache_ready() -> tuple[bool, str]:
    """Kho đã có dữ liệu chưa (để quyết định dùng kho hay gọi Sapo như cũ)."""
    o, o_at = load("orders")
    r, r_at = load("returns")
    if not o or not r:
        return False, f"kho chưa đủ: {len(o)} đơn / {len(r)} phiếu trả"
    return True, f"{len(o)} đơn (tới {o_at}) · {len(r)} phiếu trả (tới {r_at})"
