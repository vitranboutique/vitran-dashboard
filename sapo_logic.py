"""
sapo_logic.py — Logic nghiệp vụ "Báo cáo sáng" (dịch từ script JS gốc).

Mọi hàm nhận `fetch_json` (lấy từ sapo_client.make_fetch_json) làm tham số
=> dễ test, tách rời tầng mạng. Cuối file có dữ liệu DEMO cho chế độ xem thử.

QUY TẮC NGHIỆP VỤ (bắt buộc giữ đúng):
  1. Múi giờ Sapo = UTC. Giờ VN = UTC+7. "Hôm nay" = từ 00:00 VN = 17:00 UTC hôm trước.
  2. Chờ xác nhận  = status=open  & issue_status='pending'.
  3. Đơn hủy       = status=cancelled & có fulfillments & cancelled_on trong 7 ngày.
  4. LOẠI TRỪ kháng nghị thành công: order.id thuộc tập order_id của order_returns
     có status='canceled' -> bỏ khỏi danh sách đơn hủy / đơn trả.
  5. Đóng gói: packed_status='packed' = đã đóng gói (kho phải lấy lại) · khác = chưa.
"""
from __future__ import annotations

import io
import json
import os
from datetime import datetime, timedelta, timezone

SNAPSHOT_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "snapshot.json")


# ───────────────────────── Helpers thời gian ─────────────────────────

def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _vn_day_bounds():
    """Trả về (today_start, yest_start) dạng ISO không zone, theo mốc 00:00 VN."""
    today_utc = _now_utc().replace(hour=17, minute=0, second=0, microsecond=0)
    today_start = (today_utc - timedelta(days=1)).isoformat().replace("+00:00", "")
    yest_start = (today_utc - timedelta(days=2)).isoformat().replace("+00:00", "")
    return today_start, yest_start


# ───────────────────────── 1. Chờ xác nhận ─────────────────────────

def get_pending(fetch_json) -> dict:
    orders = fetch_json("/admin/orders.json", limit=250, page=1, status="open")["orders"]
    pending = [o for o in orders if o.get("issue_status") == "pending"]

    today_start, yest_start = _vn_day_bounds()

    sources: dict[str, int] = {}
    carriers: dict[str, int] = {}
    stores: dict[str, int] = {}
    sku_map: dict[str, dict] = {}
    total_items = fast = express = 0

    for o in pending:
        src = o.get("source_name") or "Khác"
        sources[src] = sources.get(src, 0) + 1

        cd = o.get("channel_definition") or {}
        store = cd.get("branch_name") or src or "Khác"
        stores[store] = stores.get(store, 0) + 1

        sl = (o.get("shipping_lines") or [{}])[0]
        carrier = sl.get("carrier_name") or sl.get("title") or "Chưa rõ"
        if sl.get("code") == "sapo_fulfillment_by_seller" and not sl.get("carrier_name"):
            carrier = "NB tự VC"
        carriers[carrier] = carriers.get(carrier, 0) + 1

        if o.get("shipment_category") == "express":
            express += 1
        else:
            fast += 1

        for li in (o.get("line_items") or []):
            sku = li.get("sku") or "N/A"
            m = sku_map.setdefault(sku, {"sku": sku, "name": li.get("title") or sku, "qty": 0, "orders": 0})
            m["qty"] += li.get("quantity", 0)
            m["orders"] += 1
            total_items += li.get("quantity", 0)

    return {
        "total": len(pending),
        "today": sum(1 for o in pending if o.get("created_on", "") >= today_start),
        "yesterday": sum(1 for o in pending if yest_start <= o.get("created_on", "") < today_start),
        "total_items": total_items,
        "sources": sources,
        "stores": stores,
        "carriers": carriers,
        "fast": fast,
        "express": express,
        "skus": sorted(sku_map.values(), key=lambda x: -x["qty"]),
        "sku_count": len(sku_map),
    }


# ───────────────────── 2. Đã đẩy VC → hủy (7 ngày) ─────────────────────

def get_appealed_order_ids(fetch_json, days: int = 30) -> set:
    """order_id có phiếu trả status='canceled' (kháng nghị thành công)."""
    cutoff = (_now_utc() - timedelta(days=days)).isoformat()
    ids: set = set()
    for p in range(1, 21):
        rows = fetch_json("/admin/order_returns.json", limit=250, page=p).get("order_returns", [])
        if not rows:
            break
        ids.update(x["order_id"] for x in rows if x.get("status") == "canceled")
        if rows[-1].get("created_on", "") < cutoff:  # returns sắp xếp mới->cũ
            break
    return ids


