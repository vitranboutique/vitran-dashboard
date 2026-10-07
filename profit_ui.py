"""profit_ui.py — Lợi nhuận gộp theo SKU / nhóm SKU (giá vốn lấy từ Sapo, đơn đọc từ KHO ĐỆM).

Không quét lại đơn từ Sapo: đơn đọc từ kho đệm (sapo_cache) — muốn mới hơn thì bấm
"🔄 Lấy đơn mới từ Sapo" ở sidebar. Chỉ gọi Sapo khi bấm "Lấy giá vốn từ Sapo" (≈53 SP → vài trang).

  Lợi nhuận gộp = Doanh thu net − Số lượng × Giá vốn − Phí sàn (ước tính theo % từng sàn)
  Doanh thu net của dòng = (tiền dòng sau giảm giá) × (1 − tiền hoàn / tổng đơn). Đơn hủy bị bỏ.
"""
from __future__ import annotations

import re
from collections import defaultdict
from datetime import datetime, timedelta, timezone

# Phí sàn MẶC ĐỊNH TẠM (chủ shop sửa theo báo cáo đối soát). Không phải số của sàn.
DEFAULT_FEES = {"TikTok": 10.0, "Shopee": 12.0, "Khác": 0.0}


def _num(v) -> float:
    try:
        return float(v)
    except Exception:
        return 0.0


def variant_cost(v: dict) -> tuple[float, str]:
    """Tìm GIÁ VỐN trong 1 variant của Sapo. Trả (giá, tên_trường) hoặc (0, "").
    Sapo đổi tên trường theo phiên bản nên dò theo từ khóa; ưu tiên 'giá vốn' hơn 'giá nhập'."""
    best = None
    for k, val in (v or {}).items():
        lk = str(k).lower()
        if lk in ("cost_price", "initial_cost", "avg_cost", "average_cost", "cost"):
            n = _num(val)
            if n > 0:
                return n, k
        if "import" in lk and "price" in lk and _num(val) > 0:
            best = best or (_num(val), k)
    for vp in (v or {}).get("variant_prices") or []:
        if not isinstance(vp, dict):
            continue
        nm = str(vp.get("name") or (vp.get("price_list") or {}).get("name") or "").lower()
        n = _num(vp.get("value") if vp.get("value") is not None else vp.get("price"))
        if n > 0 and any(w in nm for w in ("vốn", "von", "cost")):
            return n, f"variant_prices[{nm}]"
        if n > 0 and any(w in nm for w in ("nhập", "nhap", "import")):
            best = best or (n, f"variant_prices[{nm}]")
    return best if best else (0.0, "")


def fetch_costs(fetch_json, max_pages: int = 12) -> dict:
    """{'costs': {SKU_UPPER: giá vốn}, 'field': tên trường dùng, 'n_sku': số SKU thấy,
    'sample_keys': các khóa của 1 variant (để chẩn đoán khi không thấy giá vốn)}."""
    costs, n_sku, fields, sample_keys = {}, 0, defaultdict(int), []
    for p in range(1, max_pages + 1):
        chunk = (fetch_json("/admin/products.json", limit=250, page=p) or {}).get("products", [])
        if not chunk:
            break
        for prod in chunk:
            for v in prod.get("variants") or []:
                sku = str(v.get("sku") or "").strip().upper()
                if not sku:
                    continue
                n_sku += 1
                if not sample_keys:
                    sample_keys = sorted(v.keys())
                c, f = variant_cost(v)
                if c > 0:
                    costs[sku] = c
                    fields[f] += 1
        if len(chunk) < 250:
            break
    field = max(fields, key=fields.get) if fields else ""
    return {"costs": costs, "field": field, "n_sku": n_sku, "sample_keys": sample_keys}


def _channel_of(order: dict) -> str:
    name = str((order.get("channel_definition") or {}).get("branch_name")
               or order.get("source_name") or "").lower()
    if "tiktok" in name:
        return "TikTok"
    if "shopee" in name:
        return "Shopee"
    return "Khác"


def _vn_date(s):
    try:
        return (datetime.fromisoformat(str(s).replace("Z", "+00:00")).astimezone(
            timezone(timedelta(hours=7)))).date()
    except Exception:
        return None


def _group_of(sku: str) -> str:
    sku = str(sku or "?").strip().upper() or "?"
    try:
        from sapo_tools import parse_sku
        return parse_sku(sku).get("productCode") or sku.split("-")[0] or "?"
    except Exception:
        return sku.split("-")[0] or "?"


