from __future__ import annotations

import math
import re
import unicodedata
from datetime import date, datetime, time, timedelta, timezone
from difflib import SequenceMatcher


SAPO_BASE = "https://vitranboutiquehcm.mysapo.net"
SIZE_ORDER = ["XS", "S", "M", "L", "XL"]
SIZE_SET = set(SIZE_ORDER)
ALL_PRICE_SIZES = ["XS", "S", "M", "L", "XL", "XXL"]


def _num(value, default=0.0) -> float:
    if value is None or value == "":
        return default
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().replace(",", "")
    try:
        return float(text)
    except Exception:
        digits = re.sub(r"[^\d.\-]", "", text)
        try:
            return float(digits) if digits else default
        except Exception:
            return default


def _int(value) -> int:
    return int(round(_num(value, 0)))


def money(value) -> int:
    return int(round(_num(value, 0)))


def normalize_sku(sku) -> str:
    return str(sku or "").strip().upper()


def _fold_text(value) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.upper().replace("Đ", "D")
    return re.sub(r"[^A-Z0-9]+", " ", text).strip()


def _variant_search_text(row: dict) -> str:
    return _fold_text(" ".join(str(row.get(k) or "") for k in (
        "sku", "product_name", "variant_name", "product_type", "tags", "barcode"
    )))


def _variant_score(row: dict, query: str) -> float:
    q = _fold_text(query)
    if not q:
        return 1
    sku = _fold_text(row.get("sku"))
    name = _fold_text(row.get("product_name"))
    variant = _fold_text(row.get("variant_name"))
    hay = " ".join(x for x in (sku, name, variant, _fold_text(row.get("product_type")), _fold_text(row.get("tags")), _fold_text(row.get("barcode"))) if x)
    compact_q = q.replace(" ", "")
    compact_sku = sku.replace(" ", "")
    words = [w for w in q.split() if w]
    score = 0.0
    if compact_q and compact_sku.startswith(compact_q):
        score += 120
    elif compact_q and compact_q in compact_sku:
        score += 95
    if q in hay:
        score += 80
    if words:
        matched = sum(1 for w in words if w in hay)
        score += matched / len(words) * 55
        if matched == len(words):
            score += 25
    score += SequenceMatcher(None, q, sku).ratio() * 35
    score += SequenceMatcher(None, q, name).ratio() * 30
    score += SequenceMatcher(None, q, f"{name} {variant}".strip()).ratio() * 25
    return score


def parse_sku(sku) -> dict:
    clean = normalize_sku(sku)
    if not clean:
        return {"sku": "", "productCode": "", "colorCode": "", "size": "", "productColorKey": "", "sortKey": ""}
    parts = [p.strip() for p in clean.split("-") if p.strip()]
    size = ""
    if parts and parts[-1].upper() in SIZE_SET:
        size = parts.pop().upper()
    product_code = parts[0].upper() if parts else clean
    color_code = "-".join(parts[1:]).upper() if len(parts) > 1 else ""
    product_color_key = " - ".join([p for p in (product_code, color_code) if p])
    return {
        "sku": clean,
        "productCode": product_code,
        "colorCode": color_code,
        "size": size,
        "productColorKey": product_color_key,
        "sortKey": f"{product_code}__{color_code}__{size}",
    }


def material_family(product_code) -> str:
    code = str(product_code or "").upper()
    if re.match(r"^(S|CVBC|GV|SB)", code):
        return "COTTON XỊN"
    if re.match(r"^(OL|OS)", code):
        return "THUN UMI"
    if re.match(r"^(A|TC|TD|CL|DD|DN|DDC1|DDDC1)", code):
        return "COTTON BORIP"
    return "KHÁC"


def cut_capacity(product_code) -> int:
    code = str(product_code or "").upper()
    if re.match(r"^(CVBC|GV)", code):
        return 100
    if re.match(r"^(OL|OS)", code):
        return 70
    if re.match(r"^(A|TC|TD|CL)", code):
        return 150
    if re.match(r"^D", code):
        return 76
    if re.match(r"^S", code) or re.match(r"^SB", code):
        return 150
    return 100


def fabric_color_group(parsed: dict) -> str:
    code = str((parsed or {}).get("productCode") or "").upper()
    raw = str((parsed or {}).get("colorCode") or "").upper()
    if code in {"SD", "CVBC", "SB"}:
        return "DE"
    if code == "ST":
        return "TR"
    return raw or "(không màu)"


def material_order(family) -> int:
    return {"COTTON XỊN": 1, "THUN UMI": 2, "COTTON BORIP": 3, "KHÁC": 9}.get(str(family or ""), 9)


def _round_qty(value, mode: str) -> int | float:
    if mode == "none":
        return value
    if mode == "round":
        return int(round(value))
    return int(math.ceil(value))


def _size_rank(size) -> int:
    s = str(size or "").upper()
    return SIZE_ORDER.index(s) + 1 if s in SIZE_ORDER else 99