def get_cancelled(fetch_json, days: int = 7, scan_days: int = 30) -> dict:
    week_ago = (_now_utc() - timedelta(days=days)).isoformat()
    # Đơn hủy sắp xếp theo created_on mới->cũ. Đơn hủy trong 7 ngày gần như chắc
    # chắn được tạo trong ~30 ngày gần đây -> dừng quét khi đã lùi quá mốc này.
    scan_cutoff = (_now_utc() - timedelta(days=scan_days)).isoformat()
    appealed = get_appealed_order_ids(fetch_json)

    all_orders = []
    for p in range(1, 26):
        rows = fetch_json("/admin/orders.json", limit=250, page=p, status="cancelled").get("orders", [])
        if not rows:
            break
        all_orders += [
            o for o in rows
            if o.get("fulfillments")
            and o.get("cancelled_on", "") >= week_ago
            and o.get("id") not in appealed
        ]
        if rows[-1].get("created_on", "") < scan_cutoff:  # đã lùi quá 30 ngày -> dừng
            break

    packed = [o for o in all_orders if o["fulfillments"][0].get("packed_status") == "packed"]
    not_packed = [o for o in all_orders if o["fulfillments"][0].get("packed_status") != "packed"]
    return {
        "total": len(all_orders),
        "excluded_appeal": len(appealed),
        "packed": packed,
        "not_packed": not_packed,
    }


# ───────────────────── Phiếu nhặt hàng (tự kéo từ Sapo) ─────────────────────

def _parse_vn(iso):
    """Parse ISO UTC (có/không Z) -> datetime giờ VN (+7)."""
    if not iso:
        return None
    s = str(iso).replace("Z", "").replace("+00:00", "").split(".")[0]
    try:
        return datetime.fromisoformat(s) + timedelta(hours=7)
    except Exception:
        return None


def _picking_deadline_vn(created_vn):
    """Hạn xác nhận: 18h ngày đặt; nếu đặt từ 18h trở đi -> 18h hôm sau."""
    cutoff = created_vn.replace(hour=18, minute=0, second=0, microsecond=0)
    return cutoff if created_vn < cutoff else cutoff + timedelta(days=1)


def _summarize_picking(orders):
    today = (_now_utc() + timedelta(hours=7)).date()
    channels, stores, carriers, sku = {}, {}, {}, {}
    total_qty = old = new = late = 0
    late_list = []
    for o in orders:
        cd = o.get("channel_definition") or {}
        ch = cd.get("main_name") or o.get("source_name") or "Khác"
        store = cd.get("branch_name") or ch or "Khác"
        sl = (o.get("shipping_lines") or [{}])[0]
        carrier = sl.get("carrier_name") or sl.get("title") or "Chưa rõ"
        channels[ch] = channels.get(ch, 0) + 1
        stores[store] = stores.get(store, 0) + 1
        carriers[carrier] = carriers.get(carrier, 0) + 1
        for li in (o.get("line_items") or []):
            s = li.get("sku") or "N/A"
            q = li.get("quantity", 0) or 0
            sku[s] = sku.get(s, 0) + q
            total_qty += q
        conf_vn = _parse_vn(o.get("confirmed_on"))
        cre_vn = _parse_vn(o.get("created_on"))
        if conf_vn:
            if conf_vn.date() == today:
                new += 1
            else:
                old += 1
            if cre_vn and conf_vn > _picking_deadline_vn(cre_vn):
                late += 1
                late_list.append(o.get("name"))
    srt = lambda d: dict(sorted(d.items(), key=lambda x: (-x[1], str(x[0]))))
    return {
        "total_orders": len(orders),
        "total_qty": total_qty,
        "sku_count": len(sku),
        "old": old, "new": new, "late": late, "late_list": late_list,
        "channels": srt(channels), "stores": srt(stores), "carriers": srt(carriers),
        "skus": sorted(sku.items(), key=lambda x: (-x[1], str(x[0]))),
    }


