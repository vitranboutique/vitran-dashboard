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
import re
from datetime import datetime, timedelta, timezone

# Mẫu mã vận đơn để bóc từ note (SPXVN.../VTPVN... hoặc mã số 11–14 chữ số như J&T 861...)
_TRACK_RE = re.compile(r'[A-Z]{2,}VN\d+|\b\d{11,14}\b')
_PHONE_RE = re.compile(r'(?:s\s*[đd]t|phone|tel|dien\s*thoai|điện\s*thoại)\s*[:\-]?\s*(?:\+?84|0)?\d[\d\s.\-]{7,12}|\b(?:\+?84|0)\d[\d\s.\-]{8,12}\b', re.I)

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


def _has_customer_phone(note) -> bool:
    return bool(_PHONE_RE.search(str(note or "")))


def _order_has_customer_phone(order) -> bool:
    parts = [
        order.get("note"),
        order.get("phone"),
        order.get("customer", {}).get("phone") if isinstance(order.get("customer"), dict) else "",
    ]
    for key in ("shipping_address", "billing_address"):
        addr = order.get(key) or {}
        if isinstance(addr, dict):
            parts.extend([addr.get("phone"), addr.get("phone_number"), addr.get("mobile")])
    return any(_has_customer_phone(x) for x in parts if x)


def _picking_deadline_vn(created_vn):
    """Hạn xác nhận: 18h ngày đặt; nếu đặt từ 18h trở đi -> 18h hôm sau."""
    cutoff = created_vn.replace(hour=18, minute=0, second=0, microsecond=0)
    return cutoff if created_vn < cutoff else cutoff + timedelta(days=1)


def _shipping_service_label(order, shipping_line):
    for key in ("service_name", "shipping_service", "service_type", "delivery_service", "title"):
        val = shipping_line.get(key)
        if val:
            return val
    return "Hỏa tốc" if order.get("shipment_category") == "express" else "Nhanh"


def _summarize_picking(orders):
    today = (_now_utc() + timedelta(hours=7)).date()
    channels, stores, carriers, services, sku = {}, {}, {}, {}, {}
    total_qty = old = new = late = 0
    late_list = []
    for o in orders:
        cd = o.get("channel_definition") or {}
        ch = cd.get("main_name") or o.get("source_name") or "Khác"
        store = cd.get("branch_name") or ch or "Khác"
        sl = (o.get("shipping_lines") or [{}])[0]
        carrier = sl.get("carrier_name") or sl.get("title") or "Chưa rõ"
        service = _shipping_service_label(o, sl)
        channels[ch] = channels.get(ch, 0) + 1
        stores[store] = stores.get(store, 0) + 1
        carriers[carrier] = carriers.get(carrier, 0) + 1
        services[service] = services.get(service, 0) + 1
        for li in (o.get("line_items") or []):
            s = li.get("sku") or "N/A"
            q = li.get("quantity", 0) or 0
            sku[s] = sku.get(s, 0) + q
            total_qty += q
        f = (o.get("fulfillments") or [{}])[0]
        xuly_vn = _parse_vn(f.get("shipment_created_on") or f.get("created_on"))
        cre_vn = _parse_vn(o.get("created_on"))
        if xuly_vn:
            if xuly_vn.date() == today:   # mới: Ngày xử lý hôm nay
                new += 1
            else:                          # cũ/tồn: Ngày xử lý hôm trước
                old += 1
            if cre_vn and xuly_vn > _picking_deadline_vn(cre_vn):
                late += 1
                late_list.append(o.get("name"))
    srt = lambda d: dict(sorted(d.items(), key=lambda x: (-x[1], str(x[0]))))
    return {
        "total_orders": len(orders),
        "total_qty": total_qty,
        "sku_count": len(sku),
        "old": old, "new": new, "late": late, "late_list": late_list,
        "channels": srt(channels), "stores": srt(stores), "carriers": srt(carriers),
        "services": srt(services),
        "skus": sorted(sku.items(), key=lambda x: (-x[1], str(x[0]))),
    }


def get_tt_customer_candidates(fetch_json, days: int = 15, max_pages: int = 30, channel_filter: str = "tiktok") -> dict:
    """Đơn còn thiếu SĐT/TTKH trong ghi chú để NV lấy thông tin từ TikTok rồi ghi ngược vào SAPO.

    Nguồn: danh sách đơn hàng "Tất cả"; loại đơn hủy; chỉ lấy đơn tạo trong `days` ngày gần nhất;
    chỉ lấy đơn chưa có SĐT trong ghi chú.
    """
    now_vn = (_now_utc() + timedelta(hours=7)).replace(tzinfo=None)
    cutoff_vn = now_vn - timedelta(days=days)
    rows = []
    stopped_by_old = False

    def _money_value(value) -> int:
        try:
            return int(round(float(value or 0)))
        except Exception:
            return 0

    def _line_discount(li: dict) -> int:
        keys = ("total_discount", "discount_amount", "total_discount_amount", "discount")
        direct = sum(_money_value(li.get(k)) for k in keys if li.get(k) not in (None, ""))
        allocs = li.get("discount_allocations") or li.get("discount_applications") or []
        alloc_total = 0
        if isinstance(allocs, list):
            for a in allocs:
                if isinstance(a, dict):
                    alloc_total += _money_value(a.get("amount") or a.get("discount_amount") or a.get("value"))
        return max(direct, alloc_total)

    def _line_prices(li: dict, qty: int) -> tuple[int, int, int]:
        original_unit = _money_value(li.get("original_price") or li.get("base_price") or li.get("price"))
        discounted_unit = _money_value(
            li.get("discounted_price")
            or li.get("final_price")
            or li.get("sale_price")
            or li.get("price_after_discount")
        )
        line_total = _money_value(
            li.get("line_price")
            or li.get("total_price")
            or li.get("total")
            or li.get("subtotal_price")
        )
        discount = _line_discount(li)
        if not line_total and original_unit:
            line_total = max(0, original_unit * max(qty, 1) - discount)
        if not discounted_unit and line_total and qty:
            discounted_unit = int(round(line_total / qty))
        if not discounted_unit:
            discounted_unit = original_unit
            line_total = discounted_unit * max(qty, 1)
        return original_unit, discounted_unit, line_total

    created_min = cutoff_vn.isoformat()
    for page in range(1, int(max_pages) + 1):
        data = fetch_json("/admin/orders.json", limit=250, page=page, created_on_min=created_min)
        orders = data.get("orders", []) or []
        if not orders:
            break

        page_has_recent = False
        for o in orders:
            created_vn = _parse_vn(o.get("created_on"))
            if not created_vn:
                continue
            if created_vn < cutoff_vn:
                continue
            page_has_recent = True
            if str(o.get("status") or "").lower() == "cancelled" or o.get("cancelled_on"):
                continue
            note = o.get("note") or ""
            if _order_has_customer_phone(o):
                continue
            line_items = o.get("line_items") or []
            total_qty = int(round(sum((li.get("quantity") or 0) for li in line_items)))
            if total_qty <= 0:
                continue
            products = []
            order_value = 0
            for li in line_items:
                q = int(round(li.get("quantity") or 0))
                original_price, price, line_total = _line_prices(li, q)
                order_value += line_total
                products.append({
                    "sku": li.get("sku") or "N/A",
                    "qty": q,
                    "price": price,
                    "original_price": original_price,
                    "line_total": line_total,
                    "title": li.get("product_title") or li.get("product_name") or li.get("title") or li.get("name") or "",
                    "variant": li.get("variant_title") or li.get("variant_name") or li.get("variant") or "",
                })
            cd = o.get("channel_definition") or {}
            store = cd.get("branch_name") or o.get("source_name") or "Khác"
            channel = cd.get("main_name") or o.get("source_name") or "Khác"
            channel_key = str(channel_filter or "all").lower()
            haystack = f"{channel} {store} {o.get('source_name') or ''}".lower()
            if channel_key != "all" and channel_key not in haystack:
                continue
            rows.append({
                "order_id": o.get("id"),
                "customer_id": (o.get("customer") or {}).get("id") if isinstance(o.get("customer"), dict) else o.get("customer_id"),
                "created_on": created_vn.strftime("%d/%m %H:%M"),
                "created_sort": created_vn.isoformat(),
                "name": o.get("source_identifier") or o.get("name") or o.get("code") or o.get("id"),
                "sapo_name": o.get("name") or o.get("code") or "",
                "source_identifier": o.get("source_identifier") or "",
                "qty": total_qty,
                "store": store,
                "channel": channel,
                "note": note,
                "products": products,
                "order_value": order_value,
                "shipping_phone": ((o.get("shipping_address") or {}).get("phone") or ""),
            })

        if not page_has_recent:
            stopped_by_old = True
            break

    multi = sorted(
        [r for r in rows if r["qty"] >= 2],
        key=lambda x: (-x["qty"], x.get("created_sort") or "", str(x["name"])),
    )
    single = sorted(
        [r for r in rows if r["qty"] == 1],
        key=lambda x: (x.get("created_sort") or "", str(x["name"])),
    )
    return {
        "days": days,
        "channel_filter": channel_filter,
        "multi": multi,
        "single": single,
        "total": len(rows),
        "stopped_by_old": stopped_by_old,
        "generated_at_vn": now_vn.strftime("%H:%M %d/%m/%Y"),
    }