def _size_need_text(items) -> str:
    parts = []
    for item in items:
        qty = _num(item.get("needQty"), 0)
        if qty <= 0:
            continue
        size = item.get("size") or "(không size)"
        ratio = _num(item.get("sizeRatio"), 0) * 100
        parts.append(f"{size}: {qty:,.0f} ({ratio:.1f}%)")
    return " • ".join(parts)


def _size_need_all_text(skus) -> str:
    total = sum(_num(x.get("needQty"), 0) for x in skus)
    by_size = {}
    for item in skus:
        size = str((item.get("parsed") or {}).get("size") or "").upper()
        if size:
            by_size[size] = by_size.get(size, 0) + _num(item.get("needQty"), 0)
    parts = []
    for size in SIZE_ORDER:
        qty = by_size.get(size, 0)
        ratio = (qty / total * 100) if total else 0
        parts.append(f"{size}: {ratio:.1f}% ({qty:,.0f})")
    return " • ".join(parts)


def _vn_now() -> datetime:
    return datetime.now(timezone.utc) + timedelta(hours=7)


def _date_to_utc_iso_vn(d: date, end_of_day=False) -> str:
    local_dt = datetime.combine(d, time(23, 59, 59) if end_of_day else time.min)
    utc_dt = local_dt - timedelta(hours=7)
    return utc_dt.replace(tzinfo=timezone.utc).isoformat().replace("+00:00", "")


def _created_vn_date(iso_str):
    """Đổi created_on (UTC ISO của Sapo) → NGÀY theo giờ VN (UTC+7). None nếu không đọc được."""
    s = str(iso_str or "").strip()
    if not s:
        return None
    s = s.replace("Z", "+00:00")
    dt = None
    for cand in (s, s[:19]):
        try:
            dt = datetime.fromisoformat(cand)
            break
        except Exception:
            continue
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return (dt.astimezone(timezone.utc) + timedelta(hours=7)).date()


def _extract_root(data: dict, *keys):
    for key in keys:
        val = data.get(key)
        if isinstance(val, list):
            return val
    return []


def get_catalog_variants(fetch_json, *, max_pages: int = 80, query: str | None = None) -> list[dict]:
    """Load Sapo product variants with SKU, current stock and current price."""
    variants: list[dict] = []
    seen = set()
    fields = "id,name,title,vendor,product_type,tags,variants,options,modified_on,published_on"
    for page in range(1, int(max_pages) + 1):
        params = {"limit": 250, "page": page, "fields": fields}
        if query:
            params["query"] = query
        data = fetch_json("/admin/products.json", **params)
        products = _extract_root(data, "products")
        if not products:
            break
        for product in products:
            pname = product.get("name") or product.get("title") or ""
            for var in (product.get("variants") or []):
                sku = normalize_sku(var.get("sku"))
                if not sku:
                    continue
                key = (sku, str(var.get("id") or ""))
                if key in seen:
                    continue
                seen.add(key)
                variants.append({
                    "sku": sku,
                    "variant_id": var.get("id"),
                    "product_id": product.get("id"),
                    "product_name": pname,
                    "variant_name": var.get("title") or var.get("variant_title") or "",
                    "price": money(var.get("price")),
                    "compare_at_price": money(var.get("compare_at_price")),
                    "inventory_quantity": _int(
                        var.get("inventory_quantity")
                        if var.get("inventory_quantity") is not None
                        else var.get("inventory_qty")
                    ),
                    "barcode": var.get("barcode") or "",
                    "vendor": product.get("vendor") or "",
                    "product_type": product.get("product_type") or "",
                    "tags": product.get("tags") or "",
                    "option1": var.get("option1") or "",
                    "option2": var.get("option2") or "",
                    "option3": var.get("option3") or "",
                    "modified_on": var.get("modified_on") or product.get("modified_on") or "",
                })
        if len(products) < 250:
            break
    return sorted(variants, key=lambda r: r["sku"])


def catalog_by_sku(variants: list[dict]) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for row in variants:
        sku = normalize_sku(row.get("sku"))
        if not sku:
            continue
        cur = out.setdefault(sku, {
            "sku": sku,
            "product_name": row.get("product_name") or "",
            "variant_name": row.get("variant_name") or "",
            "price": money(row.get("price")),
            "inventory_quantity": 0,
            "variants": [],
            "product_type": row.get("product_type") or "",
            "tags": row.get("tags") or "",
        })
        cur["inventory_quantity"] += _int(row.get("inventory_quantity"))
        if not cur.get("price") and row.get("price"):
            cur["price"] = money(row.get("price"))
        if not cur.get("product_name") and row.get("product_name"):
            cur["product_name"] = row.get("product_name") or ""
        if not cur.get("variant_name") and row.get("variant_name"):
            cur["variant_name"] = row.get("variant_name") or ""
        cur["variants"].append(row)
    return out