def get_picking(fetch_json, max_pages: int = 15) -> dict:
    """Đơn cần nhặt = chờ đóng gói (packing) + đã in phiếu giao hàng (shipping_label_slip_url).
    Tách hỏa tốc (express) / thường (còn lại)."""
    orders = []
    for p in range(1, max_pages + 1):
        rows = fetch_json("/admin/orders.json", limit=250, page=p, status="open").get("orders", [])
        if not rows:
            break
        orders += rows

    def f0(o):
        return (o.get("fulfillments") or [{}])[0]

    pick = [o for o in orders
            if f0(o).get("packed_status") == "packing"
            and f0(o).get("shipping_label_slip_url")]
    express = [o for o in pick if o.get("shipment_category") == "express"]
    normal = [o for o in pick if o.get("shipment_category") != "express"]
    return {
        "express": _summarize_picking(express),
        "normal": _summarize_picking(normal),
        "total": len(pick),
    }


# ───────────────────── Tổng quan điều hành (overview) ─────────────────────

def _vn_date_of(iso):
    d = _parse_vn(iso)
    return d.date() if d else None


def get_overview(fetch_json, days: int = 7) -> dict:
    """6 thẻ tổng + dữ liệu 3 biểu đồ (theo ngày / sàn / gian hàng) cho trang Tổng quan.
    Dùng count.json (nhanh) cho các con số tổng; tải đơn tuần để tính breakdown."""
    now_vn = _now_utc() + timedelta(hours=7)
    today = now_vn.date()
    yest = today - timedelta(days=1)
    week_start = today - timedelta(days=days - 1)

    def _iso(d, end=False):
        return d.isoformat() + ("T23:59:59+07:00" if end else "T00:00:00+07:00")

    def _count(cmin, cmax):
        try:
            return int(fetch_json("/admin/orders/count.json",
                                  created_on_min=cmin, created_on_max=cmax).get("count", 0))
        except Exception:
            return 0

    don_today = _count(_iso(today), _iso(today, True))
    don_yest = _count(_iso(yest), _iso(yest, True))
    don_week = _count(_iso(week_start), _iso(today, True))

    # Tải đơn tuần này để tính breakdown + biểu đồ
    orders, cmin = [], _iso(week_start)
    for p in range(1, 25):
        rows = fetch_json("/admin/orders.json", limit=250, page=p, created_on_min=cmin).get("orders", [])
        if not rows:
            break
        orders += rows
        last = _parse_vn(rows[-1].get("created_on"))
        if last and last.date() < week_start:
            break

    daily = {week_start + timedelta(days=i): {"don": 0, "sp": 0} for i in range(days)}
    sources, stores, sku_set = {}, {}, set()
    week_sp = today_sp = yest_sp = 0

    for o in orders:
        d = _vn_date_of(o.get("created_on"))
        if not d or d < week_start or d > today:
            continue
        sp = sum((li.get("quantity", 0) or 0) for li in (o.get("line_items") or []))
        for li in (o.get("line_items") or []):
            if li.get("sku"):
                sku_set.add(li["sku"])
        week_sp += sp
        if d in daily:
            daily[d]["don"] += 1
            daily[d]["sp"] += sp
        if d == today:
            today_sp += sp
        elif d == yest:
            yest_sp += sp
        src = o.get("source_name") or "Khác"
        sources[src] = sources.get(src, 0) + 1
        cd = o.get("channel_definition") or {}
        store = cd.get("branch_name") or src or "Khác"
        stores[store] = stores.get(store, 0) + 1

    # ---- PHỄU GIAO HÀNG HÔM NAY: quét đơn open theo TRẠNG THÁI HIỆN TẠI ----
    # Đếm theo NGÀY XÁC NHẬN / ĐÓNG GÓI / XUẤT VC (không phụ thuộc ngày tạo đơn).
    open_orders = []
    for p in range(1, 30):
        rows = fetch_json("/admin/orders.json", limit=250, page=p, status="open").get("orders", [])
        if not rows:
            break
        open_orders += rows

    cg = {"da_xac_nhan": 0, "da_dong": 0, "shipper_nhan": 0,
          "cho_giao": 0, "cho_moi": 0, "cho_sot": 0, "hoa_toc_cho": 0,
          "cho_packed": 0, "cho_chua_dong": 0}
    dvvc = {}
    al = {"conf_after18": 0, "late_confirm": 0, "express_pending": 0}

    for o in open_orders:
        f = (o.get("fulfillments") or [{}])[0]
        ss = f.get("shipment_status")
        is_express = o.get("shipment_category") == "express"
        conf_vn = _parse_vn(o.get("confirmed_on"))
        conf_d = conf_vn.date() if conf_vn else None

        # Đã xác nhận hôm nay (+ cảnh báo xác nhận sau 18h)
        if conf_d == today:
            cg["da_xac_nhan"] += 1
            if conf_vn.hour >= 18:
                al["conf_after18"] += 1
                _cre = _parse_vn(o.get("created_on"))
                if _cre and _cre.date() == today and _cre.hour < 18:
                    al["late_confirm"] += 1
        # Đã đóng hàng hôm nay / Shipper đã nhận (xuất VC) hôm nay
        if _vn_date_of(f.get("packed_on")) == today:
            cg["da_dong"] += 1
        if _vn_date_of(f.get("issued_on")) == today:
            cg["shipper_nhan"] += 1

        # Đang chờ giao = đã có vận đơn, shipper CHƯA LẤY (shipment_status=pending)
        if ss == "pending":
            cg["cho_giao"] += 1
            if conf_d == today:
                cg["cho_moi"] += 1       # mới: xác nhận hôm nay
            else:
                cg["cho_sot"] += 1       # sót: xác nhận hôm trước, xử lý hôm nay
            packed = f.get("packed_status") == "packed"
            cg["cho_packed" if packed else "cho_chua_dong"] += 1
            if is_express:
                cg["hoa_toc_cho"] += 1
                al["express_pending"] += 1
            car = (o.get("shipping_lines") or [{}])[0].get("carrier_name") or "NB tự VC"
            e = dvvc.setdefault(car, {"dvvc": car, "total": 0, "thuong": 0,
                                      "hoatoc": 0, "packed": 0, "chua_dong": 0})
            e["total"] += 1
            e["hoatoc" if is_express else "thuong"] += 1
            e["packed" if packed else "chua_dong"] += 1

    # ---- Đơn hủy sau đẩy VC (dùng get_cancelled) ----
    try:
        canc = get_cancelled(fetch_json)
        canc_orders = canc["packed"] + canc["not_packed"]
    except Exception:
        canc, canc_orders = {"total": 0}, []
    sku_canc, risk_value = {}, 0
    for o in canc_orders:
        for li in (o.get("line_items") or []):
            sku = li.get("sku") or "N/A"
            q = li.get("quantity", 0) or 0
            val = q * (li.get("price", 0) or 0)
            m = sku_canc.setdefault(sku, {"sku": sku, "qty": 0, "value": 0})
            m["qty"] += q
            m["value"] += val
            risk_value += val
    cancel = {
        "today": sum(1 for o in canc_orders if _vn_date_of(o.get("cancelled_on")) == today),
        "yest": sum(1 for o in canc_orders if _vn_date_of(o.get("cancelled_on")) == yest),
        "total7d": canc.get("total", 0),
        "risk_value": risk_value,
        "top_sku": sorted(sku_canc.values(), key=lambda x: -x["qty"])[:6],
    }

    srt = lambda dd: dict(sorted(dd.items(), key=lambda x: -x[1]))
    return {
        "don_today": don_today, "don_yest": don_yest, "don_week": don_week,
        "sp_today": today_sp, "sp_yest": yest_sp, "sp_week": week_sp,
        "sku_count": len(sku_set),
        "sp_per_order": round(week_sp / don_week, 2) if don_week else 0,
        "daily": [{"ngay": d.strftime("%d/%m"), "don": v["don"], "sp": v["sp"]}
                  for d, v in daily.items()],
        "sources": srt(sources), "stores": srt(stores),
        "delivery": cg,
        "dvvc": sorted(dvvc.values(), key=lambda x: -x["total"]),
        "alerts": al,
        "cancel": cancel,
    }