def _packing_history(orders, gap_min: int = 20, ref_date=None) -> dict:
    """Suy ra các ĐỢT SOẠN HÀNG trong ngày từ mốc đóng gói (packed_on).
    Gom các đơn đóng gói cách nhau <= gap_min phút thành 1 đợt. ref_date=None → hôm nay."""
    today = ref_date or (_now_utc() + timedelta(hours=7)).date()
    rows = []
    for o in orders:
        f = (o.get("fulfillments") or [{}])[0]
        pv = _parse_vn(f.get("packed_on"))
        if pv and pv.date() == today:
            rows.append((pv, o))
    rows.sort(key=lambda x: x[0])
    batches = []
    for pv, o in rows:
        if batches and (pv - batches[-1]["_last"]).total_seconds() <= gap_min * 60:
            b = batches[-1]
        else:
            b = {"_start": pv, "_last": pv, "orders": []}
            batches.append(b)
        b["_last"] = pv
        b["orders"].append(o)
    out = []
    for i, b in enumerate(batches, 1):
        g = _summarize_picking(b["orders"])         # full summary để render phiếu
        g1, g2 = b["_start"].strftime("%H:%M"), b["_last"].strftime("%H:%M")
        xuat = sum(1 for o in b["orders"]
                   if _vn_date_of((o.get("fulfillments") or [{}])[0].get("issued_on")) == today)
        out.append({
            "dot": i, "gio": g1 if g1 == g2 else f"{g1}–{g2}",
            "don": g["total_orders"], "sp": g["total_qty"], "sku_count": g["sku_count"],
            "hoatoc": sum(1 for o in b["orders"] if o.get("shipment_category") == "express"),
            "xuat": xuat, "summary": g,
        })
    return {
        "batches": out,
        "so_dot": len(out),
        "tong_don": sum(x["don"] for x in out),
        "tong_sp": sum(x["sp"] for x in out),
    }


def _packing_reconcile(orders) -> dict:
    """Đối chiếu SP SOẠN HÀNG (đóng gói hôm nay) vs SP XUẤT KHO (giao ĐVVC hôm nay) theo SKU,
    kèm LÝ DO từng SKU lệch (đơn nào đã soạn chưa xuất / xuất từ đơn soạn hôm trước)."""
    today = (_now_utc() + timedelta(hours=7)).date()
    soan, xuat = {}, {}
    pend, prev = {}, {}   # sku -> {"qty": int, "pairs": [(mã vận đơn, ĐVVC)]}
    for o in orders:
        f = (o.get("fulfillments") or [{}])[0]
        p_today = _vn_date_of(f.get("packed_on")) == today
        i_today = _vn_date_of(f.get("issued_on")) == today
        if not (p_today or i_today):
            continue
        vd = (f.get("tracking_number") or (f.get("tracking_numbers") or [None])[0]
              or o.get("name") or "?")
        carrier = ((f.get("tracking_info") or {}).get("carrier_name")
                   or (o.get("shipping_lines") or [{}])[0].get("carrier_name") or "Chưa rõ")
        for li in (o.get("line_items") or []):
            sk = li.get("sku") or "N/A"
            q = li.get("quantity", 0) or 0
            if p_today:
                soan[sk] = soan.get(sk, 0) + q
            if i_today:
                xuat[sk] = xuat.get(sk, 0) + q
            if p_today and not i_today:        # đã soạn hôm nay, chưa xuất
                e = pend.setdefault(sk, {"qty": 0, "pairs": []})
                e["qty"] += q
                e["pairs"].append((vd, carrier))
            elif i_today and not p_today:       # xuất hôm nay từ đơn soạn hôm trước
                e = prev.setdefault(sk, {"qty": 0, "pairs": []})
                e["qty"] += q
                e["pairs"].append((vd, carrier))

    def _fmt_vd(pairs, n=4):
        by = {}
        for vd, ca in pairs:
            by.setdefault(ca, [])
            if vd not in by[ca]:
                by[ca].append(vd)
        segs = []
        for ca, vds in by.items():
            shown = ", ".join(vds[:n]) + (f" …+{len(vds) - n}" if len(vds) > n else "")
            segs.append(f"{ca} (VĐ {shown})")
        return " · ".join(segs)

    rows = []
    for sk in set(soan) | set(xuat):
        sn, xu = soan.get(sk, 0), xuat.get(sk, 0)
        lech = sn - xu
        reason = ""
        if lech != 0:
            parts = []
            if sk in pend:
                parts.append(f"🕒 {pend[sk]['qty']} đã soạn chưa xuất (chờ lấy) — {_fmt_vd(pend[sk]['pairs'])}")
            if sk in prev:
                parts.append(f"📤 {prev[sk]['qty']} xuất từ đơn soạn hôm trước — {_fmt_vd(prev[sk]['pairs'])}")
            reason = " · ".join(parts) if parts else "—"
        rows.append({"SKU": sk, "SL soạn": sn, "SL xuất kho": xu, "Lệch": lech, "Lý do lệch": reason})
    rows.sort(key=lambda r: (r["Lệch"] == 0, -abs(r["Lệch"]), -r["SL soạn"]))
    return {
        "rows": rows,
        "tong_soan": sum(soan.values()),
        "tong_xuat": sum(xuat.values()),
        "so_sku": len(rows),
        "so_sku_lech": sum(1 for r in rows if r["Lệch"] != 0),
    }


def _cancel_after_pick(open_orders, fetch_json) -> dict:
    """SP bị HỦY sau khi đã IN PHIẾU NHẶT hôm nay (đơn hủy + có shipping_label_slip_url).
    Báo mã vận đơn / SKU+SL / SP / thuộc ĐỢT soạn nào (khớp theo packed_on cụm như lịch sử)."""
    today = (_now_utc() + timedelta(hours=7)).date()

    def f0(o):
        return (o.get("fulfillments") or [{}])[0]

    # Đợt soạn hôm nay = cụm packed_on của đơn open (giống _packing_history)
    pts = sorted(p for o in open_orders
                 for p in [_parse_vn(f0(o).get("packed_on"))] if p and p.date() == today)
    windows = []
    for t in pts:
        if windows and (t - windows[-1][1]).total_seconds() <= 20 * 60:
            windows[-1][1] = t
        else:
            windows.append([t, t])

    def dot_of(t):
        if not t:
            return None
        for i, (s, e) in enumerate(windows, 1):
            if s - timedelta(minutes=20) <= t <= e + timedelta(minutes=20):
                return i
        return None

    try:
        canc = get_cancelled(fetch_json)
    except Exception:
        return {"rows": [], "tong_don": 0, "tong_sp": 0}
    rows = []
    for o in (canc.get("packed", []) + canc.get("not_packed", [])):
        f = f0(o)
        if not f.get("shipping_label_slip_url"):          # chưa in phiếu -> bỏ
            continue
        if _vn_date_of(o.get("cancelled_on")) != today:    # chỉ hủy hôm nay
            continue
        t_pack = _parse_vn(f.get("packed_on"))
        t_ref = t_pack or _parse_vn(f.get("shipment_created_on") or f.get("created_on"))
        dot = dot_of(t_pack) or dot_of(t_ref)
        ch = _parse_vn(o.get("cancelled_on"))
        rows.append({
            "Mã vận đơn": (f.get("tracking_number") or (f.get("tracking_numbers") or [None])[0]
                           or o.get("name") or ""),
            "ĐVVC": ((f.get("tracking_info") or {}).get("carrier_name")
                     or (o.get("shipping_lines") or [{}])[0].get("carrier_name") or "?"),
            "SKU (SL)": "; ".join(f"{li.get('sku') or 'N/A'} ×{li.get('quantity', 0) or 0}"
                                  for li in (o.get("line_items") or [])),
            "SP": sum((li.get("quantity", 0) or 0) for li in (o.get("line_items") or [])),
            "Đợt in phiếu": f"Đợt {dot}" if dot else "—",
            "Giờ in phiếu": t_ref.strftime("%H:%M") if t_ref else "",
            "Giờ hủy": ch.strftime("%H:%M") if ch else "",
        })
    rows.sort(key=lambda r: r["Giờ in phiếu"])
    return {"rows": rows, "tong_don": len(rows), "tong_sp": sum(r["SP"] for r in rows)}


def get_picking(fetch_json, max_pages: int = 15) -> dict:
    """Đơn cần nhặt = chờ đóng gói (packing) + đã in phiếu giao hàng (shipping_label_slip_url).
    Tách hỏa tốc (express) / thường (còn lại). Kèm lịch sử đợt soạn hàng hôm nay."""
    orders = []
    for p in range(1, max_pages + 1):
        rows = fetch_json("/admin/orders.json", limit=250, page=p, status="open").get("orders", [])
        if not rows:
            break
        orders += rows

    def f0(o):
        return (o.get("fulfillments") or [{}])[0]

    # cần nhặt = ĐÃ IN phiếu giao + CHƯA đóng gói (labeling/packing... — mọi trạng thái trước "packed")
    pick = [o for o in orders
            if f0(o).get("shipping_label_slip_url")
            and f0(o).get("packed_status") not in ("packed", None)]
    express = [o for o in pick if o.get("shipment_category") == "express"]
    normal = [o for o in pick if o.get("shipment_category") != "express"]
    today = (_now_utc() + timedelta(hours=7)).date()
    packed_ids = [[c for c in [f0(o).get("tracking_number"), o.get("name")] if c]
                  for o in orders if _vn_date_of(f0(o).get("packed_on")) == today]
    return {
        "express": _summarize_picking(express),
        "normal": _summarize_picking(normal),
        "total": len(pick),
        "history": _packing_history(orders),
        "reconcile": _packing_reconcile(orders),
        "cancel_pick": _cancel_after_pick(orders, fetch_json),
        "packed_ids": packed_ids,
    }