def movement_by_sku(rows: list[dict]) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for row in rows or []:
        sku = normalize_sku(row.get("variant_sku") or row.get("sku"))
        if not sku:
            continue
        cur = out.setdefault(sku, {
            "sku": sku,
            "product_title": row.get("product_title") or "",
            "variant_title": row.get("variant_title") or "",
            "product_type": row.get("product_type") or "",
            "product_vendor": row.get("product_vendor") or "",
            "opening_quantity": 0,
            "inward_quantity": 0,
            "outward_quantity": 0,
            "closing_quantity": 0,
            "opening_value": 0,
            "inward_value": 0,
            "outward_value": 0,
            "closing_value": 0,
        })
        for key in (
            "opening_quantity", "inward_quantity", "outward_quantity", "closing_quantity",
            "opening_value", "inward_value", "outward_value", "closing_value",
        ):
            cur[key] += _num(row.get(key), 0)
        for key in ("product_title", "variant_title", "product_type", "product_vendor"):
            if not cur.get(key) and row.get(key):
                cur[key] = row.get(key) or ""
    return out


def filter_variants(variants: list[dict], query: str, *, limit: int = 50) -> list[dict]:
    q = str(query or "").strip()
    if not q:
        return variants[:limit]
    scored = []
    for row in variants:
        score = _variant_score(row, q)
        if score >= 30:
            scored.append((score, row))
    scored.sort(key=lambda item: (
        -item[0],
        -int(_fold_text(item[1].get("sku")).replace(" ", "").startswith(_fold_text(q).replace(" ", ""))),
        str(item[1].get("sku") or ""),
    ))
    return [row for _, row in scored[:limit]]


def get_sales_by_sku(
    fetch_json,
    *,
    start_date: date,
    end_date: date,
    max_pages: int = 80,
    include_cancelled: bool = False,
) -> dict:
    sales: dict[str, dict] = {}
    total_orders = 0
    total_items = 0
    fields = "id,name,status,cancelled_on,created_on,source_name,line_items"
    stop = False
    for page in range(1, int(max_pages) + 1):
        # KHÔNG gửi status/financial_status/fulfillment_status="any": Sapo Open API
        # (key/secret) trả về RỖNG với "any". Bỏ đi → API trả TẤT CẢ đơn mọi trạng thái;
        # đơn hủy được lọc bằng tay bên dưới.
        rows = fetch_json(
            "/admin/orders.json",
            limit=250,
            page=page,
            created_on_min=_date_to_utc_iso_vn(start_date),
            created_on_max=_date_to_utc_iso_vn(end_date, end_of_day=True),
            fields=fields,
        ).get("orders", []) or []
        if not rows:
            break
        for order in rows:
            # Sapo Open API BỎ QUA created_on_min/max (trả cả ngoài khoảng) → tự lọc theo
            # NGÀY giờ VN. Đơn xếp mới→cũ nên gặp đơn cũ hơn đầu kỳ thì DỪNG (khỏi kéo cả năm).
            cvd = _created_vn_date(order.get("created_on"))
            if cvd is not None:
                if cvd > end_date:
                    continue
                if cvd < start_date:
                    stop = True
                    continue
            if not include_cancelled and (order.get("status") == "cancelled" or order.get("cancelled_on")):
                continue
            total_orders += 1
            touched = set()
            for li in order.get("line_items") or []:
                sku = normalize_sku(li.get("sku"))
                if not sku:
                    continue
                qty = _int(li.get("quantity"))
                rec = sales.setdefault(sku, {
                    "sku": sku,
                    "qty": 0,
                    "orders": 0,
                    "revenue": 0,
                    "name": li.get("title") or sku,
                })
                rec["qty"] += qty
                rec["revenue"] += money(li.get("price")) * qty
                rec["name"] = rec.get("name") or li.get("title") or sku
                touched.add(sku)
                total_items += qty
            for sku in touched:
                sales[sku]["orders"] += 1
        if stop or len(rows) < 250:
            break
    return {
        "sales": sales,
        "total_orders": total_orders,
        "total_items": total_items,
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
    }


def _sum_by_sku_in_period(fetch_json, path, root_key, qty_keys, date_keys,
                          start_date: date, end_date: date, max_pages: int = 40) -> dict:
    """Cộng số lượng theo SKU từ các phiếu (nhập kho / trả hàng) trong khoảng ngày (giờ VN).

    API bỏ qua lọc ngày nên tự lọc bằng code; phiếu xếp mới→cũ nên gặp phiếu cũ hơn
    đầu kỳ thì dừng. qty_keys: thử lần lượt các field số lượng (lấy field đầu > 0)."""
    out: dict[str, float] = {}
    stop = False
    for page in range(1, int(max_pages) + 1):
        rows = fetch_json(path, limit=250, page=page).get(root_key, []) or []
        if not rows:
            break
        for doc in rows:
            if str(doc.get("status") or "").lower() in ("cancelled", "canceled") or doc.get("cancelled_on"):
                continue
            d = None
            for dk in date_keys:
                d = _created_vn_date(doc.get(dk))
                if d is not None:
                    break
            if d is not None:
                if d > end_date:
                    continue
                if d < start_date:
                    stop = True
                    continue
            for li in doc.get("line_items") or []:
                sku = normalize_sku(li.get("sku"))
                if not sku:
                    continue
                qty = 0.0
                for qk in qty_keys:
                    v = _num(li.get(qk))
                    if v:
                        qty = v
                        break
                if qty:
                    out[sku] = out.get(sku, 0.0) + qty
        if stop or len(rows) < 250:
            break
    return out