# ───────────────────────── 3. Đơn trả hàng ─────────────────────────

def _has_thang(note) -> bool:
    n = (note or "").lower()
    return "thắng" in n or ("thang" in n and "tháng" not in n)


def get_returns_summary(fetch_json, days: int = 7) -> dict:
    """Summary phiếu trả 7 ngày (nhanh, vài trang)."""
    week_ago = (_now_utc() - timedelta(days=days)).isoformat()
    rows = []
    for p in range(1, 11):
        chunk = fetch_json("/admin/order_returns.json", limit=250, page=p).get("order_returns", [])
        if not chunk:
            break
        rows += chunk
        if chunk[-1].get("created_on", "") < week_ago:
            break
    recent = [x for x in rows if x.get("created_on", "") >= week_ago]
    by = lambda s: sum(1 for x in recent if x.get("status") == s)
    return {
        "recent7d_total": len(recent), "open": by("open"), "closed": by("closed"),
        "canceled": by("canceled"), "active": sum(1 for x in recent if x.get("status") != "canceled"),
    }


def get_returns_followup(fetch_json, max_pages: int = 26) -> list:
    """Danh sách đơn trả NĂM NAY cần theo dõi: chưa nhận hàng trả (restock 'unrestock'),
    chưa 'THẮNG', chưa canceled. Quét cả năm -> gọi riêng (cache lâu)."""
    now_vn = _now_utc() + timedelta(hours=7)
    year_start = f"{now_vn.year}-01-01T00:00:00"
    rows = []
    for p in range(1, max_pages):
        chunk = fetch_json("/admin/order_returns.json", limit=250, page=p).get("order_returns", [])
        if not chunk:
            break
        rows += chunk
        if chunk[-1].get("created_on", "") < year_start:
            break
    return [{
        "name": x.get("name"),
        "note": (x.get("note") or "").strip() or "(không ghi chú)",
        "status": x.get("status"),
        "loai": x.get("return_type"),
        "SL": x.get("total_quantity"),
        "ngay_tao": (x.get("created_on") or "")[:10],
    } for x in rows
        if x.get("created_on", "") >= year_start
        and x.get("restock_status") == "unrestock"
        and x.get("status") != "canceled"
        and not _has_thang(x.get("note"))]