# ───────────────────── Tổng quan điều hành (overview) ─────────────────────

def _vn_date_of(iso):
    d = _parse_vn(iso)
    return d.date() if d else None


def _vn_hm(iso):
    """ISO UTC -> 'HH:MM DD/MM' giờ VN (cho mốc nhận hàng trả)."""
    d = _parse_vn(iso)
    return d.strftime("%H:%M %d/%m") if d else ""


def _order_codes(o) -> set:
    """Mã định danh để khớp video Dohana: mã vận đơn + mã đơn (name)."""
    f = (o.get("fulfillments") or [{}])[0]
    c = set()
    if f.get("tracking_number"):
        c.add(str(f["tracking_number"]))
    for t in (f.get("tracking_numbers") or []):
        c.add(str(t))
    if o.get("name"):
        c.add(str(o["name"]))
    return c


def get_alerts(fetch_json) -> dict:
    """Số liệu CẢNH BÁO cho popup (mọi trang): xác nhận trễ, chưa giao, hỏa tốc,
    đơn HỦY SAU GÓI cần lấy lại. Quét đơn open + get_cancelled (nhẹ, cache)."""
    today = (_now_utc() + timedelta(hours=7)).date()

    def f0(o):
        return (o.get("fulfillments") or [{}])[0]

    open_orders = []
    for p in range(1, 30):
        rows = fetch_json("/admin/orders.json", limit=250, page=p, status="open").get("orders", [])
        if not rows:
            break
        open_orders += rows
    conf_after18 = late_confirm = chua_giao = express_pending = 0
    xot_chua_dong = xot_da_dong = 0   # đơn xót lại (chưa giao) chia theo ĐÃ/CHƯA đóng gói
    for o in open_orders:
        f = f0(o)
        ss = f.get("shipment_status")
        xuly = _parse_vn(f.get("shipment_created_on") or f.get("created_on"))
        if xuly and xuly.date() == today and xuly.hour >= 18:
            conf_after18 += 1
            cre = _parse_vn(o.get("created_on"))
            if cre and cre.date() == today and cre.hour < 18:
                late_confirm += 1
        if ss == "pending":
            chua_giao += 1
            if f.get("packed_status") == "packed":
                xot_da_dong += 1
            else:
                xot_chua_dong += 1
            if o.get("shipment_category") == "express":
                express_pending += 1
    # Đơn HỦY SAU GÓI cần lấy lại = đã đóng gói + HỦY HÔM NAY (khớp Sapo "Hủy hôm nay")
    cancel_retrieve = cancel_retrieve_express = 0
    try:
        canc = get_cancelled(fetch_json)
        for o in canc.get("packed", []):
            if _vn_date_of(o.get("cancelled_on")) == today:
                cancel_retrieve += 1
                if o.get("shipment_category") == "express":
                    cancel_retrieve_express += 1
    except Exception:
        pass
    return {"conf_after18": conf_after18, "late_confirm": late_confirm,
            "chua_giao": chua_giao, "express_pending": express_pending,
            "xot_chua_dong": xot_chua_dong, "xot_da_dong": xot_da_dong,
            "cancel_retrieve": cancel_retrieve,
            "cancel_retrieve_express": cancel_retrieve_express}


def get_week_summary(fetch_json, days: int = 7) -> list:
    """Tổng hợp NHIỀU NGÀY (mặc định 7) — mỗi ngày: đóng gói / hủy đã gói / shipper nhận /
    giao khách / soạn. Số liệu cố định sau ngày (mốc packed_on/issued_on/delivered_on/cancelled_on
    không đổi) nên query lại là ra số cuối, KHÔNG cần lưu. Quét đơn open + closed(theo created_on)
    + cancelled, gom theo từng ngày."""
    now_vn = _now_utc() + timedelta(hours=7)
    today = now_vn.date()
    day_list = [today - timedelta(days=i) for i in range(days)]   # mới → cũ
    day_set = set(day_list)
    agg = {d: {"dong_goi": 0, "huy": 0, "shipper_nhan": 0, "giao_khach": 0} for d in day_set}

    def f0(o):
        return (o.get("fulfillments") or [{}])[0]

    # Đơn open + closed (created_on lùi ~ days+10 ngày để phủ packed/issued/delivered trong tuần)
    orders = []
    for p in range(1, 30):
        rows = fetch_json("/admin/orders.json", limit=250, page=p, status="open").get("orders", [])
        if not rows:
            break
        orders += rows
    back = days + 10
    cmin = (today - timedelta(days=back)).isoformat() + "T00:00:00+07:00"
    for p in range(1, 25):
        rows = fetch_json("/admin/orders.json", limit=250, page=p,
                          status="closed", created_on_min=cmin).get("orders", [])
        if not rows:
            break
        orders += rows
        last = _vn_date_of(rows[-1].get("created_on"))
        if last and last < (today - timedelta(days=back)):
            break

    for o in orders:
        f = f0(o)
        for fld, key in (("packed_on", "dong_goi"), ("issued_on", "shipper_nhan")):
            d = _vn_date_of(f.get(fld))
            if d in agg:
                agg[d][key] += 1
        # Giao khách = trong số đơn đóng gói ngày đó, đã giao đến tay khách (status delivered)
        pd = _vn_date_of(f.get("packed_on"))
        if pd in agg and f.get("shipment_status") == "delivered":
            agg[pd]["giao_khach"] += 1
    # Hủy đã gói theo cancelled_on (đơn đã đóng gói)
    try:
        canc = get_cancelled(fetch_json, days=days)
        for o in canc.get("packed", []):
            d = _vn_date_of(o.get("cancelled_on"))
            if d in agg:
                agg[d]["huy"] += 1
    except Exception:
        pass

    _wd = ["T2", "T3", "T4", "T5", "T6", "T7", "CN"]
    out = []
    for d in day_list:
        a = agg[d]
        out.append({
            "ngay": d.strftime("%d/%m"),
            "thu": _wd[d.weekday()],
            "iso": d.isoformat(),
            "dong_goi": a["dong_goi"],
            "huy": a["huy"],
            "soan": a["dong_goi"] + a["huy"],     # đã soạn = đóng gói + hủy đã gói
            "shipper_nhan": a["shipper_nhan"],
            "giao_khach": a["giao_khach"],
            "is_today": d == today,
        })
    return out


# ── Thống kê MẤT HÀNG (THUA/HẾT HẠN): trích ĐVVC + shipper từ carrier_name/ghi chú ──
_LOST_CARRIERS = [("j&t", "J&T Express"), ("jnt", "J&T Express"), ("spx", "SPX (Shopee)"),
                  ("shopee", "SPX (Shopee)"), ("viettel", "Viettel Post"), ("vtp", "Viettel Post"),
                  ("ghn", "GHN"), ("giao hàng nhanh", "GHN"), ("ghtk", "GHTK"),
                  ("tiết kiệm", "GHTK"), ("ninja", "Ninja Van"), ("best", "BEST"), ("ahamove", "Ahamove")]


def _norm_dvvc(s):
    s = str(s or "").lower()
    for k, v in _LOST_CARRIERS:
        if k in s:
            return v
    return ""


def _lost_dvvc(x):
    return (_norm_dvvc((x.get("shipping_info") or {}).get("carrier_name"))
            or _norm_dvvc(x.get("note")) or "(không rõ)")


def _lost_phone(note):
    m = re.search(r"(?<!\d)0\d{9}(?!\d)", re.sub(r"[.\s\-]", "", str(note or "")))
    return m.group(0) if m else ""


def _lost_person(note):
    m = re.search(r"ho[aà]n\s*:\s*([^\n\r|]+)", str(note or ""), flags=re.I)
    if not m:
        return ""
    s = re.sub(r"\(.*", "", m.group(1))
    s = re.sub(r"\d.*", "", s)
    for h in ("J&T Express", "SPX Express", "Viettel Post", "SPXVN", "Shopee"):
        s = s.replace(h, "")
    return s.strip(" ,-")