def compute(orders: dict | list, costs: dict, start, end, fees: dict, by_group: bool = True) -> dict:
    """Gom lợi nhuận gộp theo SKU/nhóm SKU trong [start, end]. orders = kho đệm {id: order}."""
    rows_in = orders.values() if isinstance(orders, dict) else orders
    acc = defaultdict(lambda: {"qty": 0, "rev": 0.0, "cogs": 0.0, "fee": 0.0, "qty_no_cost": 0, "rev_no_cost": 0.0})
    n_orders = 0
    for o in rows_in:
        if not isinstance(o, dict) or o.get("cancelled_on") or o.get("status") == "cancelled":
            continue
        d = _vn_date(o.get("created_on"))
        if not d or d < start or d > end:
            continue
        n_orders += 1
        tp = _num(o.get("total_price"))
        keep = max(0.0, min(1.0, (tp - _num(o.get("total_refunded"))) / tp)) if tp > 0 else 1.0
        fee_pct = _num(fees.get(_channel_of(o), 0.0)) / 100.0
        for li in o.get("line_items") or []:
            qty = int(round(_num(li.get("quantity"))))
            if qty <= 0:
                continue
            gross = _num(li.get("line_amount")) if li.get("line_amount") is not None \
                else _num(li.get("price")) * qty - _num(li.get("total_discount") or li.get("discount_amount"))
            rev = max(0.0, gross) * keep
            sku = str(li.get("sku") or "?").strip().upper() or "?"
            key = _group_of(sku) if by_group else sku
            a = acc[key]
            a["qty"] += qty
            a["rev"] += rev
            a["fee"] += rev * fee_pct
            c = costs.get(sku)
            if c:
                a["cogs"] += c * qty
            else:
                a["qty_no_cost"] += qty
                a["rev_no_cost"] += rev
    out = []
    for k, a in acc.items():
        full = a["qty_no_cost"] == 0
        has_any = a["qty_no_cost"] < a["qty"]
        profit = a["rev"] - a["cogs"] - a["fee"] if full else None
        out.append({
            "key": k, "qty": a["qty"], "rev": a["rev"], "cogs": a["cogs"], "fee": a["fee"],
            "profit": profit, "margin": (profit / a["rev"] * 100.0) if (profit is not None and a["rev"] > 0) else None,
            "missing_qty": a["qty_no_cost"], "partial": has_any and not full,
        })
    out.sort(key=lambda r: r["rev"], reverse=True)
    return {"rows": out, "n_orders": n_orders}