# ───────────────────────── Tải gộp (LIVE) ─────────────────────────

def load_live(fetch_json) -> dict:
    return {
        "pending": get_pending(fetch_json),
        "cancelled": get_cancelled(fetch_json),
        "returns": get_returns_summary(fetch_json),
    }


# ───────────────────── Snapshot (dữ liệu thật đã chụp) ─────────────────────

def snapshot_exists() -> bool:
    return os.path.exists(SNAPSHOT_PATH)


def load_snapshot() -> dict:
    """Đọc snapshot.json (dữ liệu thật chụp từ phiên Sapo)."""
    with io.open(SNAPSHOT_PATH, encoding="utf-8") as f:
        d = json.load(f)
    return {
        "pending": d["pending"],
        "cancelled": d["cancelled"],
        "returns": d["returns"],
        "generated_at_vn": d.get("generated_at_vn"),
    }


# ═══════════════════════════ DỮ LIỆU DEMO ═══════════════════════════
# Số liệu mẫu theo Phụ lục tài liệu (lần chạy 13/06/2026) để xem giao diện
# mà không cần đăng nhập Sapo.

def _demo_cancel_order(name, carrier, packed, day, items):
    return {
        "id": name,
        "name": name,
        "cancelled_on": f"2026-06-{day:02d}T03:00:00",
        "shipping_lines": [{"carrier_name": carrier}],
        "fulfillments": [{
            "tracking_number": f"VN{name[-6:]}",
            "tracking_company": carrier,
            "packed_status": "packed" if packed else "packing",
        }],
        "line_items": [{"sku": sku, "quantity": q} for sku, q in items],
    }