def get_returns_in_progress(fetch_json, max_pages: int = 120) -> dict:
    """ĐƠN TRẢ HÀNG ĐANG XỬ LÝ — CHƯA nhập kho (bổ sung cho mục 'đã nhận hàng trả').
    Tổng đơn trả lấy theo tab TẤT CẢ của phiếu trả trong NĂM NAY, loại phiếu hủy/gạch ngang.
    Phạm vi: phiếu trả chưa bị hủy & chưa nhập kho đầy đủ, gồm cả:
    {returning=Đang hoàn hàng, returned=Đã giao người bán, no_return=Không cần trả lại}.
    Cờ CẦN KHIẾU NẠI:
      • đã giao người bán (returned) mà chưa nhập kho → khiếu nại
      • đang hoàn hàng (returning) HƠN 5 ngày → khiếu nại
      • 'Trả hàng hoàn tiền' có mã hoàn về nhưng chưa có tên shipper hoàn → hơn 5 ngày vẫn khiếu nại
      • NGOẠI LỆ: 'Trả hàng hoàn tiền' chỉ 1 VĐ và chưa quá 5 ngày → CHƯA khiếu nại
    (Giao hàng thất bại có 1 VĐ trả là bình thường; Trả hàng hoàn tiền phải có 2 VĐ.)
    Kèm SKU, SL SP, tổng tiền (total_price) mỗi đơn."""
    today = (_now_utc() + timedelta(hours=7)).date()
    _kn_days = 5   # đang hoàn hàng HƠN N ngày → CẦN KN (user đổi 01/07: 7 → 5)
    _type_vn = {"return_and_refund": "Trả hàng hoàn tiền", "delivery_failed": "Giao hàng thất bại",
                "refund": "Chỉ hoàn tiền"}
    _ship_vn = {"returning": "Đang hoàn hàng", "returned": "Đã giao người bán",
                "no_return": "Không cần trả lại", "not_required": "Không cần trả lại"}
    _stock_vn = {
        "stocked": "Đã nhập kho", "restocked": "Đã nhập kho",
        "partial_stocked": "Nhập kho một phần", "partially_stocked": "Nhập kho một phần",
        "partial_restocked": "Nhập kho một phần", "partially_restocked": "Nhập kho một phần",
        "partial": "Nhập kho một phần", "partially": "Nhập kho một phần",
        "unstocked": "Không nhập kho", "unrestock": "Không nhập kho",
        "not_stocked": "Không nhập kho", "not_restocked": "Không nhập kho",
        "no_stock": "Không nhập kho", "no_restock": "Không nhập kho",
    }

    def _stock_code(x):
        return str(x.get("stock_status") or x.get("restock_status") or "").lower()

    def _not_fully_stocked(x):
        return _stock_code(x) not in ("stocked", "restocked")

    def _ship_code(x):
        s = str(x.get("shipment_status") or "").lower()
        rtype = x.get("return_type") or "refund"
        if s in ("no_return", "not_required"):
            return "no_return"
        if s in ("returning", "returned"):
            return s
        if rtype == "refund":
            return "no_return"
        return s or "unknown"

    def _is_canceled_return(x):
        status = str(x.get("status") or "").lower()
        return status in ("canceled", "cancelled") or bool(x.get("cancelled_on") or x.get("canceled_on"))

    def _return_shipper_name(x):
        note = str(x.get("note") or "")
        m = re.search(r"shipper\s*ho[aà]n\s*:\s*([^|\n\r]+)", note, flags=re.I)
        if m:
            return m.group(1).strip()
        si = x.get("shipping_info") or {}
        for key in ("return_shipper_name", "shipper_name", "delivery_staff_name", "driver_name"):
            val = str(si.get(key) or "").strip()
            if val:
                return val
        return ""

    def _return_detail_row(x, complaint=False, reason=""):
        si = x.get("shipping_info") or {}
        lis = x.get("line_items") or []
        sku = "; ".join(f"{(li.get('sku') or 'N/A')}×{int(round(li.get('quantity') or 0))}" for li in lis)
        _con = x.get("created_on")
        try:
            created_disp = (datetime.fromisoformat(str(_con).replace("Z", "").split(".")[0])
                            + timedelta(hours=7)).strftime("%d/%m %H:%M")
        except Exception:
            created_disp = ""
        _ch = (x.get("order") or {}).get("channel_definition") or {}
        gian_hang = (_ch.get("branch_name") or _ch.get("main_name")
                     or (x.get("order_source") or "").title() or "—")
        _ocode = (x.get("order") or {}).get("name") or x.get("name") or ""
        _osrc = (x.get("order_source") or "").lower()
        if "tiktok" in _osrc:
            order_link = f"https://seller-vn.tiktok.com/order?main_order_id[]={_ocode}&selected_sort=6&tab=all"
            return_link = "https://seller-vn.tiktok.com/order/return?order_sort_comp=OrderSort_UPADTE_TIME_DESC&tab=100"
        elif "shopee" in _osrc:
            order_link = f"https://banhang.shopee.vn/portal/sale?search={_ocode}"
            return_link = "https://banhang.shopee.vn/portal/sale/returnrefundcancel"
        else:
            order_link = ""
            return_link = ""
        cdate = _vn_date_of(x.get("created_on"))
        age = (today - cdate).days if cdate else None
        return_shipper = _return_shipper_name(x)
        ucodes = {c for c in ([si.get("tracking_number")] + (si.get("fulfillment_tracking_numbers") or [])) if c}
        rtype = x.get("return_type") or "refund"
        sstat = _ship_code(x)
        return {
            "order_code": _ocode or "?",
            "order_link": order_link,
            "return_code": x.get("name") or "",
            "return_link": return_link,
            "gian_hang": gian_hang,
            "created": created_disp, "created_on": _con,
            "vd_di": (si.get("fulfillment_tracking_numbers") or [None])[0],
            "vd_tra": si.get("tracking_number"),
            "return_shipper": return_shipper,
            "has_return_shipper": bool(return_shipper),
            "note": (x.get("note") or "").strip(),
            "loai_tra": _type_vn.get(rtype, rtype), "loai_tra_code": rtype,
            "ship_status": _ship_vn.get(sstat, sstat), "ship_code": sstat,
            "stock_status": _stock_vn.get(_stock_code(x), _stock_code(x) or "Chưa rõ"),
            "stock_code": _stock_code(x),
            "n_track": len(ucodes), "age": age, "complaint": complaint, "reason": reason,
            "sku": sku, "qty": int(round(x.get("total_quantity") or 0)),
            "money": int(round(x.get("total_price") or 0)),
            "need_kn": False,
        }

    rows, capped = [], False
    for p in range(1, max_pages + 1):
        chunk = fetch_json("/admin/order_returns.json", limit=250, page=p).get("order_returns", [])
        if not chunk:
            break
        rows += chunk
        _last = _vn_date_of(chunk[-1].get("created_on"))
        if _last and _last.year < today.year:   # đã lùi sang NĂM TRƯỚC (sort created giảm dần) → dừng
            break
        if p == max_pages and len(chunk) == 250:
            capped = True

    def _include_in_total_returns(x):
        cdate = _vn_date_of(x.get("created_on"))
        if not cdate or cdate.year != today.year:
            return False
        if _is_canceled_return(x):
            return False
        return True

    def _include_in_detail(x):
        cdate = _vn_date_of(x.get("created_on"))
        if not cdate or cdate.year != today.year:
            return False
        if not _not_fully_stocked(x):
            return False
        sstat = _ship_code(x)
        if sstat not in ("returning", "returned", "no_return"):
            return False
        if _is_canceled_return(x):
            return False
        return True

    # CHỈ tính NĂM NAY (loại hết đơn năm trước)
    all_returns = [x for x in rows if _include_in_total_returns(x)]
    inprog = [x for x in rows if _include_in_detail(x)]

    cnt, detail, n_complaint = {}, [], 0
    for x in inprog:
        rtype = x.get("return_type") or "refund"
        sstat = _ship_code(x)
        cnt.setdefault(rtype, {"returning": 0, "returned": 0, "no_return": 0})
        cnt[rtype][sstat] = cnt[rtype].get(sstat, 0) + 1
        si = x.get("shipping_info") or {}
        ucodes = {c for c in ([si.get("tracking_number")] + (si.get("fulfillment_tracking_numbers") or [])) if c}
        n_track = len(ucodes)
        return_shipper = _return_shipper_name(x)
        has_return_waybill = bool(si.get("tracking_number"))
        cdate = _vn_date_of(x.get("created_on"))
        age = (today - cdate).days if cdate else None
        # NGOẠI LỆ chỉ cho ĐANG HOÀN HÀNG khi chưa quá 7 ngày.
        # Quá 7 ngày mà chưa có shipper hoàn/tên shipper vẫn phải vào nhóm CẦN KN.
        if sstat == "no_return":
            complaint, reason = True, "Chỉ hoàn tiền/không có hàng hoàn về — cần kết luận KN"
        elif rtype == "return_and_refund" and sstat == "returning" and n_track < 2 and (age or 0) <= _kn_days:
            complaint, reason = False, "Người mua chưa giao ĐVVC (1 VĐ) — chưa cần khiếu nại"
        elif sstat == "returned":
            complaint, reason = True, "Đã giao người bán mà chưa nhập kho — cần khiếu nại"
        elif rtype == "return_and_refund" and sstat == "returning" and has_return_waybill and not return_shipper and age is not None and age > _kn_days:
            complaint, reason = True, f"Có mã hoàn về nhưng chưa có tên shipper hoàn {age} ngày — cần khiếu nại"
        elif sstat == "returning" and age is not None and age > _kn_days:
            complaint, reason = True, f"Đang hoàn hàng {age} ngày (quá 5 ngày) — cần khiếu nại"
        else:
            complaint, reason = False, ("Đang hoàn hàng — theo dõi" if sstat == "returning" else "")
        if complaint:
            n_complaint += 1
        detail.append(_return_detail_row(x, complaint=complaint, reason=reason))
    detail.sort(key=lambda d: d["created_on"] or "", reverse=True)   # MỚI NHẤT lên đầu
    detail_by_return = {d.get("return_code"): d for d in detail if d.get("return_code")}
    all_detail = []
    for x in all_returns:
        row = _return_detail_row(x)
        if row.get("return_code") in detail_by_return:
            row = detail_by_return[row.get("return_code")]
        all_detail.append(row)
    all_detail.sort(key=lambda d: d["created_on"] or "", reverse=True)

    # THỐNG KÊ KẾT QUẢ KHIẾU NẠI theo PREFIX ghi chú trong đúng danh sách đang xử lý.
    # Giữ cùng phạm vi với bảng chi tiết và ô CẦN KN, tránh trộn cả phiếu đã nhập kho/đã đóng.
    # NV ghi đầu note: 🟢/✅ THẮNG · 🔴/❌ THUA · ⛔/⚪ KHÔNG CẦN KN · 🚨 CẦN KN · ⚫ HẾT HẠN.
    import unicodedata as _ud

    def _asc(s):  # bỏ dấu + emoji → CHỮ HOA để khớp keyword
        return _ud.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode().upper()
    _amt_re = re.compile(r"(\d[\d.]*)\s*đ")   # bóc số tiền trong note (vd "186.760đ")

    def _amt(note):
        m = _amt_re.search(str(note or ""))
        if not m:
            return None
        try:
            return int(m.group(1).replace(".", ""))
        except Exception:
            return None

    def _is_khong_can_kn(pre):
        compact = "".join(ch for ch in str(pre or "") if ch.isalnum())
        return "KHONGCANKN" in compact or "KHONGCANKHIEUNAI" in compact

    def _resolved(pre):   # đã có ghi chú KẾT QUẢ chuẩn → coi như xử lý xong
        return ("THANG" in pre or "THUA" in pre or "HET HAN" in pre
                or _is_khong_can_kn(pre))
    oc = {k: {"n": 0, "money": 0} for k in ("thang", "thua", "khong_kn", "can_kn", "het_han")}
    all_oc = {k: {"n": 0, "money": 0} for k in ("thang", "thua", "khong_kn", "het_han")}
    for x in all_returns:
        note = x.get("note") or ""
        pre = _asc(note.split("|")[0])
        amt = _amt(note)
        if amt is None:
            amt = int(round(x.get("total_price") or 0))
        is_khong_can_kn = _is_khong_can_kn(pre)
        cat = ("thang" if "THANG" in pre else "thua" if "THUA" in pre
               else "het_han" if "HET HAN" in pre else None)
        if cat:
            all_oc[cat]["n"] += 1
            all_oc[cat]["money"] += amt
        elif is_khong_can_kn:
            all_oc["khong_kn"]["n"] += 1
            all_oc["khong_kn"]["money"] += amt
    # Kết quả cuối lấy theo prefix note trong chính bảng detail.
    # "Không cần KN" là kết luận đã xử lý/không khiếu nại, không đồng nghĩa mất hàng.
    for d in detail:
        note = d.get("note") or ""
        pre = _asc(note.split("|")[0])
        amt = _amt(note)
        if amt is None:
            amt = int(d.get("money") or 0)
        is_khong_can_kn = _is_khong_can_kn(pre)
        d["khong_can_kn_note"] = is_khong_can_kn
        d["khong_can_kn_money"] = amt if is_khong_can_kn else None
        cat = ("thang" if "THANG" in pre else "thua" if "THUA" in pre
               else "het_han" if "HET HAN" in pre else None)
        if cat:
            oc[cat]["n"] += 1
            oc[cat]["money"] += amt
        elif is_khong_can_kn:
            oc["khong_kn"]["n"] += 1
            oc["khong_kn"]["money"] += amt
    # CẦN KN (cờ need_kn, dùng cho highlight + đếm). LOẠI đơn đã có ghi chú KẾT QUẢ chuẩn.
    #  • ĐÃ GIAO NGƯỜI BÁN (returned) → MẶC ĐỊNH cần KN (bất kể tuổi).
    #  • KHÔNG CÓ HÀNG HOÀN VỀ / CHỈ HOÀN TIỀN (no_return) → cần KN nếu chưa có kết luận chuẩn.
    #  • ĐANG HOÀN HÀNG (returning) → cần KN nếu QUÁ 7 ngày; chỉ chưa cần khi refund 1 VĐ và chưa quá 7 ngày.
    for d in detail:
        if _resolved(_asc((d.get("note") or "").split("|")[0])):
            d["need_kn"] = False
        elif d.get("ship_code") == "returned":
            d["need_kn"] = True
        elif d.get("ship_code") == "no_return":
            d["need_kn"] = True
        elif d.get("loai_tra_code") == "return_and_refund" and (d.get("n_track") or 0) < 2 and (d.get("age") or 0) <= _kn_days:
            d["need_kn"] = False
        else:
            d["need_kn"] = (d.get("age") or 0) > _kn_days
        if not d["need_kn"]:
            continue
        amt = _amt(d.get("note"))
        oc["can_kn"]["n"] += 1
        oc["can_kn"]["money"] += amt if amt is not None else int(d.get("money") or 0)

    # THỐNG KÊ MẤT HÀNG (THUA + HẾT HẠN) theo ĐVVC + shipper.
    # CHỈ đơn ĐANG xử lý (inprog = hàng CHƯA về kho) → đúng nghĩa "mất hàng" + khớp card "Kết quả khiếu nại".
    from collections import defaultdict as _dd
    _ldv = _dd(lambda: {"n": 0, "money": 0, "thua": 0, "het": 0})
    _lsp, _ltot = {}, {"n": 0, "money": 0}
    _lmon = _dd(lambda: _dd(int))   # tháng -> ĐVVC -> tiền mất
    for x in inprog:
        _p = _asc((x.get("note") or "").split("|")[0])
        _k = "thua" if "THUA" in _p else ("het" if "HET HAN" in _p else None)
        if not _k:
            continue
        _mo = _amt(x.get("note"))
        if _mo is None:
            _mo = int(round(x.get("total_price") or 0))
        _dv = _lost_dvvc(x)
        _ldv[_dv]["n"] += 1; _ldv[_dv]["money"] += _mo; _ldv[_dv][_k] += 1
        _ltot["n"] += 1; _ltot["money"] += _mo
        _md = _vn_date_of(x.get("created_on"))
        if _md:
            _lmon[_md.month][_dv] += _mo
        _ph = _lost_phone(x.get("note"))
        if _ph:
            s = _lsp.setdefault(_ph, {"phone": _ph, "name": "", "dvvc": "", "n": 0, "money": 0, "thua": 0, "het": 0})
            s["n"] += 1; s["money"] += _mo; s[_k] += 1
            s["name"] = s["name"] or _lost_person(x.get("note"))
            s["dvvc"] = s["dvvc"] or _dv
    _by_dvvc = sorted(({"dvvc": k, **v} for k, v in _ldv.items()), key=lambda d: -d["money"])
    _months = list(range(min(_lmon), today.month + 1)) if _lmon else []   # liền mạch tới tháng hiện tại
    _dvorder = [d["dvvc"] for d in _by_dvvc]
    lost_stats = {"total": _ltot, "by_dvvc": _by_dvvc,
                  "by_shipper": sorted(_lsp.values(), key=lambda d: -d["money"]),
                  "by_month": {"labels": [f"T{m}" for m in _months],
                               "series": [{"dvvc": dv, "money": [int(_lmon[m].get(dv, 0)) for m in _months]}
                                          for dv in _dvorder],
                               "total": [int(sum(_lmon[m].values())) for m in _months]}}

    return {
        "total": len(inprog), "total_returns": len(all_returns), "capped": capped, "n_complaint": n_complaint,
        "lost_stats": lost_stats,
        "outcomes": oc,
        "all_outcomes": all_oc,
        "refund": cnt.get("return_and_refund", {"returning": 0, "returned": 0}),
        "fail": cnt.get("delivery_failed", {"returning": 0, "returned": 0}),
        "refund_only": cnt.get("refund", {"returning": 0, "returned": 0, "no_return": 0}),
        "tot_returning": sum(c.get("returning", 0) for c in cnt.values()),
        "tot_returned": sum(c.get("returned", 0) for c in cnt.values()),
        "tot_no_return": sum(c.get("no_return", 0) for c in cnt.values()),
        "detail": detail,
        "all_detail": all_detail,
    }