# ───────────────────────── Giao diện (Streamlit) ─────────────────────────
def render():
    import pandas as pd
    import streamlit as st
    import sapo_cache

    st.title("💰 Lợi nhuận gộp theo SKU")
    st.caption("Giá vốn lấy từ Sapo · đơn đọc từ kho đệm (không gọi lại Sapo mỗi lần mở) · "
               "đơn hủy bỏ, tiền hoàn đã trừ.")

    # 1) Giá vốn từ Sapo — chỉ gọi khi bấm
    c1, c2 = st.columns([1, 2])
    if c1.button("📥 Lấy giá vốn từ Sapo", width="stretch", key="profit_pull_cost"):
        try:
            from sapo_client import build_session, make_fetch_json
            with st.spinner("Đang lấy giá vốn từ Sapo…"):
                st.session_state["profit_costs"] = fetch_costs(make_fetch_json(build_session()))
                st.session_state["profit_costs_at"] = datetime.now(timezone(timedelta(hours=7)))
        except Exception as e:
            st.error(f"Không lấy được giá vốn: {type(e).__name__}: {str(e)[:150]}")
    info = st.session_state.get("profit_costs")
    if not info:
        c2.info("Bấm **Lấy giá vốn từ Sapo** để bắt đầu (chỉ vài lượt gọi).")
        return
    at = st.session_state.get("profit_costs_at")
    c2.caption(f"Lấy lúc {at:%H:%M %d/%m}: có giá vốn cho **{len(info['costs'])}/{info['n_sku']}** SKU"
               + (f" · trường dùng: `{info['field']}`" if info["field"] else ""))
    if not info["costs"]:
        st.error("Sapo không trả giá vốn trong dữ liệu sản phẩm. Các trường em thấy ở 1 variant: "
                 + ", ".join(info["sample_keys"]) + ". Chị gửi em tên trường giá vốn (hoặc ảnh màn hình "
                 "Sapo chỗ hiện giá vốn) để em chỉnh.")
        return

    # 2) Đơn từ kho đệm
    orders, upto = sapo_cache.load("orders")
    if not orders:
        st.warning("Kho đệm chưa có đơn. Bấm **🔄 Lấy đơn mới từ Sapo** ở sidebar (mục Đồng bộ dữ liệu chung).")
        return
    st.caption(f"Kho đệm có {len(orders):,} đơn, cập nhật tới {upto or '—'} (UTC).")

    # 3) Tham số
    today = (datetime.now(timezone.utc) + timedelta(hours=7)).date()
    f1, f2, f3 = st.columns(3)
    preset = f1.selectbox("Kỳ", ["7 ngày qua", "30 ngày qua", "Tháng này", "Tùy chọn"], index=1, key="profit_range")
    if preset == "7 ngày qua":
        s, e = today - timedelta(days=6), today
    elif preset == "30 ngày qua":
        s, e = today - timedelta(days=29), today
    elif preset == "Tháng này":
        s, e = today.replace(day=1), today
    else:
        rng = f2.date_input("Từ – đến", (today - timedelta(days=29), today), key="profit_custom")
        s, e = (rng[0], rng[1]) if isinstance(rng, (tuple, list)) and len(rng) == 2 else (today - timedelta(days=29), today)
    by_group = f3.radio("Gộp theo", ["Nhóm SKU", "Từng SKU"], horizontal=True, key="profit_group") == "Nhóm SKU"

    with st.expander("💸 Phí sàn ước tính (% doanh thu) — sửa theo báo cáo đối soát", expanded=False):
        st.caption("Số mặc định chỉ là ước tính tạm, KHÔNG phải số thật của sàn. Sapo không trả phí sàn.")
        fc = st.columns(3)
        fees = {
            "TikTok": fc[0].number_input("TikTok %", 0.0, 50.0, DEFAULT_FEES["TikTok"], 0.5, key="fee_tt"),
            "Shopee": fc[1].number_input("Shopee %", 0.0, 50.0, DEFAULT_FEES["Shopee"], 0.5, key="fee_sp"),
            "Khác": fc[2].number_input("Kênh khác %", 0.0, 50.0, DEFAULT_FEES["Khác"], 0.5, key="fee_ot"),
        }

    res = compute(orders, info["costs"], s, e, fees, by_group)
    rows = res["rows"]
    if not rows:
        st.info("Không có đơn trong kỳ này (hoặc kho đệm chưa phủ kỳ này).")
        return

    full = [r for r in rows if r["profit"] is not None]
    tot_rev = sum(r["rev"] for r in full)
    tot_profit = sum(r["profit"] for r in full)
    m = st.columns(4)
    m[0].metric("Đơn trong kỳ", f"{res['n_orders']:,}")
    m[1].metric("Doanh thu net (đủ giá vốn)", f"{tot_rev:,.0f} đ")
    m[2].metric("Lợi nhuận gộp", f"{tot_profit:,.0f} đ")
    m[3].metric("Biên lợi nhuận", f"{(tot_profit / tot_rev * 100):.1f}%" if tot_rev else "—")
    missing = [r for r in rows if r["profit"] is None]
    if missing:
        st.warning(f"{len(missing)} mục **chưa đủ giá vốn** — không tính vào tổng, tránh đọc nhầm: "
                   + ", ".join(r["key"] for r in missing[:12]) + (" …" if len(missing) > 12 else ""))

    df = pd.DataFrame([{
        ("Nhóm SKU" if by_group else "SKU"): r["key"],
        "SL bán": r["qty"],
        "Doanh thu net": round(r["rev"]),
        "Giá vốn": round(r["cogs"]) if r["profit"] is not None else None,
        "Phí sàn ước tính": round(r["fee"]) if r["profit"] is not None else None,
        "Lợi nhuận gộp": round(r["profit"]) if r["profit"] is not None else None,
        "Biên %": round(r["margin"], 1) if r["margin"] is not None else None,
        "SL thiếu giá vốn": r["missing_qty"],
    } for r in rows])
    st.dataframe(df, hide_index=True, width="stretch", height=min(620, 80 + 36 * len(df)))
    st.download_button("⬇️ Tải bảng (CSV)", df.to_csv(index=False).encode("utf-8-sig"),
                       file_name=f"loi_nhuan_{s}_{e}.csv", mime="text/csv")