def demo_payload() -> dict:
    pending = {
        "total": 95, "today": 28, "yesterday": 67,
        "total_items": 99, "sku_count": 29,
        "sources": {"tiktokshop": 68, "shopee": 27},
        "stores": {"VITRAN BOUTIQUE - Tiktokshop": 55, "VITRAN BOUTIQUE - Shopee": 22,
                   "SMOSS - Shopee": 13, "MUN - AI - Shopee": 5},
        "carriers": {
            "J&T Express": 55, "SPX Express": 22, "NB tự VC": 13,
            "Hỏa Tốc": 2, "Giao Hàng Nhanh": 2, "Nhanh": 1,
        },
        "fast": 93, "express": 2,
        "skus": [
            {"sku": "VTB-DAM-001", "name": "Đầm suông tay lỡ", "qty": 11, "orders": 9},
            {"sku": "VTB-SET-014", "name": "Set áo + chân váy", "qty": 9, "orders": 7},
            {"sku": "VTB-AO-203", "name": "Áo sơ mi linen", "qty": 8, "orders": 8},
            {"sku": "VTB-QUAN-077", "name": "Quần ống rộng", "qty": 7, "orders": 6},
            {"sku": "VTB-DAM-052", "name": "Đầm hai dây lụa", "qty": 6, "orders": 5},
            {"sku": "VTB-AO-118", "name": "Áo croptop gân", "qty": 6, "orders": 4},
            {"sku": "VTB-CHANVAY-09", "name": "Chân váy chữ A", "qty": 5, "orders": 5},
            {"sku": "VTB-SET-031", "name": "Set thể thao nỉ", "qty": 5, "orders": 3},
            {"sku": "VTB-AO-220", "name": "Áo blazer dáng dài", "qty": 4, "orders": 4},
            {"sku": "VTB-DAM-088", "name": "Đầm body ôm", "qty": 4, "orders": 3},
            {"sku": "VTB-QUAN-101", "name": "Quần jean baggy", "qty": 3, "orders": 3},
            {"sku": "VTB-PK-005", "name": "Túi vải canvas", "qty": 3, "orders": 2},
        ],
    }

    cancelled = {
        "total": 16, "excluded_appeal": 6,
        "packed": [
            _demo_cancel_order("VTB2406A1", "J&T Express", True, 11, [("VTB-DAM-001", 1)]),
            _demo_cancel_order("VTB2406A2", "SPX Express", True, 10, [("VTB-AO-203", 2)]),
            _demo_cancel_order("VTB2406A3", "J&T Express", True, 10, [("VTB-SET-014", 1)]),
            _demo_cancel_order("VTB2406A4", "Giao Hàng Nhanh", True, 9, [("VTB-QUAN-077", 1), ("VTB-AO-118", 1)]),
            _demo_cancel_order("VTB2406A5", "SPX Express", True, 9, [("VTB-DAM-052", 1)]),
            _demo_cancel_order("VTB2406A6", "J&T Express", True, 8, [("VTB-CHANVAY-09", 1)]),
            _demo_cancel_order("VTB2406A7", "Nhanh", True, 7, [("VTB-AO-220", 1)]),
        ],
        "not_packed": [
            _demo_cancel_order("VTB2406B1", "J&T Express", False, 11, [("VTB-DAM-088", 1)]),
            _demo_cancel_order("VTB2406B2", "SPX Express", False, 11, [("VTB-QUAN-101", 1)]),
            _demo_cancel_order("VTB2406B3", "J&T Express", False, 10, [("VTB-PK-005", 2)]),
            _demo_cancel_order("VTB2406B4", "SPX Express", False, 10, [("VTB-AO-203", 1)]),
            _demo_cancel_order("VTB2406B5", "Giao Hàng Nhanh", False, 9, [("VTB-SET-031", 1)]),
            _demo_cancel_order("VTB2406B6", "J&T Express", False, 9, [("VTB-DAM-001", 1)]),
            _demo_cancel_order("VTB2406B7", "SPX Express", False, 8, [("VTB-AO-118", 1)]),
            _demo_cancel_order("VTB2406B8", "J&T Express", False, 8, [("VTB-QUAN-077", 1)]),
            _demo_cancel_order("VTB2406B9", "Nhanh", False, 7, [("VTB-CHANVAY-09", 1)]),
        ],
    }

    returns = {
        "recent7d_total": 103, "open": 80, "closed": 17, "canceled": 6, "active": 97,
        "followup_count": 3,
        "followup": [
            {"name": "584491689258616181", "note": "Sản phẩm quá to/quá nhỏ", "status": "open",
             "loai": "return_and_refund", "SL": 1, "ngay_tao": "2026-06-15"},
            {"name": "584465093436212384", "note": "Không còn nhu cầu", "status": "open",
             "loai": "return_and_refund", "SL": 2, "ngay_tao": "2026-06-14"},
            {"name": "584426414620771662", "note": "Giao hàng thất bại", "status": "open",
             "loai": "delivery_failed", "SL": 1, "ngay_tao": "2026-06-12"},
        ],
    }

    return {"pending": pending, "cancelled": cancelled, "returns": returns}


if __name__ == "__main__":
    # Smoke test: in nhanh payload demo
    import json
    d = demo_payload()
    print("pending.total =", d["pending"]["total"])
    print("cancelled.total =", d["cancelled"]["total"],
          "| packed =", len(d["cancelled"]["packed"]),
          "| not_packed =", len(d["cancelled"]["not_packed"]))
    print("returns =", json.dumps(d["returns"], ensure_ascii=False))