def get_returns_received_today(fetch_json, scan_days: int = 60, max_pages: int = 12,
                               target_date=None) -> dict:
    """ĐƠN HÀNG HOÀN ĐÃ NHẬN VỀ KHO (giờ VN; mặc định hôm nay, hoặc target_date cho ngày cũ).
    = phiếu trả có restock_status='restocked' VÀ mốc nhập kho (restocked_ons) rơi vào ngày đó.
    Phiếu trả sắp xếp created_on giảm dần → quét lùi tối đa scan_days ngày (đủ phủ phiếu tạo
    từ trước nhưng mới nhập kho ngày đó; API bỏ qua modified_on_min nên không lọc nhanh được).
    Kèm số phiếu ĐANG HOÀN VỀ chưa nhập kho (cần theo dõi nhận hàng)."""
    now_vn = _now_utc() + timedelta(hours=7)
    today = target_date or now_vn.date()
    cutoff = (now_vn - timedelta(days=scan_days)).date()

    def _restocked_today(x):
        if x.get("restock_status") != "restocked":
            return False
        ons = x.get("restocked_ons") or []
        if isinstance(ons, str):
            ons = [ons]
        return any(_vn_date_of(o) == today for o in ons)

    rows = []
    for p in range(1, max_pages + 1):
        chunk = fetch_json("/admin/order_returns.json", limit=250, page=p).get("order_returns", [])
        if not chunk:
            break
        rows += chunk
        last = _vn_date_of(chunk[-1].get("created_on"))
        if last and last < cutoff:
            break

    # NHÂN VIÊN NHẬN HÀNG: map user_id -> HỌ TÊN (last_name + first_name, đúng như Sapo
    # hiển thị, vd "Inventory Mun"); fallback phần trước @ của email nếu chưa đặt tên.
    # /admin/accounts bị 403 nhưng /admin/users.json chạy được.
    def _uname(u):
        nm = " ".join(p for p in [(u.get("last_name") or "").strip(),
                                   (u.get("first_name") or "").strip()] if p)
        return nm or (u.get("email") or "").split("@")[0]
    try:
        _users = {u.get("id"): _uname(u)
                  for u in (fetch_json("/admin/users.json").get("users", []) or [])}
    except Exception:
        _users = {}

    _reason_vn = {
        "unwanted": "Không còn nhu cầu", "delivery_failed": "Giao thất bại",
        "defective": "Lỗi/hư hỏng", "wrong_item": "Giao sai hàng",
        "not_as_described": "Khác mô tả", "damaged": "Hư hỏng",
        "size": "Không vừa size", "change_of_mind": "Đổi ý",
        "wrong_size": "Sai size", "quality": "Chất lượng", "other": "Khác",
    }
    # LOẠI TRẢ HÀNG (Sapo return_type): khách trả hoàn tiền vs giao thất bại (hoàn về)
    _type_vn = {
        "return_and_refund": "Trả hàng hoàn tiền",
        "delivery_failed": "Giao hàng thất bại",
        "refund": "Hoàn tiền (không trả hàng)",
    }

    recv = [x for x in rows if _restocked_today(x)]
    by_source, so_sp, detail = {}, 0, []
    for x in recv:
        s = x.get("order_source") or "Khác"
        by_source[s] = by_source.get(s, 0) + 1
        so_sp += int(round(x.get("total_quantity") or 0))
        si = x.get("shipping_info") or {}
        track = si.get("tracking_number")           # mã vận đơn HOÀN-VỀ (thường KHÔNG tra ra ở Sapo)
        fft = si.get("fulfillment_tracking_numbers") or []
        out_track = (fft[0] if fft else None)       # mã vận đơn GIAO ĐI (nằm trên đơn → TRA ĐƯỢC)
        order_name = (x.get("order") or {}).get("name")   # mã đơn (sàn) → TRA ĐƯỢC ở Sapo
        # Mã ứng viên để khớp video khui hàng (NV có thể quét VĐ hoàn-về, VĐ giao-đi, hoặc mã đơn)
        codes = set()
        for c in (track, out_track, order_name, x.get("name")):
            if c:
                codes.add(str(c))
        for t in fft:
            codes.add(str(t))
        # ⚠️ VĐ HOÀN VỀ THẬT (Sapo UI "Vận chuyển hàng hoàn") thường KHÔNG ở field cấu trúc mà
        # nằm trong NOTE (vd "🚚 Hoàn: SPXVN061695285316"). Bóc mã từ note để KHỚP CHÍNH XÁC clip
        # (NV quét clip theo đúng mã hoàn-về này) → khỏi phải đoán theo ĐVVC.
        codes.update(_TRACK_RE.findall(str(x.get("note") or "")))
        lis = x.get("line_items") or []
        sku = "; ".join(f"{(li.get('sku') or 'N/A')}×{int(round(li.get('quantity') or 0))}"
                        for li in lis)
        rsn = lis[0].get("return_reason") if lis else None
        rtype = x.get("return_type")
        # Mốc NHẬN hàng trả (restock) rơi vào ngày báo cáo + NV NHẬN HÀNG.
        # NV nhận hàng = người NHẬP KHO đơn trả = restocked_user_ids (KHÔNG phải user_id,
        # field này thường null). Lấy id đầu tiên có giá trị, fallback user_id.
        _ons = x.get("restocked_ons") or []
        if isinstance(_ons, str):
            _ons = [_ons]
        _recv_on = next((o for o in _ons if _vn_date_of(o) == today), _ons[0] if _ons else None)
        _recv_uid = next((u for u in (x.get("restocked_user_ids") or []) if u), None) or x.get("user_id")
        detail.append({
            # Hiển thị MÃ TRA ĐƯỢC ở Sapo: ưu tiên mã đơn (sàn), kèm VĐ giao đi. KHÔNG show VĐ
            # hoàn-về (track) làm mã chính vì tra Sapo không ra (chỉ nằm trên phiếu hoàn).
            "order_code": order_name or x.get("name") or "?",
            "tracking": out_track or order_name or track or "?",
            "track_return": track,
            "carrier": si.get("carrier_name") or "?",
            "order_name": order_name,
            "sku": sku,
            "sp": int(round(x.get("total_quantity") or 0)),
            # SL THỰC NHẬP KHO (Σ stocked_quantity). Khách trả THIẾU → nhỏ hơn 'sp' (kỳ vọng).
            "sp_nhap": int(round(sum((li.get("stocked_quantity") or 0) for li in lis))),
            "ly_do": _reason_vn.get(rsn, rsn or "—"),
            "loai_tra": _type_vn.get(rtype, rtype or "—"),
            "loai_tra_code": rtype,
            "recv_time": _vn_hm(_recv_on),                 # ngày giờ NHẬN hàng trả (Sapo)
            "nhan_vien": _users.get(_recv_uid) or "",      # NV NHẬN HÀNG (người nhập kho) từ Sapo
            "codes": sorted(codes),
        })
    cho_xu_ly = sum(1 for x in rows
                    if x.get("status") != "canceled"
                    and x.get("restock_status") == "unrestock"
                    and x.get("shipment_status") == "returning")
    # Map mã VĐ/đơn -> info cho MỌI đơn hoàn (kể cả CHƯA nhập kho) → để điền mã đơn/VĐ gửi đi/
    # SKU/loại trả cho clip dư (vd đơn TRÁO HÀNG giữ tranh chấp, chưa nhập kho).
    all_by_code = {}
    for x in rows:
        si = x.get("shipping_info") or {}
        fft = si.get("fulfillment_tracking_numbers") or []
        on = (x.get("order") or {}).get("name")
        lis = x.get("line_items") or []
        info = {
            "order_code": on or x.get("name"),
            "vd_gui": (fft[0] if fft else None),
            "sku": "; ".join(f"{(li.get('sku') or 'N/A')}×{int(round(li.get('quantity') or 0))}"
                             for li in lis),
            "loai_tra": _type_vn.get(x.get("return_type"), x.get("return_type") or "—"),
            "loai_tra_code": x.get("return_type"),
        }
        cset = {str(c) for c in (si.get("tracking_number"), info["vd_gui"], on, x.get("name")) if c}
        cset.update(str(t) for t in fft)
        cset.update(_TRACK_RE.findall(str(x.get("note") or "")))
        for c in cset:
            all_by_code.setdefault(c, info)
    return {
        "so_phieu": len(recv),
        "so_sp": so_sp,
        "by_source": dict(sorted(by_source.items(), key=lambda x: -x[1])),
        "cho_xu_ly": cho_xu_ly,
        "detail": detail,
        "all_by_code": all_by_code,
    }