def get_inbound_by_sku(fetch_json, *, start_date: date, end_date: date, max_pages: int = 40) -> dict:
    """Nhập kho trong kỳ theo SKU, tách 2 nguồn:
      - ncc     : phiếu nhập kho (receive_inventories) = nhập từ nhà cung cấp.
      - returns : đơn trả hàng (order_returns) đã nhập lại kho (restocked).
    Trả {ncc:{sku:qty}, returns:{sku:qty}}."""
    ncc = _sum_by_sku_in_period(
        fetch_json, "/admin/receive_inventories.json", "receive_inventories",
        qty_keys=("quantity",), date_keys=("received_on", "created_on"),
        start_date=start_date, end_date=end_date, max_pages=max_pages)
    returns = _sum_by_sku_in_period(
        fetch_json, "/admin/order_returns.json", "order_returns",
        qty_keys=("restocked_quantity", "stocked_quantity"),
        date_keys=("returned_on", "completed_on", "created_on"),
        start_date=start_date, end_date=end_date, max_pages=max_pages)
    return {"ncc": ncc, "returns": returns}


def _csrf_token(html: str) -> str | None:
    m = re.search(r'<meta[^>]+name=["\']csrf-token["\'][^>]+content=["\']([^"\']+)["\']', html or "", re.I)
    if m:
        return m.group(1)
    m = re.search(r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+name=["\']csrf-token["\']', html or "", re.I)
    return m.group(1) if m else None


def _report_csrf_token(session) -> str | None:
    try:
        resp = session.get(
            f"{SAPO_BASE}/admin/reports/inventory_movement",
            headers={"Accept": "text/html,application/xhtml+xml"},
            timeout=30,
        )
        if resp.status_code < 400:
            return _csrf_token(resp.text or "")
    except Exception:
        return None
    return None


def _report_result_to_rows(result: dict) -> tuple[list[dict], dict, int]:
    columns = [c.get("field") if isinstance(c, dict) else str(c) for c in (result.get("columns") or [])]
    rows = []
    for raw in result.get("data") or []:
        if isinstance(raw, dict):
            rows.append(raw)
        else:
            rows.append({field: raw[idx] if idx < len(raw) else None for idx, field in enumerate(columns)})
    summary_raw = result.get("summary") or []
    if isinstance(summary_raw, dict):
        summary = summary_raw
    else:
        summary = {field: summary_raw[idx] if idx < len(summary_raw) else None for idx, field in enumerate(columns)}
    return rows, summary, int(result.get("count") or len(rows))


def post_report_query(session, query: str) -> tuple[list[dict], dict, int]:
    headers = {
        "Accept": "application/json, text/plain, */*",
        "X-Requested-With": "XMLHttpRequest",
        "X-Sapo-Client": "frontend",
    }
    token = _report_csrf_token(session)
    if token:
        headers["X-CSRF-Token"] = token
    resp = session.post(f"{SAPO_BASE}/admin/reports/query.json", data={"q": query}, headers=headers, timeout=60)
    resp.raise_for_status()
    data = resp.json() if resp.content else {}
    result = data.get("result") or data
    return _report_result_to_rows(result)


def _inventory_movement_query(start_date: date, end_date: date, *, limit: int, offset: int) -> str:
    show = ",".join([
        "opening_quantity", "opening_value",
        "inward_quantity", "inward_value",
        "outward_quantity", "outward_value",
        "closing_quantity", "closing_value",
    ])
    by = ",".join([
        "product_id", "variant_id", "product_title", "variant_title", "variant_sku",
        "variant_barcode", "variant_unit", "product_type", "product_vendor",
    ])
    return (
        f"SHOW {show} BY {by} FROM aggregate_inventory_movements "
        f"SINCE {start_date.isoformat()} UNTIL {end_date.isoformat()} "
        'WHERE variant_type == "normal" AND tracked == TRUE '
        f"ORDER BY variant_id DESC LIMIT {int(limit)} OFFSET {int(offset)}"
    )


def get_inventory_movement_rows(
    session,
    *,
    start_date: date,
    end_date: date,
    page_limit: int = 250,
    max_pages: int = 80,
) -> dict:
    rows: list[dict] = []
    summary: dict = {}
    total_count = 0
    page_limit = max(1, min(int(page_limit or 250), 500))
    for page in range(max(1, int(max_pages or 1))):
        query = _inventory_movement_query(start_date, end_date, limit=page_limit, offset=page * page_limit)
        chunk, summary, count = post_report_query(session, query)
        total_count = count or total_count
        rows.extend(chunk)
        if not chunk or len(rows) >= total_count or len(chunk) < page_limit:
            break
    return {
        "rows": rows,
        "summary": summary or {},
        "count": total_count or len(rows),
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
    }


def compute_production_forecast(
    variants: list[dict],
    sales: dict[str, dict],
    *,
    inventory_rows: list[dict] | None = None,
    data_months: int = 3,
    forecast_months: int = 1,
    safety_factor: float = 1.15,
    round_mode: str = "ceil",
) -> dict:
    data_months = max(1, int(data_months or 1))
    forecast_months = max(1, int(forecast_months or 1))
    safety_factor = max(0, float(safety_factor or 1))
    stock = catalog_by_sku(variants)
    movement = movement_by_sku(inventory_rows or []) if inventory_rows is not None else {}
    all_skus = sorted(set(stock) | set(sales) | set(movement))

    aggregated = []
    for sku in all_skus:
        cat = stock.get(sku) or {}
        sale = sales.get(sku) or {}
        mv = movement.get(sku) or {}
        parsed = parse_sku(sku)
        if inventory_rows is not None:
            total_out = _int(mv.get("outward_quantity"))
            total_in = _int(mv.get("inward_quantity"))
            ending_stock = _int(mv.get("closing_quantity")) if mv else _int(cat.get("inventory_quantity"))
        else:
            total_out = _int(sale.get("qty"))
            total_in = 0
            ending_stock = _int(cat.get("inventory_quantity"))
        avg_monthly_out = total_out / data_months
        avg_monthly_in = total_in / data_months
        target_stock = avg_monthly_out * forecast_months * safety_factor
        need_qty_raw = max(0, target_stock - ending_stock)
        need_qty = _round_qty(need_qty_raw, round_mode)
        family = material_family(parsed["productCode"])
        capacity = cut_capacity(parsed["productCode"])
        color_group = fabric_color_group(parsed)
        stock_cover = ending_stock / avg_monthly_out if avg_monthly_out > 0 else (999 if ending_stock > 0 else 0)
        aggregated.append({
            "sku": sku,
            "productName": mv.get("product_title") or cat.get("product_name") or sale.get("name") or "",
            "variantName": mv.get("variant_title") or cat.get("variant_name") or "",
            "price": money(cat.get("price")),
            "orders": _int(sale.get("orders")),
            "totalIn": total_in,
            "totalOut": total_out,
            "endingStock": ending_stock,
            "parsed": parsed,
            "family": family,
            "cutCapacity": capacity,
            "fabricColorGroup": color_group,
            "avgMonthlyOut": avg_monthly_out,
            "avgMonthlyIn": avg_monthly_in,
            "targetStock": target_stock,
            "needQtyRaw": need_qty_raw,
            "needQty": need_qty,
            "needFlag": _num(need_qty) > 0,
            "stockCoverMonths": stock_cover,
            "forecastNeedWindow": forecast_months * safety_factor,
            "outOfStock": ending_stock <= 0,
            "noSales": total_out <= 0,
            "rollsNeeded": math.ceil(_num(need_qty) / max(capacity, 1)) if _num(need_qty) > 0 else 0,
        })

    group_demand: dict[str, dict] = {}
    for item in aggregated:
        key = item["parsed"]["productColorKey"] or item["parsed"]["productCode"]
        rec = group_demand.setdefault(key, {"totalOut": 0, "totalNeed": 0, "count": 0})
        rec["totalOut"] += item["totalOut"]
        rec["totalNeed"] += _num(item["needQty"])
        rec["count"] += 1

    enhanced = []
    for item in aggregated:
        key = item["parsed"]["productColorKey"] or item["parsed"]["productCode"]
        group = group_demand.get(key) or {"totalOut": 0, "totalNeed": 0, "count": 1}
        if group["totalOut"] > 0:
            size_ratio = item["totalOut"] / group["totalOut"]
        elif group["totalNeed"] > 0:
            size_ratio = 1 / max(group["count"], 1)
        else:
            size_ratio = 0
        enhanced.append({
            **item,
            "sizeRatio": size_ratio,
            "sizeRatioText": f"{size_ratio * 100:.1f}%" if item["parsed"].get("size") else "100%",
        })

    enhanced.sort(key=lambda x: (
        material_order(x["family"]),
        x["parsed"]["productCode"],
        x["parsed"]["colorCode"],
        _size_rank(x["parsed"]["size"]),
        x["sku"],
    ))

    groups: dict[str, dict] = {}
    for item in enhanced:
        key = item["parsed"]["productColorKey"] or item["parsed"]["productCode"]
        rec = groups.setdefault(key, {
            "key": key,
            "productCode": item["parsed"]["productCode"],
            "colorCode": item["parsed"]["colorCode"],
            "fabricColorGroup": item["fabricColorGroup"],
            "family": item["family"],
            "cutCapacity": item["cutCapacity"],
            "skus": [],
            "totalNeed": 0,
            "totalOut": 0,
            "totalIn": 0,
            "totalStock": 0,
            "avgMonthlyOut": 0,
            "avgMonthlyIn": 0,
            "outSkuCount": 0,
            "zeroSalesSkuCount": 0,
            "sizeCount": 0,
            "name": item.get("productName") or "",
        })
        rec["skus"].append(item)
        rec["totalNeed"] += _num(item["needQty"])
        rec["totalOut"] += item["totalOut"]
        rec["totalIn"] += item["totalIn"]
        rec["totalStock"] += item["endingStock"]
        rec["avgMonthlyOut"] += item["avgMonthlyOut"]
        rec["avgMonthlyIn"] += item["avgMonthlyIn"]
        rec["outSkuCount"] += 1 if item["outOfStock"] else 0
        rec["zeroSalesSkuCount"] += 1 if item["noSales"] else 0
        rec["sizeCount"] += 1

    group_rows = []
    for rec in groups.values():
        out_rate = rec["outSkuCount"] / rec["sizeCount"] if rec["sizeCount"] else 0
        no_sales_rate = rec["zeroSalesSkuCount"] / rec["sizeCount"] if rec["sizeCount"] else 0
        stock_cover = rec["totalStock"] / rec["avgMonthlyOut"] if rec["avgMonthlyOut"] > 0 else (999 if rec["totalStock"] > 0 else 0)
        # Cần SX ≤ 5 cái → TỰ CẮT TAY (số nhỏ, cắt cả cây phí). Cần > 5 mới cắt cây:
        # bán ≥ 30/kỳ = bắt buộc, còn lại = gợi ý.
        manual = 0 < rec["totalNeed"] <= 5
        must = rec["totalNeed"] > 5 and rec["totalOut"] >= 30
        suggest = rec["totalNeed"] > 5 and rec["totalOut"] < 30
        rolls = math.ceil(rec["totalNeed"] / max(rec["cutCapacity"], 1)) if rec["totalNeed"] > 0 else 0
        size_text = _size_need_text([
            {"size": x["parsed"]["size"], "needQty": x["needQty"], "sizeRatio": x["sizeRatio"]}
            for x in rec["skus"]
        ])
        suggestion = "Đủ tồn" if rec["totalNeed"] <= 0 else ("Bắt buộc SX" if must else ("Gợi ý SX" if suggest else "Tự cắt tay"))
        group_rows.append({
            **rec,
            "outRate": out_rate,
            "noSalesRate": no_sales_rate,
            "stockCoverMonths": stock_cover,
            "sizeNeedText": size_text,
            "sizeNeedAllText": _size_need_all_text(rec["skus"]),
            "activeSizeText": " • ".join(f"{x['parsed']['size'] or '(không size)'} tồn {x['endingStock']:,.0f}" for x in rec["skus"]),
            "mustProduce": must,
            "suggestProduce": suggest,
            "manualCut": manual,
            "rollsNeeded": rolls,
            "suggestionType": suggestion,
        })
    group_rows.sort(key=lambda x: (material_order(x["family"]), -x["totalNeed"], -x["totalOut"], x["key"]))

    group_by_key = {g["key"]: g for g in group_rows}
    need_rows = []
    for item in enhanced:
        if not item["needFlag"]:
            continue
        key = item["parsed"]["productColorKey"] or item["parsed"]["productCode"]
        grp = group_by_key.get(key) or {}
        need_rows.append({
            **item,
            "mustProduce": bool(grp.get("mustProduce")),
            "suggestProduce": bool(grp.get("suggestProduce")),
            "manualCut": bool(grp.get("manualCut")),
            "groupRollsNeeded": grp.get("rollsNeeded") or 0,
        })
    need_rows.sort(key=lambda x: (
        material_order(x["family"]),
        -int(bool(x["mustProduce"])),
        int(bool(x["manualCut"])),
        -_num(x["needQty"]),
        x["sku"],
    ))

    family_map: dict[str, dict] = {}
    for g in [g for g in group_rows if g["totalNeed"] > 0]:
        rec = family_map.setdefault(g["family"], {
            "family": g["family"], "qty": 0, "rollQty": 0, "groupCount": 0,
            "mustCount": 0, "suggestCount": 0, "manualCount": 0,
        })
        rec["qty"] += g["totalNeed"]
        rec["rollQty"] += g["rollsNeeded"]
        rec["groupCount"] += 1
        rec["mustCount"] += 1 if g["mustProduce"] else 0
        rec["suggestCount"] += 1 if g["suggestProduce"] else 0
        rec["manualCount"] += 1 if g["manualCut"] else 0
    family_rows = sorted(family_map.values(), key=lambda x: (material_order(x["family"]), -x["qty"]))

    cut_map: dict[str, dict] = {}
    for g in [g for g in group_rows if g["totalNeed"] > 0 and not g["manualCut"]]:
        key = f"{g['family']}__{g['fabricColorGroup'] or '(không màu)'}"
        rec = cut_map.setdefault(key, {
            "family": g["family"], "colorCode": g["fabricColorGroup"] or "(không màu)",
            "totalNeed": 0, "totalRolls": 0, "groups": [],
        })
        rec["totalNeed"] += g["totalNeed"]
        rec["totalRolls"] += g["rollsNeeded"]
        rec["groups"].append(g)
    cut_batches = []
    for rec in cut_map.values():
        rec["groups"].sort(key=lambda x: -x["totalNeed"])
        cut_batches.append({
            **rec,
            "groupsText": " • ".join(
                f"{g['productCode']}{' - ' + g['colorCode'] if g['colorCode'] else ''}: "
                f"{g['totalNeed']:,.0f} cái • {g['rollsNeeded']:,.0f} cây • {g['sizeNeedText'] or 'không tách size'}"
                for g in rec["groups"]
            ),
        })
    cut_batches.sort(key=lambda x: (material_order(x["family"]), -x["totalNeed"]))

    out_skus = sorted([x for x in enhanced if x["outOfStock"]], key=lambda x: (-x["totalOut"], x["sku"]))
    zero_sales = sorted([x for x in enhanced if x["noSales"] and x["endingStock"] > 0], key=lambda x: (-x["endingStock"], x["sku"]))
    slow_stock = sorted(
        [x for x in enhanced if x["endingStock"] > 0 and x["avgMonthlyOut"] > 0 and x["stockCoverMonths"] > forecast_months * 2 and _num(x["needQty"]) <= 0],
        key=lambda x: (-x["stockCoverMonths"], -x["endingStock"], x["sku"]),
    )
    alerts = []
    alerts.append(f"Tổng tồn hiện tại: {sum(x['endingStock'] for x in enhanced):,.0f} • Tổng bán trong kỳ: {sum(x['totalOut'] for x in enhanced):,.0f}.")
    if out_skus:
        alerts.append(f"{len(out_skus):,.0f} SKU đang hết hàng; ưu tiên SKU có bán trong kỳ.")
    if zero_sales:
        alerts.append(f"{len(zero_sales):,.0f} SKU có tồn nhưng không phát sinh bán trong kỳ.")
    if slow_stock:
        alerts.append(f"{len(slow_stock):,.0f} SKU tồn đủ hơn {forecast_months * 2:g} tháng, cần kiểm tra link/ẩn sản phẩm.")

    return {
        "aggregated": enhanced,
        "needRows": need_rows,
        "familyRows": family_rows,
        "groupRows": group_rows,
        "cutBatchGroups": cut_batches,
        "outSkuList": out_skus,
        "zeroSalesList": zero_sales,
        "slowStockList": slow_stock,
        "critical": {
            "mustProduceGroups": [g for g in group_rows if g["mustProduce"]],
            "suggestGroups": [g for g in group_rows if g["suggestProduce"]],
            "manualCutGroups": [g for g in group_rows if g["manualCut"]],
            "cutBatchGroups": cut_batches,
            "alerts": alerts,
        },
        "meta": {
            "dataMonths": data_months,
            "forecastMonths": forecast_months,
            "safetyFactor": safety_factor,
            "roundMode": round_mode,
        },
    }


def get_production_forecast(
    fetch_json,
    *,
    data_months: int = 3,
    forecast_months: int = 1,
    safety_factor: float = 1.15,
    round_mode: str = "ceil",
    end_date: date | None = None,
    max_product_pages: int = 80,
    max_order_pages: int = 80,
    include_cancelled: bool = False,
) -> dict:
    end = end_date or _vn_now().date()
    start = end - timedelta(days=max(1, int(data_months or 1)) * 30)
    variants = get_catalog_variants(fetch_json, max_pages=max_product_pages)
    sales_payload = get_sales_by_sku(
        fetch_json,
        start_date=start,
        end_date=end,
        max_pages=max_order_pages,
        include_cancelled=include_cancelled,
    )
    result = compute_production_forecast(
        variants,
        sales_payload["sales"],
        data_months=data_months,
        forecast_months=forecast_months,
        safety_factor=safety_factor,
        round_mode=round_mode,
    )
    result["source"] = {
        "variant_count": len(variants),
        "sku_count": len(catalog_by_sku(variants)),
        "order_count": sales_payload["total_orders"],
        "sold_items": sales_payload["total_items"],
        "start_date": sales_payload["start_date"],
        "end_date": sales_payload["end_date"],
        "basis": "orders",
    }
    return result


def get_production_forecast_from_sapo_report(
    session,
    fetch_json,
    *,
    data_months: int = 3,
    forecast_months: int = 1,
    safety_factor: float = 1.15,
    round_mode: str = "ceil",
    end_date: date | None = None,
    max_product_pages: int = 80,
    max_report_pages: int = 80,
) -> dict:
    end = end_date or _vn_now().date()
    start = end - timedelta(days=max(1, int(data_months or 1)) * 30)
    variants = get_catalog_variants(fetch_json, max_pages=max_product_pages)
    movement = get_inventory_movement_rows(
        session,
        start_date=start,
        end_date=end,
        max_pages=max_report_pages,
    )
    result = compute_production_forecast(
        variants,
        {},
        inventory_rows=movement["rows"],
        data_months=data_months,
        forecast_months=forecast_months,
        safety_factor=safety_factor,
        round_mode=round_mode,
    )
    rows = movement.get("rows") or []
    result["source"] = {
        "variant_count": len(variants),
        "sku_count": len(catalog_by_sku(variants)),
        "movement_rows": len(rows),
        "movement_count": movement.get("count") or len(rows),
        "sold_items": _int(sum(_num(r.get("outward_quantity"), 0) for r in rows)),
        "inward_items": _int(sum(_num(r.get("inward_quantity"), 0) for r in rows)),
        "closing_items": _int(sum(_num(r.get("closing_quantity"), 0) for r in rows)),
        "start_date": movement["start_date"],
        "end_date": movement["end_date"],
        "basis": "inventory_movement_report",
    }
    return result


def extract_fabric_specs(*texts) -> dict:
    text = " ".join(str(x or "") for x in texts)
    norm = text.lower().replace(",", ".")
    width = None
    meters_per_kg = None
    for pat in (r"(?:khổ|kho|k)\s*[:=\-]?\s*(\d{2,3})(?:\s*cm)?", r"\b(\d{2,3})\s*cm\b"):
        m = re.search(pat, norm, re.I)
        if m:
            val = float(m.group(1))
            if 60 <= val <= 260:
                width = val
                break
    for pat in (r"(\d+(?:\.\d+)?)\s*(?:m/kg|m\s*/\s*kg|mét/kg|met/kg)", r"(\d+(?:\.\d+)?)\s*m\s*(?:1\s*)?kg"):
        m = re.search(pat, norm, re.I)
        if m:
            val = float(m.group(1))
            if 0 < val <= 20:
                meters_per_kg = val
                break
    return {"fabric_width_cm": width, "meters_per_kg": meters_per_kg}


def price_size_list(size_count: int, base_size: str) -> list[str]:
    if str(base_size or "").upper() == "FREESIZE" or int(size_count or 1) == 1:
        return ["FREESIZE"]
    size_count = max(1, min(6, int(size_count or 1)))
    return ALL_PRICE_SIZES[:size_count]


def calculate_selling_price(data: dict) -> dict:
    price_per_kg = _num(data.get("price_per_kg"))
    meters_per_kg = _num(data.get("meters_per_kg"))
    fabric_width_cm = _num(data.get("fabric_width_cm"))
    if price_per_kg <= 0 or meters_per_kg <= 0 or fabric_width_cm <= 0:
        raise ValueError("Thiếu giá vải, chiều dài/kg hoặc khổ vải.")
    meter_price = price_per_kg / meters_per_kg
    fabric_width_m = fabric_width_cm / 100
    size_list = price_size_list(int(data.get("size_count") or 5), str(data.get("base_size") or "M"))
    production_cost = sum(_num(data.get(k)) for k in (
        "cut_cost", "sewing_cost", "iron_pack_cost", "zipper_cost", "thread_cost", "tag_cost",
        "operation_cost", "button_cost", "elastic_cost", "glue_cost", "lace_cost", "other_cost",
    ))
    waste_rate = _num(data.get("waste_percent"), 0) / 100
    markup = _num(data.get("markup_multiplier"), 4)
    main_layers = _num(data.get("main_layers"), 1)
    lining_layers = _num(data.get("lining_layers"), 0)
    main_length = _num(data.get("main_length_cm"))
    main_width = _num(data.get("main_width_cm"))
    lining_length = _num(data.get("lining_length_cm"))
    lining_width = _num(data.get("lining_width_cm"))
    width_diff = _num(data.get("size_width_diff_cm"), 2)
    length_diff = _num(data.get("size_length_diff_cm"), 1)
    base_index = size_list.index("M") if "M" in size_list else max(0, len(size_list) // 2)
    rows = []
    for size in size_list:
        offset = 0 if size == "FREESIZE" else size_list.index(size) - base_index
        ml = max(main_length + offset * length_diff, 0)
        mw = max(main_width + offset * width_diff, 0)
        ll = max(lining_length + offset * length_diff, 0) if lining_layers > 0 else 0
        lw = max(lining_width + offset * width_diff, 0) if lining_layers > 0 else 0
        main_area = (ml / 100) * (mw / 100) * main_layers
        lining_area = (ll / 100) * (lw / 100) * lining_layers
        total_area = (main_area + lining_area) * (1 + waste_rate)
        fabric_meters = total_area / fabric_width_m if fabric_width_m else 0
        fabric_cost = fabric_meters * meter_price
        cost_price = fabric_cost + production_cost
        selling_price = cost_price * markup
        rows.append({
            "productSku": normalize_sku(data.get("product_sku")),
            "fabricSku": normalize_sku(data.get("fabric_sku")),
            "size": size,
            "mainLengthCm": ml,
            "mainWidthCm": mw,
            "liningLengthCm": ll,
            "liningWidthCm": lw,
            "totalAreaM2": total_area,
            "fabricMeters": fabric_meters,
            "fabricCost": fabric_cost,
            "productionCost": production_cost,
            "costPrice": cost_price,
            "sellingPrice": selling_price,
            "consumptionRatio": fabric_meters,
        })
    avg = lambda key: sum(row[key] for row in rows) / len(rows) if rows else 0
    return {
        "rows": rows,
        "summary": {
            "productSku": normalize_sku(data.get("product_sku")),
            "fabricSku": normalize_sku(data.get("fabric_sku")),
            "meterPrice": meter_price,
            "productionCost": production_cost,
            "avgFabricMeters": avg("fabricMeters"),
            "avgFabricCost": avg("fabricCost"),
            "avgCostPrice": avg("costPrice"),
            "avgSellingPrice": avg("sellingPrice"),
            "avgConsumptionRatio": avg("consumptionRatio"),
        },
    }