def get_daily_report(fetch_json, target_date=None) -> dict:
    """Tổng hợp BÁO CÁO CUỐI NGÀY: số đơn theo ĐVVC (đóng gói/hủy/shipper nhận/còn lại),
    các đợt soạn hàng, tổng nhập–xuất. target_date=None → hôm nay; truyền ngày cũ để
    XEM LẠI (số liệu cố định sau ngày vì mốc packed_on/issued_on/... không đổi)."""
    real_today = (_now_utc() + timedelta(hours=7)).date()
    today = target_date or real_today
    is_past = today < real_today

    def f0(o):
        return (o.get("fulfillments") or [{}])[0]

    def carrier(o):
        f = f0(o)
        c = ((f.get("tracking_info") or {}).get("carrier_name")
             or (o.get("shipping_lines") or [{}])[0].get("carrier_name") or "Khác")
        return "Hỏa tốc (SPX Instant)" if c == "SPX Instant" else c

    open_orders = []
    for p in range(1, 30):
        rows = fetch_json("/admin/orders.json", limit=250, page=p, status="open").get("orders", [])
        if not rows:
            break
        open_orders += rows

    # Gộp đơn ĐÃ ĐÓNG (status=closed) đóng gói / xuất / GIAO KHÁCH HÔM NAY — vd hỏa tốc
    # SPX Instant giao xong ngay trong ngày → rớt khỏi scan "open". Kéo riêng để KHÔNG bỏ sót
    # đơn đóng gói + đếm được đơn đã giao đến khách. Lọc created_on_min cho nhẹ.
    cmin = (today - timedelta(days=7)).isoformat() + "T00:00:00+07:00"
    cparams = {"status": "closed", "created_on_min": cmin}
    if is_past:   # xem ngày cũ → chặn trên để khỏi kéo cả đống đơn closed về sau
        cparams["created_on_max"] = (today + timedelta(days=2)).isoformat() + "T23:59:59+07:00"
    for p in range(1, 20):
        rows = fetch_json("/admin/orders.json", limit=250, page=p, **cparams).get("orders", [])
        if not rows:
            break
        for o in rows:
            ff = (o.get("fulfillments") or [{}])[0]
            if (_vn_date_of(ff.get("packed_on")) == today
                    or _vn_date_of(ff.get("issued_on")) == today):
                open_orders.append(o)
        last = _vn_date_of(rows[-1].get("created_on"))
        if last and last < (today - timedelta(days=7)):
            break

    cr = {}

    def ce(c):
        return cr.setdefault(c, {"carrier": c, "dong_goi": 0, "dg_cu": 0, "huy": 0, "xuat_kho": 0,
                                 "shipper_nhan": 0, "giao_khach": 0, "con_lai": 0,
                                 "cx_packed": 0, "cx_unpacked": 0})

    def _today_pipeline(o):
        """Đơn ĐANG xử lý hôm nay = tạo vận đơn HOẶC đóng gói HOẶC xuất kho == hôm nay."""
        f = f0(o)
        return (_vn_date_of(f.get("shipment_created_on")) == today
                or _vn_date_of(f.get("packed_on")) == today
                or _vn_date_of(f.get("issued_on")) == today)

    def _odet(o):
        """Mô tả 1 đơn để liệt kê chi tiết (mã đơn, mã VĐ, ĐVVC, SKU×SL, tổng SP, ngày tạo)."""
        f = f0(o)
        lis = o.get("line_items") or []
        cr = _vn_date_of(o.get("created_on"))
        return {
            "name": o.get("name") or "?",
            "tracking": f.get("tracking_number") or o.get("name") or "?",
            "carrier": carrier(o),
            "sku": "; ".join(f"{li.get('sku') or 'N/A'}×{int(round(li.get('quantity') or 0))}"
                             for li in lis),
            "sp": sum(int(round(li.get("quantity") or 0)) for li in lis),
            "created": cr.strftime("%d/%m") if cr else "?",
            "old": bool(cr and cr < today),   # tạo trước hôm nay = đơn tồn (xót cũ)
        }

    dong_goi_codes, huy_goi_codes, dong_goi_order_codes = set(), set(), []
    issued_orders = []
    for o in open_orders:
        f = f0(o)
        c = carrier(o)
        _pd = _vn_date_of(f.get("packed_on"))
        # Khớp video: đơn ĐÓNG GÓI HÔM NAY (packed_on==today)
        if _pd == today:
            cc = _order_codes(o)
            dong_goi_codes |= cc
            dong_goi_order_codes.append({
                "track": f.get("tracking_number") or o.get("name") or "?",
                "codes": sorted(cc)})
        # Cột "Đóng gói" = đơn pipeline ĐÃ GÓI, tách theo NGÀY XÁC NHẬN (KHÔNG theo ngày gói):
        # CŨ = xác nhận hôm TRƯỚC (đơn sót, đã gói) · HÔM NAY = xác nhận hôm nay + đã gói.
        # Nhờ vậy "đóng gói hôm nay" ≤ "xác nhận hôm nay", và đơn sót đã gói nằm ở "cũ".
        _packed = (_pd is not None) or f.get("packed_status") == "packed"
        if _today_pipeline(o) and _packed:
            if _vn_date_of(f.get("shipment_created_on")) == today:
                ce(c)["dong_goi"] += 1    # đóng gói HÔM NAY (xác nhận hôm nay + đã gói)
            else:
                ce(c)["dg_cu"] += 1       # đóng gói CŨ (xác nhận hôm trước + đã gói = đơn sót)
        if _vn_date_of(f.get("issued_on")) == today:
            ce(c)["xuat_kho"] += 1        # shop ĐÃ XUẤT KHO (issued) — chưa chắc shipper đã nhận
            issued_orders.append(o)
            # SHIPPER THỰC NHẬN = ĐVVC đã xác nhận lấy = shipment_status đã rời 'pending' (đã bàn giao).
            # Tính theo TRẠNG THÁI ĐƠN (không lọc ngày tạo vận đơn) → đếm được cả ĐƠN CŨ giao hôm nay.
            if f.get("shipment_status") not in ("pending", None):
                ce(c)["shipper_nhan"] += 1
        # Giao tới khách = TRONG SỐ đơn đóng gói hôm nay, đã giao đến tay khách (tới hiện tại)
        if _vn_date_of(f.get("packed_on")) == today and f.get("shipment_status") == "delivered":
            ce(c)["giao_khach"] += 1
    huy_total = 0
    huy_goi_orders, huy_detail, huy_all_detail = [], [], []
    try:
        canc = get_cancelled(fetch_json)
        for o in (canc.get("packed", []) + canc.get("not_packed", [])):
            ff = f0(o)
            if _vn_date_of(ff.get("packed_on")) == today:   # gói hôm nay → có soạn + video
                huy_goi_codes |= _order_codes(o)
            if _vn_date_of(o.get("cancelled_on")) == today:
                ce(carrier(o))["huy"] += 1
                _hd = _odet(o)
                _hd["packed"] = (ff.get("packed_status") == "packed")  # đã gói → cần lấy lại hàng
                huy_all_detail.append(_hd)
                if ff.get("packed_status") == "packed":
                    huy_total += 1
                    ce(carrier(o))["dong_goi"] += 1  # hủy đã gói VẪN tính vào đóng gói (khớp NV)
                    huy_goi_orders.append(o)        # đã soạn → tính vào đợt soạn
                    huy_detail.append({
                        "tracking": ff.get("tracking_number") or o.get("name") or "?",
                        "carrier": ((ff.get("tracking_info") or {}).get("carrier_name")
                                    or (o.get("shipping_lines") or [{}])[0].get("carrier_name") or "?"),
                        "sku": "; ".join(f"{li.get('sku') or 'N/A'}×{int(round(li.get('quantity') or 0))}"
                                         for li in (o.get("line_items") or [])),
                        "ten": " · ".join(dict.fromkeys(
                            (li.get("product_title") or li.get("title") or "").strip()
                            for li in (o.get("line_items") or []) if (li.get("product_title") or li.get("title")))),
                        "sp": sum(int(round(li.get("quantity") or 0)) for li in (o.get("line_items") or [])),
                    })
    except Exception:
        pass

    # SHIPPER THỰC NHẬN tính ở vòng lặp trên theo TRẠNG THÁI ĐƠN (shipment_status ≠ 'pending' =
    # ĐVVC đã xác nhận lấy / đã bàn giao). KHÔNG dùng /shipments lọc theo ngày tạo vận đơn nữa vì
    # đơn CŨ giao hôm nay có vận đơn tạo từ ngày trước → bị bỏ sót (NV báo 55, máy ra 53).
    # "Chưa x.nhận" = đã xuất kho mà shipment_status CÒN 'pending' = NGHI MẤT ĐƠN.
    for c, r in cr.items():
        r["con_lai"] = max(0, r["xuat_kho"] - r["shipper_nhan"])
    # CÒN XÓT LẠI = đơn ĐÃ XÁC NHẬN hôm nay (tạo vận đơn) nhưng CHƯA giao được shipper
    # (shipment_status='pending'). Tách: ĐÃ đóng hàng (packed → CẦN xác nhận LẤY LẠI HÀNG)
    # vs CHƯA đóng hàng (chưa gói → KHÔNG cần lấy lại). (Khác cột "Chưa x.nhận"=xuất kho−shipper.)
    con_xot_packed, con_xot_unpacked = [], []
    for o in open_orders:
        f = f0(o)
        if (_vn_date_of(f.get("shipment_created_on")) == today
                and f.get("shipment_status") == "pending"):
            d = _odet(o)
            _cc = carrier(o)
            if f.get("packed_status") == "packed" or _vn_date_of(f.get("packed_on")) == today:
                con_xot_packed.append(d)
                ce(_cc)["cx_packed"] += 1
            else:
                con_xot_unpacked.append(d)
                ce(_cc)["cx_unpacked"] += 1
    # ĐVVC: dòng HỎA TỐC lên ĐẦU, còn lại theo số đóng gói giảm dần
    rows = sorted(cr.values(),
                  key=lambda x: (0 if "Hỏa tốc" in str(x["carrier"]) else 1, -x["dong_goi"]))
    tot = {k: sum(r[k] for r in rows)
           for k in ("dong_goi", "dg_cu", "huy", "xuat_kho", "shipper_nhan", "giao_khach",
                     "con_lai", "cx_packed", "cx_unpacked")}
    # Đợt soạn GỒM cả đơn đã hủy đã gói (vì đã soạn rồi mới hủy) → tổng soạn = đóng gói + hủy đã gói
    hist = _packing_history(open_orders + huy_goi_orders, ref_date=today)
    try:
        nhap_kho = get_returns_received_today(fetch_json, target_date=today)
    except Exception:
        nhap_kho = {"so_phieu": 0, "so_sp": 0, "by_source": {}, "cho_xu_ly": 0}

    # ── PHỄU: xác nhận → soạn → video → ĐVVC đã nhận → hủy / còn xót ──
    # Đã xác nhận = đơn TẠO VẬN ĐƠN hôm nay, GỒM CẢ đơn đã hủy (3 đơn hủy cũng xác nhận/soạn/
    # đóng gói/quay video trong ngày, chỉ hủy sau) → khớp tổng đợt soạn (89).
    # "ĐVVC đã nhận" = "shipper thực nhận" = đã bàn giao (issued) = 86 (khớp số NV báo;
    # KHÔNG dùng delivery_status vì NV tính shipper-thực-nhận = lúc bàn giao, không chờ ĐVVC quét).
    # Đã xác nhận = baseline phễu, phải ≥ mọi bước sau. = đơn xác nhận HÔM NAY (tạo vận đơn)
    # HỢP đơn SÓT (xác nhận hôm trước, hôm nay mới đóng gói/xuất kho). Nếu chỉ đếm shipment_created
    # ==today thì đơn sót có video/đóng gói hôm nay bị bỏ → "video > đã xác nhận" (vô lý).
    xac_nhan = sum(1 for o in open_orders if _today_pipeline(o))
    xac_nhan += sum(1 for o in huy_goi_orders if _today_pipeline(o))
    # Tách: xác nhận HÔM NAY (tạo vận đơn hôm nay) vs đơn SÓT hôm trước (xử lý hôm nay nhưng
    # tạo vận đơn hôm trước). Tổng = xác nhận hôm nay + sót hôm trước = "tổng đơn cần gửi".
    xac_nhan_today = sum(1 for o in open_orders
                         if _vn_date_of(f0(o).get("shipment_created_on")) == today)
    xac_nhan_today += sum(1 for o in huy_goi_orders
                          if _vn_date_of(f0(o).get("shipment_created_on")) == today)
    xot_truoc = max(0, xac_nhan - xac_nhan_today)
    funnel = {
        "xac_nhan": xac_nhan,                    # = tổng đơn cần gửi hôm nay (baseline phễu)
        "xac_nhan_today": xac_nhan_today,        # xác nhận HÔM NAY (tạo vận đơn hôm nay)
        "xot_truoc": xot_truoc,                  # đơn SÓT hôm trước (xử lý hôm nay)
        "soan": None,                            # đã in phiếu nhặt qua dashboard (picklog, gắn ở app.py)
        "dong_goi": tot["dong_goi"],             # đóng gói (gồm hủy) = 89
        "base": hist["tong_don"],                # đợt soạn (89) — baseline so lệch video
        "video": None,                           # đóng gói có video (gắn ở app.py)
        "dvvc_nhan": tot["shipper_nhan"],        # shipper THỰC NHẬN = ĐVVC đã xác nhận lấy = 84
        "huy": tot["huy"],
        "con_xot": len(con_xot_packed) + len(con_xot_unpacked),  # xác nhận nhưng chưa giao shipper
    }
    return {
        "date": today.strftime("%d/%m/%Y"),
        "by_carrier": rows,
        "totals": tot,
        "funnel": funnel,
        "batches": hist["batches"],
        "tong_don_soan": hist["tong_don"],
        "tong_sp_soan": hist["tong_sp"],
        "huy_da_goi": huy_total,
        "huy_detail": huy_detail,
        "huy_all_detail": huy_all_detail,
        "con_xot_packed": con_xot_packed,
        "con_xot_unpacked": con_xot_unpacked,
        "nhap_kho": nhap_kho,
        "dong_goi_codes": dong_goi_codes,
        "huy_goi_codes": huy_goi_codes,
        "dong_goi_order_codes": dong_goi_order_codes,
    }


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
    excl_today = excl_yest = excl_week = 0   # đơn khách đặt CHƯA xử lý đã hủy -> loại

    for o in orders:
        d = _vn_date_of(o.get("created_on"))
        if not d or d < week_start or d > today:
            continue
        # Loại đơn khách đặt nhưng CHƯA xử lý (chưa có vận đơn) đã bị HỦY
        if o.get("cancelled_on") and not (o.get("fulfillments") or [{}])[0].get("shipment_created_on"):
            if d == today:
                excl_today += 1
            elif d == yest:
                excl_yest += 1
            excl_week += 1
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

    # Trừ đơn hủy-chưa-xử-lý khỏi "đơn đặt" (giữ đơn đã xử lý dù sau đó hủy)
    don_today = max(0, don_today - excl_today)
    don_yest = max(0, don_yest - excl_yest)
    don_week = max(0, don_week - excl_week)

    # ---- PHỄU GIAO HÀNG HÔM NAY: quét đơn open theo TRẠNG THÁI HIỆN TẠI ----
    # Đếm theo NGÀY XÁC NHẬN / ĐÓNG GÓI / XUẤT VC (không phụ thuộc ngày tạo đơn).
    open_orders = []
    for p in range(1, 30):
        rows = fetch_json("/admin/orders.json", limit=250, page=p, status="open").get("orders", [])
        if not rows:
            break
        open_orders += rows

    # Phễu "Đơn cần giao hôm nay": Tổng = Mới + Sót = Đã giao shipper + Còn chưa giao
    cg = {"tong": 0, "moi": 0, "sot": 0, "da_xac_nhan": 0, "da_dong": 0,
          "shipper_nhan": 0, "chua_giao": 0, "hoa_toc": 0, "cho_xac_nhan": 0}
    cg_tracks = []
    dvvc = {}
    al = {"conf_after18": 0, "late_confirm": 0, "express_pending": 0}
    sot_list = []
    _fmtvn = lambda x: (_parse_vn(x).strftime("%d/%m %H:%M") if _parse_vn(x) else "")

    for o in open_orders:
        f = (o.get("fulfillments") or [{}])[0]
        ss = f.get("shipment_status")
        is_express = o.get("shipment_category") == "express"
        # "Ngày xử lý" = lúc TẠO VẬN ĐƠN = thời gian xác nhận của shop
        xuly_vn = _parse_vn(f.get("shipment_created_on") or f.get("created_on"))
        xuly_d = xuly_vn.date() if xuly_vn else None
        issued_today = _vn_date_of(f.get("issued_on")) == today

        # Cảnh báo xử lý sau 18h (theo Ngày xử lý hôm nay)
        if xuly_d == today and xuly_vn.hour >= 18:
            al["conf_after18"] += 1
            _cre = _parse_vn(o.get("created_on"))
            if _cre and _cre.date() == today and _cre.hour < 18:
                al["late_confirm"] += 1

        # Đơn CHỜ XÁC NHẬN = đơn mở CHƯA tạo vận đơn (chưa xử lý)
        if not f.get("shipment_created_on"):
            cg["cho_xac_nhan"] += 1

        # ĐƠN CẦN GIAO HÔM NAY = đang chờ giao (pending) HOẶC đã giao shipper HÔM NAY
        if not (xuly_vn and (ss == "pending"
                             or (ss in ("delivering", "delivered") and issued_today))):
            continue
        handed = ss != "pending"
        cg["tong"] += 1
        cg_tracks.append([f.get("tracking_number") or (f.get("tracking_numbers") or [None])[0],
                          o.get("name")])
        cg["moi" if xuly_d == today else "sot"] += 1
        cg["shipper_nhan" if handed else "chua_giao"] += 1
        if o.get("confirmed_on"):
            cg["da_xac_nhan"] += 1
        if f.get("packed_status") == "packed":
            cg["da_dong"] += 1
        if is_express:
            cg["hoa_toc"] += 1
            if not handed:
                al["express_pending"] += 1
        # Chi tiết đơn SÓT còn chưa giao (xử lý hôm trước, chưa giao)
        if xuly_d != today and not handed:
            sot_list.append({
                "Mã vận đơn": (f.get("tracking_number") or (f.get("tracking_numbers") or [None])[0]
                               or o.get("name") or ""),
                "ĐVVC": ((f.get("tracking_info") or {}).get("carrier_name")
                         or (o.get("shipping_lines") or [{}])[0].get("carrier_name") or "NB tự VC"),
                "Ngày xử lý": _fmtvn(f.get("shipment_created_on") or f.get("created_on")),
                "Trạng thái đóng": "Đã đóng" if f.get("packed_status") == "packed" else "Chờ đóng gói",
            })
        # Bảng phân bổ theo ĐVVC
        car = (o.get("shipping_lines") or [{}])[0].get("carrier_name") or "NB tự VC"
        e = dvvc.setdefault(car, {"dvvc": car, "total": 0, "thuong": 0,
                                  "hoatoc": 0, "da_giao": 0, "chua_giao": 0})
        e["total"] += 1
        e["hoatoc" if is_express else "thuong"] += 1
        e["da_giao" if handed else "chua_giao"] += 1
    cg["sot_list"] = sorted(sot_list, key=lambda x: x["Ngày xử lý"])
    cg["order_ids"] = [[c for c in ids if c] for ids in cg_tracks]

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
