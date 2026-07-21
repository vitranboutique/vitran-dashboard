"""
app.py — Dashboard "Báo cáo sáng" VITRAN BOUTIQUE HCM (Sapo → Streamlit + Plotly).

Chạy:  streamlit run app.py
DEMO:  tự bật khi chưa cấu hình credential (xem README để chuyển sang LIVE).
"""
import os
import json
import re
import time
import unicodedata
from datetime import date, datetime, timedelta, timezone
from html import escape as _esc
from urllib.parse import parse_qsl, quote_plus, urlencode, urlsplit, urlunsplit

import pandas as pd
import plotly.graph_objects as go
import requests
import streamlit as st
import streamlit.components.v1 as components
import streamlit_authenticator as stauth

import sapo_logic as L
import sapo_tools as PT
import customer_address_fix as CAF
import picklog
import dohana
import daily_report
import cham_cong
import cham_cong_ui
from sapo_address import resolve_address
from sapo_client import (
    SapoAuthError, build_session, credential_present, make_fetch_json,
    find_order_returns_by_codes, get_customer, get_order, get_order_return, parse_codes,
    update_order_customer_info, update_order_note, update_order_return_note,
    customer_exists_by_phone, update_customer_address_from_info, upsert_customer_from_info,
    find_orders_by_phone, update_customer_note_lines,
)
from picking_render import picking_html

# ───────── Tự nạp lại module logic mỗi lần chạy → sửa code là CÓ NGAY, khỏi Reboot ─────────
# app.py hot-reload khi push, nhưng module (sapo_logic, daily_report) thì Streamlit giữ bản cũ
# trong RAM tới khi Reboot. Reload tại đây để 2 module đó luôn chạy code mới nhất mà không cần
# Reboot. Chỉ reload 2 module THUẦN hàm/hằng (không giữ state, không gọi API ở cấp module) nên
# an toàn & nhẹ; KHÔNG reload dohana/picklog (giữ throttle/cache, tránh 429).
import importlib as _importlib
_RELOAD_ERR = ""
for _m in (L, daily_report):
    try:
        _importlib.reload(_m)
    except Exception as _e:            # lỗi hiếm; giữ bản đang chạy, ghi lại để hiện cảnh báo
        _RELOAD_ERR += f"{getattr(_m, '__name__', '?')}: {_e}\n"
# picklog: reload để có hàm MỚI ngay (khỏi Reboot), nhưng GIỮ _GID_CACHE để khỏi list lại gist mỗi rerun.
try:
    _gid_keep = getattr(picklog, "_GID_CACHE", None)
    _importlib.reload(picklog)
    if _gid_keep and not getattr(picklog, "_GID_CACHE", None):
        picklog._GID_CACHE = _gid_keep
except Exception as _e:
    _RELOAD_ERR += f"picklog: {_e}\n"

# ───────────────────────── Cấu hình trang ─────────────────────────
st.set_page_config(
    page_title="VITRAN BOUTIQUE",
    page_icon="🛍️",
    layout="wide",
)

# ───────────────────────── Bảng màu (đồng bộ báo cáo PNG) ─────────────────────────
COLOR_SOURCE = {"tiktokshop": "#161823", "shopee": "#EE4D2D"}   # TikTok đen, Shopee cam
SOURCE_LABEL = {"tiktokshop": "TikTok Shop", "shopee": "Shopee"}
COLOR_CARRIER = {
    "J&T Express": "#E2231A", "SPX Express": "#F26922", "SPX Instant": "#FB8C00",
    "Giao Hàng Nhanh": "#F9A825", "GHN": "#F9A825", "Hỏa Tốc": "#D32F2F",
    "Nhanh": "#1E88E5", "NB tự VC": "#888780", "Viettel Post": "#E4002B",
    "Ninja Van": "#C62828", "Best Express": "#1565C0", "Chưa rõ": "#B0BEC5",
}
# Palette cho gian hàng (không có màu thương hiệu cố định)
PALETTE = ["#534AB7", "#1D9E75", "#BA7517", "#E24B4A", "#378ADD",
           "#639922", "#D85A30", "#7B1FA2", "#00897B", "#5D4037", "#C2185B"]
ACCENT_ORANGE = "#BA7517"   # phần Chờ xác nhận
ACCENT_RED = "#E24B4A"      # phần Đơn hủy
ACCENT_BLUE = "#378ADD"     # phần Đơn trả
SHOPEE_RETURN_LIST_URL = "https://banhang.shopee.vn/portal/sale/returnrefundcancel"
SHOPEE_RETURN_SEARCH_URL = SHOPEE_RETURN_LIST_URL + "?keyword={}"
SHOPEE_ORDER_LIST_URL = "https://banhang.shopee.vn/portal/sale/order"
SHOPEE_ORDER_SEARCH_URL = SHOPEE_ORDER_LIST_URL + "?search={}"
SHOPEE_LOCAL_LAUNCHER_URL = os.environ.get("VITRAN_SHOPEE_LAUNCHER_URL", "http://127.0.0.1:17654/open").strip()
SHOPEE_SHOP_CONTEXT_IDS = {
    "smoss": "58785946",
    "mun-ai": "736667756",
    "mun ai": "736667756",
    "vitran boutique": "179402721",
    "vitranboutique": "179402721",
}
TIKTOK_ORDER_LIST_URL = "https://seller-vn.tiktok.com/order?selected_sort=6&tab=all"
TIKTOK_ORDER_SEARCH_URL = TIKTOK_ORDER_LIST_URL + "&main_order_id={}"
TIKTOK_TICKET_LIST_URL = "https://seller-vn.tiktok.com/ticket?shop_region=VN"


def _plain_text_key(value):
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return re.sub(r"\s+", " ", text).strip().lower()


def _url_query_value(url, *names):
    wanted = {str(n).lower() for n in names}
    try:
        pairs = parse_qsl(urlsplit(str(url or "")).query, keep_blank_values=True)
    except Exception:
        return ""
    for key, value in pairs:
        if key.lower() in wanted:
            return value
    return ""


def _with_url_query(url, **params):
    url = str(url or "").strip()
    if not url:
        return ""
    try:
        parts = urlsplit(url)
    except Exception:
        return url
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    for key, value in params.items():
        if value not in (None, ""):
            query[key] = str(value)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))


def _shopee_shop_context_id(row_or_text):
    if isinstance(row_or_text, dict):
        raw = " ".join(str(row_or_text.get(k) or "") for k in (
            "gian_hang", "Gian hàng", "Gian hÃ ng", "order_source", "store", "branch",
            "order_link", "return_link",
        ))
    else:
        raw = str(row_or_text or "")
    text = _plain_text_key(raw)
    if "58785946" in text or "smoss" in text:
        return SHOPEE_SHOP_CONTEXT_IDS["smoss"]
    if "736667756" in text or ("mun" in text and ("ai" in text or "official" in text or "partnership" in text)):
        return SHOPEE_SHOP_CONTEXT_IDS["mun-ai"]
    if "179402721" in text or "vitran boutique" in text or "vitranboutique" in text:
        return SHOPEE_SHOP_CONTEXT_IDS["vitran boutique"]
    return ""


def _with_shopee_shop_context(url, row_or_text=None):
    url = str(url or "").strip()
    if "banhang.shopee.vn/portal/sale/" not in url:
        return url
    shop_id = _shopee_shop_context_id(row_or_text) or _url_query_value(url, "cnsc_shop_id", "cnscShopId")
    if not shop_id:
        return url
    return _with_url_query(url, cnsc_shop_id=shop_id)


def _shopee_chrome_launcher_url(url, row_or_text=None):
    url = _with_shopee_shop_context(url, row_or_text)
    if not SHOPEE_LOCAL_LAUNCHER_URL or "banhang.shopee.vn/portal/sale/" not in url:
        return url
    shop_id = _shopee_shop_context_id(row_or_text) or _url_query_value(url, "cnsc_shop_id", "cnscShopId")
    if not shop_id:
        return url
    return _with_url_query(SHOPEE_LOCAL_LAUNCHER_URL, shop_id=shop_id, target=url)


def _is_shopee_chrome_launcher_url(url):
    return bool(SHOPEE_LOCAL_LAUNCHER_URL and str(url or "").startswith(SHOPEE_LOCAL_LAUNCHER_URL))


def _shopee_return_url(return_code=""):
    code = str(return_code or "").strip()
    if not code:
        return SHOPEE_RETURN_LIST_URL
    return SHOPEE_RETURN_SEARCH_URL.format(quote_plus(code))


def _normalize_shopee_return_link(url, fallback_code=""):
    url = str(url or "").strip()
    if "banhang.shopee.vn/portal/sale/return" not in url:
        return url
    if re.search(r"/portal/sale/return/\d+", url):
        return url
    code = _url_query_value(url, "keyword", "search", "query") or str(fallback_code or "").strip()
    normalized = _shopee_return_url(code)
    shop_id = _url_query_value(url, "cnsc_shop_id", "cnscShopId")
    return _with_url_query(normalized, cnsc_shop_id=shop_id) if shop_id else normalized


def _shopee_order_url(order_code=""):
    code = str(order_code or "").strip()
    if not code:
        return SHOPEE_ORDER_LIST_URL
    return _with_url_query(SHOPEE_ORDER_LIST_URL, search=code, keyword=code)


def _normalize_shopee_order_link(url):
    url = str(url or "").strip()
    if "banhang.shopee.vn/portal/sale/order" not in url:
        return url
    if re.search(r"/portal/sale/order/\d+", url):
        return url
    code = _url_query_value(url, "search", "keyword")
    if code:
        normalized = _shopee_order_url(code)
        shop_id = _url_query_value(url, "cnsc_shop_id", "cnscShopId")
        return _with_url_query(normalized, cnsc_shop_id=shop_id) if shop_id else normalized
    return url


def _tiktok_order_url(order_code=""):
    code = str(order_code or "").strip()
    if not code:
        return TIKTOK_ORDER_LIST_URL
    return TIKTOK_ORDER_SEARCH_URL.format(quote_plus(code))


def _normalize_tiktok_order_link(url):
    url = str(url or "").strip()
    if "seller-vn.tiktok.com/order" not in url:
        return url
    if "seller-vn.tiktok.com/order/return" in url:
        return url
    match = re.search(r"(?:[?&](?:main_order_id|order_no|search_numbers)=|/order/detail/)([^&#/]+)", url)
    if match:
        return _tiktok_order_url(match.group(1))
    if "seller-vn.tiktok.com/order/detail" in url:
        return TIKTOK_ORDER_LIST_URL
    return url

# ───────────────────────── CSS nhẹ (viền trái màu, tiêu đề mục) ─────────────────────────
def _norm_marketplace_code(value):
    return re.sub(r"[^A-Z0-9]+", "", str(value or "").upper())


def _same_marketplace_code(a, b):
    left = _norm_marketplace_code(a)
    right = _norm_marketplace_code(b)
    return bool(left and right and left == right)


def _display_return_code(row, order_code=None, return_code=None):
    row = row or {}
    order = order_code if order_code is not None else (
        row.get("order_code") or row.get("Mã đơn") or row.get("MÃ£ Ä‘Æ¡n") or row.get("ma_don")
    )
    ret = return_code if return_code is not None else (
        row.get("return_code") or row.get("Mã trả") or row.get("MÃ£ tráº£") or row.get("ma_tra")
    )
    return "" if _same_marketplace_code(order, ret) else str(ret or "").strip()


st.markdown(
    """
    <style>
      .block-container { padding-top: 2rem; }
      .sec {
        border-left: 6px solid #ccc; padding: 8px 0 4px 16px;
        margin: 10px 0 6px 0; font-size: 1.35rem; font-weight: 700;
      }
      .sec-orange { border-color: #BA7517; color: #BA7517; }
      .sec-red    { border-color: #E24B4A; color: #E24B4A; }
      .sec-blue   { border-color: #378ADD; color: #378ADD; }
      .sub { color: #6b6b6b; font-size: .95rem; font-weight: 400; }
      .ic { cursor: help; color: #9aa3ab; font-size: .82em; margin-left: 5px; font-weight: 400;
            border: 1px solid #c7ccd1; border-radius: 50%; padding: 0 5px; }
      .ic:hover { color: #fff; background: #6b6b6b; border-color: #6b6b6b; }

      /* ====== PHONG CÁCH SAPO: nền xám, thẻ trắng bo góc, số to ====== */
      .stApp { background: #f4f6f8; }
      [data-testid="stMetric"] {
        background: #ffffff; border: 1px solid #e8eaed; border-radius: 12px;
        padding: 14px 16px 12px; box-shadow: 0 1px 3px rgba(16,24,40,.06);
      }
      [data-testid="stMetricLabel"] p { color: #6b7280; font-size: .82rem; font-weight: 600; }
      [data-testid="stMetricValue"] { font-size: 1.9rem !important; font-weight: 800; color: #111827; }
      [data-testid="stHorizontalBlock"] { gap: 12px; }
      h1 { color: #111827; font-weight: 900; letter-spacing: .3px; }
      [data-testid="stDataFrame"] { border: 1px solid #e8eaed; border-radius: 12px; }

      /* ====== SIDEBAR TỐI KIỂU SAPO (navy) ====== */
      section[data-testid="stSidebar"] { background: #16233f; }
      section[data-testid="stSidebar"] h1,
      section[data-testid="stSidebar"] h2,
      section[data-testid="stSidebar"] h3,
      section[data-testid="stSidebar"] [data-testid="stWidgetLabel"] p,
      section[data-testid="stSidebar"] [data-testid="stMarkdownContainer"] p,
      section[data-testid="stSidebar"] label p,
      section[data-testid="stSidebar"] label span { color: #e3e9f3 !important; }
      section[data-testid="stSidebar"] [data-testid="stCaptionContainer"] p,
      section[data-testid="stSidebar"] small { color: #9fb0cc !important; }
      section[data-testid="stSidebar"] hr { border-color: rgba(255,255,255,.14) !important; }
      section[data-testid="stSidebar"] [data-testid="stExpander"] { border-color: rgba(255,255,255,.18) !important; }
      section[data-testid="stSidebar"] .stButton button {
        background: rgba(255,255,255,.10) !important; border: 1px solid rgba(255,255,255,.28) !important;
        color: #fff !important;
      }
      section[data-testid="stSidebar"] .stButton button:hover {
        background: rgba(255,255,255,.20) !important; border-color: rgba(255,255,255,.5) !important;
      }
      section[data-testid="stSidebar"] .stButton button p { color: #fff !important; }

      /* ====== TỰ ĐỘNG: GIAO DIỆN ĐIỆN THOẠI (màn hình ≤ 640px) ====== */
      @media (max-width: 640px) {
        .block-container { padding: 1rem 0.6rem 2.5rem 0.6rem !important; }
        h1 { font-size: 1.4rem !important; line-height: 1.25 !important; }
        .sec { font-size: 1.05rem !important; padding-left: 10px !important; }
        /* Mặc định: mọi cột xếp DỌC -> biểu đồ tràn full màn hình */
        div[data-testid="stHorizontalBlock"] {
          flex-direction: column !important; gap: 0.4rem !important;
        }
        div[data-testid="stHorizontalBlock"] > div[data-testid="stColumn"],
        div[data-testid="stHorizontalBlock"] > div[data-testid="column"] {
          width: 100% !important; flex: 1 1 100% !important; min-width: 0 !important;
        }
        /* Riêng hàng số liệu: xếp 2 ô/hàng cho gọn (máy hỗ trợ :has) */
        div[data-testid="stHorizontalBlock"]:has(div[data-testid="stMetric"]) {
          flex-direction: row !important; flex-wrap: wrap !important;
        }
        div[data-testid="stHorizontalBlock"]:has(div[data-testid="stMetric"]) > div[data-testid="stColumn"],
        div[data-testid="stHorizontalBlock"]:has(div[data-testid="stMetric"]) > div[data-testid="column"] {
          flex: 1 1 44% !important; width: auto !important; min-width: 42% !important;
        }
        div[data-testid="stMetricValue"] { font-size: 1.5rem !important; }
      }

      /* ====== IN A4 / PDF (chỉ áp dụng khi in) ====== */
      .print-only { display: none; }
      @media print {
        @page { size: A4 portrait; margin: 12mm; }
        section[data-testid="stSidebar"], [data-testid="stToolbar"], [data-testid="stHeader"],
        [data-testid="stStatusWidget"], iframe, [data-testid="stAlert"] { display: none !important; }
        .block-container { padding: 0 !important; max-width: 100% !important; }
        /* In bảng HTML đầy đủ thay cho dataframe dạng canvas */
        .print-only { display: block !important; margin: 4px 0 10px; }
        [data-testid="stDataFrame"] { display: none !important; }
        .print-only table { width: 100%; border-collapse: collapse; font-size: 11px; }
        .print-only th, .print-only td { border: 1px solid #ccc; padding: 3px 6px; text-align: left; }
        .print-only th { background: #f3f3f3; }
        div[data-testid="stHorizontalBlock"], [data-testid="stPlotlyChart"] { break-inside: avoid; }
        .sec { break-after: avoid; }
        .ctab-wrap { display: none !important; }
      }

      /* ====== BẢNG GỌN (compact HTML table) ====== */
      .ctab-wrap { max-height: 360px; overflow: auto; border: 1px solid #e8eaed; border-radius: 10px; margin: 2px 0 6px; }
      .ctab { width: 100%; border-collapse: collapse; font-size: .78rem; }
      .ctab th, .ctab td { padding: 3px 8px; border-bottom: 1px solid #eef0f3; text-align: left; vertical-align: top; }
      .ctab thead th { position: sticky; top: 0; background: #f4f6f8; font-weight: 700; color: #374151; z-index: 1; white-space: nowrap; }
      .ctab tbody tr:hover { background: #fafbfc; }
      .ctab tr.hl td { background: #fdecea; color: #b3261e; font-weight: 700; }
      .ctab td.num { text-align: right; white-space: nowrap; }

      /* ====== POPUP CẢNH BÁO cố định (mọi trang, trượt không mất) ====== */
      .alert-pop { position: fixed; right: 14px; bottom: 76px; z-index: 99999;
        width: 240px; max-width: 70vw; background: #fff5f5; border: 2px solid #e24b4a;
        border-radius: 12px; box-shadow: 0 6px 22px rgba(180,30,30,.28); overflow: hidden;
        font-family: system-ui,-apple-system,Segoe UI,Roboto,Arial,sans-serif; }
      .alert-pop summary { list-style: none; cursor: pointer; padding: 8px 12px;
        background: #e24b4a; color: #fff; font-weight: 800; font-size: .9rem;
        display: flex; align-items: center; justify-content: space-between; }
      .alert-pop summary::-webkit-details-marker { display: none; }
      .alert-pop .body { padding: 8px 12px 10px; font-size: .82rem; }
      .alert-pop .row { display: flex; justify-content: space-between; gap: 8px; padding: 3px 0;
        border-bottom: 1px dashed #f1c9c7; }
      .alert-pop .row:last-child { border-bottom: 0; }
      .alert-pop .v { font-weight: 800; color: #9aa0a6; }
      .alert-pop .v.hot { color: #b3261e; }
      .alert-pop .ok { color: #1e7d3c; font-weight: 700; padding: 6px 2px; }
      .st-key-ttkh_save_float {
        position: fixed !important; right: 14px; bottom: 184px; z-index: 100000;
        width: 260px !important; max-width: 72vw; background: #f7fbff;
        border: 2px solid #378ADD; border-radius: 12px;
        box-shadow: 0 6px 22px rgba(30,100,180,.22); padding: 0 10px 10px;
      }
      .st-key-ttkh_save_float .stButton button {
        background: #378ADD !important; color: #fff !important; border-color: #378ADD !important;
        font-weight: 800 !important; width: 100%;
      }
      .st-key-ttkh_save_float .stButton button p { color: #fff !important; }
      @media (max-width: 640px) { .alert-pop { width: 190px; right: 8px; bottom: 72px; } }
      @media (max-width: 640px) { .st-key-ttkh_save_float { width: 210px !important; right: 8px; bottom: 180px; } }
      @media print { .alert-pop { display: none !important; } }
      @media print { .st-key-ttkh_save_float { display: none !important; } }
    </style>
    """,
    unsafe_allow_html=True,
)


def _video_audit_anchor(day, kind):
    base = re.sub(r"[^A-Za-z0-9_-]+", "-", str(day or "unknown")).strip("-").lower()
    return f"audit-{base or 'unknown'}-{kind}"


def _video_audit_num(value):
    try:
        return int(value or 0)
    except Exception:
        return 0


def _video_audit_chip(icon, n, day, kind, fg, bgc, tip):
    n = _video_audit_num(n)
    if n <= 0:
        return ""
    anchor_id = _video_audit_anchor(day, kind)
    return (
        f'<span title="{_esc(tip)}" style="display:inline-flex;align-items:center;gap:3px;'
        f'margin:2px 3px 2px 0;padding:2px 6px;border-radius:999px;background:{bgc};'
        f'color:{fg};font-weight:900;white-space:nowrap"><span aria-hidden="true">{_esc(icon)}</span>'
        f'<a href="#{anchor_id}" style="color:{fg};text-decoration:underline;text-underline-offset:2px">{n}</a></span>'
    )


def _video_audit_chot_html(row=None, chot="", day=""):
    if row is None:
        row = {}
    day = day or row.get("Ngày") or row.get("Ngay") or row.get("iso")
    chips = "".join([
        _video_audit_chip("🎥📦-", row.get("Đóng thiếu SL"), day, "pkg-miss", "#b91c1c", "#fee2e2", "Thiếu video đóng hàng"),
        _video_audit_chip("🎥📦+", row.get("Đóng dư SL"), day, "pkg-extra", "#1d4ed8", "#dbeafe", "Dư video đóng hàng"),
        _video_audit_chip("🎥↩-", row.get("Hoàn thiếu SL"), day, "ret-miss", "#b91c1c", "#fee2e2", "Thiếu video khui hoàn"),
        _video_audit_chip("🎥↩+", row.get("Hoàn dư SL"), day, "ret-extra", "#1d4ed8", "#dbeafe", "Dư video khui hoàn"),
    ])
    if chips:
        return chips
    norm = "".join(ch for ch in unicodedata.normalize("NFKD", str(chot or "")).upper()
                   if not unicodedata.combining(ch))
    return "🔁" if "LON MUC" in norm else "✅"


def _week_table_html(data):
    """Bảng tổng hợp N ngày + TỔNG tháng. NHÓM MÀU: cột ĐÓNG (kèm Vid đóng) = XANH, cột HOÀN
    (kèm Vid hoàn + Tag) = CAM. Gạch ĐẬM giữa tuần; cột Tag liệt kê tag video (Khách tráo/Đã dùng…);
    cột cuối 'Ghi chú' (hiện nội dung đã lưu); tô ĐỎ hủy/thiếu>0. Tiêu đề sticky, tổng ở đầu."""
    if isinstance(data, dict):
        wk = data.get("days", [])
        month = data.get("month") or {}
        mlabel = data.get("month_label", "")
    else:                                   # dự phòng shape cũ (list)
        wk, month, mlabel = data, {}, ""
    cols = [("ngay", "Ngày"), ("thu", "Thứ"),
            # ── ĐÓNG HÀNG (xanh) — luồng: soạn (SP · đơn) → đóng gói THẬT (video) → mất hàng → hủy → giao ──
            ("soan_sp", "Soạn (SP)"), ("soan", "Soạn (đơn)"),
            ("vid_dong", "Đóng gói (video)"), ("tag_dong", "⚠️ Mất hàng (đóng)"),
            ("huy_truoc", "Hủy trước soạn"), ("huy_sau", "Hủy sau soạn"),
            ("shipper_nhan", "Shipper nhận"), ("giao_khach", "Giao khách"),
            # ── HOÀN HÀNG (cam) ──
            ("hoan_don", "Hoàn (đơn)"), ("hoan_sp", "Hoàn SP"), ("vid_hoan", "Vid hoàn"),
            ("thieu", "Thiếu SP"), ("tag_hoan", "Tag hoàn"),
            # ── CHỐT đối chiếu video đóng↔khui (đưa lên từ bảng đối chiếu) ──
            ("chot_video", "Chốt video"),
            ("ghi_chu", "Ghi chú")]
    _sepkey = "hoan_don"                     # cột đầu khối HOÀN → kẻ vạch dọc ngăn 2 khối
    def _lsep(k):
        return "border-left:3px solid #64748b;" if k == _sepkey else ""
    _bd = "border:1px solid #aab2c2;"
    _tagcols = ("tag_dong", "tag_hoan")
    _txt = ("ngay", "thu", "tag_dong", "tag_hoan", "ghi_chu", "chot_video")
    _dong = ("soan_sp", "soan", "vid_dong", "tag_dong", "huy_truoc", "huy_sau", "shipper_nhan", "giao_khach")  # ĐÓNG → XANH
    _hoan = ("hoan_don", "hoan_sp", "vid_hoan", "thieu", "tag_hoan")                            # HOÀN → CAM
    _redkeys = ("huy_sau", "thieu")   # sau soạn (cần lấy lại) > 0 → tô đỏ. Trước soạn = khách hủy sớm, thường.
    _numkeys = ("soan_sp", "soan", "vid_dong", "huy_truoc", "huy_sau", "shipper_nhan", "giao_khach",
                "hoan_don", "hoan_sp", "vid_hoan", "thieu")

    def _bg(k, kind):                       # kind: head | cell | tot
        if k in _dong:
            return {"head": "#cfe0f3", "cell": "#eef4fb", "tot": "#dbe7f6"}[kind]
        if k in _hoan:
            return {"head": "#f9dcb8", "cell": "#fdf3e6", "tot": "#f6e2c6"}[kind]
        return {"head": "#dfe4ec", "cell": "#ffffff", "tot": "#eef1f6"}[kind]

    def _red(k, v):
        return "color:#dc2626;font-weight:800;" if (k in _redkeys and isinstance(v, (int, float)) and v > 0) else ""

    _DOHANA_RETENTION = 25   # Dohana chỉ giữ ~25 ngày video → ngày cũ hơn KHÔNG đồng bộ lại được
    _today_vn = (datetime.now(timezone.utc) + timedelta(hours=7)).date()

    def _gap_badge(sym, fg, bgc, word, n, tip):
        return (f' <span title="{tip}" style="color:{fg};background:{bgc};font-size:9px;'
                f'font-weight:800;white-space:nowrap;padding:1px 4px;border-radius:4px;'
                f'margin-left:3px">{sym}{n} {word}</span>')

    def _audit_count(row, key):
        return _video_audit_num(row.get(key)) if isinstance(row, dict) else 0

    def _apply_audit_video_badges(out, d):
        audit_row = _audit_by_day.get(str((d or {}).get("iso") or ""))
        if not isinstance(audit_row, dict):
            return
        out.pop("vid_dong", None)
        out.pop("vid_hoan", None)
        pkg_missing = _audit_count(audit_row, "Đóng thiếu SL")
        pkg_extra = _audit_count(audit_row, "Đóng dư SL")
        ret_missing = _audit_count(audit_row, "Hoàn thiếu SL")
        ret_extra = _audit_count(audit_row, "Hoàn dư SL")
        if pkg_missing:
            out["vid_dong"] = _gap_badge("▼", "#b91c1c", "#fee2e2", "thiếu", pkg_missing,
                                         "Số thiếu đã chốt từ bảng khớp mã, không dùng chênh lệch thô Soạn - Video.")
        elif pkg_extra:
            out["vid_dong"] = _gap_badge("▲", "#1d4ed8", "#dbeafe", "dư", pkg_extra,
                                         "Số dư đã chốt từ bảng khớp mã, không dùng chênh lệch thô Soạn - Video.")
        if ret_missing:
            out["vid_hoan"] = _gap_badge("⚠", "#b91c1c", "#fee2e2", "chưa quay", ret_missing,
                                         "Số thiếu đã chốt từ bảng khớp mã.")
        elif ret_extra:
            out["vid_hoan"] = _gap_badge("▲", "#1d4ed8", "#dbeafe", "video lẻ", ret_extra,
                                         "Số dư đã chốt từ bảng khớp mã.")

    def _lech_badge(d):
        """Trả badge lệch cho từng cột cần đối chiếu (▼ thiếu · ▲ dư):
        Vid đóng vs Đóng gói · Vid hoàn vs Hoàn đơn · Shipper nhận: Soạn = Hủy+Shipper (ngày đã qua).
        Ngày quá hạn Dohana (~25 ngày) → badge video xám 'kho cũ' vì số có thể thiếu do kho lưu chưa
        đầy lúc đó, KHÔNG kết luận NV quên quay."""
        def _n(key):
            try:
                return int(round(float(d.get(key) or 0)))
            except Exception:
                return 0
        try:
            _stale = (_today_vn - date.fromisoformat(str(d.get("iso") or ""))).days > _DOHANA_RETENTION
        except Exception:
            _stale = False
        # Video khui có TAG TRANH CHẤP (khách tráo / đã dùng / hư hỏng / trả thiếu) → NV KHÔNG nhập
        # kho là ĐÚNG QUY TRÌNH → giải thích phần "dư" của Vid hoàn (không tính lỗi).
        _dispute = sum(int(x) for x in re.findall(r"×\s*(\d+)", str(d.get("tag_hoan") or "")))

        out = {}
        for k, lech, tip in (
            ("vid_dong", _n("soan") - _n("vid_dong"), "Soạn − Đóng gói(video): đơn đã nhặt mà chưa gói/quay video"),
            ("shipper_nhan", (0 if d.get("is_today") else _n("soan") - _n("huy_sau") - _n("shipper_nhan")),
             "Shipper nhận nên = Soạn (đơn) − Hủy sau soạn. Lệch = đơn đã soạn mà chưa giao shipper "
             "(còn tồn / hủy sau soạn chưa trừ / lệch ngày giao)."),
        ):
            if not lech:
                continue
            _is_vid = k in ("vid_dong", "vid_hoan")
            if _is_vid and _stale and lech > 0:   # ngoài hạn Dohana → xám, không đổ lỗi NV
                out[k] = _gap_badge("▽", "#64748b", "#f1f5f9", "kho cũ", abs(lech),
                                "Ngày đã quá hạn Dohana (~25 ngày) — không đồng bộ lại được. "
                                "Số video có thể thiếu do kho lưu lúc đó chưa đầy, KHÔNG chắc NV quên quay")
                continue
            if lech > 0:      # THIẾU (đỏ) — bên này thiếu video, cần quay bù / chuyển tới
                out[k] = _gap_badge("▼", "#b91c1c", "#fee2e2", "thiếu", abs(lech), tip)
            else:             # DƯ (xanh) — bên này dư video, có thể quay lộn sang → chuyển đi
                out[k] = _gap_badge("▲", "#1d4ed8", "#dbeafe", "dư", abs(lech), tip)

        # ── VID HOÀN: đo "THIẾU CLIP KHUI" (đơn hoàn CHƯA quay) TRỰC TIẾP, không bị triệt tiêu ──
        # Đơn tráo/đã dùng/hư (tag_hoan) CÓ quay clip nhưng KHÔNG nhập kho → làm Vid hoàn "dư" hơn
        # Hoàn(nhập kho); phần dư đó dễ che lấp 1 đơn chưa quay khiến "lệch" = 0 (giấu lỗi). Cộng bù
        # phần tráo để lộ đúng số đơn chưa quay: thiếu clip = tag tranh chấp + Hoàn nhập kho − Vid hoàn.
        _tc = _dispute + _n("hoan_don") - _n("vid_hoan")
        if _tc > 0:
            if _stale:        # ngoài hạn Dohana → kho video lúc đó có thể chưa đầy, KHÔNG đổ lỗi NV
                out["vid_hoan"] = _gap_badge("▽", "#64748b", "#f1f5f9", "kho cũ", _tc,
                    "Ngày quá hạn Dohana (~25 ngày) — kho video lúc đó có thể chưa đầy, "
                    "KHÔNG chắc NV quên quay.")
            else:
                out["vid_hoan"] = _gap_badge("⚠", "#b91c1c", "#fee2e2", "chưa quay", _tc,
                    "THIẾU CLIP KHUI = (tag tráo/đã dùng/hư) + Hoàn nhập kho − Vid hoàn. >0 = còn đơn "
                    "hoàn CHƯA quay clip khui (đã bù phần tráo/đã dùng vốn CÓ quay mà không nhập kho). "
                    "Mở báo cáo A4 ngày này để biết ĐƠN nào chưa quay.")
        elif _tc < 0:
            out["vid_hoan"] = _gap_badge("▲", "#1d4ed8", "#dbeafe", "video lẻ", -_tc,
                "Video khui DƯ hơn cả đơn hoàn lẫn tag tráo/đã dùng — có thể NV quay LỘN bên đóng "
                "hàng, quay dư, hoặc quên gắn tag. Mở A4 để đối chiếu.")
        _apply_audit_video_badges(out, d)
        return out

    def _total_gap_badges(rows):
        """Cộng lệch từng ngày; không để ngày dư và ngày thiếu triệt tiêu nhau."""
        totals = {
            "pkg_missing": 0, "pkg_extra": 0, "pkg_old": 0,
            "ret_missing": 0, "ret_extra": 0, "ret_old": 0,
            "ship_missing": 0, "ship_extra": 0,
        }
        for row in rows or []:
            try:
                stale = (_today_vn - date.fromisoformat(str(row.get("iso") or ""))).days > _DOHANA_RETENTION
            except Exception:
                stale = False
            audit_row = _audit_by_day.get(str((row or {}).get("iso") or ""))
            if isinstance(audit_row, dict):
                pkg_missing = _audit_count(audit_row, "Đóng thiếu SL")
                pkg_extra = _audit_count(audit_row, "Đóng dư SL")
                ret_missing = _audit_count(audit_row, "Hoàn thiếu SL")
                ret_extra = _audit_count(audit_row, "Hoàn dư SL")
                if pkg_missing:
                    totals["pkg_old" if stale else "pkg_missing"] += pkg_missing
                if pkg_extra:
                    totals["pkg_extra"] += pkg_extra
                if ret_missing:
                    totals["ret_old" if stale else "ret_missing"] += ret_missing
                if ret_extra:
                    totals["ret_extra"] += ret_extra
            else:
                pkg_gap = int(round(float(row.get("soan") or 0))) - int(round(float(row.get("vid_dong") or 0)))
                dispute = sum(int(x) for x in re.findall(r"×\s*(\d+)", str(row.get("tag_hoan") or "")))
                ret_gap = dispute + int(round(float(row.get("hoan_don") or 0))) - int(round(float(row.get("vid_hoan") or 0)))
                if pkg_gap > 0:
                    totals["pkg_old" if stale else "pkg_missing"] += pkg_gap
                elif pkg_gap < 0:
                    totals["pkg_extra"] += -pkg_gap
                if ret_gap > 0:
                    totals["ret_old" if stale else "ret_missing"] += ret_gap
                elif ret_gap < 0:
                    totals["ret_extra"] += -ret_gap
            # Hôm nay đơn còn tiếp tục bàn giao nên không kết luận thiếu shipper.
            if not row.get("is_today"):
                ship_gap = (int(round(float(row.get("soan") or 0)))
                            - int(round(float(row.get("huy_sau") or 0)))
                            - int(round(float(row.get("shipper_nhan") or 0))))
                if ship_gap > 0:
                    totals["ship_missing"] += ship_gap
                elif ship_gap < 0:
                    totals["ship_extra"] += -ship_gap

        pkg = ""
        if totals["pkg_missing"]:
            pkg += _gap_badge("▼", "#b91c1c", "#fee2e2", "thiếu", totals["pkg_missing"],
                              "Tổng số video đóng thiếu, cộng riêng theo từng ngày.")
        if totals["pkg_extra"]:
            pkg += _gap_badge("▲", "#1d4ed8", "#dbeafe", "dư", totals["pkg_extra"],
                              "Tổng số video đóng dư, cộng riêng theo từng ngày.")
        if totals["pkg_old"]:
            pkg += _gap_badge("▽", "#64748b", "#f1f5f9", "kho cũ", totals["pkg_old"],
                              "Tổng chênh thiếu thuộc các ngày đã quá hạn lưu video Dohana.")

        ret = ""
        if totals["ret_missing"]:
            ret += _gap_badge("⚠", "#b91c1c", "#fee2e2", "chưa quay", totals["ret_missing"],
                              "Tổng số video khui hoàn thiếu, cộng riêng theo từng ngày.")
        if totals["ret_extra"]:
            ret += _gap_badge("▲", "#1d4ed8", "#dbeafe", "video lẻ", totals["ret_extra"],
                              "Tổng số video khui hoàn dư, cộng riêng theo từng ngày.")
        if totals["ret_old"]:
            ret += _gap_badge("▽", "#64748b", "#f1f5f9", "kho cũ", totals["ret_old"],
                              "Tổng chênh thiếu thuộc các ngày đã quá hạn lưu video Dohana.")
        ship = ""
        if totals["ship_missing"]:
            ship += _gap_badge("▼", "#b91c1c", "#fee2e2", "thiếu", totals["ship_missing"],
                               "Tổng đơn chưa bàn giao shipper, cộng riêng theo từng ngày đã chốt.")
        if totals["ship_extra"]:
            ship += _gap_badge("▲", "#1d4ed8", "#dbeafe", "dư", totals["ship_extra"],
                               "Tổng số shipper nhận dư, cộng riêng theo từng ngày đã chốt.")
        return {"vid_dong": pkg, "vid_hoan": ret, "shipper_nhan": ship}

    head = "".join(
        f'<th style="position:sticky;top:0;z-index:3;text-align:{"left" if k in _txt else "right"};'
        f'padding:6px 8px;{_bd}{_lsep(k)}background:{_bg(k, "head")};'
        f'color:{"#b91c1c" if k == "tag_dong" else "#16233f"}'
        f'{";min-width:130px" if k == "ghi_chu" else ";min-width:150px" if k == "chot_video" else ""}">{lbl}</th>'
        for k, lbl in cols)
    _audit_by_day = {
        str(row.get("Ngày") or row.get("Ngay") or ""): row
        for row in ((data.get("video_audit_matrix") if isinstance(data, dict) else None) or [])
        if isinstance(row, dict)
    }

    body = ""
    prev_wk = None
    for r in wk:
        hot = r.get("is_today")
        try:                    # gạch ĐẬM khi sang tuần khác (ISO week Mon–CN)
            _wkkey = datetime.fromisoformat(str(r.get("iso"))).isocalendar()[:2]
        except Exception:
            _wkkey = None
        wtop = "border-top:3px solid #334155;" if (prev_wk is not None and _wkkey != prev_wk) else ""
        prev_wk = _wkkey
        cells = ""
        _badges = _lech_badge(r)
        for k, _ in cols:
            al = "left" if k in _txt else "right"
            if k in ("ghi_chu",) or k in _tagcols:
                v = str(r.get(k, "") or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            elif k == "chot_video":
                v = str(r.get(k, "") or "")
            elif k in ("huy_sau", "huy_truoc") and not r.get("huy_split_known"):
                v = "—"      # hôm nay số còn chạy → chưa suy được sau/trước soạn
            else:
                v = r.get(k, "")
            mw = "min-width:150px;" if k == "chot_video" else "min-width:110px;" if (k == "ghi_chu" or k in _tagcols) else ""
            _nay = (' <span style="color:#E24B4A;font-size:11px">• nay</span>'
                    if hot and k == "ngay" else "")
            if k == "tag_dong" and v:      # đóng thiếu/sai sp = MẤT HÀNG / lỗi đóng → đỏ đậm
                _tagclr = "color:#b91c1c;font-weight:800;"
            elif k == "tag_hoan" and v:    # tag hoàn (tráo/đã dùng) → tím
                _tagclr = "color:#7c3aed;font-weight:700;"
            else:
                _tagclr = ""
            wt = "font-weight:800;" if hot else ""
            bg = "#fff2e0" if hot else _bg(k, "cell")     # hôm nay: nền cam nhạt cả dòng
            _chotc = ""
            if k == "chot_video" and v:                    # xanh = đủ/khớp · đỏ = còn lệch
                _audit_row = _audit_by_day.get(str(r.get("iso") or ""))
                v = _video_audit_chot_html(_audit_row, v, str(r.get("iso") or ""))
                if not _audit_row and str(r.get(k, "") or "").startswith("Đủ"):
                    bg, _chotc = "#dcfce7", "color:#166534;font-weight:700;"
                elif _audit_row:
                    bg, _chotc = "#fff7ed", ""
                else:
                    bg, _chotc = "#dcfce7", "color:#166534;font-weight:700;"
            cells += (f'<td style="text-align:{al};padding:5px 8px;{_bd}{_lsep(k)}{wtop}{mw}background:{bg};{wt}{_red(k, v)}{_tagclr}{_chotc}">'
                      f'{v}{_nay}{_badges.get(k, "")}</td>')
        body += f'<tr>{cells}</tr>'

    def _tot_row(label, src, label_bg, rows=None):
        cells = f'<td colspan="2" style="text-align:left;padding:6px 8px;{_bd}background:{label_bg}">{label}</td>'
        _tbadge = _lech_badge(src)
        if rows is not None:
            _tbadge.update(_total_gap_badges(rows))
        for k, _ in cols[2:]:
            if k in ("ghi_chu", "chot_video"):
                cells += f'<td style="padding:6px 8px;{_bd}background:#ffffff"></td>'
                continue
            if k in _tagcols:
                tv = str(src.get(k, "") or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
                _tc = ("color:#b91c1c;font-weight:800;" if (k == "tag_dong" and tv)
                       else ("color:#7c3aed;" if tv else ""))
                cells += (f'<td style="text-align:left;padding:6px 8px;{_bd}{_lsep(k)}background:{_bg(k, "tot")};'
                          f'{_tc}">{tv}</td>')
                continue
            v = src.get(k, 0)
            if k in ("huy_sau", "huy_truoc") and not src.get("huy_split_known"):
                v = "—"
            cells += (f'<td style="text-align:right;padding:6px 8px;{_bd}{_lsep(k)}background:{_bg(k, "tot")};'
                      f'{_red(k, v)}">{v}{_tbadge.get(k, "")}</td>')
        return f'<tr style="font-weight:800;color:#16233f">{cells}</tr>'

    tot_all = {k: sum(r.get(k, 0) for r in wk) for k in _numkeys}
    tots = _tot_row(f"TỔNG {len(wk)} ngày qua", tot_all, "#eef1f6", wk)
    if month:
        _month_prefix = _today_vn.strftime("%Y-%m")
        _month_rows = [r for r in wk if str(r.get("iso") or "").startswith(_month_prefix)]
        tots += _tot_row(f"TỔNG tháng {mlabel}", month, "#e0e7ff", _month_rows)
    # Tổng ĐEM LÊN ĐẦU (ngay dưới tiêu đề); tiêu đề STICKY (position:sticky) → trượt không mất.
    return (f'<div style="max-height:540px;overflow:auto;border:1px solid #aab2c2;border-radius:6px">'
            f'<table style="width:100%;border-collapse:collapse;font-size:11.5px">'
            f'<thead><tr>{head}</tr></thead><tbody>{tots}{body}</tbody></table></div>')


def _render_week_video_audit(data):
    def _fallback_matrix_rows(src):
        if not isinstance(src, dict):
            return []

        def _n(value):
            try:
                return int(round(float(value or 0)))
            except Exception:
                return 0

        def _age(iso):
            try:
                _d = date.fromisoformat(str(iso or "")[:10])
                _stale = ((datetime.now(timezone.utc) + timedelta(hours=7)).date() - _d).days > _DOHANA_RETENTION
                return "Kho cũ" if _stale else "Còn trong hạn Dohana"
            except Exception:
                return ""

        def _join(vals):
            from collections import Counter as _Counter
            vals = [str(v or "").strip() for v in (vals or []) if str(v or "").strip()]
            cnt = _Counter(vals)
            return " · ".join(
                f"{v} ×{cnt[v]}" if cnt[v] > 1 else v
                for v in dict.fromkeys(vals)
            )

        out = []
        a4_by_day = src.get("a4_package_recon_by_day") or {}
        for day in src.get("days") or []:
            if not isinstance(day, dict):
                continue
            iso = str(day.get("iso") or "")
            if not iso:
                continue
            a4 = a4_by_day.get(iso) or {}
            a4_missing = [
                str(v or "").strip()
                for v in (a4.get("missing") or [])
                if str(v or "").strip()
            ]
            pkg_gap = _n(day.get("soan")) - _n(day.get("vid_dong"))
            pkg_missing_n = len(a4_missing) if a4_missing else max(pkg_gap, 0)
            pkg_extra_n = 0 if a4_missing else max(-pkg_gap, 0)
            dispute = sum(int(x) for x in re.findall(r"[×x]\s*(\d+)", str(day.get("tag_hoan") or ""), flags=re.I))
            ret_gap = dispute + _n(day.get("hoan_don")) - _n(day.get("vid_hoan"))
            ret_missing_n = max(ret_gap, 0)
            ret_extra_n = max(-ret_gap, 0)
            if not (pkg_missing_n or pkg_extra_n or ret_missing_n or ret_extra_n):
                continue
            parts = []
            if pkg_missing_n:
                parts.append(f"Thiếu video đóng: {pkg_missing_n}")
            if ret_missing_n:
                parts.append(f"Thiếu video khui hoàn: {ret_missing_n}")
            if pkg_extra_n:
                parts.append(f"Dư video đóng: {pkg_extra_n}")
            if ret_extra_n:
                parts.append(f"Dư video khui hoàn: {ret_extra_n}")
            out.append({
                "Ngày": iso,
                "Nhóm tuổi": _age(iso),
                "Mã đối chiếu": "",
                "Đóng thiếu SL": pkg_missing_n,
                "Đóng thiếu": _join(a4_missing),
                "Đóng dư SL": pkg_extra_n,
                "Đóng dư": "",
                "Hoàn thiếu SL": ret_missing_n,
                "Hoàn thiếu": "",
                "Hoàn dư SL": ret_extra_n,
                "Hoàn dư": "",
                "Khớp lộn mục": "",
                "Video chưa khớp đơn": "",
                "Chốt": str(day.get("chot_video") or ("Còn lệch: " + "; ".join(parts))),
            })
        return out

    matrix_rows = (data or {}).get("video_audit_matrix") or []
    if not matrix_rows:
        matrix_rows = _fallback_matrix_rows(data or {})
    rows = matrix_rows or (data or {}).get("video_audit") or []
    if not rows:
        with st.expander("🔎 Bảng khớp mã video đóng hàng ↔ khui hàng — 0 dòng", expanded=True):
            st.info("Chưa có dòng lệch để đối chiếu mã.")
        return
    with st.expander(f"🔎 Đối chiếu mã dư/thiếu video đóng hàng ↔ khui hàng — {len(rows)} dòng", expanded=True):
        st.markdown("**Bảng khớp mã**")
        st.caption(
            "Mỗi dòng là 1 ngày. App tự khớp mã thiếu bên này với mã dư bên kia; ô vàng là khả năng cao quay lộn mục. "
            "Cột Chốt là kết quả sau khi đã bù trừ các mã khớp lộn."
        )
        # ── 🔍 SOI 1 MÃ: video trong kho (ngày/type/trạng thái) + đang nằm ở cột thiếu/dư nào ──
        _probe = st.text_input("🔍 Soi 1 mã (vì sao vào cột thiếu/dư này)", key="week_audit_probe",
                               placeholder="Dán mã vận đơn / mã đơn, vd 861877934768…").strip()
        if _probe:
            _pn = _ascii_code(_probe)
            _pvids = [v for v in (picklog.read_dohana_videos() if picklog.configured() else [])
                      if _pn and _pn in _ascii_code(v.get("code"))]
            if _pvids:
                st.markdown(f"**Kho video — {len(_pvids)} clip khớp `{_probe}`:**")
                st.dataframe(pd.DataFrame([{
                    "Mã": v.get("code"),
                    "Loại": ("đóng hàng" if v.get("type") == "package"
                             else "khui hàng" if v.get("type") == "inbound" else str(v.get("type"))),
                    "Ngày": v.get("date"), "Giờ": v.get("time"),
                    "Trạng thái": v.get("status") or "—",
                    "Tag": v.get("tag_name") or v.get("locked_tag_name") or "",
                } for v in _pvids]), hide_index=True, use_container_width=True)
            else:
                st.warning(f"KHÔNG thấy `{_probe}` trong kho video đã lưu → app chưa lưu được clip này "
                           "(bị xóa trước khi app kịp đồng bộ, hoặc ngoài phạm vi quét).")
            _phits = []
            for _r in rows:
                if not isinstance(_r, dict):
                    continue
                _rday = _r.get("Ngày") or _r.get("iso") or _r.get("ngay") or "?"
                for _col, _val in _r.items():
                    if _col in ("Ngày", "iso", "ngay", "Thứ", "thu"):
                        continue
                    if _pn and _pn in _ascii_code(_val):
                        _phits.append(f"{_rday} → **{_col}**")
            st.markdown("**Đang nằm ở:** " + (" · ".join(_phits[:15]) if _phits
                        else "_không thấy ở cột thiếu/dư nào trong bảng dưới_"))
            # ── DẤU VẾT ĐỐI CHIẾU BÊN ĐÓNG: vì sao vào (hay KHÔNG vào) cột "Đóng dư" ──
            _trace = (data or {}).get("video_trace_by_day") or {}
            _trace_rows = []
            for _td, _tv in _trace.items():
                if not isinstance(_tv, dict):
                    continue
                _in = lambda lst: any(_pn and _pn in _ascii_code(x) for x in (lst or []))
                _is_soan = _in(_tv.get("soan"))
                _is_video = _in(_tv.get("pkg_video"))
                _is_matched = _in(_tv.get("pkg_matched"))
                _is_extra = _in(_tv.get("pkg_extra"))
                if not (_is_soan or _is_video):
                    continue
                if _is_matched:
                    _kl = "✅ KHỚP soạn → không tính dư (đúng: có soạn mã này)"
                elif _is_extra:
                    _kl = "🟦 Video đóng KHÔNG khớp soạn → PHẢI vào 'Đóng dư'"
                elif _is_video and not _tv.get("has_soan_list"):
                    _kl = "⚠️ Có video nhưng NGÀY MẤT phiếu soạn → không ghép được"
                else:
                    _kl = "—"
                _trace_rows.append({
                    "Ngày": _td,
                    "Có trong SOẠN?": "có" if _is_soan else "không",
                    "Là video ĐÓNG?": "có" if _is_video else "không",
                    "Đã khớp soạn?": "có" if _is_matched else "không",
                    "Xếp vào Đóng dư?": "có" if _is_extra else "không",
                    "Kết luận": _kl,
                })
            if _trace_rows:
                st.markdown("**Dấu vết bên ĐÓNG (vì sao vào/không vào cột Đóng dư):**")
                st.dataframe(pd.DataFrame(_trace_rows), hide_index=True, use_container_width=True)
                _ctx = (data or {}).get("order_context_by_code") or {}
                _ctx_lbl = _ctx.get(_pn) or _ctx.get(_probe)
                if _ctx_lbl:
                    st.caption(f"Nhãn ngữ cảnh của mã này: `{_ctx_lbl}`")
        df = pd.DataFrame(rows)
        if "Nhóm tuổi" in df.columns:
            _age_filter = st.radio(
                "Phạm vi",
                ["Tất cả", "Còn trong hạn Dohana", "Kho cũ"],
                horizontal=True,
                key="week_video_audit_age_filter",
            )
            if _age_filter != "Tất cả":
                df = df[df["Nhóm tuổi"] == _age_filter]
        if df.empty:
            st.info("Không có dòng trong phạm vi đã chọn.")
            return
        if matrix_rows:
            def _fmt_cell(v, highlight=False, anchor_id=""):
                txt = str(v or "").strip()
                anchor = f' id="{anchor_id}" class="audit-target"' if anchor_id else ""
                if not txt:
                    return f'<td{anchor} style="padding:6px 8px;border:1px solid #d6dce6;color:#94a3b8">—</td>'
                sep = "\n" if "\n" in txt else " · "
                parts = [_esc(p.strip()) for p in txt.split(sep) if p.strip()]
                body = "<br>".join(parts)
                bg = "#fff7cc" if highlight else "#ffffff"
                fw = "font-weight:800;" if highlight else ""
                return f'<td{anchor} style="padding:6px 8px;border:1px solid #d6dce6;background:{bg};{fw};vertical-align:top">{body}</td>'

            def _chot_cell(r):
                chot = str(r.get("Chốt") or "").strip()
                content = _video_audit_chot_html(r, chot, str(r.get("Ngày") or ""))
                tip = chot or "Đủ"
                bg = "#fff7ed" if "<a " in content else "#dcfce7"
                return (f'<td title="{_esc(tip)}" style="padding:6px 8px;border:1px solid #d6dce6;'
                        f'background:{bg};text-align:center;font-weight:900;vertical-align:top">{content}</td>')

            body = []
            for _, r in df.iterrows():
                has_match = bool(str(r.get("Khớp lộn mục") or "").strip())
                day_key = str(r.get("Ngày") or "")
                anchors = {
                    "pkg_miss": _video_audit_anchor(day_key, "pkg-miss"),
                    "pkg_extra": _video_audit_anchor(day_key, "pkg-extra"),
                    "ret_miss": _video_audit_anchor(day_key, "ret-miss"),
                    "ret_extra": _video_audit_anchor(day_key, "ret-extra"),
                }
                cells = [
                    "<tr>",
                    f'<td style="padding:6px 8px;border:1px solid #d6dce6;white-space:nowrap">{_esc(str(r.get("Ngày") or ""))}</td>',
                    _fmt_cell(r.get("Khớp lộn mục"), has_match),
                    f'<td style="padding:6px 8px;border:1px solid #d6dce6;text-align:right;font-weight:800">{_video_audit_num(r.get("Đóng thiếu SL"))}</td>',
                    _fmt_cell(r.get("Đóng thiếu"), anchor_id=anchors["pkg_miss"]),
                    f'<td style="padding:6px 8px;border:1px solid #d6dce6;text-align:right;font-weight:800">{_video_audit_num(r.get("Đóng dư SL"))}</td>',
                    _fmt_cell(r.get("Đóng dư"), anchor_id=anchors["pkg_extra"]),
                    f'<td style="padding:6px 8px;border:1px solid #d6dce6;text-align:right;font-weight:800">{_video_audit_num(r.get("Hoàn thiếu SL"))}</td>',
                    _fmt_cell(r.get("Hoàn thiếu"), anchor_id=anchors["ret_miss"]),
                    f'<td style="padding:6px 8px;border:1px solid #d6dce6;text-align:right;font-weight:800">{_video_audit_num(r.get("Hoàn dư SL"))}</td>',
                    _fmt_cell(r.get("Hoàn dư"), anchor_id=anchors["ret_extra"]),
                    _chot_cell(r),
                    "</tr>",
                ]
                body.append("".join(cells))
            st.markdown(
                """
<style>
td.audit-target:target {
  outline: 3px solid #f59e0b;
  outline-offset: -3px;
  background: #fffbeb !important;
}
</style>
<div style="max-height:520px;overflow:auto;border:1px solid #d6dce6;border-radius:8px">
<table style="width:100%;border-collapse:collapse;font-size:12px;background:white">
  <thead>
    <tr>
      <th rowspan="2" style="position:sticky;top:0;z-index:3;padding:7px 8px;border:1px solid #cbd5e1;background:#e2e8f0">Ngày</th>
      <th rowspan="2" style="position:sticky;top:0;z-index:3;padding:7px 8px;border:1px solid #cbd5e1;background:#fef3c7;min-width:220px">Khớp lộn mục</th>
      <th colspan="4" style="position:sticky;top:0;z-index:3;padding:7px 8px;border:1px solid #cbd5e1;background:#dbeafe">Đóng hàng</th>
      <th colspan="4" style="position:sticky;top:0;z-index:3;padding:7px 8px;border:1px solid #cbd5e1;background:#ffedd5">Nhập hàng hoàn</th>
      <th rowspan="2" style="position:sticky;top:0;z-index:3;padding:7px 8px;border:1px solid #cbd5e1;background:#f1f5f9;min-width:160px">Chốt</th>
    </tr>
    <tr>
      <th style="position:sticky;top:31px;z-index:3;padding:6px 8px;border:1px solid #cbd5e1;background:#dbeafe">Thiếu SL</th>
      <th style="position:sticky;top:31px;z-index:3;padding:6px 8px;border:1px solid #cbd5e1;background:#dbeafe;min-width:190px">Thiếu mã</th>
      <th style="position:sticky;top:31px;z-index:3;padding:6px 8px;border:1px solid #cbd5e1;background:#dbeafe">Dư SL</th>
      <th style="position:sticky;top:31px;z-index:3;padding:6px 8px;border:1px solid #cbd5e1;background:#dbeafe;min-width:190px">Dư mã</th>
      <th style="position:sticky;top:31px;z-index:3;padding:6px 8px;border:1px solid #cbd5e1;background:#ffedd5">Thiếu SL</th>
      <th style="position:sticky;top:31px;z-index:3;padding:6px 8px;border:1px solid #cbd5e1;background:#ffedd5;min-width:190px">Thiếu mã</th>
      <th style="position:sticky;top:31px;z-index:3;padding:6px 8px;border:1px solid #cbd5e1;background:#ffedd5">Dư SL</th>
      <th style="position:sticky;top:31px;z-index:3;padding:6px 8px;border:1px solid #cbd5e1;background:#ffedd5;min-width:190px">Dư mã</th>
    </tr>
  </thead>
  <tbody>
""" + "".join(body) + """
  </tbody>
</table>
</div>
""",
                unsafe_allow_html=True,
            )
            return
        st.dataframe(
            df,
            hide_index=True,
            width="stretch",
            column_config={
                "Mã cần kiểm": st.column_config.TextColumn("Mã cần kiểm", width="large"),
                "Mã dư/thiếu đối diện": st.column_config.TextColumn("Mã dư/thiếu đối diện", width="large"),
                "Khớp lộn mục": st.column_config.TextColumn("Khớp lộn mục", width="large"),
                "Gợi ý": st.column_config.TextColumn("Gợi ý", width="large"),
            },
        )


def _ascii_code(s):
    """Chuẩn hoá mã để khớp: BỎ DẤU tiếng Việt (do app Dohana lỗi phông biến YX→Ỹ…),
    in HOA, chỉ giữ chữ-số. VD 'GỸQMQTD' -> 'GYQMQTD'."""
    s = str(s or "").replace("Đ", "D").replace("đ", "d")
    s = unicodedata.normalize("NFKD", str(s or ""))
    s = "".join(c for c in s if not unicodedata.combining(c))
    return "".join(c for c in s.upper() if c.isalnum())


def _note_prefix_compact(note):
    first = str(note or "").replace("\r", "\n").split("\n")[0].split("|", 1)[0]
    return "".join(ch for ch in _ascii_code(first) if ch.isalnum())


def _compact_is_khong_can_kn(compact):
    compact = str(compact or "")
    return "KHONGCANKN" in compact or "KHONGCANKHIEUNAI" in compact


def _compact_is_can_kn(compact):
    compact = str(compact or "")
    if _compact_is_khong_can_kn(compact):
        return False
    return "CANKN" in compact or "CANKHIEUNAI" in compact


def _subseq(a, b):
    """a có phải SUBSEQUENCE của b không (b giữ thứ tự, được phép xen ký tự)."""
    it = iter(b)
    return all(c in it for c in a)


def match_packing_videos(order_codes, vcodes):
    """Khớp ĐƠN ↔ VIDEO chịu được LỖI PHÔNG app Dohana (mã video bị méo/dính).
    order_codes: list[list[str]] — mỗi đơn là danh sách mã ứng viên (vận đơn + mã đơn).
    vcodes: iterable mã video (orderCode trên Dohana).
    3 mức khớp:
      1) CHÍNH XÁC sau bỏ dấu (bắt mã chỉ sai dấu/hoa-thường).
      2) DÍNH MÃ: mã đơn (≥10 ký tự, vd VĐ) là chuỗi con của mã video — vd
         '861864498916SPXVN064435411156' chứa 'SPXVN064435411156'.
      3) MẤT KÝ TỰ do lỗi phông: mã video (CHỈ mã có ký tự lạ) là subsequence của
         mã đơn, cùng ký tự đầu, lệch ≤5, và GHÉP DUY NHẤT — vd 'GYQMQTD'⊂'GYXQMQTD'.
    Trả (matched: {idx_đơn: (mã_video, kiểu)}, font_pairs: [(mã_video, mã_đơn)] các ca cứu được)."""
    vn2c = {}
    for vc in vcodes:
        n = _ascii_code(vc)
        if n:
            vn2c.setdefault(n, vc)
    # mỗi đơn: list (mã gốc, mã chuẩn-hoá) — giữ mã gốc để hiển thị cặp khớp
    onorms = [[(c, _ascii_code(c)) for c in (codes or []) if _ascii_code(c)] for codes in order_codes]
    matched, used, mcode = {}, set(), {}
    for i, lst in enumerate(onorms):                   # 1) chính xác (bỏ dấu)
        for orig, nc in lst:
            if nc in vn2c and vn2c[nc] not in used:
                matched[i] = (vn2c[nc], "exact"); used.add(vn2c[nc]); mcode[i] = orig; break
    for i, lst in enumerate(onorms):                   # 2) mã dính nhau (substring mã dài)
        if i in matched:
            continue
        for orig, nc in lst:
            if len(nc) < 10:
                continue
            hit = next((vc for vn, vc in vn2c.items()
                        if vc not in used and (nc in vn or vn in nc)), None)
            if hit:
                matched[i] = (hit, "substr"); used.add(hit); mcode[i] = orig; break
    corrupt = {vn: vc for vn, vc in vn2c.items()       # CHỈ mã video có ký tự lạ (lỗi phông)
               if vc not in used and any(ord(ch) > 127 for ch in str(vc))}
    for i, lst in enumerate(onorms):                   # 3) lỗi phông mất ký tự (subsequence, DUY NHẤT)
        if i in matched:
            continue
        cand = {}
        for orig, nc in lst:
            if len(nc) < 4:
                continue
            for vn, vc in corrupt.items():
                if vc not in used and vn and vn[0] == nc[0] \
                   and 0 <= len(nc) - len(vn) <= 5 and _subseq(vn, nc):
                    cand.setdefault(vc, orig)
        if len(cand) == 1:
            vc, orig = next(iter(cand.items()))
            if vc not in used:
                matched[i] = (vc, "font"); used.add(vc); mcode[i] = orig
    font_pairs = [(matched[i][0], mcode[i])
                  for i in matched if matched[i][1] in ("substr", "font")]
    return matched, font_pairs


def _video_tag_id(m):
    return (m or {}).get("locked_tag_id") or (m or {}).get("tag_id") or ""


def _video_tag_name(m):
    return (m or {}).get("locked_tag_name") or (m or {}).get("tag_name") or (m or {}).get("tag") or ""


def _video_tag_label(m):
    tid = _video_tag_id(m)
    name = _video_tag_name(m)
    tag = dohana._tag_name(tid, name) if tid else name
    if str(tag).strip() in ("⚠️ Có tag", "Có tag"):
        return "⚠️ Tag chưa map tên"
    return tag


def _enrich_daily(rep, dvr, inb):
    """Gắn đối chiếu CLIP KHUI HÀNG (inbound) + VIDEO ĐÓNG GÓI (package) vào rep.
    Dùng chung cho cả báo cáo hôm nay và xem lại ngày cũ."""
    def _clip_tag(m):
        if not m:
            return ""
        return _video_tag_label(m)

    nk = rep.get("nhap_kho") or {}
    if inb is not None:
        mset, cnt = inb.get("match", set()), inb.get("count", {})
        meta = inb.get("meta", {})
        consumed = set()
        for d in nk.get("detail", []):
            hit = next((c for c in d.get("codes", []) if c in mset), None)
            d["clip"] = bool(hit)
            d["clip_count"] = cnt.get(hit, 0) if hit else 0
            d["clip_code"] = hit            # MÃ tra clip trên app đóng hàng (Dohana)
            m = meta.get(hit) if hit else None
            d["clip_dur"] = m.get("dur") if m else None
            d["clip_time"] = m.get("recorded") if m else ""
            d["clip_link"] = m.get("link") if m else ""
            d["clip_tag_id"] = _video_tag_id(m) if m else ""
            d["clip_tag"] = _clip_tag(m)
            d["clip_staff"] = m.get("staff") if m else ""
            if hit:
                consumed.add(hit)
        # GHÉP MỀM: đơn hoàn chưa khớp mã ↔ clip khui hàng còn dư CÙNG ĐVVC. Đơn hoàn (nhất là SPX)
        # đi qua NHIỀU mã vận đơn (giao đi → hoàn về); Sapo lưu mã này, NV quét clip mã khác →
        # khớp-theo-mã trượt. Nếu còn clip dư cùng ĐVVC thì coi như ĐÃ CÓ (đánh dấu "mã khác"),
        # tránh báo "thiếu clip" oan khi thực tế đã quay đủ.
        def _cg(code):   # NHÓM ĐVVC từ mã VĐ: J&T có CẢ dải 86x lẫn 85x → gộp chung
            s = str(code or "")
            if s.startswith("SPXVN"):
                return "SPX"
            if s.startswith(("VTPVN", "VTP")):
                return "VTP"
            if s.startswith("GHN"):
                return "GHN"
            if s[:2] in ("86", "85", "84", "87"):
                return "JT"
            return s[:3]
        def _cgname(n):  # NHÓM ĐVVC từ TÊN đơn vị (đáng tin hơn mã)
            n = str(n or "").lower()
            if "spx" in n:
                return "SPX"
            if "viettel" in n or "vtp" in n:
                return "VTP"
            if "ghn" in n or "giao hàng nhanh" in n:
                return "GHN"
            if "j&t" in n or "jt" in n:
                return "JT"
            return n[:3]
        leftover = sorted(inb.get("today_codes", set()) - consumed)
        for d in nk.get("detail", []):
            if d.get("clip") or not leftover:
                continue
            if d.get("loai_tra_code") == "delivery_failed":
                continue   # GIAO THẤT BẠI: VĐ về = VĐ đi = mã Dohana chính xác → KHÔNG ghép mềm
                           # (tránh gán nhầm clip J&T khác vào đơn — như ca user báo link sai)
            rp = _cgname(d.get("carrier"))
            pick = next((c for c in leftover if _cg(c) == rp), None)
            if pick:
                leftover.remove(pick)
                consumed.add(pick)
                d["clip"] = True
                d["clip_altcode"] = True   # khớp theo ĐVVC + ngày, KHÔNG khớp chính xác mã
                d["clip_code"] = pick      # mã clip trên Dohana (ghép mềm)
                m = meta.get(pick)
                if m:
                    d["clip_dur"] = m.get("dur")
                    d["clip_time"] = m.get("recorded")
                    d["clip_link"] = m.get("link")
                    d["clip_tag_id"] = _video_tag_id(m)
                    d["clip_tag"] = _clip_tag(m)
                    d["clip_staff"] = m.get("staff")
        nk["clip_available"] = True
        nk["clip_co"] = sum(1 for d in nk.get("detail", []) if d.get("clip"))
        nk["clip_total"] = inb.get("total", 0)
        nk["clip_unmatched"] = sorted(inb.get("today_codes", set()) - consumed)
        # Kèm TAG (vd Khách tráo!) + thời lượng/giờ cho clip dư — đơn có tag thường bị giữ lại
        # xử lý tranh chấp nên KHÔNG nhập kho (đúng quy trình) → cần hiện rõ tag để theo dõi.
        nk["clip_unmatched_detail"] = [
            {"code": c, "tag_id": _video_tag_id(meta.get(c) or {}),
             "tag": _clip_tag(meta.get(c) or {}),
             "dur": (meta.get(c) or {}).get("dur"),
             "recorded": (meta.get(c) or {}).get("recorded", ""),
             "link": (meta.get(c) or {}).get("link", ""),
             "staff": (meta.get(c) or {}).get("staff", "")}
            for c in nk["clip_unmatched"]
        ]
    else:
        # Dohana lỗi/429: KHÔNG có clip. Nhưng ĐƠN TRẢ HÀNG (đã nhập kho) VẪN PHẢI HIỆN —
        # chỉ thiếu cột clip. ĐỪNG để recon rỗng làm bảng "đã nhận hàng trả" BIẾN MẤT.
        nk["clip_available"] = False
        for d in nk.get("detail", []):
            d["clip"] = False
        nk["clip_co"], nk["clip_total"] = 0, 0
        nk["clip_unmatched"], nk["clip_unmatched_detail"] = [], []
    # GỘP đơn hoàn CÙNG KIỆN: cùng mã đơn + cùng VĐ gửi đi (khách trả NHIỀU SP của 1 đơn về
    # trong 1 kiện, NV quay 1 clip) → gộp thành 1 DÒNG (nối mã đơn trả + SKU, cộng SP), tránh
    # lặp clip nhiều dòng nhìn "trùng/sai". clip_co đếm lại theo KIỆN.
    _kien, _korder = {}, []
    for _d in nk.get("detail", []):
        _kk = (str(_d.get("order_code") or ""), str(_d.get("tracking") or ""))
        _g = _kien.get(_kk)
        if _g is None:
            _g = dict(_d)
            _g["_ret_codes"] = [str(_d["return_code"])] if _d.get("return_code") else []
            _g["_skus"] = [str(_d["sku"])] if _d.get("sku") else []
            _kien[_kk] = _g
            _korder.append(_kk)
        else:
            if _d.get("return_code"):
                _g["_ret_codes"].append(str(_d["return_code"]))
            if _d.get("sku"):
                _g["_skus"].append(str(_d["sku"]))
            _g["sp"] = (_g.get("sp") or 0) + (_d.get("sp") or 0)
            _g["sp_nhap"] = (_g.get("sp_nhap") or 0) + (_d.get("sp_nhap") or 0)
            if not _g.get("clip") and _d.get("clip"):   # 1 dòng trong kiện có clip → cả kiện có
                for _ck in ("clip", "clip_code", "clip_time", "clip_dur", "clip_tag",
                            "clip_tag_id", "clip_altcode", "clip_link", "clip_staff"):
                    _g[_ck] = _d.get(_ck)
    _merged = [_kien[_kk] for _kk in _korder]
    for _g in _merged:
        if len(_g.get("_ret_codes") or []) > 1:
            _g["return_code"] = " · ".join(_g["_ret_codes"])
        if len(_g.get("_skus") or []) > 1:
            _g["sku"] = " · ".join(_g["_skus"])
    nk["detail"] = _merged
    # HOÀN NHẬP KHO đếm theo MÃ ĐƠN (distinct) — 1 đơn nhiều SP/mã trả = 1 (khớp cột "Đã nhận hàng trả")
    nk["so_phieu"] = len({str(_d.get("order_code") or "") for _d in _merged if _d.get("order_code")})
    if nk.get("clip_available"):
        nk["clip_co"] = sum(1 for _d in _merged if _d.get("clip"))
    # BẢNG ĐỐI CHIẾU: DỰNG LUÔN LUÔN (kể cả khi Dohana lỗi/429) → đơn trả hàng KHÔNG biến mất;
    # không lấy được clip thì cột clip để trống. Đơn ĐÃ nhập kho (Sapo) + clip DƯ (chưa nhập kho).
    recon = []
    for d in nk.get("detail", []):
        recon.append({
            "clip_code": d.get("clip_code"), "clip_time": d.get("clip_time"),
            "clip_dur": d.get("clip_dur"), "clip_link": d.get("clip_link"),
            "clip_tag": d.get("clip_tag"),
            "clip_tag_id": d.get("clip_tag_id"),
            "clip_alt": d.get("clip_altcode"), "has_clip": bool(d.get("clip")),
            "order_code": d.get("order_code"), "recv_time": d.get("recv_time"),
            "vd_gui": d.get("tracking"),   # mã VĐ GIAO ĐI (tra Sapo/sàn được)
            "return_code": d.get("return_code") or "",     # MÃ ĐƠN TRẢ (tra trên sàn, vd 585...-R1)
            "track_return": d.get("track_return") or "",   # VĐ HOÀN VỀ (giao thất bại = trùng mã đi = mã Dohana)
            # Cột "Đã nhận hàng trả (Sapo)" → CHỉ lấy NV nhận hàng từ Sapo,
            # KHÔNG fallback sang NV quay clip (Dohana) để tránh hiển thị sai người.
            "nhan_vien": d.get("nhan_vien") or "",
            "sku": d.get("sku"), "loai_tra": d.get("loai_tra"),
            "sp": d.get("sp"), "sp_nhap": d.get("sp_nhap"),   # SL kỳ vọng vs SL THỰC nhập kho
            "loai_tra_code": d.get("loai_tra_code"), "has_sapo": True,
        })
    _abc = nk.get("all_by_code") or {}
    for u in nk.get("clip_unmatched_detail", []):
        info = _abc.get(u.get("code")) or {}   # đơn hoàn CHƯA nhập kho (vd tráo hàng giữ tranh chấp)
        recon.append({
            "clip_code": u.get("code"), "clip_time": u.get("recorded"),
            "clip_dur": u.get("dur"), "clip_link": u.get("link"),
            "clip_tag": u.get("tag"),
            "clip_tag_id": u.get("tag_id"),
            "clip_alt": False, "has_clip": True,
            "order_code": info.get("order_code") or "", "recv_time": "", "vd_gui": info.get("vd_gui") or "",
            "return_code": info.get("return_code") or "",
            "track_return": info.get("track_return") or u.get("code") or "",   # clip dư: mã clip chính là VĐ hoàn về
            "nhan_vien": u.get("staff") or "",
            "sku": info.get("sku") or "", "loai_tra": info.get("loai_tra") or "",
            "loai_tra_code": info.get("loai_tra_code") or "", "has_sapo": False,
        })
    nk["recon_rows"] = recon
    if dvr is not None:
        vset = set((dvr.get("codes") or {}).keys())
        dgc = rep.get("dong_goi_codes") or set()
        hgc = rep.get("huy_goi_codes") or set()
        dgo = rep.get("dong_goi_order_codes") or []
        # Khớp CHỊU LỖI PHÔNG (mã video méo/dính) thay vì so khớp tuyệt đối.
        _matched, _font = match_packing_videos([d.get("codes", []) for d in dgo], vset)
        owv = len(_matched)
        missing = [d.get("track") for i, d in enumerate(dgo) if i not in _matched]
        _mcanc = sum(1 for c in vset if c not in dgc and c in hgc)
        rep["video_recon"] = {
            "available": True, "total": dvr.get("total", 0),
            "dup": dvr.get("dup", {}), "open_with_video": owv,
            "missing_video": len(missing), "missing_codes": missing,
            "font_fixed": _font,            # [(mã_video_lỗi, mã_đơn)] đã tự cứu được
        }
        if isinstance(rep.get("funnel"), dict):
            # Đã có video = đóng gói còn hiệu lực có video + đơn HỦY đã gói có video (gồm cả hủy)
            rep["funnel"]["video"] = owv + _mcanc
    else:
        rep["video_recon"] = {"available": False}


def render_compact_table(df, red_mask=None):
    """Bảng HTML gọn (nhỏ, ít khoảng trắng); red_mask=list bool để tô đỏ dòng lệch."""
    cols = list(df.columns)
    head = "".join(f"<th>{_esc(str(c))}</th>" for c in cols)
    rm = list(red_mask) if red_mask is not None else None
    body = []
    for i in range(len(df)):
        row = df.iloc[i]
        cls = " class='hl'" if rm is not None and rm[i] else ""
        tds = ""
        for c in cols:
            v = row[c]
            is_num = isinstance(v, (int, float)) and not isinstance(v, bool)
            tds += (f"<td class='num'>{_esc(str(v))}</td>" if is_num
                    else f"<td>{_esc(str(v))}</td>")
        body.append(f"<tr{cls}>{tds}</tr>")
    st.markdown(
        "<div class='ctab-wrap'><table class='ctab'><thead><tr>" + head
        + "</tr></thead><tbody>" + "".join(body) + "</tbody></table></div>",
        unsafe_allow_html=True,
    )


_PICKLOG_SETUP = """
**Bật lưu lịch sử in phiếu — lưu trên GitHub Gist (bền, không bao giờ tự xóa):**

1. Tạo **token GitHub**: vào https://github.com/settings/tokens → **Generate new token (classic)**
   → tick đúng ô **`gist`** → Generate → **copy** token (dạng `ghp_...`).
2. Mở **Streamlit Cloud** → app VITRAN → **⋮ Manage app → Settings → Secrets**, thêm rồi **Save**:
   ```toml
   [picklog]
   github_token = "ghp_xxx"
   ```
3. App tự khởi động lại. Bấm **🖨️ In phiếu nhặt + tự lưu đợt** là tự lưu (gist tự tạo lần đầu).
"""

_DOHANA_SETUP = """
**Bật đối chiếu video đóng hàng (Dohana) — thêm vào Streamlit Secrets:**

1. Mở **Streamlit Cloud** → app VITRAN → **⋮ Manage app → Settings → Secrets**.
2. Thêm 2 dòng (API Key lấy ở Dohana → Cài đặt → API Keys) rồi **Save**:
   ```toml
   [dohana]
   x_api_key = "API-KEY-CỦA-BẠN"
   ```
3. App tự khởi động lại — sẽ tự đối chiếu số video vs số đơn đã đóng + báo video trùng.
"""


# ═══════════════════════ ĐĂNG NHẬP (multi-user) ═══════════════════════
def _auth_configured() -> bool:
    try:
        return "auth" in st.secrets and "users" in st.secrets["auth"] and len(st.secrets["auth"]["users"]) > 0
    except Exception:
        return False


def require_login():
    """Chặn nếu chưa đăng nhập. Trả về (name, username, role).
    Nếu CHƯA cấu hình tài khoản trong secrets -> bỏ qua đăng nhập (mở tự do)."""
    if not _auth_configured():
        st.sidebar.caption("🔓 Chưa cấu hình tài khoản — đang mở tự do (xem README).")
        return ("Khách", "guest", "admin")

    users = st.secrets["auth"].get("users", {})
    ck = st.secrets["auth"].get("cookie", {})
    credentials = {"usernames": {}}
    for uname, info in users.items():
        password = (
            info.get("password")
            or info.get("password_hash")
            or info.get("hashed_password")
            or info.get("pass")
        )
        if not password:
            continue
        credentials["usernames"][uname] = {
            "name": info.get("name", uname),
            "password": password,
            "email": info.get("email", f"{uname}@vitran.local"),
            "roles": [info.get("role", "viewer")],
        }
    if not credentials["usernames"]:
        st.error("Auth secrets co [auth.users] nhung chua co user nao co password hop le.")
        st.stop()

    authenticator = stauth.Authenticate(
        credentials,
        ck.get("name", "vitran_dashboard_auth"),
        ck.get("key", "vitran-please-change-this-key"),
        ck.get("expiry_days", 30),
        auto_hash=True,
    )
    authenticator.login(location="main", fields={
        "Form name": "🔒 Đăng nhập — Báo cáo VITRAN BOUTIQUE",
        "Username": "Tên đăng nhập", "Password": "Mật khẩu", "Login": "Đăng nhập",
    })

    status = st.session_state.get("authentication_status")
    if status is False:
        st.error("❌ Sai tên đăng nhập hoặc mật khẩu.")
        st.stop()
    if status is None:
        st.info("🔒 Vui lòng đăng nhập để xem báo cáo. Tài khoản do quản trị cấp (gửi qua Zalo).")
        st.stop()

    name = st.session_state.get("name")
    username = st.session_state.get("username")
    roles = st.session_state.get("roles") or ["viewer"]
    with st.sidebar:
        st.markdown(
            f'<div style="background:rgba(255,255,255,.08);border:1px solid rgba(255,255,255,.18);'
            f'border-radius:10px;padding:10px 12px;margin-bottom:8px">'
            f'<div style="font-weight:800;color:#fff">👤 {name}</div>'
            f'<div style="font-size:.78rem;color:#aebcd4">{username} · vai trò: {roles[0]}</div></div>',
            unsafe_allow_html=True)
        authenticator.logout("🚪 Đăng xuất", "sidebar")
        st.divider()
    return (name, username, roles[0])


# ── Chế độ THIẾT BỊ: NV mở link ?nv=kho&k=... → vào THẲNG chấm công, khỏi đăng nhập ──
_dv_nv = st.query_params.get("nv")
if _dv_nv and cham_cong.verify_device(_dv_nv, st.query_params.get("k")):
    if _dv_nv == "shop":
        cham_cong_ui.render_shop_qr()      # máy shop: link riêng → thẳng trang mã, khỏi đăng nhập
    else:
        cham_cong_ui.render_checkin_dev(_dv_nv)
    st.stop()

CUR_NAME, CUR_USER, CUR_ROLE = require_login()


# ───────────────────────── Chọn trang ─────────────────────────
PAGE_OVERVIEW = "📊 Tổng quan điều hành"
PAGE_REPORT = "📋 Báo cáo sáng"
PAGE_PICK = "🧾 Phiếu nhặt hàng"
PAGE_TTKH = "📞 Lấy - lưu TTKH"
PAGE_DAILY = "📄 Báo cáo cuối ngày"
PAGE_RETURNS = "📦 Đơn trả hàng đang xử lý"
PAGE_PRODUCTION = "🧵 Dự đoán sản xuất"
PAGE_PRICE = "🧮 Tính giá bán"
PAGE_CHAMCONG = "🕘 Chấm công"
PAGE_LUONG = "💰 Lương của tôi"
PAGE_QRSHOP = "📲 QR chấm công (shop)"
PAGE_QLCC = "🛠️ Quản lý chấm công"
PAGE_OPS = "📊 Vận hành"   # tab: Báo cáo cuối ngày + Đơn trả + Phiếu nhặt (CSKH chỉ thấy Báo cáo)

# Phân quyền theo tài khoản.
#  · Tổng quan + Báo cáo cuối ngày: AI CŨNG xem được.
#  · Kho: thêm Phiếu nhặt + Đơn trả.  · CSKH: thêm Lấy-lưu TTKH.
#  · Chấm công/Lương: của ai người nấy.  · Admin: xem hết + QR shop + quản lý chấm công.
_cc_role = cham_cong.role_of(CUR_USER)
_cc_emp = cham_cong.emp_of(CUR_USER)
# Trang "Tổng quan điều hành" TÁCH RIÊNG — chỉ chủ shop + zenzen197 xem được.
_OWNER_USERS = {"vitran2291@gmail.com", "zenzen197@gmail.com"}
_is_owner = str(CUR_USER).strip().lower() in _OWNER_USERS
_is_cskh = (_cc_role == "nv" and _cc_emp != "kho")   # CSKH: KHÔNG thấy tab Đơn trả & Phiếu nhặt
# PAGE_OPS (Vận hành) gồm: Báo cáo cuối ngày (mặc định) + Đơn trả + Phiếu nhặt (tab ngang).
if _cc_role == "nv":
    _rolepg = [PAGE_PRODUCTION] if _cc_emp == "kho" else [PAGE_TTKH]
    _opts = [PAGE_OPS] + _rolepg + [PAGE_CHAMCONG, PAGE_LUONG]
    _default = PAGE_CHAMCONG if st.query_params.get("tk") else PAGE_OPS   # quét QR → về Chấm công
elif _cc_role == "shop":                    # máy shop: CHỈ thấy trang hiện mã QR chấm công
    _opts = [PAGE_QRSHOP]
    _default = PAGE_QRSHOP
elif _cc_role == "admin":
    _opts = [PAGE_OPS, PAGE_PRODUCTION, PAGE_PRICE, PAGE_TTKH, PAGE_QRSHOP, PAGE_QLCC]
    _default = PAGE_OPS
else:
    _opts = [PAGE_OPS, PAGE_PRODUCTION, PAGE_PRICE, PAGE_TTKH]
    _default = PAGE_OPS
if _is_owner:                               # chủ shop + zenzen197: thêm trang Tổng quan điều hành
    _opts = [PAGE_OVERVIEW] + _opts
if (st.query_params.get("page_ttkh") or st.query_params.get("ttkh_phone")) and PAGE_TTKH in _opts:
    _default = PAGE_TTKH
_sees_production = PAGE_PRODUCTION in _opts   # kho/admin: hiện cảnh báo việc SX/cắt tay mọi tab
_idx = _opts.index(_default) if _default in _opts else 0
_page = st.sidebar.radio("Trang", _opts, index=_idx)
st.sidebar.divider()

# ── Trang CHẤM CÔNG (tách riêng — không cần dữ liệu Sapo) ──
if _page == PAGE_CHAMCONG:
    cham_cong_ui.render_checkin(CUR_USER); st.stop()
if _page == PAGE_LUONG:
    cham_cong_ui.render_my_salary(CUR_USER); st.stop()
if _page == PAGE_QRSHOP:
    cham_cong_ui.render_shop_qr(); st.stop()
if _page == PAGE_QLCC:
    cham_cong_ui.render_admin(); st.stop()


# ── Biểu đồ dùng chung ──
def donut(labels, values, colors, center_text):
    fig = go.Figure(go.Pie(
        labels=labels, values=values, hole=0.58,
        marker=dict(colors=colors, line=dict(color="white", width=2)),
        sort=False, textinfo="label+value", textposition="outside",
    ))
    fig.update_layout(
        annotations=[dict(text=center_text, x=0.5, y=0.5, font_size=24,
                          font_color="#333", showarrow=False)],
        showlegend=True,
        legend=dict(orientation="h", y=-0.12, x=0.5, xanchor="center"),
        margin=dict(t=10, b=10, l=10, r=10), height=330,
    )
    return fig


def daily_chart(daily):
    x = [d["ngay"] for d in daily]
    fig = go.Figure()
    fig.add_bar(x=x, y=[d["don"] for d in daily], name="Tổng đơn", marker_color="#534AB7")
    fig.add_scatter(x=x, y=[d["sp"] for d in daily], name="Tổng SP", mode="lines+markers",
                    line=dict(color="#1D9E75", width=3), yaxis="y2")
    fig.update_layout(
        height=300, margin=dict(t=24, b=10, l=10, r=10),
        yaxis2=dict(overlaying="y", side="right", showgrid=False),
        legend=dict(orientation="h", y=1.14, x=0), bargap=0.45,
    )
    return fig


@st.cache_data(ttl=300, show_spinner="Đang tải tổng quan từ Sapo…")
def load_overview():
    return L.get_overview(make_fetch_json(build_session()))


@st.cache_data(ttl=120, show_spinner="Đang kéo đơn cần nhặt từ Sapo…")
def load_picking():
    return L.get_picking(make_fetch_json(build_session()))


@st.cache_data(ttl=180, show_spinner="Đang lọc đơn cần lấy TTKH…")
def load_ttkh_candidates(days=15, channel_filter="tiktok"):
    # Đơn CẦN lấy TTKH = đơn chưa có SĐT trên đơn (real-time từ Sapo). Tự hiện/tự mất,
    # KHÔNG dùng danh sách chờ lưu cứng (dễ kẹt). Phần khách text/thiếu → tab Kiểm tra.
    return L.get_tt_customer_candidates(make_fetch_json(build_session()), days=days,
                                        channel_filter=channel_filter, pending_ids=None)


@st.cache_data(ttl=600, show_spinner=False)
def load_customer_phone_set():
    """Tập SĐT khách hàng (canon) — cache 10 phút. Shop ~28k khách (~115 trang),
    max_pages=220 (~55k) chừa dư cho tăng trưởng để không bỏ sót khách."""
    return L.get_customer_phone_set(make_fetch_json(build_session()), max_pages=220)


def _sapo_lookup_key(value) -> str:
    return re.sub(r"\s+", "", str(value or "")).upper()


def _standard_result_note_text(note: str) -> str:
    note = str(note or "").strip()
    if not note:
        return ""
    lines = note.splitlines()
    first = lines[0].strip() if lines else ""
    compact = "".join(ch for ch in _ascii_code(first) if ch.isalnum())
    standards = [
        ("KHONGCANKN", "⚪ KHÔNG CẦN KN"),
        ("KHONGCANKHIEUNAI", "⚪ KHÔNG CẦN KN"),
        ("HETHAN", "⏰ HẾT HẠN"),
        ("THANG", "✅ THẮNG"),
        ("THUA", "❌ THUA"),
        ("HUY", "🚫 HỦY"),
        ("CANKN", "🚨 CẦN KN"),
    ]
    for token, label in standards:
        if token in compact and label not in first:
            suffix = first.split("|", 1)[1].strip() if "|" in first else ""
            lines[0] = f"{label} | {suffix}".rstrip(" |")
            break
    return "\n".join(lines).strip()


def _note_is_standard(note: str) -> bool:
    """Ghi chú CHUẨN = dòng đầu có nhãn kết quả KN (KHÔNG CẦN KN / HẾT HẠN / THẮNG / THUA / HỦY / CẦN KN)."""
    first = (str(note or "").strip().splitlines() or [""])[0]
    compact = "".join(ch for ch in _ascii_code(first) if ch.isalnum())
    return any(t in compact for t in
               ("KHONGCANKN", "KHONGCANKHIEUNAI", "HETHAN", "THANG", "THUA", "HUY", "CANKN"))


def _note_is_concluded(note: str) -> bool:
    """Ghi chú ĐÃ KẾT LUẬN (hết cần KN): THẮNG / THUA / KHÔNG CẦN KN / HẾT HẠN / HỦY.
    ⚠️ 'CẦN KN' KHÔNG tính kết luận (vẫn phải khiếu nại → giữ tô vàng + nằm trong bảng Cần KN)."""
    first = (str(note or "").strip().splitlines() or [""])[0]
    compact = "".join(ch for ch in _ascii_code(first) if ch.isalnum())
    return any(t in compact for t in
               ("KHONGCANKN", "KHONGCANKHIEUNAI", "HETHAN", "THANG", "THUA", "HUY"))


def _nv_row_restock(it):
    """Đổi 1 đơn 'ĐÃ nhập kho nhưng thiếu video khui' (đã enrich) → row cho _sub_table.
    Lý do KN = 'NV nhập kho sai' cho CẢ bảng; tô vàng (need_kn) đến khi có ghi chú CHUẨN thì thôi
    (khi đó tự rớt khỏi Cần KN). Dùng chung cho bảng 'theo loại' lẫn danh sách Cần KN."""
    _std = _note_is_standard(it.get("ghi_chu", ""))
    # Đơn CHỈ HOÀN TIỀN (không có hàng hoàn về) → KHÔNG cần video khui → KHÔNG phải lỗi NV: đổi nhãn
    # + KHÔNG tô vàng / KHÔNG đưa vào Cần KN. Nhờ group theo loại, đơn này tự nằm ở mục "Chỉ hoàn tiền".
    _refund = str(it.get("loai_tra_code") or "") == "refund"
    return {
        "order_code": it.get("order_code") or "", "return_code": it.get("return_code") or "",
        "order_source": it.get("order_source") or "", "gian_hang": it.get("gian_hang") or "",
        "order_link": it.get("order_link") or "", "return_link": it.get("return_link") or "",
        "vd_di": it.get("vd_di") or "", "vd_tra": it.get("vd_tra") or "",
        "created": it.get("ngay_tao") or it.get("restock_date") or "",
        "created_on": it.get("restock_date") or "",
        "note": it.get("ghi_chu") or "", "reason": it.get("ly_do") or "",
        "_reason_label": ("💸 Chỉ hoàn tiền — không cần video" if _refund else "❌ NV nhập kho sai"),
        "loai_tra": it.get("loai_tra") or "", "loai_tra_code": it.get("loai_tra_code") or "",
        "sku": it.get("sku") or "", "qty": it.get("sp") or 0, "money": it.get("money") or 0,
        "stock_status": "Đã nhập kho", "return_shipper": it.get("carrier") or "",
        "need_kn": (False if _refund else (not _std)),  # refund: không tô vàng, không vào Cần KN
        "_restock_novideo": True,
    }


def _return_row_from_sapo_api(row: dict, detail: dict | None = None) -> dict:
    detail = detail or row or {}
    row = row or {}
    order = detail.get("order") or row.get("order") or {}
    order_id = order.get("id") or detail.get("order_id") or row.get("order_id")
    if not order and order_id:
        try:
            order = get_order(build_session(), order_id) or {}
        except Exception:
            order = {}
    si = detail.get("shipping_info") or row.get("shipping_info") or {}
    created_raw = detail.get("created_on") or row.get("created_on") or ""
    try:
        created_disp = (datetime.fromisoformat(str(created_raw).replace("Z", "").split(".")[0])
                        + timedelta(hours=7)).strftime("%d/%m %H:%M")
    except Exception:
        created_disp = ""
    return_id = detail.get("id") or row.get("id") or ""
    return_type = detail.get("return_type") or row.get("return_type") or "refund"
    ship_status = str(detail.get("shipment_status") or row.get("shipment_status") or "").lower()
    stock_code = str(detail.get("stock_status") or detail.get("restock_status")
                     or row.get("stock_status") or row.get("restock_status") or "").lower()
    note = _standard_result_note_text(detail.get("note") or row.get("note") or "")
    m = re.search(r"shipper\s*ho[aà]n\s*:\s*([^|\n\r]+)", note, flags=re.I)
    return_shipper = (m.group(1).strip() if m else "")
    if not return_shipper:
        for key in ("return_shipper_name", "shipper_name", "delivery_staff_name", "driver_name"):
            val = str(si.get(key) or "").strip()
            if val:
                return_shipper = val
                break
    def _nested_line_items(*docs):
        for doc in docs:
            if not isinstance(doc, dict):
                continue
            for key in ("line_items", "return_line_items", "order_return_line_items", "refund_line_items", "items"):
                items = doc.get(key) or []
                if items:
                    return items
        return []

    def _li_sku(li):
        src = li.get("line_item") or li.get("product") or li.get("variant") or li
        return (li.get("sku") or src.get("sku") or li.get("variant_sku")
                or src.get("variant_sku") or li.get("barcode") or src.get("barcode") or "N/A")

    def _li_qty(li):
        for key in ("quantity", "return_quantity", "returned_quantity", "restock_quantity", "qty"):
            try:
                val = float(li.get(key) or 0)
            except Exception:
                val = 0
            if val:
                return val
        return 0

    def _li_money(li):
        for key in ("total_price", "line_price", "subtotal", "amount"):
            try:
                val = float(li.get(key) or 0)
            except Exception:
                val = 0
            if val:
                return val
        for key in ("price", "unit_price", "original_price"):
            try:
                val = float(li.get(key) or 0) * _li_qty(li)
            except Exception:
                val = 0
            if val:
                return val
        return 0

    line_items = _nested_line_items(detail, row) or _nested_line_items(order)
    sku = "; ".join(f"{_li_sku(li)}×{int(round(_li_qty(li)))}" for li in line_items)
    qty = detail.get("total_quantity") or row.get("total_quantity")
    if qty in (None, "") and line_items:
        qty = sum(_li_qty(li) for li in line_items)
    money = detail.get("total_price") or row.get("total_price")
    if money in (None, "") and line_items:
        money = sum(_li_money(li) for li in line_items)
    channel = (order.get("channel_definition") or detail.get("channel_definition")
               or row.get("channel_definition") or {})
    source_name = str(
        detail.get("order_source") or row.get("order_source") or order.get("source_name")
        or order.get("source") or channel.get("source_name") or channel.get("name") or ""
    ).strip()
    source_label = {
        "tiktokshop": "Tiktokshop", "tiktok": "Tiktokshop",
        "shopee": "Shopee", "shopee2": "Shopee",
    }.get(source_name.lower(), source_name.title())
    branch = channel.get("branch_name") or channel.get("main_name") or "VITRAN BOUTIQUE"
    gian_hang = " - ".join(x for x in (branch, source_label) if x)
    order_code = order.get("name") or ""
    return_code = detail.get("name") or row.get("name") or ""
    source_l = source_name.lower()
    if "shopee" in source_l:
        order_link = L.shopee_order_detail_url(detail, row, order, keyword=order_code)
        return_link = L.shopee_return_detail_url(
            detail,
            row,
            keyword=return_code or si.get("tracking_number") or order.get("name") or "",
        )
    elif "tiktok" in source_l:
        order_link = L.tiktok_order_detail_url(order_code)
        _ret_key = re.sub(r"[^A-Z0-9]+", "", str(return_code or "").upper())
        _ord_key = re.sub(r"[^A-Z0-9]+", "", str(order_code or "").upper())
        if _ret_key and _ret_key == _ord_key:
            return_link = order_link
        else:
            return_link = L.tiktok_return_search_url(detail, row, return_code, si.get("tracking_number"))
    else:
        order_link = f"https://vitranboutiquehcm.mysapo.net/admin/orders/{order_id}" if order_id else ""
        return_link = f"https://vitranboutiquehcm.mysapo.net/admin/order_returns/{return_id}" if return_id else ""
    return {
        "sapo_return_id": return_id,
        "order_code": order_code,
        "order_link": order_link,
        "return_code": return_code,
        "return_link": return_link,
        "created": created_disp,
        "created_on": created_raw,
        "vd_di": ((si.get("fulfillment_tracking_numbers") or [None])[0]) or "",
        "vd_tra": si.get("tracking_number") or "",
        "return_shipper": return_shipper,
        "note": note,
        "order_source": source_name,
        "gian_hang": gian_hang,
        "sku": sku,
        "qty": int(round(float(qty or 0))),
        "money": int(round(float(money or 0))),
        "loai_tra": {
            "return_and_refund": "Trả hàng hoàn tiền",
            "delivery_failed": "Giao hàng thất bại",
            "refund": "Chỉ hoàn tiền",
        }.get(return_type, return_type),
        "loai_tra_code": return_type,
        "ship_code": ship_status or "",
        "stock_status": stock_code or "Chưa rõ",
        "stock_code": stock_code,
        "need_kn": False,
        "_from_sapo_lookup": True,
    }


@st.cache_data(ttl=1800, show_spinner=False)
def load_return_rows_by_codes(codes_tuple, max_pages=180):
    """Dò Sapo Trả hàng theo mã Dohana/mã vận đơn để lấy lại mã đơn thật, kể cả phiếu bị Sapo gạch/hủy."""
    codes = sorted({_sapo_lookup_key(c) for c in (codes_tuple or []) if _sapo_lookup_key(c)})
    if not codes:
        return {}
    session = build_session()
    matches = find_order_returns_by_codes(session, codes, max_pages=int(max_pages))
    out = {c: [] for c in codes}
    for code in codes:
        for row in matches.get(code) or []:
            detail = row
            rid = row.get("id")
            if rid:
                try:
                    detail = {**row, **(get_order_return(session, rid) or {})}
                except Exception:
                    detail = row
            out[code].append(_return_row_from_sapo_api(row, detail))
    return out


# Dohana: fetch TRỰC TIẾP thành công → MERGE vào kho Gist (lưu cả năm) rồi trả về. Nếu API tạm
# không phản hồi (rate limit 10 req/s / 429) → DỰNG LẠI từ KHO đã lưu → báo cáo LUÔN có video.
def _dohana_merge(live):
    """Fetch OK → gộp records vào kho Gist (khử trùng), rồi trả nguyên dict live."""
    if picklog.configured() and isinstance(live, dict) and live.get("records"):
        try:
            picklog.merge_dohana_videos(live["records"])
        except Exception:
            pass
    return live


def _dohana_pkg_from_store(date_iso, days_match=3):
    """Dựng lại dict video ĐÓNG GÓI (package) từ kho khi Dohana tạm không lấy được."""
    from datetime import date as _date, timedelta as _td
    recs = [r for r in picklog.read_dohana_videos()
            if r.get("type") == "package" and _dohana_video_active(r)]
    lo = (_date.fromisoformat(date_iso) - _td(days=days_match - 1)).isoformat()
    day = [r for r in recs if r.get("date") == date_iso]
    codes = {}
    for r in day:
        c = r.get("code")
        if c:
            codes[c] = codes.get(c, 0) + 1
    return {"total": len(day), "codes": codes, "dup": {},
            "match": {r.get("code") for r in recs
                      if r.get("code") and r.get("date") and lo <= r["date"] <= date_iso},
            "records": [], "_from_store": True}


def _dohana_inb_from_store(date_iso, days_match=3):
    """Dựng lại dict CLIP KHUI HÀNG (inbound) từ kho khi Dohana tạm không lấy được."""
    from datetime import date as _date, timedelta as _td
    recs = [r for r in picklog.read_dohana_videos()
            if r.get("type") == "inbound" and _dohana_video_active(r)]
    lo = (_date.fromisoformat(date_iso) - _td(days=days_match - 1)).isoformat()
    day = [r for r in recs if r.get("date") == date_iso]
    win = [r for r in recs if r.get("code") and r.get("date") and lo <= r["date"] <= date_iso]
    count, meta = {}, {}
    for r in win:
        c = r["code"]
        count[c] = count.get(c, 0) + 1
        if c not in meta:
            _p = str(r.get("date") or "").split("-")
            _dd = f"{_p[2]}/{_p[1]}" if len(_p) == 3 else ""
            meta[c] = {"dur": r.get("dur"), "recorded": (f"{r.get('time') or ''} {_dd}").strip(),
                       "tag_id": _video_tag_id(r),
                       "tag": _video_tag_label(r),
                       "link": r.get("link") or "",
                       "staff": r.get("staff") or ""}
    return {"total": len(day), "count": count, "match": set(count),
            "today_codes": {r.get("code") for r in day if r.get("code")},
            "dup": {}, "meta": meta, "records": [], "_from_store": True}


def _today_iso_vn():
    return (datetime.now(timezone.utc) + timedelta(hours=7)).date().isoformat()


def _dohana_video_active(row):
    status = _ascii_code((row or {}).get("status") or "")
    return not any(token in status for token in ("DELETED", "REMOVED", "DAXOA", "XOA"))


@st.cache_data(ttl=3600, show_spinner=False)   # 1 GIỜ: gọi Dohana thật thưa để khỏi bị phạt 429
def load_dohana():
    live = dohana.today_package_videos()
    if live is not None:
        return _dohana_merge(live)
    return _dohana_pkg_from_store(_today_iso_vn()) if picklog.configured() else None


@st.cache_data(ttl=3600, show_spinner=False)   # 1 GIỜ: gọi Dohana thật thưa để khỏi bị phạt 429
def load_dohana_inbound():
    live = dohana.inbound_videos()
    if live is not None:
        return _dohana_merge(live)
    return _dohana_inb_from_store(_today_iso_vn()) if picklog.configured() else None


@st.cache_data(ttl=3600, show_spinner=False)
def load_dohana_videos():
    """Metadata MỌI video Dohana (trạng thái·ngày·giờ·thời lượng·tag) — TÍCH LUỸ vào Gist để LƯU
    CẢ NĂM (Dohana chỉ giữ 30 ngày; kho Gist là bản lưu bền)."""
    if not picklog.configured():
        return []
    dvr = load_dohana() or {}
    inb = load_dohana_inbound() or {}
    new = (dvr.get("records") or []) + (inb.get("records") or [])
    return picklog.merge_dohana_videos(new)


@st.cache_data(ttl=900, show_spinner=False)
def load_dohana_video_store():
    """Đọc nhanh kho video đã lưu, không gọi live Dohana khi mở trang trả hàng."""
    if not picklog.configured():
        return []
    return picklog.read_dohana_videos()


@st.cache_data(ttl=1800, show_spinner=False)  # video ngày cũ không đổi → cache dài, đỡ gọi Dohana
def load_dohana_date(date_iso):
    from datetime import date as _date
    live = dohana.today_package_videos(target_date=_date.fromisoformat(date_iso))
    if live is not None:
        merged = _dohana_merge(live)
        if merged.get("total") or merged.get("match") or not picklog.configured():
            return merged
        store = _dohana_pkg_from_store(date_iso)
        return store if (store.get("total") or store.get("match")) else merged
    return _dohana_pkg_from_store(date_iso) if picklog.configured() else None


@st.cache_data(ttl=1800, show_spinner=False)  # video ngày cũ không đổi → cache dài, đỡ gọi Dohana
def load_dohana_inbound_date(date_iso):
    from datetime import date as _date
    live = dohana.inbound_videos(target_date=_date.fromisoformat(date_iso))
    if live is not None:
        merged = _dohana_merge(live)
        if merged.get("total") or merged.get("match") or not picklog.configured():
            return merged
        store = _dohana_inb_from_store(date_iso)
        return store if (store.get("total") or store.get("match")) else merged
    return _dohana_inb_from_store(date_iso) if picklog.configured() else None


@st.cache_data(ttl=180, show_spinner="Đang tổng hợp báo cáo cuối ngày…")
def load_daily_report(date_iso=None):
    from datetime import date as _date
    td = _date.fromisoformat(date_iso) if date_iso else None
    return L.get_daily_report(make_fetch_json(build_session()), target_date=td)


def _inject_huy_soan(rep, date_iso):
    """Cắm cờ 'soan' cho từng đơn HỦY: mã (VĐ/đơn) ∈ mã phiếu nhặt đã lưu ngày đó = ĐÃ SOẠN
    (cầm hàng ra kho → cần lấy lại). Không có trong phiếu nhặt = hủy sớm, khỏi lấy.
    Chỉ tách được khi phiếu nhặt ngày đó có lưu mã đơn (từ bản cập nhật này trở đi)."""
    if not (picklog.configured() and isinstance(rep, dict) and rep.get("huy_all_detail")):
        return
    try:
        _codes = set()
        for _e in picklog.read_date(date_iso):
            _codes |= {str(c).strip() for c in (_e.get("codes") or []) if c}
        if not _codes:
            return   # ngày chưa lưu mã phiếu nhặt → không tách được (giữ list cũ)
        for _h in rep["huy_all_detail"]:
            _h["soan"] = bool(str(_h.get("tracking") or "").strip() in _codes
                              or str(_h.get("name") or "").strip() in _codes)
        rep["huy_soan_known"] = True
    except Exception:
        pass


def _apply_picklog_soan_to_daily(rep, rows, dvr=None, dup_orders=0):
    """Dùng phiếu nhặt đã khử trùng làm số đã soạn trong báo cáo A4."""
    if not (isinstance(rep, dict) and rows):
        return
    batches = []
    total_orders = total_qty = 0
    code_groups, code_labels = [], []
    from collections import Counter
    carrier_counts = Counter()
    alias_raw, alias_norm = {}, {}

    def _add_alias_group(values):
        _codes = {str(c).strip() for c in (values or []) if str(c).strip()}
        if not _codes:
            return
        for _c in _codes:
            alias_raw.setdefault(_c, set()).update(_codes)
            _nc = _ascii_code(_c)
            if _nc:
                alias_norm.setdefault(_nc, set()).update(_codes)

    for _item in rep.get("dong_goi_order_codes") or []:
        _vals = list(_item.get("codes") or [])
        _vals.append(_item.get("track"))
        _add_alias_group(_vals)
    for _item in rep.get("confirmed_today_order_codes") or []:
        _vals = list(_item.get("codes") or [])
        for _key in ("tracking", "track", "name"):
            _vals.append(_item.get(_key))
        _add_alias_group(_vals)
    for _item in rep.get("order_code_aliases") or []:
        _vals = list(_item.get("codes") or [])
        for _key in ("tracking", "track", "name"):
            _vals.append(_item.get(_key))
        _add_alias_group(_vals)

    def _prefer_video_lookup_code(codes):
        vals = [str(c or "").strip() for c in (codes or []) if str(c or "").strip()]
        vals = list(dict.fromkeys(vals))
        if not vals:
            return ""

        def _score(code):
            raw = str(code or "").strip()
            n = _ascii_code(raw)
            if not n:
                return (9, raw)
            if n.startswith(("SPXVN", "VTPVN", "GYX", "GHN", "GHTK", "JNT", "JT")):
                return (0, raw)
            if re.fullmatch(r"\d{9,14}", n):
                return (1, raw)
            if "_" in raw:
                return (5, raw)
            return (3, raw)

        return sorted(vals, key=_score)[0]

    def _expand_group(group):
        out = {str(c).strip() for c in (group or []) if str(c).strip()}
        for c in list(out):
            out.update(alias_raw.get(c, set()))
            nc = _ascii_code(c)
            if nc:
                out.update(alias_norm.get(nc, set()))
        return sorted(out)

    for idx, r in enumerate(rows, 1):
        don = int(r.get("so_don") or 0)
        sp = int(r.get("so_sp") or 0)
        total_orders += don
        total_qty += sp
        for _c, _n in (r.get("carriers") or {}).items():
            _ck = "Hỏa tốc (SPX Instant)" if str(_c) == "SPX Instant" else str(_c or "Khác")
            carrier_counts[_ck] += int(_n or 0)
        codes = [str(c).strip() for c in (r.get("codes") or []) if str(c).strip()]
        row_groups = []
        raw_groups = r.get("code_groups") or []
        if raw_groups:
            for group in raw_groups:
                expanded = _expand_group(group)
                if expanded:
                    row_groups.append(expanded)
        else:
            row_groups = [_expand_group([code]) for code in codes]
        if don and len(row_groups) > don:
            row_groups = row_groups[:don]
        for group in row_groups:
            code_groups.append(group)
            code_labels.append(_prefer_video_lookup_code(group))
        batches.append({
            "dot": idx,
            "gio": str(r.get("gio") or "—"),
            "don": don,
            "sp": sp,
            "sku_count": int(r.get("so_sku") or 0),
            "hoatoc": int(r.get("ht_don") or 0),
            "xuat": 0,
            "summary": {},
        })
    if rep.get("confirmed_today_order_codes") is not None:
        _pick_codes, _pick_norms = set(), set()
        for _group in code_groups:
            for _c in _group:
                _s = str(_c or "").strip()
                if not _s:
                    continue
                _pick_codes.add(_s)
                _n = _ascii_code(_s)
                if _n:
                    _pick_norms.add(_n)
        _miss_confirmed = []
        for _item in rep.get("confirmed_today_order_codes") or []:
            _codes = [str(c or "").strip() for c in (_item.get("codes") or []) if str(c or "").strip()]
            _hit = False
            for _c in _codes:
                if _c in _pick_codes:
                    _hit = True
                    break
                _n = _ascii_code(_c)
                if _n and _n in _pick_norms:
                    _hit = True
                    break
            if not _hit:
                _miss_confirmed.append(_item)
        rep["confirmed_not_in_picklog"] = _miss_confirmed
    rep["batches"] = batches
    rep["tong_don_soan"] = total_orders
    rep["tong_sp_soan"] = total_qty
    rep["soan_source"] = "picklog_dedup"
    if isinstance(rep.get("by_carrier"), list):
        if carrier_counts:
            for _r in rep["by_carrier"]:
                _r["soan"] = int(carrier_counts.get(str(_r.get("carrier") or "Khác"), 0))
        else:
            for _r in rep["by_carrier"]:
                _r["soan"] = int(_r.get("dg_cu") or 0) + int(_r.get("dong_goi") or 0)
    if isinstance(rep.get("totals"), dict):
        rep["totals"]["soan"] = total_orders
    if dup_orders:
        rep["soan_dup_orders"] = int(dup_orders)
    if isinstance(rep.get("funnel"), dict):
        rep["funnel"]["soan"] = total_orders or None
        rep["funnel"]["soan_sp"] = total_qty or None
        rep["funnel"]["base"] = total_orders or rep["funnel"].get("base")
    if dvr is not None and code_groups:
        vset = set((dvr.get("codes") or {}).keys())
        matched, font_fixed = match_packing_videos(code_groups, vset)
        missing = [code_labels[i] for i in range(len(code_groups)) if i not in matched]
        unknown = max(0, total_orders - len(code_groups))
        if unknown:
            missing += [f"{unknown} đơn phiếu nhặt chưa lưu mã đối chiếu"]
        missing_count = len(missing)
        video_total = int(dvr.get("total") or 0)
        unique_video = len(vset)
        rep["video_recon"] = {
            "available": True,
            "total": video_total,
            "unique_total": unique_video,
            "dup": dvr.get("dup", {}),
            "open_with_video": len(matched),
            "matched_video": len(matched),
            "unmatched_order_count": missing_count,
            "raw_unmatched_order_count": max(0, total_orders - len(matched)),
            "unmatched_order_codes": missing,
            "missing_video": missing_count,
            "missing_codes": missing,
            "font_fixed": font_fixed,
            "source": "picklog_dedup",
        }
        if isinstance(rep.get("funnel"), dict):
            rep["funnel"]["video"] = len(matched)


@st.cache_data(ttl=300, show_spinner="Đang tổng hợp 30 ngày (1 tháng)…")
def load_week_summary():
    data = L.get_week_summary(make_fetch_json(build_session()), days=30)
    # SOẠN = tổng đơn các ĐỢT PHIẾU NHẶT đã in trong ngày (picklog so_don) — đúng số ở tab Phiếu nhặt.
    # Ngày CHƯA lưu đợt nào → giữ ước lượng theo shipment_created_on (từ sapo_logic).
    try:
        if picklog.configured():
            _psumm = picklog.summaries_by_date()
            _psum = {k: int(v.get("so_don") or 0) for k, v in _psumm.items()}
            _psp = {k: int(v.get("so_sp") or 0) for k, v in _psumm.items()}
            _pcodes = {}
            for _iso, _summ in _psumm.items():
                _codes = set()
                for _r in _summ.get("rows") or []:
                    _codes.update(str(c).strip() for c in (_r.get("codes") or []) if str(c).strip())
                if _codes:
                    _pcodes[_iso] = _codes
            for _d in data.get("days", []):
                _iso = _d.get("iso")
                if _iso in _psum:
                    _d["soan"] = _psum[_iso]
                    _d["soan_sp"] = _psp.get(_iso, 0)
                    _d["soan_src"] = "pick"      # lấy từ phiếu nhặt đã khử trùng
                    _dup = int((_psumm.get(_iso) or {}).get("dup_orders") or 0)
                    if _dup:
                        _d["ghi_chu"] = (str(_d.get("ghi_chu") or "") + f" · đã bỏ {_dup} đơn phiếu trùng").strip(" ·")
                # HỦY SAU SOẠN:
                # Ưu tiên đối chiếu mã đơn hủy với mã đã lưu trong phiếu nhặt; cách này dùng được cả hôm nay.
                # Nếu ngày cũ thiếu mã phiếu nhặt thì fallback theo chênh Soạn - Shipper nhận.
                _huy = int(_d.get("huy") or 0)
                _huy_codes = {str(c).strip() for c in (_d.get("huy_codes") or []) if str(c).strip()}
                _huy_packed_codes = {str(c).strip() for c in (_d.get("huy_packed_codes") or []) if str(c).strip()}
                _picked_codes = _pcodes.get(_iso) or set()
                if _huy_codes and _picked_codes:
                    _hsau = len(_huy_codes & _picked_codes)
                    _d["huy_sau"] = min(_huy, _hsau)
                    _d["huy_truoc"] = max(0, _huy - _d["huy_sau"])
                    _d["huy_split_known"] = True
                elif _huy_packed_codes:
                    _d["huy_sau"] = min(_huy, len(_huy_packed_codes))
                    _d["huy_truoc"] = max(0, _huy - _d["huy_sau"])
                    _d["huy_split_known"] = True
                elif _d.get("is_today"):
                    _d["huy_split_known"] = False
                    _d["huy_sau"] = _d["huy_truoc"] = 0
                else:
                    _gap = int(_d.get("soan") or 0) - int(_d.get("shipper_nhan") or 0)
                    _hsau = max(0, min(_huy, _gap))
                    _d["huy_sau"] = _hsau
                    _d["huy_truoc"] = _huy - _hsau
                    _d["huy_split_known"] = True
            if isinstance(data.get("month"), dict) and _psum:
                _mpref = (data.get("days") or [{}])[0].get("iso", "")[:7]
                _mtot = sum(v for k, v in _psum.items() if str(k)[:7] == _mpref)
                _msp = sum(v for k, v in _psp.items() if str(k)[:7] == _mpref)
                if _mtot:
                    data["month"]["soan"] = _mtot
                    data["month"]["soan_sp"] = _msp
            if isinstance(data.get("month"), dict):
                _msau = sum(d.get("huy_sau", 0) for d in data.get("days", []) if d.get("huy_split_known"))
                data["month"]["huy_sau"] = _msau
                data["month"]["huy_truoc"] = max(0, int(data["month"].get("huy") or 0) - _msau)
                data["month"]["huy_split_known"] = True
    except Exception:
        pass
    # SỐ VIDEO đóng/hoàn + TAG (Khách tráo / Đã sử dụng / Hư hỏng...) từ kho video Dohana, theo NGÀY.
    for day in data.get("days", []):
        for _k, _v in (("vid_dong", 0), ("vid_hoan", 0), ("tag_dong", ""), ("tag_hoan", ""),
                       ("soan_sp", 0), ("huy_sau", 0), ("huy_truoc", 0)):
            day.setdefault(_k, _v)
    if isinstance(data.get("month"), dict):
        for _k, _v in (("vid_dong", 0), ("vid_hoan", 0), ("tag_dong", ""), ("tag_hoan", ""),
                       ("soan_sp", 0), ("huy_sau", 0), ("huy_truoc", 0)):
            data["month"].setdefault(_k, _v)
    try:
        if picklog.configured():
            from collections import Counter as _Ct
            _video_audit = []
            _video_matrix = []
            _report_return_missing = []
            _order_context_by_code = data.get("order_context_by_code") or {}

            def _audit_age(iso):
                try:
                    _d = date.fromisoformat(str(iso or "")[:10])
                    _stale = ((datetime.now(timezone.utc) + timedelta(hours=7)).date() - _d).days > 25
                    return "Kho cũ" if _stale else "Còn trong hạn Dohana"
                except Exception:
                    return ""

            def _short_codes(vals, limit=None):
                vals = [str(v or "").strip() for v in (vals or []) if str(v or "").strip()]
                vals = list(dict.fromkeys(vals))
                if limit is not None and len(vals) > limit:
                    return " · ".join(vals[:limit]) + f" · ...(+{len(vals) - limit})"
                return " · ".join(vals)

            def _codes_from_item(item):
                raw = str(item or "").strip()
                if not raw:
                    return []
                if "Chưa có vận đơn" in raw:
                    return []
                out = []
                for part in re.findall(r"[A-Za-z0-9À-ỹĐđ]+", raw):
                    code = _ascii_code(part)
                    if len(code) >= 2:
                        out.append(code)
                return list(dict.fromkeys(out))

            def _display_code_raw(item):
                raw = str(item or "").strip()
                if raw.lower().startswith("chưa khớp đơn:"):
                    raw = raw.split(":", 1)[1].strip()
                return raw

            def _short_display_code(item, prefer=""):
                raw = _display_code_raw(item)
                if not raw:
                    return ""
                if "|" not in raw and ":" not in raw:
                    return raw
                def _field(pattern):
                    m = re.search(pattern, raw, flags=re.I)
                    if not m:
                        return ""
                    return _short_codes(_codes_from_item(m.group(1)))
                if prefer == "return":
                    got = _field(r"(?:VĐ hoàn|VD hoan)\s*:\s*([^|]+)")
                    if got:
                        return got
                got = _field(r"(?:VĐ đi/đóng|VD di/dong|VĐ đóng|VD dong|VĐ đi|VD di)\s*:\s*([^|]+)")
                if got:
                    return got
                got = _field(r"(?:Mã đơn|Ma don|Mã trả|Ma tra)\s*:\s*([^|]+)")
                return got or raw

            def _waybill_display(item, prefer):
                """Chỉ hiện mã vận đơn đúng phía, không kèm mã đơn/mã trả."""
                raw = _display_code_raw(item)
                if not raw:
                    return ""
                if "|" not in raw and ":" not in raw:
                    return raw
                outbound_pattern = r"(?:VĐ đi/đóng|VD di/dong|VĐ đóng|VD dong|VĐ đi|VD di)\s*:\s*([^|]+)"
                patterns = ([r"(?:VĐ hoàn|VD hoan)\s*:\s*([^|]+)", outbound_pattern]
                            if prefer == "return" else [outbound_pattern])
                for pattern in patterns:
                    match = re.search(pattern, raw, flags=re.I)
                    shown = _short_codes(_identifier_tokens(match.group(1))) if match else ""
                    if shown:
                        return shown
                # Mã đóng DƯ thực chất là 1 VĐ hoàn quay nhầm bên đóng → nhãn không có ô "VĐ đi/đóng".
                # Vẫn phải hiện mã ở cột "Đóng dư", nếu không cả dòng bị lọc mất (đúng ca 861877934768).
                if prefer != "return":
                    _wbs = [t for t in _identifier_tokens(raw) if _is_waybill_code(t)]
                    if _wbs:
                        return _short_codes(_wbs)
                return ""

            def _is_waybill_code(code):
                s = _ascii_code(code)
                if not s:
                    return False
                if s.startswith(("SPXVN", "VTPVN", "VTP", "GHN")):
                    return True
                return bool(re.fullmatch(r"8[4567]\d{8,14}", s))

            def _prefer_waybill_label(codes, fallback=""):
                vals = [str(v or "").strip() for v in (codes or []) if str(v or "").strip()]
                waybills = [v for v in vals if _is_waybill_code(v)]
                picked = waybills or [str(fallback or "").strip()]
                picked = list(dict.fromkeys([v for v in picked if v]))
                return " · ".join(picked)

            def _is_order_code(code):
                s = _ascii_code(code)
                if not s or _is_waybill_code(s):
                    return False
                if s.startswith("FUN") or s.startswith("SAPO"):
                    return False
                if s.isdigit() and len(s) < 12:
                    return False
                if s.startswith(("58", "26", "25")) and len(s) >= 10:
                    return True
                return bool(re.search(r"[A-Z]", s) and re.search(r"\d", s) and len(s) >= 8)

            def _codes_from_group(group):
                vals = [str(v or "").strip() for v in (group or []) if str(v or "").strip()]
                waybills = [v for v in vals if _is_waybill_code(v)]
                orders = [v for v in vals if _is_order_code(v)]
                return _short_codes(waybills), _short_codes(orders)

            def _match_codes_from_group(group, video_code=""):
                vals = [video_code, *(group or [])]
                out = []
                for val in vals:
                    raw = str(val or "").strip()
                    if not raw:
                        continue
                    parts = _codes_from_item(raw) if "|" in raw or ":" in raw else [raw]
                    for part in parts:
                        code = str(part or "").strip()
                        if code and (_is_waybill_code(code) or _is_order_code(code) or _order_context_label(code)):
                            out.append(code)
                return list(dict.fromkeys(out))

            def _package_label(group, video_code=""):
                wb, oc = _codes_from_group(group)
                if not wb and _is_waybill_code(video_code):
                    wb = str(video_code).strip()
                if not oc and _is_order_code(video_code):
                    oc = str(video_code).strip()
                return f"VĐ đi/đóng: {wb} | VĐ hoàn: | Mã trả: | Mã đơn: {oc}"

            def _order_context_label(code):
                key = _ascii_code(code)
                return _order_context_by_code.get(key) or ""

            def _package_context_label(group, video_code=""):
                for code in [video_code, *(group or [])]:
                    lbl = _order_context_label(code)
                    if lbl:
                        return lbl
                return _package_label(group, video_code)

            def _extra_package_label(code):
                # Nhãn cho video đóng DƯ: BẮT BUỘC chứa chính mã video này — để (1) hiện được ở cột
                # "Đóng dư" và (2) bắt cặp lộn-mục với dòng "Hoàn thiếu" cùng mã. Nếu context-label
                # dựng từ mã đơn/mã trả KHÁC (không chứa mã video) → coi mã video là VĐ đóng.
                key = _ascii_code(code)
                lbl = _order_context_label(code)
                if lbl and key and key in {_ascii_code(t) for t in _codes_from_item(lbl)}:
                    return lbl
                return _package_label([code], code)

            def _compare_code_line(item):
                raw = str(item or "")
                outbound_wbs, return_wbs, returns, orders = [], [], [], []
                outbound_wbs.extend(re.findall(r"(?:VĐ đi/đóng|VD di/dong|VĐ đóng|VD dong|VĐ đi|VD di)\s*:\s*([^|]+)", raw, flags=re.I))
                return_wbs.extend(re.findall(r"(?:VĐ hoàn|VD hoan)\s*:\s*([^|]+)", raw, flags=re.I))
                for token in _codes_from_item(raw):
                    if _is_waybill_code(token):
                        if return_wbs:
                            return_wbs.append(token)
                        elif outbound_wbs:
                            outbound_wbs.append(token)
                        else:
                            outbound_wbs.append(token)
                returns.extend(re.findall(r"(?:Mã trả|Ma tra)\s*:\s*([A-Za-z0-9_.-]+)", raw, flags=re.I))
                returns.extend(re.findall(r"\b\d{12,24}-R\d+\b", raw))
                orders.extend(re.findall(r"(?:Mã đơn|Ma don)\s*:\s*([A-Za-z0-9_.-]+)", raw, flags=re.I))
                return (
                    f"VĐ đi/đóng: {_short_codes(outbound_wbs)} | "
                    f"VĐ hoàn: {_short_codes(return_wbs)} | "
                    f"Mã trả: {_short_codes(returns)} | "
                    f"Mã đơn: {_short_codes(orders)}"
                )

            def _compare_code_lines(*groups, limit=12):
                items = []
                for group in groups:
                    items.extend(_uniq(group))
                items = list(dict.fromkeys(items))
                lines = [_compare_code_line(item) for item in items[:limit]]
                if len(items) > limit:
                    lines.append(f"...(+{len(items) - limit})")
                return "\n".join(lines)

            def _code_match(a, b):
                if not a or not b:
                    return False
                if a == b:
                    return True
                # Mã số vận đơn phải trùng tuyệt đối; các chuỗi số dài rất dễ bị
                # ghép oan nếu dùng subsequence. Mã chữ-số chỉ chịu sai tối đa
                # một ký tự do lỗi font/OCR (ví dụ ký tự có dấu hoặc X bị mất).
                if a.isdigit() or b.isdigit() or min(len(a), len(b)) < 6:
                    return False
                if abs(len(a) - len(b)) > 1:
                    return False
                if len(a) == len(b):
                    return sum(x != y for x, y in zip(a, b)) <= 1
                shorter, longer = (a, b) if len(a) < len(b) else (b, a)
                i = j = edits = 0
                while i < len(shorter) and j < len(longer):
                    if shorter[i] == longer[j]:
                        i += 1
                        j += 1
                    else:
                        edits += 1
                        j += 1
                        if edits > 1:
                            return False
                return True

            def _preferred_tokens(item, prefer):
                shown = _waybill_display(item, prefer)
                return _identifier_tokens(shown)

            def _identifier_tokens(item):
                # Chỉ giữ mã nghiệp vụ thật. Các nhãn chung như "VĐ", "Mã",
                # "đơn" từng làm hai dòng không liên quan vẫn bị ghép với nhau.
                return [
                    code for code in _codes_from_item(_display_code_raw(item))
                    if len(code) >= 6 and any(ch.isdigit() for ch in code)
                ]

            def _exact_context_match(a_item, b_item):
                return bool(set(_identifier_tokens(a_item)) & set(_identifier_tokens(b_item)))

            def _preferred_match(a_item, b_item, a_prefer, b_prefer):
                atoks = _preferred_tokens(a_item, a_prefer)
                btoks = _preferred_tokens(b_item, b_prefer)
                return any(_code_match(a, b) for a in atoks for b in btoks)

            def _match_tokens(a_item, b_item):
                atoks = _identifier_tokens(a_item)
                btoks = _identifier_tokens(b_item)
                if set(atoks) & set(btoks):
                    return True
                awb = [x for x in atoks if _is_waybill_code(x)]
                bwb = [x for x in btoks if _is_waybill_code(x)]
                return bool(awb and bwb and any(_code_match(a, b) for a in awb for b in bwb))

            def _group_matches_video(group, video_code):
                gtoks = []
                for item in group or []:
                    raw = str(item or "").strip()
                    if not raw:
                        continue
                    gtoks.extend(_codes_from_item(raw) if "|" in raw or ":" in raw else [_ascii_code(raw)])
                vtoks = _codes_from_item(video_code)
                return any(_code_match(g, v) for g in gtoks for v in vtoks)

            def _match_video_occurrences(groups, video_codes):
                matched, used_videos = {}, set()
                for gi, group in enumerate(groups or []):
                    for vi, vc in enumerate(video_codes or []):
                        if vi in used_videos:
                            continue
                        if _group_matches_video(group, vc):
                            matched[gi] = (vi, vc)
                            used_videos.add(vi)
                            break
                return matched, used_videos

            def _cross_matches(missing, extra, limit=20):
                pairs = []
                for miss in missing or []:
                    if not _codes_from_item(miss):
                        continue
                    for ex in extra or []:
                        if _match_tokens(miss, ex):
                            pairs.append(f"{miss} ↔ {ex}")
                            break
                pairs = list(dict.fromkeys(pairs))
                if len(pairs) > limit:
                    return " · ".join(pairs[:limit]) + f" · ...(+{len(pairs) - limit})"
                return " · ".join(pairs)

            def _cross_match_pairs(missing, extra, missing_prefer, extra_prefer):
                pairs, used_extra = [], set()
                for miss in missing or []:
                    for ex_idx, ex in enumerate(extra or []):
                        ex_key = str(ex or "").strip()
                        if not ex_key or ex_idx in used_extra:
                            continue
                        # Cùng mã đơn/mã trả/vận đơn chính xác là cùng hồ sơ. Nếu
                        # không có mã chung, chỉ chịu lỗi font ở đúng loại vận đơn
                        # đang đối chiếu, tuyệt đối không so gần đúng toàn bộ dòng.
                        if (_exact_context_match(miss, ex_key)
                                or _preferred_match(miss, ex_key, missing_prefer, extra_prefer)):
                            pairs.append((str(miss).strip(), ex_key))
                            used_extra.add(ex_idx)
                            break
                return pairs

            def _uniq(vals):
                return list(dict.fromkeys([str(v or "").strip() for v in (vals or []) if str(v or "").strip()]))

            def _day_video_limits(day):
                if not isinstance(day, dict):
                    return {}
                def _n(key):
                    try:
                        return int(round(float(day.get(key) or 0)))
                    except Exception:
                        return 0
                _dispute = sum(int(x) for x in re.findall(r"×\s*(\d+)", str(day.get("tag_hoan") or "")))
                _pkg_gap = _n("soan") - _n("vid_dong")
                _ret_gap = _dispute + _n("hoan_don") - _n("vid_hoan")
                return {
                    "pkg_missing": max(_pkg_gap, 0),
                    "pkg_extra": max(-_pkg_gap, 0),
                    "return_missing": max(_ret_gap, 0),
                    "inbound_extra": max(-_ret_gap, 0),
                }

            def _limit_rows(rows, limit, pad_label=""):
                rows = list(rows or [])
                if limit is None:
                    return rows
                n = max(0, int(limit or 0))
                rows = rows[:n]
                if pad_label and len(rows) < n:
                    rows += [f"{pad_label} #{i}" for i in range(len(rows) + 1, n + 1)]
                return rows

            def _pad_min_rows(rows, minimum, pad_label=""):
                rows = list(rows or [])
                n = max(0, int(minimum or 0))
                if pad_label and len(rows) < n:
                    rows += [f"{pad_label} #{i}" for i in range(len(rows) + 1, n + 1)]
                return rows

            def _add_matrix(iso, pkg_missing, pkg_extra, return_missing, inbound_extra, pkg_unknown=None, day=None,
                            pkg_missing_count=None):
                pkg_missing_raw = [str(v or "").strip() for v in (pkg_missing or []) if str(v or "").strip()]
                pkg_missing = _uniq(pkg_missing_raw)
                pkg_extra = [str(v or "").strip() for v in (pkg_extra or []) if str(v or "").strip()]
                return_missing = _uniq(return_missing)
                inbound_extra = [str(v or "").strip() for v in (inbound_extra or []) if str(v or "").strip()]
                pkg_unknown = [str(v or "").strip() for v in (pkg_unknown or []) if str(v or "").strip()]
                limits = _day_video_limits(day)
                pkg_unknown_rows = [f"Chưa khớp đơn: {x}" for x in pkg_unknown]
                # Chi tiết thiếu/dư ĐÓNG hiện đúng SỐ LỆCH RÒNG (soạn − vid_dong) để KHỚP bảng 30 ngày:
                # ngày soạn = vid_dong (vd 137 = 137) → 0 thiếu, 0 dư — KHÔNG báo oan mấy clip quay bằng mã lạ.
                # NGOẠI LỆ: mã đóng nào trùng 1 mã đang "Hoàn thiếu" = clip khui quay NHẦM sang đóng (lộn mục)
                # → LUÔN hiện ở "Đóng dư" dù ròng = 0 (vd 861877934768). Mã lạ (không phải vận đơn) KHÔNG tính là dư.
                _ret_miss_codes = set()
                for _rm in (return_missing or []):
                    _ret_miss_codes |= {_ascii_code(t) for t in _codes_from_item(_rm) if _ascii_code(t)}
                _lon_muc_extra = [c for c in pkg_extra
                                  if {_ascii_code(t) for t in _codes_from_item(c)} & _ret_miss_codes]
                _rest_extra = [c for c in pkg_extra if c not in _lon_muc_extra]
                raw_pkg_extra_rows = _lon_muc_extra + _limit_rows(_rest_extra, limits.get("pkg_extra"))
                raw_pkg_missing_rows = _limit_rows(pkg_missing, limits.get("pkg_missing"))
                raw_return_missing_rows = _limit_rows(return_missing, limits.get("return_missing"))
                raw_inbound_extra_rows = _limit_rows(inbound_extra, limits.get("inbound_extra"))
                _age = _audit_age(iso)
                p1 = _cross_match_pairs(raw_pkg_missing_rows, raw_inbound_extra_rows, "package", "return")
                p2 = _cross_match_pairs(raw_return_missing_rows, raw_pkg_extra_rows, "return", "package")
                match_txt = _short_codes([f"{a} ↔ {b}" for a, b in (p1 + p2)])
                p1_missing = {a for a, _ in p1}
                p1_extra = {b for _, b in p1}
                p2_missing = {a for a, _ in p2}
                p2_extra = {b for _, b in p2}
                rem_pkg_missing_rows = [x for x in raw_pkg_missing_rows if x not in p1_missing]
                rem_inbound_extra_rows = [x for x in raw_inbound_extra_rows if x not in p1_extra]
                rem_return_missing_rows = [x for x in raw_return_missing_rows if x not in p2_missing]
                display_pkg_extra_rows = [x for x in raw_pkg_extra_rows if x not in p2_extra]
                # Hai danh sách khui hàng phải chỉ hiện mã thật. Không chèn
                # placeholder theo chênh lệch tổng, vì placeholder không thể dùng để đối chiếu.
                rem_inbound_extra_rows = list(rem_inbound_extra_rows)
                rem_return_missing_rows = list(rem_return_missing_rows)
                _report_return_missing.extend({"date": iso, "age": _age, "label": row}
                                              for row in rem_return_missing_rows)
                rem_pkg_missing = len(rem_pkg_missing_rows)
                try:
                    if pkg_missing_count is not None:
                        rem_pkg_missing = max(rem_pkg_missing, int(pkg_missing_count or 0))
                except Exception:
                    pass
                rem_inbound_extra = len(rem_inbound_extra_rows)
                rem_return_missing = len(rem_return_missing_rows)
                rem_pkg_extra = len(display_pkg_extra_rows)
                parts = []
                if rem_pkg_missing:
                    parts.append(f"Thiếu video đóng: {rem_pkg_missing}")
                if rem_return_missing:
                    parts.append(f"Thiếu video khui hoàn: {rem_return_missing}")
                if rem_pkg_extra:
                    parts.append(f"Dư video đóng: {rem_pkg_extra}")
                if rem_inbound_extra:
                    parts.append(f"Dư video khui hoàn: {rem_inbound_extra}")
                if not parts and (pkg_missing or pkg_extra or return_missing or inbound_extra):
                    chot = "Đủ sau khi chuyển lộn mục"
                elif parts:
                    chot = "Còn lệch: " + "; ".join(parts)
                else:
                    if isinstance(day, dict):
                        day["chot_video"] = "Đủ"      # khớp hết, không lệch
                    return
                if isinstance(day, dict):
                    day["chot_video"] = chot           # đưa kết quả chốt lên bảng 30 ngày
                def _disp(vals, prefer=""):
                    return [_waybill_display(v, prefer) for v in vals if _waybill_display(v, prefer)]
                def _disp_counted(vals, prefer="", raw_vals=None):
                    base = _disp(vals, prefer)
                    raw_disp = [_waybill_display(v, prefer) for v in (raw_vals or vals) if _waybill_display(v, prefer)]
                    cnt = _Ct(raw_disp)
                    return [f"{v} ×{cnt[v]}" if cnt.get(v, 0) > 1 else v for v in base]
                def _matched_waybills(a, b, a_prefer, b_prefer):
                    left = _waybill_display(a, a_prefer)
                    right = _waybill_display(b, b_prefer)
                    return f"{left} ↔ {right}" if left and right else (left or right)
                matched_rows = [
                    _matched_waybills(a, b, "package", "return") for a, b in p1
                ] + [
                    _matched_waybills(a, b, "return", "package") for a, b in p2
                ]
                _video_matrix.append({
                    "Ngày": iso,
                    "Nhóm tuổi": _audit_age(iso),
                    "Mã đối chiếu": _compare_code_lines(rem_return_missing_rows, rem_pkg_missing_rows,
                                                        display_pkg_extra_rows, rem_inbound_extra_rows),
                    "Đóng thiếu SL": rem_pkg_missing,
                    "Đóng thiếu": _short_codes(_disp_counted(rem_pkg_missing_rows, "package", pkg_missing_raw)),
                    "Đóng dư SL": len(display_pkg_extra_rows),
                    "Đóng dư": _short_codes(_disp(display_pkg_extra_rows, "package")),
                    "Hoàn thiếu SL": len(rem_return_missing_rows),
                    "Hoàn thiếu": _short_codes(_disp(rem_return_missing_rows, "return")),
                    "Hoàn dư SL": len(rem_inbound_extra_rows),
                    "Hoàn dư": _short_codes(_disp(rem_inbound_extra_rows, "return")),
                    "Khớp lộn mục": _short_codes(matched_rows),
                    "Video chưa khớp đơn": _short_codes(pkg_unknown),
                    "Chốt": chot,
                })

            def _add_audit(iso, kind, codes, opposite, hint, matched=""):
                codes = [str(v or "").strip() for v in (codes or []) if str(v or "").strip()]
                if not codes:
                    return
                _video_audit.append({
                    "Ngày": iso,
                    "Nhóm tuổi": _audit_age(iso),
                    "Loại lệch": kind,
                    "SL": len(list(dict.fromkeys(codes))),
                    "Mã cần kiểm": _short_codes(codes),
                    "Mã dư/thiếu đối diện": _short_codes(opposite),
                    "Khớp lộn mục": matched or "",
                    "Gợi ý": hint,
                })

            # TỰ ĐỒNG BỘ ~28 ngày video từ Dohana rồi gộp vào kho TRƯỚC khi đọc — để bảng 30 ngày
            # KHÔNG bị đứng số khi có video mới (Dohana giữ ~25-30 ngày; giữ nhịp _throttle chống 429).
            # Lỗi/429 → bỏ qua, đọc kho cũ (không làm bảng trống).
            try:
                _fresh = []
                for _fn in (dohana.today_package_videos, dohana.inbound_videos):
                    _r = _fn(days_match=28, max_pages=80)
                    if _r and _r.get("records"):
                        _fresh += _r["records"]
                if _fresh:
                    picklog.merge_dohana_videos(_fresh)
            except Exception:
                pass
            recs = picklog.read_dohana_videos()
            vdong, vhoan, tdong, thoan = {}, {}, {}, {}   # tag TÁCH theo loại video: đóng vs khui
            package_codes_by_day, package_unknown_by_day, inbound_codes_by_day = {}, {}, {}
            inbound_rows = []
            for r in recs:
                if not _dohana_video_active(r):
                    continue
                d, ty = r.get("date"), r.get("type")
                if not d:
                    continue
                code = str(r.get("code") or "").strip()
                tn = _video_tag_label(r) if _video_tag_id(r) else ""
                if ty == "package":          # đóng hàng → tag đóng (vd đóng thiếu SP)
                    vdong[d] = vdong.get(d, 0) + 1
                    if code:
                        if _is_waybill_code(code):
                            package_codes_by_day.setdefault(d, []).append(code)
                        else:
                            package_unknown_by_day.setdefault(d, []).append(code)
                    if tn:
                        tdong.setdefault(d, _Ct())[tn] += 1
                elif ty == "inbound":        # khui hàng → tag hoàn (tráo / mất / hư hỏng / đã dùng)
                    vhoan[d] = vhoan.get(d, 0) + 1
                    if code:
                        inbound_codes_by_day.setdefault(d, []).append(code)
                    inbound_rows.append(r)
                    if tn:
                        thoan.setdefault(d, _Ct())[tn] += 1
            # Ngày hiện tại phải dùng đúng recon của báo cáo A4. A4 tính "video đóng" theo số
            # đơn trong phiếu nhặt đã KHỚP video, không phải tổng clip thô trong Dohana.
            _a4_package_recon_by_day = {}
            try:
                _today_iso = _today_iso_vn()
                _a4_rep = L.get_daily_report(make_fetch_json(build_session()), target_date=date.fromisoformat(_today_iso))
                _a4_dvr = load_dohana()
                _ps = picklog.read_date_summary(_today_iso)
                _apply_picklog_soan_to_daily(_a4_rep, _ps.get("rows") or [], _a4_dvr, _ps.get("dup_orders") or 0)
                _vr = (_a4_rep.get("video_recon") or {}) if isinstance(_a4_rep, dict) else {}
                if _vr.get("available"):
                    _missing_codes = [
                        str(c or "").strip() for c in (_vr.get("missing_codes") or [])
                        if str(c or "").strip()
                    ]
                    _matched_count = int(_vr.get("open_with_video") or 0)
                    _missing_count = max(
                        int(_vr.get("missing_video") or 0),
                        len(_missing_codes),
                    )
                    if _missing_codes and _missing_count > len(_missing_codes):
                        _missing_codes += [_missing_codes[-1]] * (_missing_count - len(_missing_codes))
                    _a4_package_recon_by_day[_today_iso] = {
                        "matched": _matched_count,
                        "missing": _missing_codes,
                        "missing_count": _missing_count,
                        "dup": dict(_vr.get("dup") or {}),
                    }
            except Exception:
                _a4_package_recon_by_day = {}
            data["a4_package_recon_by_day"] = _a4_package_recon_by_day
            _mpref = (data.get("days") or [{}])[0].get("iso", "")[:7]   # 'YYYY-MM' tháng này

            _package_missing_by_day, _package_extra_by_day, _package_unknown_unmatched_by_day = {}, {}, {}
            _real_match_days = set()   # ngày CÓ danh sách phiếu soạn để ghép TỪNG video (ghép thật, không suy ra từ số chênh ròng)
            _video_trace_by_day = {}   # dấu vết soi 1 mã: soạn / video đóng / đã khớp / xếp dư — để chẩn đoán vì sao vào cột nào
            try:
                _package_days = set(package_codes_by_day) | set(package_unknown_by_day)
                if "_psumm" in locals():
                    _package_days |= set((_psumm or {}).keys())
                for _iso in sorted(_package_days):
                    _summ = (_psumm if "_psumm" in locals() else {}).get(_iso) or {}
                    _has_soan = bool(_summ.get("rows"))
                    # ── Mã vận đơn ĐÃ SOẠN trong ngày (lấy từ phiếu nhặt), chỉ giữ mã vận đơn ──
                    _soan_set = set()
                    for _row in (_summ.get("rows") or []):
                        _cands = list(_row.get("codes") or [])
                        for _grp in (_row.get("code_groups") or []):
                            _cands += list(_grp or [])
                        for _c in _cands:
                            _cc = _ascii_code(_c)
                            if _cc and _is_waybill_code(_cc):
                                _soan_set.add(_cc)
                    if _has_soan:
                        _real_match_days.add(_iso)
                    # ── Mã vận đơn của VIDEO ĐÓNG trong ngày (giữ thứ tự, bỏ trùng) ──
                    _pkg_wb = list(dict.fromkeys(
                        _ascii_code(c) for c in package_codes_by_day.get(_iso, []) if _ascii_code(c)))
                    _pkg_unknown = list(dict.fromkeys(
                        _ascii_code(c) for c in package_unknown_by_day.get(_iso, []) if _ascii_code(c)))
                    _pkg_set = set(_pkg_wb)
                    # ── ĐỐI CHIẾU ĐƠN GIẢN: so mã soạn ↔ mã video đóng ──
                    # Thiếu = đã soạn nhưng KHÔNG có video đóng. Dư = có video đóng nhưng KHÔNG nằm trong soạn.
                    # Ngày MẤT phiếu (kho cũ) → không đủ dữ liệu → để trống, tránh nổ toàn bộ video thành "dư".
                    if _has_soan:
                        _missing = [c for c in sorted(_soan_set) if c not in _pkg_set]
                        _extra = [c for c in _pkg_wb if c not in _soan_set]
                        _unknown_extra = list(_pkg_unknown)
                    else:
                        _missing, _extra, _unknown_extra = [], [], []
                    _video_trace_by_day[_iso] = {
                        "soan": sorted(_soan_set),
                        "pkg_video": list(_pkg_wb),
                        "pkg_matched": [c for c in _pkg_wb if c in _soan_set],
                        "pkg_extra": list(_extra),
                        "has_soan_list": _has_soan,
                    }
                    _package_missing_by_day[_iso] = _missing
                    _package_extra_by_day[_iso] = _extra
                    _package_unknown_unmatched_by_day[_iso] = _unknown_extra
            except Exception:
                _package_missing_by_day, _package_extra_by_day, _package_unknown_unmatched_by_day = {}, {}, {}
                _real_match_days = set()

            # Vid hoàn phải là clip KHỚP đơn hoàn, không phải tổng clip inbound thô.
            # Nếu đếm thô, video quay dư/sai mã/ngày có thể che mất các đơn thật sự chưa quay.
            try:
                from collections import defaultdict as _Dd

                def _norm(c):
                    return _ascii_code(c)

                def _label_field(label, pattern):
                    m = re.search(pattern, str(label or ""), flags=re.I)
                    return _codes_from_item(m.group(1)) if m else []

                def _label_codes(label):
                    return _codes_from_item(label)

                def _label_order_key(label):
                    vals = _label_field(label, r"(?:Mã đơn|Ma don)\s*:\s*([^|]+)")
                    return vals[0] if vals else _norm(label)

                def _merge_return_labels(labels):
                    fields = (
                        ("VĐ đi/đóng", r"(?:VĐ đi/đóng|VD di/dong|VĐ đóng|VD dong|VĐ đi|VD di)\s*:\s*([^|]+)"),
                        ("VĐ hoàn", r"(?:VĐ hoàn|VD hoan)\s*:\s*([^|]+)"),
                        ("Mã trả", r"(?:Mã trả|Ma tra)\s*:\s*([^|]+)"),
                        ("Mã đơn", r"(?:Mã đơn|Ma don)\s*:\s*([^|]+)"),
                    )
                    return " | ".join(
                        f"{name}: {_short_codes([code for label in labels for code in _label_field(label, pattern)])}"
                        for name, pattern in fields
                    )

                _inbound_codes = {_norm(r.get("code")) for r in inbound_rows if _norm(r.get("code"))}
                _inbound_days_by_code = _Dd(set)
                for r in inbound_rows:
                    code = _norm(r.get("code"))
                    if code and r.get("date"):
                        _inbound_days_by_code[code].add(str(r.get("date")))

                # Dùng đúng danh sách đã tạo ra cột Hoàn (đơn). Nguồn này có đủ cả ngày kho cũ,
                # không bị giới hạn trang như lượt quét API phụ trước đây.
                _return_groups_by_day = _Dd(lambda: _Dd(list))
                for dd, labels in (data.get("restocked_return_labels_by_day") or {}).items():
                    for label in labels or []:
                        if str(label or "").strip():
                            _return_groups_by_day[str(dd)][_label_order_key(label)].append(str(label))

                _return_label_by_code = {}
                _exact_used = set()
                _matched_by_day = _Dd(set)
                _matched_inbound_codes_by_day = _Dd(set)
                _return_missing_by_day = _Dd(list)
                for dd, groups in _return_groups_by_day.items():
                    for order_key, labels in groups.items():
                        merged_label = _merge_return_labels(labels)
                        label_codes = _label_codes(merged_label)
                        for code in label_codes:
                            _return_label_by_code.setdefault(_norm(code), merged_label)
                        hit = next((video for video in sorted(_inbound_codes - _exact_used)
                                    if any(_code_match(_norm(code), video) for code in label_codes)), None)
                        if hit:
                            _exact_used.add(hit)
                            _matched_by_day[dd].add(order_key)
                            for video_day in _inbound_days_by_code.get(hit, set()):
                                _matched_inbound_codes_by_day[video_day].add(hit)
                        else:
                            _return_missing_by_day[dd].append(merged_label)
                _tagged_inbound_by_day = {
                    dd: sum(cnt.values()) for dd, cnt in thoan.items()
                }
                _matched_vhoan = {
                    dd: len(vals) + int(_tagged_inbound_by_day.get(dd, 0))
                    for dd, vals in _matched_by_day.items()
                }
                for dd, tag_n in _tagged_inbound_by_day.items():
                    _matched_vhoan.setdefault(dd, int(tag_n))
                _tagged_inbound_codes_by_day = _Dd(set)
                for r in inbound_rows:
                    if _video_tag_id(r) and r.get("code"):
                        _tagged_inbound_codes_by_day[str(r.get("date") or "")].add(_norm(r.get("code")))
                _inbound_extra_by_day = {}
                for dd, codes in inbound_codes_by_day.items():
                    _raw = {_norm(c) for c in codes if _norm(c)}
                    _used = set(_matched_inbound_codes_by_day.get(dd, set())) | set(_tagged_inbound_codes_by_day.get(dd, set()))
                    _inbound_extra_by_day[dd] = [
                        _return_label_by_code.get(c) or f"VĐ đi/đóng: | VĐ hoàn: {c} | Mã trả: | Mã đơn:"
                        for c in sorted(_raw - _used)
                    ]
            except Exception:
                _matched_vhoan = {}
                _return_missing_by_day = {}
                _inbound_extra_by_day = {}

            def _tagstr(cnt):
                return " · ".join(f"{n} ×{c}" for n, c in cnt.items()) if cnt else ""

            def _msum(dic):
                return sum(c for dd, c in dic.items() if str(dd)[:7] == _mpref)

            def _mtag(dic):
                mt = _Ct()
                for dd, cnt in dic.items():
                    if str(dd)[:7] == _mpref:
                        mt.update(cnt)
                return _tagstr(mt)

            for day in data.get("days", []):
                iso = day.get("iso")
                day["vid_dong"] = vdong.get(iso, 0)
                _a4_pkg_recon = _a4_package_recon_by_day.get(str(iso or ""))
                if _a4_pkg_recon:
                    day["vid_dong"] = int(_a4_pkg_recon.get("matched") or 0)
                day["vid_hoan_raw"] = vhoan.get(iso, 0)
                day["vid_hoan"] = _matched_vhoan.get(iso, vhoan.get(iso, 0))
                day["tag_dong"] = _tagstr(tdong.get(iso))
                day["tag_hoan"] = _tagstr(thoan.get(iso))
                if day.get("vid_hoan_raw") != day.get("vid_hoan"):
                    _old_note = str(day.get("ghi_chu") or "").strip()
                    _extra_note = f"Vid hoàn thô {day.get('vid_hoan_raw')} / khớp đơn {day.get('vid_hoan')}"
                    day["ghi_chu"] = (_old_note + " · " + _extra_note).strip(" ·")
                if _a4_pkg_recon:
                    _pkg_missing = list(_a4_pkg_recon.get("missing") or [])
                    _pkg_missing_count = int(_a4_pkg_recon.get("missing_count") or len(_pkg_missing))
                    _pkg_extra = []
                    _pkg_unknown = []
                else:
                    _pkg_missing = _package_missing_by_day.get(iso, [])
                    _pkg_missing_count = None
                    _pkg_extra = _package_extra_by_day.get(iso, [])
                    _pkg_unknown = _package_unknown_unmatched_by_day.get(iso, [])
                _return_missing = _return_missing_by_day.get(iso, [])
                _inbound_extra = _inbound_extra_by_day.get(iso, [])
                _pkg_miss_vs_inbound_extra = _cross_matches(_pkg_missing, _inbound_extra)
                _return_miss_vs_pkg_extra = _cross_matches(_return_missing, _pkg_extra)
                _add_matrix(
                    iso, _pkg_missing, _pkg_extra, _return_missing, _inbound_extra,
                    _pkg_unknown, day, pkg_missing_count=_pkg_missing_count,
                )
                _add_audit(
                    iso, "Thiếu video đóng hàng", _pkg_missing,
                    _inbound_extra,
                    "Tìm mã này trong video khui hàng cùng ngày; nếu có thì quay lộn mục khui/đóng.",
                    _pkg_miss_vs_inbound_extra,
                )
                _add_audit(
                    iso, "Dư video đóng hàng", _pkg_extra,
                    _return_missing,
                    "Video đóng dư có thể là clip khui hàng quay nhầm bên đóng.",
                    _return_miss_vs_pkg_extra,
                )
                _add_audit(
                    iso, "Thiếu video khui hàng hoàn", _return_missing,
                    _pkg_extra,
                    "Tìm mã này trong video đóng hàng cùng ngày; nếu có thì quay lộn mục đóng/khui.",
                    _return_miss_vs_pkg_extra,
                )
                _add_audit(
                    iso, "Dư video khui hàng hoàn", _inbound_extra,
                    _pkg_missing,
                    "Video khui dư có thể là clip đóng hàng quay nhầm bên khui, hoặc đơn hoàn chưa nhập kho/tag thiếu.",
                    _pkg_miss_vs_inbound_extra,
                )
            if isinstance(data.get("month"), dict):
                m = data["month"]
                m["vid_dong"] = _msum(vdong)
                for _dd, _rec in (_a4_package_recon_by_day or {}).items():
                    if str(_dd).startswith(_mpref):
                        m["vid_dong"] += int(_rec.get("matched") or 0) - int(vdong.get(_dd, 0) or 0)
                m["vid_hoan_raw"] = _msum(vhoan)
                m["vid_hoan"] = _msum(_matched_vhoan) if _matched_vhoan else _msum(vhoan)
                m["tag_dong"], m["tag_hoan"] = _mtag(tdong), _mtag(thoan)
                if m.get("vid_hoan_raw") != m.get("vid_hoan"):
                    _old_note = str(m.get("ghi_chu") or "").strip()
                    _extra_note = f"Vid hoàn thô {m.get('vid_hoan_raw')} / khớp đơn {m.get('vid_hoan')}"
                    m["ghi_chu"] = (_old_note + " · " + _extra_note).strip(" ·")
            # Keep the detailed audit table aligned with A4 when today's package
            # video count is overridden by A4's matched/missing-code recon.
            try:
                _day_by_iso = {
                    str(_d.get("iso") or ""): _d
                    for _d in (data.get("days") or [])
                    if isinstance(_d, dict)
                }
                for _dd, _rec in (_a4_package_recon_by_day or {}).items():
                    _dd = str(_dd or "")
                    _missing = [
                        str(_c or "").strip()
                        for _c in ((_rec or {}).get("missing") or [])
                        if str(_c or "").strip()
                    ]
                    if not _dd or not _missing:
                        continue
                    _video_matrix = [
                        _r for _r in _video_matrix
                        if not (isinstance(_r, dict) and str(_r.get("Ngày") or "") == _dd)
                    ]
                    _add_matrix(
                        _dd,
                        _missing,
                        [],
                        _return_missing_by_day.get(_dd, []),
                        _inbound_extra_by_day.get(_dd, []),
                        [],
                        _day_by_iso.get(_dd),
                        pkg_missing_count=int((_rec or {}).get("missing_count") or len(_missing)),
                    )
                _day_order = {k: i for i, k in enumerate(_day_by_iso)}
                _video_matrix.sort(
                    key=lambda _r: _day_order.get(str(_r.get("Ngày") or ""), len(_day_order))
                    if isinstance(_r, dict) else len(_day_order)
                )
            except Exception:
                pass
            data["video_audit_matrix"] = _video_matrix
            data["video_audit"] = _video_audit
            data["report_return_video_missing"] = _report_return_missing
            data["video_trace_by_day"] = _video_trace_by_day
            data["a4_package_recon_by_day"] = _a4_package_recon_by_day
    except Exception:
        pass
    return data


@st.cache_data(ttl=180, show_spinner=False)
def load_alerts():
    return L.get_alerts(make_fetch_json(build_session()))


def render_alert_popup(sees_production=False):
    """Popup CẢNH BÁO cố định, hiện ở MỌI trang (position:fixed).
    sees_production=True (kho/admin): thêm việc CẦN SX / CẮT TAY để nhắc mọi tab."""
    if not credential_present():
        return
    try:
        a = load_alerts()
    except Exception:
        a = None
    if a is None and not sees_production:
        return
    a = a or {}
    # (label, value, [danh sách dòng phụ con])
    items = [
        ("🕒 Xác nhận sau 18h", a.get("conf_after18", 0), None),
        # Đơn xác nhận trễ = đặt TRƯỚC 18h (trong giờ) nhưng mãi SAU 18h mới xác nhận
        ("📌 Đơn xác nhận trễ", a.get("late_confirm", 0), None),
        ("📦 Đơn xót lại (chờ shipper)", a.get("chua_giao", 0), [
            ("chưa đóng hàng", a.get("xot_chua_dong", 0)),
            ("đã đóng hàng", a.get("xot_da_dong", 0)),
        ]),
        ("🔴 Hỏa tốc chưa giao", a.get("express_pending", 0), None),
        ("↩️ Hủy sau gói cần LẤY LẠI", a.get("cancel_retrieve", 0), [
            ("🔴 hỏa tốc", a.get("cancel_retrieve_express", 0)),
        ]),
    ]
    n_hot = sum(1 for _, v, _s in items if v)
    rows = ""
    for lbl, v, subs in items:
        if not v:                      # CHỈ hiện dòng có số (>0); dòng = 0 ẩn đi
            continue
        rows += (f'<div class="row"><span>{lbl}</span>'
                 f'<span class="v hot">{v}</span></div>')
        # Dòng phụ = GIẢI THÍCH "trong đó" — số NẰM TRONG CÂU (không phải ô đếm riêng),
        # tránh hiểu nhầm là có thêm đơn. VD: "↳ trong đó: 1 chưa đóng hàng".
        parts = [f'<b>{sv}</b> {slbl}' for slbl, sv in (subs or []) if sv]
        if parts:
            rows += ('<div class="row" style="padding-left:16px;font-size:.72rem;'
                     'border-bottom:0;opacity:.8">'
                     f'<span>↳ trong đó: {" · ".join(parts)}</span></div>')
    # KHO/admin: nhắc VIỆC SẢN XUẤT (cần SX / cắt tay) trên mọi tab. Số lấy từ lần mở
    # trang Dự đoán SX gần nhất (session) để KHỎI tính lại nặng ở mỗi trang.
    if sees_production:
        _pt = st.session_state.get("prod_todo")
        if _pt:
            _cansx = int(_pt.get("must", 0)) + int(_pt.get("suggest", 0))
            _cattay = int(_pt.get("manual", 0))
            if _cattay:
                n_hot += 1
            rows += ('<div class="row" style="border-top:2px solid #475569">'
                     '<span>🧵 Cần SX / ✋ Cắt tay (nhóm)</span>'
                     f'<span class="v {"hot" if _cattay else ""}">{_cansx} / {_cattay}</span></div>'
                     '<div class="row" style="padding-left:16px;font-size:.72rem;border-bottom:0;opacity:.85">'
                     '<span>↳ mở <b>Dự đoán sản xuất</b> để cắt & in phiếu cắt tay</span></div>')
        else:
            rows += ('<div class="row" style="border-top:2px solid #475569">'
                     '<span>🧵 Mở <b>Dự đoán sản xuất</b> xem việc cần làm (cắt tay…)</span>'
                     '<span class="v">›</span></div>')
    badge = f'⚠️ Cảnh báo ({n_hot})' if n_hot else '✅ Cảnh báo (0)'
    body = rows if n_hot else '<div class="ok">✅ Không có cảnh báo</div>' + rows
    st.markdown(
        f'<details class="alert-pop" open><summary>{badge}<span>▾</span></summary>'
        f'<div class="body">{body}</div></details>',
        unsafe_allow_html=True)


@st.cache_data(ttl=900, show_spinner="Đang quét đơn trả cả năm…")
def load_returns_followup():
    return L.get_returns_followup(make_fetch_json(build_session()))


@st.cache_data(ttl=600, show_spinner="Đang quét đơn trả đang xử lý…")
def load_returns_inprogress():
    _cache_ver = 15  # bump khi đổi cấu trúc trả về → buộc tính lại (tránh cache cũ gây lỗi)
    return L.get_returns_in_progress(make_fetch_json(build_session()), canceled_max_pages=120)


@st.cache_data(ttl=3600, show_spinner=False)
def load_return_detail_for_link(return_id):
    """Tải chi tiết đúng một phiếu để lấy external Shopee return id cho link trực tiếp."""
    return get_order_return(build_session(), return_id)


@st.cache_data(ttl=3600, show_spinner="Đang quét đơn trả bị đóng cả năm…")
def load_closed_returns_full_year():
    _cache_ver = 2  # include SAPO return id so Shopee links can resolve to direct detail pages
    return L.get_returns_in_progress(make_fetch_json(build_session()), max_pages=0, canceled_max_pages=500)


@st.cache_data(ttl=600, show_spinner="Đang dò đơn nhập kho thiếu video khui…")
def load_restock_novideo(days: int = 30):
    """Đối chiếu đơn ĐÃ nhập kho (Sapo, ~days ngày) với KHO VIDEO KHUI đã lưu (Gist, vĩnh viễn).
    Đơn không khớp clip khui nào → ghi vào SỔ vĩnh viễn (tích luỹ, KHÔNG mất khi Dohana xoá video);
    video hiện sau → tự chuyển 'resolved'. Trả {active, resolved, dismissed, total_scanned}."""
    cands = L.get_restocked_returns_range(make_fetch_json(build_session()), days=days)

    def _norm(c):                       # chuẩn hoá để khớp chịu lỗi hoa/thường/space
        return str(c or "").strip().upper()

    def _cg(code):                      # NHÓM ĐVVC từ MÃ VĐ (giống A4)
        s = str(code or "").upper()
        if s.startswith("SPXVN"):
            return "SPX"
        if s.startswith(("VTPVN", "VTP")):
            return "VTP"
        if s.startswith("GHN"):
            return "GHN"
        if s[:2] in ("86", "85", "84", "87"):
            return "JT"
        return s[:3]

    def _cgname(n):                     # NHÓM ĐVVC từ TÊN đơn vị (đáng tin hơn mã)
        n = str(n or "").lower()
        if "spx" in n:
            return "SPX"
        if "viettel" in n or "vtp" in n:
            return "VTP"
        if "ghn" in n or "giao hàng nhanh" in n:
            return "GHN"
        if "j&t" in n or "jt" in n:
            return "JT"
        return n[:3]

    def _pdate(s):
        try:
            return date.fromisoformat(str(s or "")[:10])
        except Exception:
            return None
    _inb = []                           # (code, nhóm ĐVVC, ngày) của video KHUI (inbound) đã lưu bền
    if picklog.configured():
        for r in picklog.read_dohana_videos():
            if r.get("type") == "inbound" and r.get("code"):
                _inb.append((_norm(r.get("code")), _cg(r.get("code")), _pdate(r.get("date"))))
    inbound_codes = {c for c, _cgx, _dx in _inb}
    _today = (datetime.now(timezone.utc) + timedelta(hours=7)).date().isoformat()
    ledger = picklog.read_restock_novideo() if picklog.configured() else {"items": {}}
    items = ledger.get("items", {})
    changed = False
    _DISPLAY = ("order_code", "return_id", "order_id", "order_link", "return_link", "vd_di", "vd_tra",
                "ngay_tao", "restock_date", "recv_time", "nhan_vien", "sku", "sp", "sp_nhap", "money",
                "ly_do", "loai_tra", "loai_tra_code", "gian_hang", "order_source", "ghi_chu")
    # AN TOÀN: kho video rỗng (Dohana 429 / chưa sync) → KHÔNG dò (tránh gắn oan cả loạt vào sổ vĩnh
    # viễn). Chỉ giữ nguyên sổ cũ. UI sẽ báo "kho video trống".
    if not inbound_codes:
        _vals0 = list(items.values())
        return {"active": sorted([v for v in _vals0 if v.get("status") == "active"],
                                 key=lambda r: r.get("restock_date", ""), reverse=True),
                "resolved": [v for v in _vals0 if v.get("status") == "resolved"],
                "dismissed": [v for v in _vals0 if v.get("status") == "dismissed"],
                "total_scanned": len(cands), "video_store": 0, "candidates": cands}
    # GHI CHÚ: lấy từ KHO GHI CHÚ RIÊNG của trang đơn trả (vitran_closed_return_notes.json) — KHÔNG
    # dùng note Sapo (thiếu). Khớp theo return_code/order_code/vd_tra/vd_di (giống trang trả hàng ép).
    _notemap = {}
    if picklog.configured():
        _rawn = picklog._read_gist_file("vitran_closed_return_notes.json") or {}
        _nn = _rawn.get("notes") if isinstance(_rawn, dict) else None
        if isinstance(_nn, dict):
            for _k, _rec in _nn.items():
                _t = (_rec.get("note") if isinstance(_rec, dict) else _rec) or ""
                if str(_t).strip():
                    _notemap[str(_k)] = str(_t).strip()

    def _lookup_note(cc):
        for _f in ("return_code", "order_code", "vd_tra", "vd_di"):
            _v = str(cc.get(_f) or "").strip()
            if _v and f"{_f}:{_v}" in _notemap:
                return _notemap[f"{_f}:{_v}"]
        return ""
    # ── KHỚP VIDEO: (1) mã CHÍNH XÁC; (2) GHÉP MỀM theo ĐVVC + ngày (±3) như A4 — đơn SPX có VĐ hoàn
    #    về chỉ NV quét trên Dohana, KHÔNG nằm trong Sapo → khớp mã trượt, cần ghép mềm để khỏi báo oan.
    from collections import defaultdict as _dd
    _exact_consumed = set()
    for c in cands:
        _hit = next((x for x in (_norm(z) for z in c.get("codes", [])) if x in inbound_codes), None)
        c["_exact"] = _hit
        if _hit:
            _exact_consumed.add(_hit)
    _leftover = _dd(list)               # nhóm ĐVVC -> [(ngày, code)] clip khui CHƯA khớp chính xác
    for _code, _cgx, _dx in _inb:
        if _code not in _exact_consumed:
            _leftover[_cgx].append((_dx, _code))
    for c in sorted(cands, key=lambda r: str(r.get("restock_date") or "")):
        if c.get("_exact"):
            c["_has_vid"] = True
            continue
        if c.get("loai_tra_code") == "delivery_failed":
            c["_has_vid"] = False       # giao thất bại: VĐ về = VĐ đi (có trong Sapo) → KHÔNG ghép mềm
            continue
        _lst = _leftover.get(_cgname(c.get("carrier"))) or []
        _rd = _pdate(c.get("restock_date"))
        _pick = next((_ix for _ix, (_vd, _vc) in enumerate(_lst)
                      if _vd is None or _rd is None or abs((_vd - _rd).days) <= 3), None)
        if _pick is not None:
            _lst.pop(_pick)
            c["_has_vid"] = True
            c["_soft"] = True
        else:
            c["_has_vid"] = False
    for c in cands:
        key = c.get("return_code") or c.get("order_code")
        if not key:
            continue
        c["ghi_chu"] = _lookup_note(c)      # ghi chú RIÊNG của trang (không phải Sapo)
        has_vid = bool(c.get("_has_vid"))
        if has_vid:
            it = items.get(key)
            if it and it.get("status") == "active":       # trước thiếu, nay có video → tự gỡ
                it["status"] = "resolved"
                it["resolved_reason"] = "video xuất hiện sau"
                it["resolved_at"] = _today
                changed = True
            continue
        it = items.get(key)                                # KHÔNG khớp video khui nào
        # Shopee KHÔNG đưa ID nội bộ cho Sapo (không link thẳng /return/{id} được) → link SEARCH TRỰC TIẾP
        # banhang.shopee.vn, KÈM cnsc_shop_id (Shopee tự chuyển đúng shop, KHÔNG cần Chrome launcher).
        if "shopee" in str(c.get("order_source") or c.get("gian_hang") or "").lower():
            _shop = str(c.get("shop_id") or "").strip()
            _ol = "https://banhang.shopee.vn/portal/sale?search=" + quote_plus(str(c.get("order_code") or ""))
            _rl = ("https://banhang.shopee.vn/portal/sale/returnrefundcancel?keyword="
                   + quote_plus(str(c.get("return_code") or "")))
            if _shop:
                _ol += "&cnsc_shop_id=" + _shop
                _rl += "&cnsc_shop_id=" + _shop
            c["order_link"], c["return_link"] = _ol, _rl
        if it is None:
            rec = {k: c.get(k) for k in _DISPLAY}
            rec.update({"return_code": key, "status": "active",
                        "first_detected": _today, "last_checked": _today})
            items[key] = rec
            changed = True
        else:
            if it.get("status") == "resolved" and it.get("resolved_reason") == "video xuất hiện sau":
                it["status"] = "active"                    # video từng có rồi lại mất (hiếm) → báo lại
                changed = True
            if it.get("status") != "dismissed":
                for k in _DISPLAY:                         # cập nhật hiển thị phòng Sapo đổi
                    if c.get(k) not in (None, "") and it.get(k) != c.get(k):
                        it[k] = c.get(k)
                        changed = True
            it["last_checked"] = _today
    if changed and picklog.configured():
        picklog.write_restock_novideo({"items": items})
    _vals = list(items.values())
    active = sorted([v for v in _vals if v.get("status") == "active"],
                    key=lambda r: r.get("restock_date", ""), reverse=True)
    resolved = [v for v in _vals if v.get("status") == "resolved"]
    dismissed = [v for v in _vals if v.get("status") == "dismissed"]
    return {"active": active, "resolved": resolved, "dismissed": dismissed,
            "total_scanned": len(cands), "video_store": len(inbound_codes), "candidates": cands}


@st.cache_data(ttl=900, show_spinner="Đang lấy danh mục sản phẩm + tồn kho từ Sapo…")
def load_sapo_catalog(max_pages=80):
    return PT.get_catalog_variants(make_fetch_json(build_session()), max_pages=max_pages)


def _attach_inbound(rep, inbound):
    """Ghép NHẬP KHO trong kỳ (NCC + hàng hoàn) vào từng SKU/nhóm + suy ra TỒN ĐẦU KỲ.
    Tồn đầu kỳ = Tồn cuối (hiện tại) − Nhập + Bán trong kỳ."""
    ncc = (inbound or {}).get("ncc", {}) or {}
    ret = (inbound or {}).get("returns", {}) or {}
    seen = set()

    def _fill(row):
        if not isinstance(row, dict) or id(row) in seen:
            return
        seen.add(id(row))
        a = int(round(ncc.get(row.get("sku"), 0) or 0))
        b = int(round(ret.get(row.get("sku"), 0) or 0))
        row["inNCC"], row["inReturn"], row["totalIn"] = a, b, a + b
        row["openingStock"] = int(round(row.get("endingStock") or 0)) - (a + b) + int(round(row.get("totalOut") or 0))

    for key in ("aggregated", "needRows", "outSkuList", "zeroSalesList", "slowStockList"):
        for r in rep.get(key, []) or []:
            _fill(r)

    def _fill_group(g):
        gn = gr = 0
        for r in g.get("skus", []) or []:
            _fill(r)
            gn += int(round(ncc.get(r.get("sku"), 0) or 0))
            gr += int(round(ret.get(r.get("sku"), 0) or 0))
        g["inNCC"], g["inReturn"], g["totalIn"] = gn, gr, gn + gr
        g["openingStock"] = int(round(g.get("totalStock") or 0)) - (gn + gr) + int(round(g.get("totalOut") or 0))

    for g in rep.get("groupRows", []) or []:
        _fill_group(g)
    for ck in ("mustProduceGroups", "suggestGroups", "manualCutGroups"):
        for g in (rep.get("critical", {}) or {}).get(ck, []) or []:
            _fill_group(g)


@st.cache_data(ttl=900, show_spinner="Đang dự đoán sản xuất từ Sapo…")
def load_production_tool(data_months, forecast_months, safety_factor, round_mode, end_date_iso,
                         max_product_pages=80, max_report_pages=80):
    end_date = datetime.fromisoformat(end_date_iso).date()
    # Tính từ ĐƠN HÀNG + tồn kho sản phẩm qua Open API (key/secret) — CHẠY NHƯ CÁC TAB KHÁC,
    # KHÔNG cần phiên admin/cookie (endpoint báo cáo xuất-nhập-tồn bị 403 với key/secret).
    fetch = make_fetch_json(build_session())
    rep = PT.get_production_forecast(
        fetch,
        data_months=int(data_months),
        forecast_months=int(forecast_months),
        safety_factor=float(safety_factor),
        round_mode=round_mode,
        end_date=end_date,
        max_product_pages=int(max_product_pages),
        max_order_pages=int(max_report_pages),
    )
    # Nhập kho trong kỳ (NCC + hàng hoàn) từ Open API → ghép để hiện đủ Xuất-Nhập-Tồn.
    _start = end_date - timedelta(days=max(1, int(data_months)) * 30)
    try:
        inbound = PT.get_inbound_by_sku(fetch, start_date=_start, end_date=end_date, max_pages=40)
    except Exception:
        inbound = {"ncc": {}, "returns": {}}
    _attach_inbound(rep, inbound)
    return rep


def _vnd(value):
    try:
        return f"{int(round(float(value or 0))):,}".replace(",", ".") + "đ"
    except Exception:
        return "0đ"


def _variant_label(row):
    sku = row.get("sku") or ""
    name = row.get("product_name") or ""
    var = row.get("variant_name") or ""
    title = " / ".join([x for x in (name, var) if x])
    short_title = title[:54] + ("..." if len(title) > 54 else "")
    tail = f"tồn {int(row.get('inventory_quantity') or 0):,} | {_vnd(row.get('price'))}".replace(",", ".")
    return f"{sku} | {short_title} | {tail}" if short_title else f"{sku} | {tail}"


def _cover_text(stock, monthly_out, cover_months):
    """Tồn hiện tại bán được bao lâu nữa (theo tốc độ bán bình quân/tháng)."""
    stock = int(round(stock or 0))
    out = float(monthly_out or 0)
    cover = float(cover_months or 0)
    if out <= 0:
        return "— chưa bán"            # không bán trong kỳ → không tính được
    if stock <= 0:
        return "❗Hết hàng"             # đang bán mà hết → khẩn cấp
    if cover >= 999:
        return "— chưa bán"
    if cover < 1:
        return f"~{cover * 30:.0f} ngày"
    return f"{cover:.1f} tháng"


def _cover_sort_val(g):
    """Khóa sắp xếp: đang-bán-mà-hết lên đầu, tồn sắp hết kế tiếp, không bán xuống cuối."""
    stock = int(round(g.get("totalStock") or 0))
    out = float(g.get("avgMonthlyOut") or 0)
    cover = float(g.get("stockCoverMonths") or 0)
    if out <= 0:
        return 1e9                      # không bán → cuối danh sách
    if stock <= 0:
        return -1.0                     # đang bán mà hết hàng → khẩn cấp nhất
    if cover >= 999:
        return 1e9
    return cover


def _group_bind_cover(g):
    """Ở bảng Cần SX: 'Tồn đủ bán' tính theo SIZE ĐANG THIẾU nhất (lý do phải SX) —
    vì tồn trung bình cả nhóm dễ gây hiểu lầm (nhóm còn nhiều nhưng 1 size sắp hết)."""
    def _cov(s):
        avg = float(s.get("avgMonthlyOut") or 0)
        st_ = float(s.get("endingStock") or 0)
        return (st_ / avg) if avg > 0 else (999.0 if st_ > 0 else 0.0)
    needing = [s for s in (g.get("skus") or []) if float(s.get("needQty") or 0) > 0]
    if needing:
        s = min(needing, key=_cov)
        return _cover_text(s.get("endingStock"), s.get("avgMonthlyOut"), _cov(s))
    return _cover_text(g.get("totalStock"), g.get("avgMonthlyOut"), g.get("stockCoverMonths"))


def _production_group_df(groups):
    return pd.DataFrame([{
        "Mức": g.get("suggestionType"),
        "Chất liệu": g.get("family"),
        "Mã": g.get("productCode"),
        "Màu": g.get("colorCode") or "",
        "Tồn đầu": int(round(g.get("openingStock") or 0)),
        "Nhập NCC": int(round(g.get("inNCC") or 0)),
        "Nhập hoàn": int(round(g.get("inReturn") or 0)),
        "Bán kỳ": int(round(g.get("totalOut") or 0)),
        "Tồn cuối": int(round(g.get("totalStock") or 0)),
        "Đủ bán (size thiếu)": _group_bind_cover(g),
        "Cần SX": int(round(g.get("totalNeed") or 0)),
        "Cây": int(round(g.get("rollsNeeded") or 0)),
        "Size cần": g.get("sizeNeedText") or g.get("sizeNeedAllText") or "",
    } for g in groups])


def _render_fabric_groups(groups):
    """1 BẢNG cho mỗi CHẤT LIỆU (chất liệu cần nhiều lên trên). Trong bảng, các MÀU VẢI
    ngăn nhau bằng GẠCH NGANG ĐẬM; màu/mã cần nhiều xếp trên. Cùng màu vải = cắt chung."""
    from collections import defaultdict
    _TD = "padding:4px 9px;border-bottom:1px solid rgba(148,163,184,.22);white-space:nowrap;"
    _TH = "padding:5px 9px;border-bottom:2px solid #94a3b8;font-weight:700;text-align:left;white-space:nowrap;"
    _GRP = "border-top:3px solid #475569;"
    fams = defaultdict(list)
    for g in groups:
        fams[g.get("family") or "(khác)"].append(g)
    fam_order = sorted(fams.items(), key=lambda kv: -sum(float(x.get("totalNeed") or 0) for x in kv[1]))
    headers = ["Mức", "Mã", "Màu", "Màu vải", "Tồn cuối", "Đủ bán (size thiếu)", "Cần SX", "Cây (cả màu)", "Size cần"]
    for fam, items in fam_order:
        by_color = defaultdict(list)
        for g in items:
            by_color[g.get("fabricColorGroup") or "(không màu)"].append(g)
        color_order = sorted(by_color.items(), key=lambda kv: -sum(float(x.get("totalNeed") or 0) for x in kv[1]))
        fam_need = int(round(sum(float(x.get("totalNeed") or 0) for x in items)))
        st.markdown(f"### 🧵 {fam} — cần {fam_need} cái")
        rows = []
        for ci, (fcol, cg) in enumerate(color_order):
            cg.sort(key=lambda x: -float(x.get("totalNeed") or 0))
            cneed = int(round(sum(float(x.get("totalNeed") or 0) for x in cg)))
            cap = max((int(x.get("cutCapacity") or 0) for x in cg), default=0) or 1
            crolls = -(-cneed // cap) if cneed > 0 else 0
            for ri, g in enumerate(cg):
                cover = _group_bind_cover(g)
                need = int(round(g.get("totalNeed") or 0))
                cells = [
                    (g.get("suggestionType") or "", _style_muc(g.get("suggestionType") or "")),
                    (g.get("productCode") or "", "font-weight:600;"),
                    (g.get("colorCode") or "", ""),
                    (fcol if ri == 0 else "", "font-weight:600;"),
                    (f"{int(round(g.get('totalStock') or 0)):,}", ""),
                    (cover, _style_cover(cover)),
                    (str(need), _style_need(need)),
                    (f"{crolls} cây" if ri == 0 else "", "font-weight:600;"),
                    (g.get("sizeNeedText") or g.get("sizeNeedAllText") or "", ""),
                ]
                grp = _GRP if (ri == 0 and ci > 0) else ""
                tds = "".join(f'<td style="{_TD}{grp}{stl}">{_esc(str(v))}</td>' for v, stl in cells)
                rows.append(f"<tr>{tds}</tr>")
        thead = "".join(f'<th style="{_TH}">{_esc(h)}</th>' for h in headers)
        st.markdown(
            '<div style="overflow-x:auto"><table style="border-collapse:collapse;width:100%;font-size:.86rem">'
            f'<thead><tr>{thead}</tr></thead><tbody>{"".join(rows)}</tbody></table></div>',
            unsafe_allow_html=True,
        )


def _manual_cut_print_html(groups):
    """Tạo phiếu HTML khổ A4 để in danh sách CẮT TAY (gom theo chất liệu + màu vải)."""
    from collections import defaultdict
    now = (datetime.now(timezone.utc) + timedelta(hours=7)).strftime("%d/%m/%Y %H:%M")
    fams = defaultdict(list)
    for g in groups:
        fams[g.get("family") or "(khác)"].append(g)
    fam_order = sorted(fams.items(), key=lambda kv: -sum(float(x.get("totalNeed") or 0) for x in kv[1]))
    blocks = []
    total = 0
    for fam, items in fam_order:
        by_color = defaultdict(list)
        for g in items:
            by_color[g.get("fabricColorGroup") or "(không màu)"].append(g)
        color_order = sorted(by_color.items(), key=lambda kv: -sum(float(x.get("totalNeed") or 0) for x in kv[1]))
        fam_need = int(round(sum(float(x.get("totalNeed") or 0) for x in items)))
        total += fam_need
        rows = []
        for ci, (fcol, cg) in enumerate(color_order):
            cg.sort(key=lambda x: -float(x.get("totalNeed") or 0))
            for ri, g in enumerate(cg):
                bd = ' style="border-top:2.5px solid #000"' if (ri == 0 and ci > 0) else ""
                code = f"{g.get('productCode') or ''}{'-' + g.get('colorCode') if g.get('colorCode') else ''}"
                vals = [fcol if ri == 0 else "", code, str(int(round(g.get("totalNeed") or 0))),
                        g.get("sizeNeedText") or g.get("sizeNeedAllText") or "", ""]
                rows.append("<tr>" + "".join(f"<td{bd}>{_esc(str(v))}</td>" for v in vals) + "</tr>")
        blocks.append(
            f"<h3>🧵 {_esc(fam)} — {fam_need} cái</h3><table>"
            "<thead><tr><th>Màu vải</th><th>Mã</th><th>Cần SX</th><th>Size cần</th><th>Đã cắt</th></tr></thead>"
            f"<tbody>{''.join(rows)}</tbody></table>")
    css = ("@page{size:A4;margin:12mm}*{font-family:Arial,'Segoe UI',sans-serif}"
           "h1{font-size:18px;margin:0}.sub{color:#444;font-size:12px;margin:2px 0 10px}"
           "h3{font-size:14px;margin:12px 0 4px;background:#eee;padding:3px 6px}"
           "table{border-collapse:collapse;width:100%;font-size:12px;margin-bottom:6px}"
           "th,td{border:1px solid #999;padding:4px 6px;text-align:left}th{background:#f0f0f0}"
           "td:last-child,th:last-child{width:64px}")
    return (f"<!doctype html><html lang='vi'><head><meta charset='utf-8'><title>Phiếu cắt tay</title>"
            f"<style>{css}</style></head><body><h1>PHIẾU CẮT TAY</h1>"
            f"<div class='sub'>Tổng {total} cái · in lúc {now} · (Cần SX ≤ 5 cái/nhóm)</div>"
            f"{''.join(blocks) or '<p>Không có nhóm cắt tay.</p>'}</body></html>")


def _stock_cover_group_df(groups):
    """Gom theo NHÓM MÃ + MÀU (cùng nhóm mới cắt chung đợt), sắp sắp-hết-hàng lên đầu."""
    gs = sorted(groups, key=_cover_sort_val)
    return pd.DataFrame([{
        "Mã": g.get("productCode"),
        "Màu": g.get("colorCode") or "",
        "Chất liệu": g.get("family"),
        "Tồn": int(round(g.get("totalStock") or 0)),
        "Bán/tháng": round(float(g.get("avgMonthlyOut") or 0), 1),
        "Tồn đủ bán": _cover_text(g.get("totalStock"), g.get("avgMonthlyOut"), g.get("stockCoverMonths")),
        "Cần SX": int(round(g.get("totalNeed") or 0)),
        "Tồn theo size": g.get("activeSizeText") or "",
    } for g in gs])


def _style_cover(val):
    s = str(val)
    if "Hết hàng" in s:
        return "background-color:#fee2e2;color:#991b1b;font-weight:700"
    if "ngày" in s:
        return "background-color:#ffedd5;color:#9a3412;font-weight:700"
    if "chưa bán" in s:
        return "color:#9ca3af"
    if "tháng" in s:
        try:
            n = float(s.split()[0])
        except Exception:
            n = 99.0
        if n < 2:
            return "background-color:#fef9c3;color:#854d0e;font-weight:700"
        if n < 4:
            return "color:#15803d;font-weight:600"
    return ""


def _style_muc(val):
    s = str(val)
    if "Bắt buộc" in s:
        return "background-color:#fee2e2;color:#991b1b;font-weight:700"
    if "Gợi ý" in s:
        return "background-color:#ffedd5;color:#9a3412;font-weight:600"
    if "Tự cắt" in s:
        return "color:#6b7280"
    return ""


def _style_need(val):
    try:
        n = int(float(val))
    except Exception:
        n = 0
    return "font-weight:700;color:#b91c1c" if n > 0 else "color:#cbd5e1"


def _style_status(val):
    s = str(val)
    if s == "Hết hàng":
        return "background-color:#fee2e2;color:#991b1b;font-weight:700"
    if s == "Cần SX":
        return "background-color:#ffedd5;color:#9a3412;font-weight:700"
    return "color:#6b7280"


def _style_prod(df):
    """Tô màu bảng dự đoán SX cho nổi bật: hết hàng đỏ, sắp hết cam/vàng, cần SX đỏ đậm."""
    if getattr(df, "empty", True):
        return df
    sty = df.style
    _cover_cols = [c for c in df.columns if "đủ bán" in str(c).lower()]
    if _cover_cols:
        sty = sty.map(_style_cover, subset=_cover_cols)
    if "Cần SX" in df.columns:
        sty = sty.map(_style_need, subset=["Cần SX"])
    if "Mức" in df.columns:
        sty = sty.map(_style_muc, subset=["Mức"])
    if "Trạng thái" in df.columns:
        sty = sty.map(_style_status, subset=["Trạng thái"])
    return sty


def _production_detail_df(rows):
    return pd.DataFrame([{
        "Trạng thái": "Cần SX" if r.get("needFlag") else ("Hết hàng" if r.get("outOfStock") else "Đủ tồn"),
        "Chất liệu": r.get("family"),
        "SKU": r.get("sku"),
        "Tên SP": r.get("productName") or "",
        "Size": (r.get("parsed") or {}).get("size") or "",
        "Tồn đầu": int(round(r.get("openingStock") or 0)),
        "Nhập NCC": int(round(r.get("inNCC") or 0)),
        "Nhập hoàn": int(round(r.get("inReturn") or 0)),
        "Bán kỳ": int(round(r.get("totalOut") or 0)),
        "Tồn cuối": int(round(r.get("endingStock") or 0)),
        "Tồn đủ bán": _cover_text(r.get("endingStock"), r.get("avgMonthlyOut"), r.get("stockCoverMonths")),
        "Bình quân/tháng": round(float(r.get("avgMonthlyOut") or 0), 2),
        "Tồn mục tiêu": round(float(r.get("targetStock") or 0), 2),
        "Cần SX": int(round(float(r.get("needQty") or 0))),
        "Cây": int(round(r.get("rollsNeeded") or 0)),
        "Giá Sapo": int(round(r.get("price") or 0)),
    } for r in rows])


def _render_cutbatch_by_material(cut_batches):
    """Cắt chung theo vải — 1 BẢNG/CHẤT LIỆU (cần nhiều lên trên), rows = màu vải.
    Cùng style HTML (header tối dính) như các tab khác cho đồng bộ."""
    from collections import defaultdict
    fams = defaultdict(list)
    for b in cut_batches:
        fams[b.get("family") or "(khác)"].append(b)
    fam_order = sorted(fams.items(), key=lambda kv: -sum(float(x.get("totalNeed") or 0) for x in kv[1]))
    _TD = "padding:4px 9px;border-bottom:1px solid rgba(148,163,184,.16);white-space:nowrap;"
    _TH = "padding:6px 9px;text-align:left;white-space:nowrap;position:sticky;top:0;background:#334155;color:#fff;z-index:1;"
    headers = ["Màu vải", "Cần cắt", "Cây", "Nhóm mã (cắt chung)"]
    for fam, items in fam_order:
        items.sort(key=lambda x: -float(x.get("totalNeed") or 0))
        fam_need = int(round(sum(float(x.get("totalNeed") or 0) for x in items)))
        fam_rolls = int(round(sum(float(x.get("totalRolls") or 0) for x in items)))
        st.markdown(f"### ✂️ {fam} — cần {fam_need} cái · ~{fam_rolls} cây")
        rows = []
        for b in items:
            cells = [
                (b.get("colorCode") or "", "font-weight:700;"),
                (str(int(round(b.get("totalNeed") or 0))), "font-weight:700;color:#b91c1c;"),
                (str(int(round(b.get("totalRolls") or 0))), ""),
                (b.get("groupsText") or "", "white-space:normal;"),
            ]
            tds = "".join(f'<td style="{_TD}{stl}">{_esc(str(v))}</td>' for v, stl in cells)
            rows.append(f"<tr>{tds}</tr>")
        thead = "".join(f'<th style="{_TH}">{_esc(h)}</th>' for h in headers)
        st.markdown('<div style="overflow-x:auto"><table style="border-collapse:collapse;width:100%;font-size:.85rem">'
                    f'<thead><tr>{thead}</tr></thead><tbody>{"".join(rows)}</tbody></table></div>',
                    unsafe_allow_html=True)


def _render_stock_cover_grouped(skus_flat):
    """Tồn còn bán bao lâu — CHIA THEO MÃ (1 mã = 1 nhóm, gồm mọi màu+size), nhóm ngăn nhau
    bằng GẠCH NGANG ĐẬM; nhóm còn ÍT HÀNG NHẤT lên đầu; trong nhóm, màu/size sắp hết lên trên."""
    from collections import defaultdict
    groups = defaultdict(list)
    for s in skus_flat:
        k = (s.get("parsed") or {}).get("productCode") or s.get("sku")
        groups[k].append(s)

    def _gsort(items):
        stock = sum(float(x.get("endingStock") or 0) for x in items)
        out = sum(float(x.get("avgMonthlyOut") or 0) for x in items)
        if out <= 0:
            return 1e9
        if stock <= 0:
            return -1.0
        cov = stock / out
        return cov if cov < 999 else 1e9

    order = sorted(groups.items(), key=lambda kv: _gsort(kv[1]))
    _TD = "padding:4px 9px;border-bottom:1px solid rgba(148,163,184,.22);white-space:nowrap;"
    _TH = "padding:5px 9px;border-bottom:2px solid #94a3b8;font-weight:700;text-align:left;white-space:nowrap;"
    headers = ["Mã", "Màu", "Chất liệu", "Size", "Tồn", "Bán/th", "Đủ bán", "Cần SX"]
    rows = []
    for gi, (_code, items) in enumerate(order):
        items.sort(key=_sku_cover)   # màu/size sắp hết lên trên trong nhóm
        for ri, s in enumerate(items):
            grp = "border-top:3px solid #475569;" if (ri == 0 and gi > 0) else ""
            scov = _cover_text(s.get("endingStock"), s.get("avgMonthlyOut"), _sku_cover(s))
            need = int(round(float(s.get("needQty") or 0)))
            ps = s.get("parsed") or {}
            cells = [
                ((ps.get("productCode") or "") if ri == 0 else "", "font-weight:600;"),
                (ps.get("colorCode") or "", ""),
                ((s.get("family") or "") if ri == 0 else "", ""),
                (ps.get("size") or "-", ""),
                (f"{int(round(s.get('endingStock') or 0)):,}", ""),
                (f"{float(s.get('avgMonthlyOut') or 0):.1f}", ""),
                (scov, _style_cover(scov)),
                (str(need), _style_need(need)),
            ]
            tds = "".join(f'<td style="{_TD}{grp}{stl}">{_esc(str(v))}</td>' for v, stl in cells)
            rows.append(f"<tr>{tds}</tr>")
    thead = "".join(f'<th style="{_TH}">{_esc(h)}</th>' for h in headers)
    st.markdown('<div style="overflow-x:auto"><table style="border-collapse:collapse;width:100%;font-size:.86rem">'
                f'<thead><tr>{thead}</tr></thead><tbody>{"".join(rows)}</tbody></table></div>',
                unsafe_allow_html=True)


def _sku_cover(s):
    avg = float(s.get("avgMonthlyOut") or 0)
    st_ = float(s.get("endingStock") or 0)
    return (st_ / avg) if avg > 0 else (999.0 if st_ > 0 else 0.0)


def _render_detail_search_table(rows):
    """Chi tiết SKU: gom Mã (gạch ĐẬM) > Màu (gạch ĐỨT) > Size + ô LỌC LIVE (gõ tới đâu
    ẩn dòng không khớp tới đó; gõ đúng mã → còn đúng 1 SKU). Lọc client-side (JS)."""
    from collections import OrderedDict, defaultdict
    prods = OrderedDict()
    for r in rows:
        prods.setdefault((r.get("parsed") or {}).get("productCode") or r.get("sku"), []).append(r)
    headers = ["SKU", "Chất liệu", "Size", "Tồn đầu", "Nhập NCC", "Nhập hoàn", "Bán kỳ", "Tồn cuối", "Đủ bán", "Cần SX"]
    body = []
    for pi, (_code, items) in enumerate(prods.items()):
        colors = defaultdict(list)
        for r in items:
            colors[(r.get("parsed") or {}).get("colorCode") or ""].append(r)
        for ci, (_color, sizes) in enumerate(colors.items()):
            for si, r in enumerate(sizes):
                border = ""
                if si == 0 and ci == 0 and pi > 0:
                    border = "border-top:3px solid #475569;"
                elif si == 0 and ci > 0:
                    border = "border-top:2px dashed #94a3b8;"
                cov = _cover_text(r.get("endingStock"), r.get("avgMonthlyOut"), _sku_cover(r))
                need = int(round(float(r.get("needQty") or 0)))
                vals = [
                    (r.get("sku") or "", "font-weight:600;"),
                    (r.get("family") or "", ""),
                    ((r.get("parsed") or {}).get("size") or "-", ""),
                    (f"{int(round(r.get('openingStock') or 0)):,}", ""),
                    (f"{int(round(r.get('inNCC') or 0)):,}", ""),
                    (f"{int(round(r.get('inReturn') or 0)):,}", ""),
                    (f"{int(round(r.get('totalOut') or 0)):,}", ""),
                    (f"{int(round(r.get('endingStock') or 0)):,}", ""),
                    (cov, _style_cover(cov)),
                    (str(need), _style_need(need)),
                ]
                key = _esc((str(r.get("sku") or "") + " " + str((r.get("parsed") or {}).get("productCode") or "")
                            + " " + str(r.get("productName") or "")).upper())
                tds = "".join(f'<td style="padding:3px 8px;border-bottom:1px solid rgba(148,163,184,.16);white-space:nowrap;{border}{stl}">{_esc(str(v))}</td>' for v, stl in vals)
                body.append(f'<tr data-k="{key}">{tds}</tr>')
    thead = "".join(f'<th style="padding:6px 8px;text-align:left;position:sticky;top:0;background:#334155;color:#fff;white-space:nowrap;z-index:1">{_esc(h)}</th>' for h in headers)
    _font = "-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,'Helvetica Neue',Arial,sans-serif"
    html = (f'<div style="font-family:{_font};color:#1e293b">'
            '<input id="q" placeholder="Gõ SKU / mã… lọc ngay khi gõ" oninput="flt()" '
            f'style="width:100%;box-sizing:border-box;padding:9px 12px;font-size:15px;font-family:{_font};border:1px solid #cbd5e1;border-radius:6px;margin:0 0 6px">'
            '<div id="cnt" style="font-size:.8rem;color:#64748b;margin-bottom:4px"></div>'
            '<div style="overflow:auto;max-height:470px"><table style="border-collapse:collapse;width:100%;font-size:.84rem">'
            '<thead><tr>' + thead + '</tr></thead><tbody id="tb">' + "".join(body) + '</tbody></table></div>'
            '<script>function flt(){var v=document.getElementById("q").value.toUpperCase().trim();'
            'var rs=document.querySelectorAll("#tb tr");var n=0;'
            'rs.forEach(function(r){var m=(!v||r.getAttribute("data-k").indexOf(v)>-1);r.style.display=m?"":"none";if(m)n++;});'
            'document.getElementById("cnt").textContent=n+" SKU khớp";}flt();</script></div>')
    components.html(html, height=560, scrolling=True)


def _render_skus_grouped(skus, order_by="stock", limit=250):
    """Danh sách SKU cảnh báo — gom theo NHÓM MÃ+MÀU (ngăn bằng gạch đậm). order_by='stock'
    xếp tồn nhiều→ít; 'need' xếp Cần SX nhiều→ít."""
    from collections import defaultdict
    if not skus:
        st.caption("— không có —")
        return
    groups = defaultdict(list)
    for s in skus:
        k = (s.get("parsed") or {}).get("productCode") or s.get("sku")   # nhóm = MÃ (gồm mọi màu)
        groups[k].append(s)

    def _gv(items):
        if order_by == "need":
            return sum(float(x.get("needQty") or 0) for x in items)
        return sum(float(x.get("endingStock") or 0) for x in items)

    order = sorted(groups.items(), key=lambda kv: -_gv(kv[1]))
    _TD = "padding:4px 9px;border-bottom:1px solid rgba(148,163,184,.22);white-space:nowrap;"
    _TH = "padding:5px 9px;border-bottom:2px solid #94a3b8;font-weight:700;text-align:left;white-space:nowrap;"
    headers = ["Mã", "Màu", "Size", "Tồn", "Bán/th", "Đủ bán", "Cần SX"]
    rows = []
    for gi, (_k, items) in enumerate(order[:limit]):
        items.sort(key=lambda s: -(float(s.get("needQty") or 0) if order_by == "need" else float(s.get("endingStock") or 0)))
        for ri, s in enumerate(items):
            grp = "border-top:3px solid #475569;" if (ri == 0 and gi > 0) else ""
            cov = _cover_text(s.get("endingStock"), s.get("avgMonthlyOut"), _sku_cover(s))
            need = int(round(float(s.get("needQty") or 0)))
            ps = s.get("parsed") or {}
            vals = [
                ((ps.get("productCode") or "") if ri == 0 else "", "font-weight:600;"),
                (ps.get("colorCode") or "", ""),
                (ps.get("size") or "-", ""),
                (f"{int(round(s.get('endingStock') or 0)):,}", ""),
                (f"{float(s.get('avgMonthlyOut') or 0):.1f}", ""),
                (cov, _style_cover(cov)),
                (str(need), _style_need(need)),
            ]
            tds = "".join(f'<td style="{_TD}{grp}{stl}">{_esc(str(v))}</td>' for v, stl in vals)
            rows.append(f"<tr>{tds}</tr>")
    thead = "".join(f'<th style="{_TH}">{_esc(h)}</th>' for h in headers)
    st.markdown('<div style="overflow-x:auto"><table style="border-collapse:collapse;width:100%;font-size:.85rem">'
                f'<thead><tr>{thead}</tr></thead><tbody>{"".join(rows)}</tbody></table></div>', unsafe_allow_html=True)
    if len(order) > limit:
        st.caption(f"(hiện {limit}/{len(order)} nhóm — tải CSV để xem hết)")


_SKU_HDR = {"ma": "Mã", "mau": "Màu", "chatlieu": "Chất liệu", "size": "Size", "ton": "Tồn",
            "banth": "Bán/th", "duban": "Đủ bán", "cansx": "Cần SX"}


def _sku_group_html(skus, cols, sort="cover", max_groups=None):
    """Trả (thead, tbody): rows = SKU, gom Mã > Màu > Size. Giữa MÃ = gạch ĐẬM,
    giữa MÀU (trong cùng mã) = gạch ĐỨT. Header dính (sticky) nền tối."""
    from collections import defaultdict

    def _rank(items):
        stock = sum(float(x.get("endingStock") or 0) for x in items)
        out = sum(float(x.get("avgMonthlyOut") or 0) for x in items)
        if sort == "need":
            return -sum(float(x.get("needQty") or 0) for x in items)
        if sort == "stock":
            return -stock
        if out <= 0:
            return 1e9
        if stock <= 0:
            return -1.0
        c = stock / out
        return c if c < 999 else 1e9

    def _cell(ck, s, code, color, ma_start, mau_start):
        ps = s.get("parsed") or {}
        if ck == "ma":
            return (code if ma_start else "", "font-weight:700;")
        if ck == "mau":
            return (color if mau_start else "", "font-weight:600;")
        if ck == "chatlieu":
            return ((s.get("family") or "") if ma_start else "", "")
        if ck == "size":
            return (ps.get("size") or "-", "")
        if ck == "ton":
            return (f"{int(round(s.get('endingStock') or 0)):,}", "")
        if ck == "banth":
            return (f"{float(s.get('avgMonthlyOut') or 0):.1f}", "")
        if ck == "duban":
            cov = _cover_text(s.get("endingStock"), s.get("avgMonthlyOut"), _sku_cover(s))
            return (cov, _style_cover(cov))
        if ck == "cansx":
            n = int(round(float(s.get("needQty") or 0)))
            return (str(n), _style_need(n))
        return ("", "")

    prods = defaultdict(list)
    for s in skus:
        prods[(s.get("parsed") or {}).get("productCode") or s.get("sku")].append(s)
    order = sorted(prods.items(), key=lambda kv: _rank(kv[1]))
    if max_groups:
        order = order[:max_groups]
    _TD = "padding:4px 9px;white-space:nowrap;border-bottom:1px solid rgba(148,163,184,.16);"
    rows = []
    for pi, (code, items) in enumerate(order):
        colors = defaultdict(list)
        for s in items:
            colors[(s.get("parsed") or {}).get("colorCode") or ""].append(s)
        corder = sorted(colors.items(), key=lambda kv: _rank(kv[1]))
        for ci, (color, sizes) in enumerate(corder):
            sizes.sort(key=_sku_cover)
            for si, s in enumerate(sizes):
                border = ""
                if si == 0 and ci == 0 and pi > 0:
                    border = "border-top:3px solid #475569;"       # MÃ mới → gạch đậm
                elif si == 0 and ci > 0:
                    border = "border-top:2px dashed #94a3b8;"       # MÀU mới trong cùng mã → gạch đứt
                ma_start = (ci == 0 and si == 0)
                cells = [_cell(ck, s, code, color, ma_start, si == 0) for ck in cols]
                tds = "".join(f'<td style="{_TD}{border}{stl}">{_esc(str(v))}</td>' for v, stl in cells)
                rows.append(f"<tr>{tds}</tr>")
    _TH = ("padding:6px 9px;text-align:left;white-space:nowrap;position:sticky;top:0;"
           "background:#334155;color:#fff;z-index:1;")
    thead = "".join(f'<th style="{_TH}">{_esc(_SKU_HDR.get(c, c))}</th>' for c in cols)
    return thead, "".join(rows)


def _render_grouped_skus(skus, cols, sort="cover", scroll_h=None, max_groups=None, note=None):
    """Bảng SKU gom Mã>Màu>Size (gạch đậm/đứt). scroll_h: cao cố định + header dính."""
    if not skus:
        st.caption("— không có —")
        return
    thead, tbody = _sku_group_html(skus, cols, sort, max_groups)
    wrap = f'<div style="max-height:{scroll_h}px;overflow:auto">' if scroll_h else '<div style="overflow-x:auto">'
    st.markdown(wrap + '<table style="border-collapse:collapse;width:100%;font-size:.85rem">'
                f'<thead><tr>{thead}</tr></thead><tbody>{tbody}</tbody></table></div>',
                unsafe_allow_html=True)
    if note:
        st.caption(note)


def _render_by_material(skus, cols, sort="need"):
    """Chia theo CHẤT LIỆU trước (chất liệu cần nhiều lên đầu), rồi mới vào bảng Mã>Màu>Size."""
    from collections import defaultdict
    fams = defaultdict(list)
    for s in skus:
        fams[s.get("family") or "(khác)"].append(s)
    fam_order = sorted(fams.items(), key=lambda kv: -sum(float(x.get("needQty") or 0) for x in kv[1]))
    for fam, items in fam_order:
        need = int(round(sum(float(x.get("needQty") or 0) for x in items)))
        st.markdown(f"### 🧵 {fam} — cần {need} cái")
        _render_grouped_skus(items, cols=cols, sort=sort)


def _render_production_page():
    st.title("🧵 Dự đoán sản xuất")
    st.caption("**Công thức cố định:** nhu cầu/tháng = tổng bán **3 tháng gần nhất ÷ 3** · "
               "tồn mục tiêu = nhu cầu/tháng **× 1,5** (dự phòng tránh hết hàng) · làm tròn LÊN. "
               "Cần SX = tồn mục tiêu − tồn hiện tại. Phân loại: cần **≤ 5 cái** = Tự cắt tay; "
               "cần > 5 & bán ≥ 30/kỳ = Bắt buộc SX; còn lại = Gợi ý. "
               "(Lấy trung bình 3 tháng gần nhất nên tự bám mùa mua.)")
    if not credential_present():
        st.warning("⚠️ Trang này cần credential Sapo LIVE.")
        st.stop()

    # CÔNG THỨC CỐ ĐỊNH (theo yêu cầu shop) — không cho chỉnh tay:
    #   nhu cầu/tháng = tổng bán 3 tháng gần nhất ÷ 3 ; tồn mục tiêu = ×1,5 ; làm tròn LÊN.
    data_months, forecast_months, safety_factor, round_mode = 3, 1, 1.5, "ceil"
    max_product_pages, max_report_pages = 80, 250
    end_date = (datetime.now(timezone.utc) + timedelta(hours=7)).date()
    if st.button("🔄 Làm mới dữ liệu Sapo", key="prod_refresh"):
        st.cache_data.clear()
        st.rerun()

    try:
        rep = load_production_tool(data_months, forecast_months, safety_factor, round_mode, end_date.isoformat(),
                                   max_product_pages, max_report_pages)
    except requests.HTTPError as e:
        st.error(f"❌ Lỗi gọi API Sapo: `{e}`")
        st.stop()
    except Exception as e:
        st.error(f"❌ Không tính được dự đoán sản xuất: `{e}`")
        st.stop()

    src = rep.get("source") or {}
    crit = rep.get("critical") or {}
    # Lưu số việc SX vào session để popup cảnh báo hiện trên MỌI tab của nhân viên kho.
    st.session_state["prod_todo"] = {
        "must": len(crit.get("mustProduceGroups") or []),
        "suggest": len(crit.get("suggestGroups") or []),
        "manual": len(crit.get("manualCutGroups") or []),
    }
    st.caption(
        f"Nguồn Sapo: {src.get('sku_count', 0):,} SKU / {src.get('variant_count', 0):,} biến thể · "
        f"{src.get('order_count', 0):,} đơn bán (tính từ đơn hàng) "
        f"từ {src.get('start_date')} đến {src.get('end_date')}."
    )
    _start, _end = src.get("start_date"), src.get("end_date")
    m = st.columns(6)
    m[0].metric("SKU Sapo", f"{src.get('sku_count', 0):,}",
                help="Tổng số SKU (biến thể sản phẩm) trong danh sách sản phẩm Sapo. "
                     "Số **Tồn** của từng SKU lấy từ tồn kho THỰC trên Sapo — đã gồm sẵn "
                     "nhập từ NCC + nhập hàng hoàn − bán ra (là tồn hiện tại, không cần cộng lại).")
    m[1].metric("SP đã bán kỳ", f"{src.get('sold_items', 0):,}", f"{src.get('order_count', 0):,} đơn",
                help=f"Tổng SỐ CÁI bán ra từ {_start} đến {_end}, cộng từ dòng hàng của MỌI đơn "
                     f"(mọi kênh TikTok/Shopee/…, mọi trạng thái TRỪ đơn hủy). Đây là số BÁN/XUẤT để "
                     f"tính nhu cầu — KHÔNG phải nhập kho. Dòng dưới ({src.get('order_count', 0):,}) là số ĐƠN. "
                     f"Muốn số nhỏ/sát hơn thì lọc bỏ đơn hoàn/trả — báo mình bật.")
    m[2].metric("Tổng cần SX", f"{sum(float(x.get('needQty') or 0) for x in rep.get('needRows', [])):,.0f}",
                help="Tổng số cái cần sản xuất = cộng 'Cần SX' của các nhóm. "
                     "Cần SX = Tồn mục tiêu − Tồn hiện tại (làm tròn LÊN). "
                     "Tồn mục tiêu = (tổng bán 3 tháng gần nhất ÷ 3) × 1,5.")
    m[3].metric("Bắt buộc SX", len(crit.get("mustProduceGroups") or []),
                help="Số NHÓM (mã+màu) bắt buộc SX: cần > 5 cái VÀ bán ≥ 30 cái/kỳ (bán chạy, cắt cây).")
    m[4].metric("Gợi ý SX", len(crit.get("suggestGroups") or []),
                help="Số nhóm nên cân nhắc SX: cần > 5 cái nhưng bán < 30 cái/kỳ.")
    m[5].metric("Tự cắt tay", len(crit.get("manualCutGroups") or []),
                help="Số nhóm cần SX ≤ 5 cái — số nhỏ, cắt cả cây vải phí nên để cắt tay.")

    _agg = rep.get("aggregated", []) or []
    def _sig(k):
        return int(round(sum(float(x.get(k) or 0) for x in _agg)))
    _ky = f"KỲ = 3 tháng gần nhất: từ {_start} đến {_end}"
    st.markdown(f"**📦 Xuất – Nhập – Tồn trong kỳ** · {_ky}  ·  Tồn đầu ➕ Nhập ➖ Bán 🟰 Tồn cuối")
    mm = st.columns(5)
    mm[0].metric("Tồn đầu kỳ", f"{_sig('openingStock'):,}",
                 help=f"{_ky}. Ước tính tồn ĐẦU kỳ = Tồn cuối (hiện tại) − Nhập trong kỳ + Bán trong kỳ.")
    mm[1].metric("➕ Nhập NCC", f"{_sig('inNCC'):,}",
                 help=f"{_ky}. Nhập kho từ NHÀ CUNG CẤP trong kỳ (phiếu nhập kho — receive_inventories).")
    mm[2].metric("➕ Nhập hoàn", f"{_sig('inReturn'):,}",
                 help=f"{_ky}. Nhập LẠI kho từ ĐƠN TRẢ HÀNG trong kỳ (số hàng đã restock vào kho).")
    mm[3].metric("➖ Bán/xuất", f"{_sig('totalOut'):,}",
                 help=f"{_ky}. Số cái bán ra trong kỳ (tính từ đơn hàng, trừ đơn hủy).")
    mm[4].metric("🟰 Tồn cuối (nay)", f"{_sig('endingStock'):,}",
                 help="Tồn kho THỰC hiện tại trên Sapo (thời điểm HÔM NAY) = Tồn đầu + Nhập − Bán.")

    tabs = st.tabs(["📋 Chi tiết SKU", "🧵 Cần sản xuất", "✋ Tự cắt tay",
                    "✂️ Cắt chung theo vải", "⚠️ Cảnh báo"])
    with tabs[0]:
        st.caption("Gõ SKU/mã — **lọc ngay khi gõ** (gõ đúng mã → còn 1 SKU). "
                   "Gạch **đậm** = đổi mã · gạch **đứt** = đổi màu.")
        detail = rep.get("aggregated", [])
        if not detail:
            st.info("Không có SKU.")
        else:
            _render_detail_search_table(detail)
            st.download_button("⬇️ Tải CSV chi tiết SKU",
                               _production_detail_df(detail).to_csv(index=False).encode("utf-8-sig"),
                               "chi-tiet-sku-du-doan.csv", "text/csv")
    with tabs[1]:
        st.caption("Cần sản xuất — **chia theo chất liệu**, trong mỗi chất liệu: "
                   "Mã (gạch đậm) → Màu (gạch đứt) → Size.")
        _need = [r for r in rep.get("needRows", []) if not r.get("manualCut")]
        if not _need:
            st.success("✅ Chưa có nhóm nào cần sản xuất theo công thức hiện tại.")
        else:
            level = st.multiselect("Lọc mức", ["Bắt buộc SX", "Gợi ý SX"],
                                   default=["Bắt buộc SX", "Gợi ý SX"])
            sel = [r for r in _need if ("Bắt buộc SX" if r.get("mustProduce") else "Gợi ý SX") in level] if level else _need
            if not sel:
                st.info("Không có mã ở mức đã chọn.")
            else:
                _render_by_material(sel, cols=["ma", "mau", "size", "ton", "banth", "duban", "cansx"], sort="need")
                st.download_button("⬇️ Tải CSV cần sản xuất",
                                   _production_detail_df(sel).to_csv(index=False).encode("utf-8-sig"),
                                   "du-doan-san-xuat.csv", "text/csv")
    with tabs[2]:
        st.caption("Nhóm **cần SX ≤ 5 cái** — cắt tay. **Chia theo chất liệu**, rồi Mã → Màu → Size.")
        mc = crit.get("manualCutGroups") or []
        _mskus = [r for r in rep.get("needRows", []) if r.get("manualCut")]
        if not _mskus:
            st.info("Không có nhóm tự cắt tay.")
        else:
            _print_html = _manual_cut_print_html(mc)
            components.html(
                '<button onclick="printCut()" style="padding:8px 16px;font-size:15px;font-weight:600;'
                'background:#2563eb;color:#fff;border:none;border-radius:6px;cursor:pointer">🖨️ In A4 để cắt</button>'
                "<script>function printCut(){var h=" + json.dumps(_print_html) + ";"
                "var w=window.open('','_blank');"
                "if(!w){alert('Trình duyệt chặn popup — cho phép popup cho trang này rồi bấm lại.');return;}"
                "w.document.open();w.document.write(h);w.document.close();w.focus();"
                "setTimeout(function(){w.print();},400);}</script>",
                height=54,
            )
            st.caption("Bấm **In A4** để mở phiếu in. Nếu bị chặn popup thì tải **phiếu HTML** rồi mở bằng trình duyệt → Ctrl+P.")
            _render_by_material(_mskus, cols=["ma", "mau", "size", "ton", "cansx"], sort="need")
            _dl = st.columns(2)
            _dl[0].download_button("🖨️ Tải phiếu in (HTML)", _print_html.encode("utf-8"),
                                   "phieu-cat-tay.html", "text/html")
            _dl[1].download_button("⬇️ Tải CSV tự cắt tay",
                                   _production_detail_df(_mskus).to_csv(index=False).encode("utf-8-sig"),
                                   "tu-cat-tay.csv", "text/csv")
    with tabs[3]:
        st.caption("Gom theo **chất liệu → màu vải** để cắt chung 1 cây. Mỗi chất liệu 1 bảng, "
                   "màu cần nhiều xếp trên. 'Nhóm mã' = các mã dùng chung màu vải đó.")
        _cb = rep.get("cutBatchGroups", [])
        if not _cb:
            st.info("Chưa có nhóm cắt chung theo vải.")
        else:
            _render_cutbatch_by_material(_cb)
    with tabs[4]:
        for msg in crit.get("alerts") or []:
            st.warning(msg)
        st.caption("Cuộn trong bảng vẫn giữ dòng tiêu đề. Gạch **đậm** = đổi mã · gạch **đứt** = đổi màu.")
        c1, c2, c3 = st.columns(3)
        with c1:
            st.markdown("**🔴 Hết hàng** · Cần SX↓")
            _render_grouped_skus(rep.get("outSkuList", []), cols=["ma", "mau", "size", "banth", "cansx"],
                                 sort="need", scroll_h=430, max_groups=150)
        with c2:
            st.markdown("**⚪ Có tồn, không bán** · tồn↓")
            _render_grouped_skus(rep.get("zeroSalesList", []), cols=["ma", "mau", "size", "ton"],
                                 sort="stock", scroll_h=430, max_groups=150)
        with c3:
            st.markdown("**🟡 Tồn chậm/dư** · tồn↓")
            _render_grouped_skus(rep.get("slowStockList", []), cols=["ma", "mau", "size", "ton", "duban"],
                                 sort="stock", scroll_h=430, max_groups=150)


def _variant_summary(row):
    if not row:
        return ""
    sku = row.get("sku") or ""
    name = row.get("product_name") or ""
    var = row.get("variant_name") or ""
    title = " / ".join([x for x in (name, var) if x])
    stock = f"{int(row.get('inventory_quantity') or 0):,}".replace(",", ".")
    return f"`{sku}` · {title[:80]} · tồn {stock} · giá {_vnd(row.get('price'))}"


def _price_field_label(label, *, required=False, missing=False):
    color = "#b91c1c" if missing else "#374151"
    star = ' <span style="color:#b91c1c">*</span>' if required else ""
    st.markdown(
        f'<div style="color:{color};font-size:.9rem;font-weight:700;margin:0 0 2px">'
        f'{_esc(label)}{star}</div>',
        unsafe_allow_html=True,
    )


def _pick_variant_ui(variants, *, query_key, select_key, label, placeholder, required_missing=False):
    _price_field_label(label, required=True, missing=required_missing)
    q = st.text_input(label, placeholder=placeholder, key=query_key, label_visibility="collapsed")
    if not q.strip():
        st.caption("Gõ tên, mã SKU hoặc barcode để hiện gợi ý từ Sapo.")
        return None

    matches = PT.filter_variants(variants, q, limit=50)
    if not matches:
        st.warning("Không thấy SKU gần đúng trong Sapo. Có thể nhập tay bên dưới.")
        return None

    idx = st.selectbox(
        "Chọn SKU đúng",
        list(range(len(matches))),
        key=select_key,
        format_func=lambda i: _variant_label(matches[i]),
    )
    picked = matches[idx] if idx is not None else None
    if picked:
        st.caption("Đã chọn: " + _variant_summary(picked))
    return picked


def _price_blank(value):
    return not str(value or "").strip()


def _price_num_missing(value):
    try:
        return float(value or 0) <= 0
    except Exception:
        return True


def _price_req_note(text="Bắt buộc nhập"):
    st.markdown(
        f'<div style="color:#b91c1c;font-size:.82rem;font-weight:700;margin-top:-8px;margin-bottom:6px">'
        f'⚠ {_esc(text)}</div>',
        unsafe_allow_html=True,
    )


def _price_required_number(container, label, *, key, value, step, min_value=0.0):
    state_value = st.session_state.get(key, value)
    missing = _price_num_missing(state_value)
    with container:
        _price_field_label(label, required=True, missing=missing)
        out = st.number_input(
            label,
            min_value=min_value,
            value=float(value),
            step=float(step),
            key=key,
            label_visibility="collapsed",
        )
        if _price_num_missing(out):
            _price_req_note()
        return out


def _price_required_text_input(label, *, key, placeholder, missing=False):
    _price_field_label(label, required=True, missing=missing)
    return st.text_input(label, key=key, placeholder=placeholder, label_visibility="collapsed")


def _render_price_formula():
    with st.container(border=True):
        st.markdown("**Công thức tính giá bán**")
        st.markdown(
            """
- `Giá/m vải = Giá 1kg vải / Chiều dài/kg`
- `Diện tích chính = Dài chính x Ngang chính x Số lớp chính / 10.000`
- `Diện tích lót = Dài lót x Ngang lót x Số lớp lót / 10.000`
- `Tổng diện tích = (Diện tích chính + Diện tích lót) x (1 + Hao hụt / 100)`
- `Mét vải/SP = Tổng diện tích / (Khổ vải / 100)`
- `Tiền vải = Mét vải/SP x Giá/m vải`
- `Chi phí SX = Cắt + May + Ủi gói + Vận hành + Phụ liệu`
- `Giá vốn = Tiền vải + Chi phí SX`
- `Giá bán sàn = Giá vốn x Hệ số giá bán`
            """
        )
        st.caption("Nếu có nhiều size, dài/ngang từng size tự cộng/trừ theo phần chênh size, lấy size M làm gốc.")


def _render_price_page():
    head = st.columns([0.78, 0.22], vertical_alignment="center")
    with head[0]:
        st.title("🧮 Tính giá bán")
        st.caption("Chọn SKU từ Sapo, nhập vài thông số chính; phần ít dùng được gom vào mục mở rộng.")
    if not credential_present():
        st.warning("⚠️ Trang này cần credential Sapo LIVE.")
        st.stop()

    with head[1]:
        if st.button("🔄 Làm mới Sapo", key="price_refresh", width="stretch"):
            st.cache_data.clear()
            st.rerun()

    try:
        variants = load_sapo_catalog()
    except requests.HTTPError as e:
        st.error(f"❌ Lỗi gọi API Sapo: `{e}`")
        st.stop()
    except Exception as e:
        st.error(f"❌ Không tải được danh mục Sapo: `{e}`")
        st.stop()

    with st.container(border=True):
        st.markdown("**1. Chọn mã sản phẩm và mã vải**")
        sku_cols = st.columns(2)
        with sku_cols[0]:
            product_state_missing = _price_blank(st.session_state.get("price_product_q")) and _price_blank(st.session_state.get("price_product_manual"))
            product = _pick_variant_ui(
                variants,
                query_key="price_product_q",
                select_key="price_product_pick",
                label="Sản phẩm",
                placeholder="Gõ tên hoặc mã, VD: áo phông, A18, CVBC",
                required_missing=product_state_missing,
            )
            product_manual_missing = not product and _price_blank(st.session_state.get("price_product_manual"))
            product_sku = product.get("sku") if product else _price_required_text_input(
                "Nhập tay SKU sản phẩm",
                key="price_product_manual",
                placeholder="VD: AO-NA-M",
                missing=product_manual_missing,
            )
            if _price_blank(product_sku):
                _price_req_note("Chọn SKU từ Sapo hoặc nhập tay SKU sản phẩm")
        with sku_cols[1]:
            fabric_state_missing = _price_blank(st.session_state.get("price_fabric_q")) and _price_blank(st.session_state.get("price_fabric_manual"))
            fabric = _pick_variant_ui(
                variants,
                query_key="price_fabric_q",
                select_key="price_fabric_pick",
                label="Vải",
                placeholder="Gõ mã vải, tên vải hoặc barcode",
                required_missing=fabric_state_missing,
            )
            fabric_manual_missing = not fabric and _price_blank(st.session_state.get("price_fabric_manual"))
            fabric_sku = fabric.get("sku") if fabric else _price_required_text_input(
                "Nhập tay SKU vải",
                key="price_fabric_manual",
                placeholder="VD: VAI...",
                missing=fabric_manual_missing,
            )
            if _price_blank(fabric_sku):
                _price_req_note("Chọn SKU từ Sapo hoặc nhập tay SKU vải")

    specs = PT.extract_fabric_specs(
        *(x for x in (
            (fabric or {}).get("sku"),
            (fabric or {}).get("product_name"),
            (fabric or {}).get("variant_name"),
            (fabric or {}).get("tags"),
        ) if x)
    )
    fabric_identity = str(fabric_sku or "").strip()
    if fabric_identity and st.session_state.get("_price_selected_fabric") != fabric_identity:
        if specs.get("fabric_width_cm"):
            st.session_state["price_width"] = float(specs["fabric_width_cm"])
        if specs.get("meters_per_kg"):
            st.session_state["price_mkg"] = float(specs["meters_per_kg"])
        if fabric and float((fabric or {}).get("price") or 0) > 0:
            st.session_state["price_pkg"] = float((fabric or {}).get("price") or 0)
        st.session_state["_price_selected_fabric"] = fabric_identity

    with st.container(border=True):
        st.markdown("**2. Thông số bắt buộc**")
        f1 = st.columns(3)
        fabric_width = _price_required_number(f1[0], "Khổ vải (cm)", min_value=0.0, value=float(specs.get("fabric_width_cm") or 160), step=1.0, key="price_width")
        meters_per_kg = _price_required_number(f1[1], "Chiều dài/kg (m/kg)", min_value=0.0, value=float(specs.get("meters_per_kg") or 2.8), step=0.05, key="price_mkg")
        price_per_kg = _price_required_number(f1[2], "Giá 1kg vải", min_value=0.0, value=float((fabric or {}).get("price") or 0), step=1000.0, key="price_pkg")

        f2 = st.columns(3)
        main_length = _price_required_number(f2[0], "Dài chính (cm)", min_value=0.0, value=60.0, step=1.0, key="price_main_l")
        main_width = _price_required_number(f2[1], "Ngang chính (cm)", min_value=0.0, value=50.0, step=1.0, key="price_main_w")
        main_layers = _price_required_number(f2[2], "Số lớp chính", min_value=0.0, value=1.0, step=1.0, key="price_main_layers")

        f3 = st.columns(3)
        size_count = f3[0].selectbox("Số size *", [1, 2, 3, 4, 5, 6], index=4, key="price_size_count")
        waste = f3[1].number_input("Hao hụt (%)", min_value=0.0, value=5.0, step=0.5, key="price_waste")
        markup = _price_required_number(f3[2], "Hệ số giá bán", min_value=0.0, value=4.0, step=0.1, key="price_markup")

    with st.container(border=True):
        st.markdown("**3. Chi phí chính**")
        c1 = st.columns(4)
        cut_cost = c1[0].number_input("Cắt", min_value=0.0, value=0.0, step=1000.0, key="price_cut_cost")
        sewing_cost = c1[1].number_input("May", min_value=0.0, value=0.0, step=1000.0, key="price_sewing_cost")
        iron_pack_cost = c1[2].number_input("Ủi gói", min_value=0.0, value=0.0, step=1000.0, key="price_iron_cost")
        operation_cost = c1[3].number_input("Vận hành/sp", min_value=0.0, value=5000.0, step=1000.0, key="price_operation_cost")

    with st.expander("Lớp lót và chênh size", expanded=False):
        r2 = st.columns(4)
        lining_length = r2[0].number_input("Dài lót (cm)", min_value=0.0, value=0.0, step=1.0, key="price_lining_l")
        lining_width = r2[1].number_input("Ngang lót (cm)", min_value=0.0, value=0.0, step=1.0, key="price_lining_w")
        lining_layers = r2[2].number_input("Số lớp lót", min_value=0.0, value=0.0, step=1.0, key="price_lining_layers")
        base_size = r2[3].selectbox("Size làm gốc", ["M", "FREESIZE"], index=0, key="price_base_size")

        r3 = st.columns(2)
        width_diff = r3[0].number_input("Chênh ngang mỗi size (cm)", min_value=0.0, value=2.0, step=0.5, key="price_width_diff")
        length_diff = r3[1].number_input("Chênh dài mỗi size (cm)", min_value=0.0, value=1.0, step=0.5, key="price_length_diff")

    with st.expander("Phụ liệu khác", expanded=False):
        c2 = st.columns(4)
        zipper_cost = c2[0].number_input("Dây kéo", min_value=0.0, value=0.0, step=1000.0, key="price_zipper_cost")
        thread_cost = c2[1].number_input("Chỉ may", min_value=0.0, value=0.0, step=1000.0, key="price_thread_cost")
        tag_cost = c2[2].number_input("Nhãn tag", min_value=0.0, value=0.0, step=1000.0, key="price_tag_cost")
        button_cost = c2[3].number_input("Cúc", min_value=0.0, value=0.0, step=1000.0, key="price_button_cost")

        c3 = st.columns(4)
        elastic_cost = c3[0].number_input("Lưng thun", min_value=0.0, value=0.0, step=1000.0, key="price_elastic_cost")
        glue_cost = c3[1].number_input("Keo", min_value=0.0, value=0.0, step=1000.0, key="price_glue_cost")
        lace_cost = c3[2].number_input("Ren", min_value=0.0, value=0.0, step=1000.0, key="price_lace_cost")
        other_cost = c3[3].number_input("Khác", min_value=0.0, value=0.0, step=1000.0, key="price_other_cost")

    _render_price_formula()

    required_missing = []
    if not str(product_sku or "").strip():
        required_missing.append("SKU sản phẩm")
    if not str(fabric_sku or "").strip():
        required_missing.append("SKU vải")
    for label, value in (
        ("khổ vải", fabric_width),
        ("chiều dài/kg", meters_per_kg),
        ("giá 1kg vải", price_per_kg),
        ("dài lớp chính", main_length),
        ("ngang lớp chính", main_width),
        ("số lớp chính", main_layers),
        ("hệ số giá bán", markup),
    ):
        if float(value or 0) <= 0:
            required_missing.append(label)

    if lining_layers > 0 and (lining_length <= 0 or lining_width <= 0):
        required_missing.append("dài/ngang lớp lót")

    if required_missing:
        st.error("Còn thiếu mục bắt buộc: " + ", ".join(required_missing) + ". Các ô thiếu đã được tô đỏ phía trên.")
        return

    try:
        result = PT.calculate_selling_price({
            "product_sku": product_sku,
            "fabric_sku": fabric_sku,
            "fabric_width_cm": fabric_width,
            "meters_per_kg": meters_per_kg,
            "price_per_kg": price_per_kg,
            "main_length_cm": main_length,
            "main_width_cm": main_width,
            "main_layers": main_layers,
            "lining_length_cm": lining_length,
            "lining_width_cm": lining_width,
            "lining_layers": lining_layers,
            "size_count": size_count,
            "base_size": base_size,
            "size_width_diff_cm": width_diff,
            "size_length_diff_cm": length_diff,
            "waste_percent": waste,
            "markup_multiplier": markup,
            "cut_cost": cut_cost,
            "sewing_cost": sewing_cost,
            "iron_pack_cost": iron_pack_cost,
            "zipper_cost": zipper_cost,
            "thread_cost": thread_cost,
            "tag_cost": tag_cost,
            "operation_cost": operation_cost,
            "button_cost": button_cost,
            "elastic_cost": elastic_cost,
            "glue_cost": glue_cost,
            "lace_cost": lace_cost,
            "other_cost": other_cost,
        })
    except Exception as e:
        st.error(f"❌ Chưa tính được: {e}")
        return

    st.markdown("#### Kết quả")
    summary = result["summary"]
    with st.container(border=True):
        kpi = st.columns(4)
        kpi[0].metric("Giá bán đề xuất", _vnd(summary["avgSellingPrice"]))
        kpi[1].metric("Giá vốn TB", _vnd(summary["avgCostPrice"]))
        kpi[2].metric("Tiền vải TB", _vnd(summary["avgFabricCost"]))
        kpi[3].metric("Mét vải TB/SP", f"{summary['avgFabricMeters']:.3f} m")
        st.caption(f"Giá/m vải: **{_vnd(summary['meterPrice'])}** · Chi phí SX/sp: **{_vnd(summary['productionCost'])}**")

    if product and product.get("price"):
        diff = int(round(summary["avgSellingPrice"] - float(product.get("price") or 0)))
        st.info(f"Giá Sapo hiện tại: **{_vnd(product.get('price'))}** · Chênh với đề xuất: **{_vnd(diff)}**")

    out = pd.DataFrame([{
        "SKU SP": r["productSku"],
        "SKU vải": r["fabricSku"],
        "Size": r["size"],
        "Dài chính": round(r["mainLengthCm"], 1),
        "Ngang chính": round(r["mainWidthCm"], 1),
        "Dài lót": round(r["liningLengthCm"], 1),
        "Ngang lót": round(r["liningWidthCm"], 1),
        "Diện tích m²": round(r["totalAreaM2"], 4),
        "Mét vải/SP": round(r["fabricMeters"], 3),
        "Tiền vải": int(round(r["fabricCost"])),
        "Chi phí SX": int(round(r["productionCost"])),
        "Giá vốn": int(round(r["costPrice"])),
        "Giá bán sàn": int(round(r["sellingPrice"])),
    } for r in result["rows"]])
    with st.expander("Chi tiết theo size", expanded=True):
        st.dataframe(out, width="stretch", hide_index=True, height=min(360, 80 + len(out) * 36))
        st.download_button(
            "⬇️ Tải CSV tính giá",
            out.to_csv(index=False).encode("utf-8-sig"),
            "tinh-gia-ban.csv",
            "text/csv",
        )


def _sync_summary(obj):
    try:
        if isinstance(obj, dict):
            for key in ("total", "total_returns", "n", "count"):
                if key in obj:
                    return str(obj.get(key))
            return f"{len(obj)} nhóm"
        if isinstance(obj, (list, tuple, set)):
            return f"{len(obj)} dòng"
    except Exception:
        pass
    return "OK"


def _run_shared_sync_tasks(tasks, fresh=True):
    rows = []
    for label, fn, clear_fn in tasks:
        t0 = time.perf_counter()
        try:
            if fresh and clear_fn:
                clear_fn()
            data = fn()
            rows.append({
                "Nguồn": label,
                "KQ": "OK",
                "SL": _sync_summary(data),
                "Giây": round(time.perf_counter() - t0, 1),
            })
        except Exception as e:
            rows.append({
                "Nguồn": label,
                "KQ": "Lỗi",
                "SL": str(e)[:120],
                "Giây": round(time.perf_counter() - t0, 1),
            })
    return rows


def _render_shared_sync_sidebar():
    if not (credential_present() and (_cc_role == "admin" or _is_owner)):
        return
    with st.sidebar.expander("📥 Đồng bộ dữ liệu chung", expanded=False):
        st.caption("Gọi đúng các hàm tải mà trang/tab đang dùng, nên trang khác sẽ đọc lại cache chung.")
        fresh = st.checkbox("Tải mới từ API", value=True, key="shared_sync_fresh")
        if st.button("⚡ Làm nóng vận hành", width="stretch", key="shared_sync_ops"):
            st.session_state["shared_sync_rows"] = _run_shared_sync_tasks([
                ("Cảnh báo", load_alerts, load_alerts.clear),
                ("Phiếu nhặt", load_picking, load_picking.clear),
                ("Báo cáo ngày", load_daily_report, load_daily_report.clear),
                ("Tổng hợp 30 ngày", load_week_summary, load_week_summary.clear),
                ("Đơn trả đang xử lý", load_returns_inprogress, load_returns_inprogress.clear),
                ("Kho video đã lưu", load_dohana_video_store, load_dohana_video_store.clear),
            ], fresh=fresh)
            st.session_state["shared_sync_at"] = datetime.now(timezone.utc) + timedelta(hours=7)
        if st.button("🧵 Làm nóng tồn kho/SP", width="stretch", key="shared_sync_catalog"):
            st.session_state["shared_sync_rows"] = _run_shared_sync_tasks([
                ("Danh mục + tồn kho", load_sapo_catalog, load_sapo_catalog.clear),
            ], fresh=fresh)
            st.session_state["shared_sync_at"] = datetime.now(timezone.utc) + timedelta(hours=7)
        if st.button("🐢 Quét đơn đóng cả năm", width="stretch", key="shared_sync_closed"):
            st.session_state["shared_sync_rows"] = _run_shared_sync_tasks([
                ("Đơn trả bị đóng cả năm", load_closed_returns_full_year, load_closed_returns_full_year.clear),
            ], fresh=fresh)
            st.session_state["shared_sync_at"] = datetime.now(timezone.utc) + timedelta(hours=7)
        rows = st.session_state.get("shared_sync_rows") or []
        if rows:
            _at = st.session_state.get("shared_sync_at")
            if _at:
                st.caption("Lần đồng bộ: " + _at.strftime("%H:%M:%S %d/%m"))
            st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch", height=min(240, 40 + 35 * len(rows)))


# Popup cảnh báo cố định — hiện ở MỌI trang (kho/admin thêm việc SX/cắt tay)
render_alert_popup(_sees_production)
_render_shared_sync_sidebar()

if _page == PAGE_PRODUCTION:
    _render_production_page()
    st.stop()

if _page == PAGE_PRICE:
    _render_price_page()
    st.stop()


# ════════════════ TRANG TỔNG QUAN ĐIỀU HÀNH ════════════════
def _render_overview():
    _l, _r = st.columns([3, 1])
    _l.title("🛍️ VITRAN BOUTIQUE")
    _l.caption("Tổng quan điều hành")
    _vn = datetime.now(timezone.utc) + timedelta(hours=7)
    _r.metric("Cập nhật (giờ VN)", _vn.strftime("%H:%M"), _vn.strftime("%d/%m/%Y"))
    if not credential_present():
        st.warning("⚠️ Trang này cần kết nối Sapo (LIVE).")
        return
    if st.button("🔄 Tải lại số liệu", key="ov_reload"):
        st.cache_data.clear()
        st.rerun()
    try:
        ov = load_overview()
    except Exception as e:
        st.error(f"❌ Lỗi tải tổng quan: `{e}`")
        return

    st.markdown('<div class="sec sec-orange">Tổng quan 7 ngày gần nhất</div>', unsafe_allow_html=True)
    _a = st.columns(3)
    _help_dat = ("Đơn khách đặt, ĐÃ LOẠI đơn đặt-nhưng-chưa-xử-lý đã hủy. "
                 "Vẫn giữ đơn đã xử lý (có vận đơn) dù sau đó bị hủy.")
    _a[0].metric("📦 Đơn đặt hôm nay", f"{ov['don_today']:,}", f"Tổng SP: {ov['sp_today']:,}",
                 delta_color="off", help=_help_dat)
    _a[1].metric("📦 Đơn đặt hôm qua", f"{ov['don_yest']:,}", f"Tổng SP: {ov['sp_yest']:,}",
                 delta_color="off", help=_help_dat)
    _a[2].metric("🗓️ Tổng đơn 7 ngày", f"{ov['don_week']:,}", f"Tổng SP: {ov['sp_week']:,}",
                 delta_color="off", help=_help_dat)
    _b = st.columns(3)
    _b[0].metric("🏷️ Tổng SKU (7 ngày)", f"{ov['sku_count']:,}")
    _b[1].metric("🛒 Tổng SP (7 ngày)", f"{ov['sp_week']:,}")
    _b[2].metric("📊 SP / đơn (TB)", ov['sp_per_order'])

    st.markdown('<div class="sec sec-orange">Đơn đặt 7 ngày</div>', unsafe_allow_html=True)
    _c1, _c2 = st.columns([3, 2])
    with _c1:
        st.markdown("**Theo ngày** — cột = số đơn · đường = số SP")
        st.plotly_chart(daily_chart(ov["daily"]), width="stretch")
    with _c2:
        st.markdown("**Theo sàn**")
        _sk = list(ov["sources"].keys())
        st.plotly_chart(donut([SOURCE_LABEL.get(k, k) for k in _sk], list(ov["sources"].values()),
                              [COLOR_SOURCE.get(k, "#ccc") for k in _sk],
                              str(sum(ov["sources"].values()))), width="stretch")
    st.markdown("**Theo gian hàng**")
    _stk = list(ov["stores"].keys())
    st.plotly_chart(donut(_stk, list(ov["stores"].values()),
                          [PALETTE[i % len(PALETTE)] for i in range(len(_stk))],
                          str(sum(ov["stores"].values()))), width="stretch")

    # ═══════════ ĐƠN CẦN GIAO HÔM NAY (theo mẫu) ═══════════
    dl = ov["delivery"]
    st.markdown('<div class="sec sec-orange">Đơn cần giao hôm nay'
                '<span class="ic" title="Đơn cần giao = Đơn mới hôm nay (Ngày xử lý hôm nay) + Đơn sót (xử lý hôm trước, hôm nay mới giao/còn chờ). Phễu: Đã xác nhận → Đã đóng hàng → Shipper đã nhận; phần còn lại = Còn chưa giao. Giờ VN.">&#9432;</span></div>',
                unsafe_allow_html=True)
    st.caption("**Đơn cần giao = Đơn mới hôm nay + Đơn sót** (gồm đơn đã giao shipper hôm nay và đơn còn chờ).")
    # Hàng 1 — Tổng / Mới / Sót
    _d = st.columns(3)
    _d[0].metric("🚚 Tổng đơn cần giao", f"{dl['tong']:,}",
                 help="Đơn cần đẩy cho shipper hôm nay = Đơn mới + Đơn sót.")
    _d[1].metric("🆕 Đơn mới hôm nay", f"{dl['moi']:,}", help="Đơn có NGÀY XỬ LÝ = hôm nay.")
    _d[2].metric("📌 Đơn sót", f"{dl['sot']:,}",
                 help="Đơn NGÀY XỬ LÝ hôm trước, hôm nay mới giao hoặc còn chờ.")
    # Số đơn cần giao ĐÃ CÓ video đóng hàng (khớp Dohana)
    _video_done = None
    if dohana.configured():
        _dvh = load_dohana()
        if _dvh:
            _mset = _dvh.get("match", set())
            _video_done = sum(1 for ids in dl.get("order_ids", []) if set(ids) & _mset)
    # Hàng 2 — phễu: chờ xác nhận → đã xác nhận → đã đóng
    _e = st.columns(3)
    _e[0].metric("📥 Đơn chờ xác nhận", f"{dl['cho_xac_nhan']:,}",
                 help="Đơn mở CHƯA tạo vận đơn (chưa xử lý / chờ xác nhận).")
    _e[1].metric("📋 Đã xác nhận", f"{dl['da_xac_nhan']:,}", help="Đơn đã xác nhận (có confirmed_on).")
    _e[2].metric("✅ Đã đóng hàng", f"{dl['da_dong']:,}", help="Đơn đã đóng gói (packed).")
    # Hàng 3 — phễu: quay video → shipper nhận → chưa giao
    _g = st.columns(3)
    _g[0].metric("🎥 Đã quay video đóng hàng",
                 f"{_video_done:,}" if _video_done is not None else "—",
                 help="Đơn cần giao đã có video đóng hàng trên Dohana (khớp mã vận đơn). "
                      "'—' = chưa bật API Dohana.")
    _g[1].metric("🚚 Shipper đã nhận", f"{dl['shipper_nhan']:,}",
                 help="Đơn đã giao cho ĐVVC / shipper (đang giao).")
    _g[2].metric("⏳ Còn chưa giao", f"{dl['chua_giao']:,}",
                 help="Đơn còn chờ shipper tới lấy (pending) = Tổng − Shipper đã nhận.")
    st.caption(f"🔴 Hỏa tốc trong nhóm cần giao: **{dl['hoa_toc']}**.")
    if dl.get("sot_list"):
        _by = {}
        for _r in dl["sot_list"]:
            _by[_r["ĐVVC"]] = _by.get(_r["ĐVVC"], 0) + 1
        _bytxt = " · ".join(f"{k}: {v}" for k, v in sorted(_by.items(), key=lambda x: -x[1]))
        with st.expander(f"📌 Xem {len(dl['sot_list'])} đơn SÓT còn chưa giao theo ĐVVC — {_bytxt}"):
            render_compact_table(pd.DataFrame(dl["sot_list"]))
            st.caption("Đơn xử lý hôm trước, còn chưa giao shipper. Mã vận đơn + ĐVVC để đối chiếu Sapo.")
    st.markdown("**📊 Bảng phân bổ đơn cần giao theo đơn vị vận chuyển**")
    if ov["dvvc"]:
        render_compact_table(pd.DataFrame(ov["dvvc"]).rename(columns={
            "dvvc": "ĐVVC", "total": "Tổng đơn", "thuong": "Đơn thường", "hoatoc": "Hỏa tốc",
            "da_giao": "Đã giao shipper", "chua_giao": "Còn chưa giao"}))

    # ═══════════ ĐƠN HỦY (Cảnh báo giờ là popup cố định mọi trang) ═══════════
    st.markdown('<div class="sec sec-red">Đơn hủy sau đẩy VC</div>', unsafe_allow_html=True)
    st.caption("💡 Các cảnh báo quan trọng (xác nhận trễ, chưa giao, hủy sau gói cần lấy lại) "
               "giờ nằm ở **popup góc phải dưới** — hiện trên mọi trang.")
    cn = ov["cancel"]
    _cc = st.columns(4)
    _cc[0].metric("Hủy hôm nay", cn["today"])
    _cc[1].metric("Hủy hôm qua", cn["yest"])
    _cc[2].metric("Hủy 7 ngày", cn["total7d"])
    _cc[3].metric("💸 Giá trị rủi ro", f"{int(cn['risk_value']):,} đ")
    if cn["top_sku"]:
        st.markdown("**Top SKU bị hủy nhiều**")
        _ts = pd.DataFrame(cn["top_sku"]).rename(
            columns={"sku": "SKU", "qty": "SL", "value": "Giá trị (đ)"})
        render_compact_table(_ts)

    st.caption("Số liệu 7 ngày gần nhất · cache 5 phút · giờ VN (UTC+7). "
               "(Khối Hàng hoàn/Khiếu nại — Phần 3 — cần nhập tay Google Sheet, làm sau.)")
    return


def _render_pick():
    st.title("🧾 Phiếu nhặt hàng")
    st.caption("Tự kéo từ Sapo: đơn **đã in phiếu giao hàng** + **chờ đóng gói**. "
               "Hỏa tốc ưu tiên nhặt trước. Đếm cũ/mới theo **Ngày xử lý** (Sapo), cảnh báo xử lý trễ.")
    if not credential_present():
        st.warning("⚠️ Trang này cần kết nối Sapo (API LIVE) — hiện chưa có credential.")
        return
    if st.button("🔄 Tải lại đơn cần nhặt"):
        st.cache_data.clear()
        st.rerun()
    try:
        pdata = load_picking()
    except Exception as e:
        st.error(f"❌ Lỗi kéo đơn từ Sapo: `{e}`")
        return

    exp, nor = pdata["express"], pdata["normal"]

    def _pick_codes_skus(_e, _n):
        """Gom MÃ ĐƠN + [(SKU, SL)] của cả hỏa tốc + thường → lưu vào picklog."""
        _codes = [c for c in (list(_e.get("codes") or []) + list(_n.get("codes") or [])) if c]
        _groups = []
        for _src in (_e, _n):
            _groups.extend([g for g in (_src.get("code_groups") or []) if g])
        _m = {}
        for _s, _q in (list(_e.get("skus") or []) + list(_n.get("skus") or [])):
            _m[_s] = _m.get(_s, 0) + int(_q or 0)
        _car = {}
        for _src in (_e, _n):
            for _c, _q in (_src.get("carriers") or {}).items():
                _car[str(_c or "Khác")] = _car.get(str(_c or "Khác"), 0) + int(_q or 0)
        return _codes, sorted(_m.items(), key=lambda x: (-x[1], str(x[0]))), _car, _groups

    k = st.columns(4)
    k[0].metric("🔴 Hỏa tốc (nhặt trước)", exp["total_orders"])
    k[1].metric("Thường", nor["total_orders"])
    k[2].metric("🟢 Đơn mới (nay)", exp["new"] + nor["new"],
                help="Đơn có NGÀY XỬ LÝ = hôm nay.")
    k[3].metric("Đơn cũ (tồn)", exp["old"] + nor["old"],
                help="Đơn có NGÀY XỬ LÝ hôm trước, nay mới nhặt.")

    late_list = exp["late_list"] + nor["late_list"]
    if late_list:
        st.error(f"⚠ **{len(late_list)} đơn xử lý TRỄ** (sau 18h ngày đặt): "
                 + ", ".join(late_list[:25]) + ("…" if len(late_list) > 25 else ""))

    now_str = (datetime.now(timezone.utc) + timedelta(hours=7)).strftime("%H:%M %d/%m/%Y")
    _picklog_today = picklog.read_today() if picklog.configured() else []

    # (Các ô báo cáo: số đợt soạn · SP hủy sau in phiếu · đối chiếu soạn↔xuất kho · video
    #  đóng hàng — ĐÃ GỘP sang tab "Báo cáo cuối ngày" (tờ A4), bỏ ở đây tránh trùng.)

    # ── Phiếu in (trái) + Lịch sử in & nút Lưu (phải, KẾ BÊN phiếu) ──
    _cslip, _clog = st.columns([3, 2])
    with _cslip:
        # 1 NÚT DUY NHẤT: vừa IN vừa LƯU đợt (lưu phía server, không vướng CORS) → rerun tự bung hộp in.
        # (Đã bỏ nút in trong phiếu để NV không in mà quên lưu.)
        if pdata["total"] > 0:
            _can_save = picklog.configured()
            _lbl = ("🖨️ IN PHIẾU NHẶT — tự lưu vào lịch sử" if _can_save
                    else "🖨️ In phiếu nhặt (chưa bật lưu lịch sử)")
            if st.button(_lbl, type="primary", width="stretch"):
                if _can_save:
                    _allsku = {s for s, _ in exp["skus"]} | {s for s, _ in nor["skus"]}
                    _pcodes, _pskum, _pcar, _pgroups = _pick_codes_skus(exp, nor)
                    _ok, _msg = picklog.log_batch({
                        "ngay": (datetime.now(timezone.utc) + timedelta(hours=7)).strftime("%Y-%m-%d"),
                        "gio": now_str[:5],
                        "so_don": exp["total_orders"] + nor["total_orders"],
                        "so_sp": exp["total_qty"] + nor["total_qty"], "so_sku": len(_allsku),
                        "ht_don": exp["total_orders"], "th_don": nor["total_orders"],
                        "so_cu": exp["old"] + nor["old"],   # đơn CŨ (xác nhận hôm trước, nay mới nhặt)
                        "codes": _pcodes,       # MÃ ĐƠN từng đơn → đối chiếu hủy trước/sau soạn
                        "sku_list": _pskum,     # [(sku, SL)] đã nhặt trong đợt
                        "carriers": _pcar,
                        "code_groups": _pgroups,
                    })
                    if not _ok:
                        st.error(_msg)
                st.session_state["_pick_autoprint"] = True
                st.rerun()
            if not _can_save:
                st.caption("⚙️ Bật kho lưu (mục bên phải) để mỗi lần IN là **tự lưu vào lịch sử**.")
        _auto = st.session_state.pop("_pick_autoprint", False)
        if _auto:
            st.success("✅ Đã lưu đợt — đang bung hộp in (cho phép cửa sổ in).")
        components.html(picking_html(pdata, now_str, auto_print=_auto), height=860, scrolling=True)
    with _clog:
        st.markdown("#### 📋 Lịch sử in phiếu hôm nay")
        if not picklog.configured():
            st.info("Chưa bật lưu lịch sử in.")
            with st.expander("⚙️ Cách bật (~30 giây)"):
                st.markdown(_PICKLOG_SETUP)
        else:
            _logrows = _picklog_today
            if _logrows:
                _ldf = pd.DataFrame([{"Lượt": i + 1, "Giờ": r.get("gio", ""),
                                      "Số đơn": r.get("so_don", 0), "Số SP": r.get("so_sp", 0),
                                      "Số SKU": r.get("so_sku", 0), "HT": r.get("ht_don", 0),
                                      "Thường": r.get("th_don", 0)} for i, r in enumerate(_logrows)])
                st.markdown(f"**{len(_logrows)} lượt** · {int(_ldf['Số đơn'].sum())} đơn · "
                            f"{int(_ldf['Số SP'].sum())} SP")
                render_compact_table(_ldf)
            else:
                st.caption("Chưa lưu lượt nào hôm nay.")
        if pdata["total"] > 0:
            st.caption("✅ Chỉ cần bấm nút xanh **🖨️ IN PHIẾU NHẶT** (bên trái) — nó **vừa in vừa tự lưu**. "
                       "Nút dưới chỉ để lưu THỦ CÔNG khi cần (không in):")
            if st.button("💾 Lưu đợt thủ công (không in)", disabled=not picklog.configured()):
                _now_vn = datetime.now(timezone.utc) + timedelta(hours=7)
                _allsku = {s for s, _ in exp["skus"]} | {s for s, _ in nor["skus"]}
                _pcodes, _pskum, _pcar, _pgroups = _pick_codes_skus(exp, nor)
                ok, msg = picklog.log_batch({
                    "ngay": _now_vn.strftime("%Y-%m-%d"), "gio": _now_vn.strftime("%H:%M"),
                    "so_don": exp["total_orders"] + nor["total_orders"],
                    "so_sp": exp["total_qty"] + nor["total_qty"], "so_sku": len(_allsku),
                    "ht_don": exp["total_orders"], "th_don": nor["total_orders"],
                    "so_cu": exp["old"] + nor["old"],
                    "codes": _pcodes, "sku_list": _pskum, "carriers": _pcar,
                    "code_groups": _pgroups,
                })
                (st.success(msg + " Bấm 🔄 Tải lại để thấy.") if ok else st.error(msg))
            if not picklog.configured():
                st.caption("⚠️ Cần bật kho lưu (xem hướng dẫn trên).")

    # Quyền SỬA/XÓA lịch sử phiếu nhặt: CHỈ admin / chủ shop. NV kho chỉ xem + in.
    _can_edit_pick = _is_owner or (_cc_role == "admin")

    if picklog.configured() and _can_edit_pick:
        # ── XÓA 1 đợt (chỉ admin) ──
        with st.expander("🗑️ Xóa đợt phiếu nhặt (chỉ admin) — sửa số liệu sai", expanded=False):
            _all_del = picklog._read_all() or {}
            _dtoday = (datetime.now(timezone.utc) + timedelta(hours=7)).date()
            _dfrom = (_dtoday - timedelta(days=29)).isoformat()
            _del_logs = [r for r in _all_del.get("logs", []) if str(r.get("ngay") or "") >= _dfrom]
            _del_logs = sorted(_del_logs, key=lambda r: (str(r.get("ngay") or ""), str(r.get("gio") or "")),
                               reverse=True)
            if not _del_logs:
                st.caption("Không có đợt nào trong 30 ngày.")
            else:
                _del_opts = [f"{r.get('ngay')} · {r.get('gio', '—')} — {int(r.get('so_don') or 0)} đơn / "
                             f"{int(r.get('so_sp') or 0)} SP" for r in _del_logs]
                _sel_del = st.selectbox("Chọn đợt cần xóa", options=list(range(len(_del_logs))),
                                        format_func=lambda i: _del_opts[i], key="pick_del_sel")
                _r = _del_logs[_sel_del]
                st.caption(f"Sẽ xóa: **{_del_opts[_sel_del]}**")
                if st.button("🗑️ Xóa đợt này", type="primary", key="pick_del_btn"):
                    _ok, _msg = picklog.delete_log(_r.get("ngay"), _r.get("gio"),
                                                   _r.get("so_don"), _r.get("so_sp"))
                    if _ok:
                        st.success(f"✅ {_msg} Mở lại bảng 30 ngày để thấy cột Soạn cập nhật.")
                        st.cache_data.clear()
                        st.rerun()
                    else:
                        st.error(_msg)

        with st.expander("➕ Bù đợt thủ công (nhập lại đợt đã in mà chưa lưu)", expanded=False):
            st.caption("Nhìn phiếu nhặt đã in rồi gõ lại từng đợt — dùng khi NV in mà quên bấm lưu. "
                       "Mỗi đợt bấm **Lưu** một lần.")
            with st.form("pick_manual_add", clear_on_submit=True):
                _mc = st.columns([1.2, 1.3, 1, 1, 1, 1])
                _m_date = _mc[0].date_input(
                    "Ngày", value=(datetime.now(timezone.utc) + timedelta(hours=7)).date(),
                    key="pm_date")
                _m_gio = _mc[1].text_input("Giờ (HH:MM)", value="", placeholder="10:08", key="pm_gio")
                _m_don = _mc[2].number_input("Số đơn", min_value=0, value=0, step=1, key="pm_don")
                _m_sp = _mc[3].number_input("Số SP", min_value=0, value=0, step=1, key="pm_sp")
                _m_ht = _mc[4].number_input("Hỏa tốc", min_value=0, value=0, step=1, key="pm_ht")
                _m_cu = _mc[5].number_input("Cũ (tồn)", min_value=0, value=0, step=1, key="pm_cu")
                _m_ok = st.form_submit_button("💾 Lưu đợt này")
            if _m_ok:
                if int(_m_don) <= 0:
                    st.error("Số đơn phải > 0.")
                else:
                    _ok, _msg = picklog.log_batch({
                        "ngay": _m_date.isoformat(), "gio": str(_m_gio or "").strip() or "—",
                        "so_don": int(_m_don), "so_sp": int(_m_sp), "so_sku": 0,
                        "ht_don": int(_m_ht), "th_don": max(0, int(_m_don) - int(_m_ht)),
                        "so_cu": int(_m_cu), "source": "manual"})
                    if _ok:
                        st.success(f"✅ Đã lưu đợt {_m_gio or ''} — {int(_m_don)} đơn / {int(_m_sp)} SP. "
                                   "Mở lại bảng 30 ngày để thấy cột Soạn cập nhật.")
                        st.cache_data.clear()
                    else:
                        st.error(_msg)

        with st.expander("📥 Nạp nhiều đợt cùng lúc (dán danh sách — bù cả tháng)", expanded=False):
            st.caption("Mỗi dòng 1 đợt: **`NGÀY, ĐỢT/GIỜ, SỐ ĐƠN, SỐ SP, SỐ CŨ`** — ví dụ "
                       "`2026-07-11, Đợt 1, 74, 83, 4`. Cột **SỐ CŨ (tồn)** không bắt buộc (bỏ trống = 0). "
                       "Ngày nhận `YYYY-MM-DD` hoặc `DD/MM/YYYY`. Đợt trùng tự bỏ qua nhưng **cập nhật số cũ** "
                       "nếu trước đó chưa có → dán lại để bổ sung cột Cũ.")
            _bulk = st.text_area("Dán danh sách đợt ở đây", height=180, key="pick_bulk_text",
                                 placeholder="2026-07-11, Đợt 1, 74, 83\n2026-07-11, Đợt 2, 44, 50\n2026-07-11, Hỏa tốc, 4, 4")
            if st.button("💾 Nạp tất cả vào lịch sử", key="pick_bulk_save",
                         disabled=not picklog.configured(), type="primary"):
                _payloads, _errln = [], []
                for _ln in (_bulk or "").splitlines():
                    _ln = _ln.strip()
                    if not _ln:
                        continue
                    _p = [x.strip() for x in _ln.split(",")]
                    if len(_p) < 4:
                        _errln.append(_ln)
                        continue
                    _md = re.match(r"^(\d{4})-(\d{1,2})-(\d{1,2})$", _p[0])
                    _md2 = re.match(r"^(\d{1,2})/(\d{1,2})/(\d{4})$", _p[0])
                    if _md:
                        _iso = f"{_md.group(1)}-{int(_md.group(2)):02d}-{int(_md.group(3)):02d}"
                    elif _md2:
                        _iso = f"{_md2.group(3)}-{int(_md2.group(2)):02d}-{int(_md2.group(1)):02d}"
                    else:
                        _errln.append(_ln)
                        continue
                    _sd = int(re.sub(r"\D", "", _p[2]) or 0)
                    _sp = int(re.sub(r"\D", "", _p[3]) or 0)
                    _cu = int(re.sub(r"\D", "", _p[4]) or 0) if len(_p) >= 5 else 0
                    if _sd <= 0:
                        _errln.append(_ln)
                        continue
                    _ht = _sd if re.search(r"h[ỏo]a\s*t[ốo]c", _p[1].lower()) else 0
                    _payloads.append({"ngay": _iso, "gio": _p[1], "so_don": _sd, "so_sp": _sp,
                                      "so_sku": 0, "ht_don": _ht, "th_don": max(0, _sd - _ht),
                                      "so_cu": _cu, "source": "bulk"})
                if not _payloads:
                    st.error("Không có dòng hợp lệ. Kiểm tra định dạng.")
                else:
                    _ok, _add, _upd, _skip, _msg = picklog.log_batches(_payloads)
                    if _ok:
                        st.success(f"✅ Nạp xong: thêm **{_add}** đợt, cập nhật cũ {_upd}, bỏ qua trùng {_skip}. "
                                   "Mở lại bảng 30 ngày để thấy cột Soạn/Cũ cập nhật.")
                        st.cache_data.clear()
                    else:
                        st.error(_msg)
                if _errln:
                    st.warning("⚠️ Dòng SAI định dạng (bỏ qua):\n" + "\n".join(f"• {x}" for x in _errln[:20]))

        with st.expander("📅 Lịch sử nhặt hàng 30 ngày (số đợt · SP mỗi đợt)", expanded=False):
            _all = picklog._read_all() or {}
            _today = (datetime.now(timezone.utc) + timedelta(hours=7)).date()
            _from = (_today - timedelta(days=29)).isoformat()
            _logs = [r for r in _all.get("logs", []) if str(r.get("ngay") or "") >= _from]
            if not _logs:
                st.caption("Chưa có lượt nhặt nào được lưu trong 30 ngày. Bấm **🖨️ In + lưu đợt** để bắt đầu lưu.")
            else:
                from collections import defaultdict as _dd
                _by_day = _dd(list)
                for _r in _logs:
                    _by_day[str(_r.get("ngay"))].append(_r)
                _wd = ["T2", "T3", "T4", "T5", "T6", "T7", "CN"]
                _summ = []
                for _d in sorted(_by_day, reverse=True):
                    _rows = _by_day[_d]
                    try:
                        _dt = date.fromisoformat(_d)
                        _thu, _lbl = _wd[_dt.weekday()], _dt.strftime("%d/%m")
                    except Exception:
                        _thu, _lbl = "", _d
                    _summ.append({"Ngày": _lbl, "Thứ": _thu, "Số đợt": len(_rows),
                                  "Tổng đơn": sum(int(x.get("so_don") or 0) for x in _rows),
                                  "Tổng SP": sum(int(x.get("so_sp") or 0) for x in _rows),
                                  "iso": _d})
                _sdf = pd.DataFrame(_summ)
                st.markdown(f"**{len(_by_day)} ngày** · {int(_sdf['Số đợt'].sum())} đợt · "
                            f"{int(_sdf['Tổng đơn'].sum())} đơn · {int(_sdf['Tổng SP'].sum())} SP")
                render_compact_table(_sdf.drop(columns=["iso"]))
                _sel = st.selectbox(
                    "Xem chi tiết từng đợt của ngày", options=list(range(len(_summ))),
                    format_func=lambda i: f"{_summ[i]['Ngày']} — {_summ[i]['Số đợt']} đợt · {_summ[i]['Tổng SP']} SP",
                    key="pick_hist_day")
                _day_rows = sorted(_by_day[_summ[_sel]["iso"]], key=lambda x: str(x.get("gio") or ""))
                _ddf = pd.DataFrame([{"Đợt": i + 1, "Giờ": r.get("gio", ""),
                                      "Số đơn": r.get("so_don", 0), "Số SP": r.get("so_sp", 0),
                                      "Số SKU": r.get("so_sku", 0), "HT": r.get("ht_don", 0),
                                      "Thường": r.get("th_don", 0)} for i, r in enumerate(_day_rows)])
                render_compact_table(_ddf)

    if picklog.configured() and not _can_edit_pick:
        st.caption("ℹ️ Lịch sử & sửa/xóa phiếu nhặt chỉ dành cho tài khoản **admin/chủ shop**.")

    with st.expander("📄 Hoặc: tạo phiếu từ file Excel (upload thủ công)"):
        _html_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "picking_slip.html")
        with open(_html_path, encoding="utf-8") as _f:
            components.html(_f.read(), height=1300, scrolling=True)
    return


# ════════════════ TRANG LẤY - LƯU TTKH ════════════════
if _page == PAGE_TTKH:
    st.title("📞 Lấy - lưu TTKH")
    st.caption("Lọc đơn chưa có SĐT trong ghi chú SAPO để nhân viên lấy TTKH từ TikTok, dán vào app rồi ghi ngược vào SAPO.")
    st.caption("Phiên bản TTKH: 2026-07-02-ttkh-v4")
    if not credential_present():
        st.warning("⚠️ Trang này cần kết nối Sapo (API LIVE).")
        st.stop()

    def _ttkh_phone_key(raw):
        digits = re.sub(r"\D+", "", str(raw or ""))
        if not digits:
            return ""
        if digits.startswith("00"):
            digits = digits[2:]
        if digits.startswith("84"):
            rest = digits[2:]
            if len(rest) == 9:
                digits = "0" + rest
            elif len(rest) == 10 and rest.startswith("0"):
                digits = rest
        digits = "0" + digits.lstrip("0")
        return digits if len(digits) == 10 else ""

    def _sapo_order_search_url(query):
        q = _ttkh_phone_key(query) or str(query or "").strip()
        return f"https://vitranboutiquehcm.mysapo.net/admin/orders?query={quote_plus(q)}" if q else ""

    def _ttkh_app_search_url(query):
        q = _ttkh_phone_key(query) or str(query or "").strip()
        return f"?page_ttkh=1&ttkh_phone={quote_plus(q)}" if q else ""

    _tabA, _tabB = st.tabs(["📝 Lấy - lưu TTKH (nhập & lưu Sapo)", "🔍 Kiểm tra & dọn khách đã lưu"])

    with _tabB:
        # ── 🔍 KIỂM TRA SÓT KHÁCH: đối chiếu đơn ↔ khách theo SĐT (chắc chắn) ──
        st.markdown("### 🔍 Kiểm tra & dọn khách đã lưu")
        st.caption("Tab này chỉ dùng để sửa dữ liệu khách đã lưu sai/chưa chuẩn trong Sapo. Kết quả quét được lưu lại, tải lại trang vẫn còn.")

        def _cust_cat_title(cat, label):
            base = str(label or cat)
            for token in ("🔴", "🟡", "⚪", "🟠", "— CẦN FIX", "— CẦN KIỂM/SỬA", "— sửa dần"):
                base = base.replace(token, "")
            return re.sub(r"\s+", " ", base).strip(" -")

        def _cust_cat_icon(cat):
            return {
                "sdt_sai": "📞",
                "thieu_ma_tinh": "📍",
                "thieu_ca_2": "📍",
                "khong_dia_chi": "🧊",
                "thieu_sdt": "📞",
                "thieu_ma_phuong": "📍",
                "thieu_ghi_chu": "📝",
            }.get(str(cat or ""), "⚠️")

        # Giữ kết quả quét gần nhất qua tải lại: nếu phiên chưa có thì đọc từ Gist
        if "ttkh_audit" not in st.session_state and picklog.configured():
            try:
                _saved_audit = picklog.read_ttkh_audit()
                if _saved_audit:
                    st.session_state["ttkh_audit"] = _saved_audit
            except Exception:
                pass
        # Mở sẵn khi đang có kết quả quét (để bảng + nút tạo khách luôn hiện, khỏi mở lại sau mỗi lần bấm)
        with st.expander("🔍 Kiểm tra đơn thiếu khách / địa chỉ chưa chuẩn — đối chiếu chắc chắn",
                         expanded=bool(st.session_state.get("ttkh_audit"))):
            st.caption("Quét MỌI đơn: đơn đã ghi SĐT lên đơn nhưng khách CHƯA ĐẠT — **chưa có khách**, HOẶC **khách "
                       "địa chỉ text** (chưa chọn Tỉnh/Quận/Phường) → liệt kê để tạo/sửa. Biết CHẮC không sót.")
            _ac = st.columns([1, 2])
            _audit_days = _ac[0].number_input("Số ngày quét", min_value=7, max_value=365, value=365, step=30,
                                              help="Tối đa 1 năm. Quét càng dài càng lâu (nhiều đơn + có thể chạm rate limit).")
            # Tự quét LẦN ĐẦU (khi chưa có dữ liệu đã lưu) — sau đó lưu Gist, khỏi quét lại
            _auto_first = ("ttkh_audit" not in st.session_state) and \
                          (not st.session_state.get("ttkh_audit_autorun")) and credential_present()
            _btn_scan = _ac[1].button("🔄 Cập nhật (quét lại) — cả năm", key="ttkh_audit_run")
            if _auto_first and not _btn_scan:
                st.info("Lần đầu chưa có dữ liệu — đang tự quét cả năm (mất vài phút, sau đó lưu lại khỏi quét nữa)…")
            if _btn_scan or _auto_first:
                st.session_state["ttkh_audit_autorun"] = True
                st.session_state.pop("ttkh_audit", None)   # xóa kết quả/lỗi cũ ngay
                _prog = st.progress(0.0, text="Bắt đầu…")
                try:
                    _prog.progress(0.02, text="Đang tải danh sách khách hàng (16k+)… ~30 giây")
                    _cores, _good, _cap = load_customer_phone_set()
                    if not _cores:
                        st.session_state["ttkh_audit"] = {"error": "Không lấy được danh sách khách hàng từ Sapo (rate limit 429). Thử lại sau ~1 phút."}
                    else:
                        _fj = make_fetch_json(build_session())

                        def _audit_prog(win_i, win_n, n_seen, n_found):
                            _prog.progress(min(0.05 + 0.95 * win_i / max(win_n, 1), 1.0),
                                           text=f"Đối chiếu tháng {win_i}/{win_n} · đã xét {n_seen} đơn · tìm thấy {n_found} đơn cần xử lý")

                        _missing = L.audit_orders_missing_customer(
                            _fj, _good, days=int(_audit_days), channel_filter="all",
                            all_phone_set=_cores, progress_cb=_audit_prog)
                        st.session_state["ttkh_audit"] = {
                            "missing": _missing, "cap": _cap, "n_suspect": len(_missing), "days": int(_audit_days),
                            "ts": (datetime.now(timezone.utc) + timedelta(hours=7)).strftime("%H:%M %d/%m")}
                        try:      # lưu bền để tải lại vẫn còn (khỏi quét lại)
                            if picklog.configured():
                                picklog.save_ttkh_audit(st.session_state["ttkh_audit"])
                        except Exception:
                            pass
                except Exception as _e:
                    st.session_state["ttkh_audit"] = {"error": str(_e)[:400]}
                _prog.empty()
                st.rerun()

            _audit = st.session_state.get("ttkh_audit")
            if _audit:
                if _audit.get("error"):
                    st.error(f"Lỗi quét: {_audit['error']}")
                else:
                    _mis = _audit.get("missing") or []
                    if _audit.get("cap"):
                        st.warning("Danh sách khách rất lớn, có thể chưa tải hết — kết quả tham khảo, nên quét lại/tăng giới hạn.")
                    if not _mis:
                        st.success(f"✅ Không sót — mọi đơn đã ghi SĐT đều có khách + địa chỉ chuẩn. (Quét {_audit['ts']}, {_audit.get('days','?')} ngày)")
                    else:
                        _list_text = [m for m in _mis if "text" in str(m.get("ly_do", "")).lower()]
                        _list_nocust = [m for m in _mis if m not in _list_text]
                        st.error(f"⚠️ Có {len(_mis)} đơn CHƯA ĐẠT (quét {_audit['ts']}, {_audit.get('days','?')} ngày).")

                        def _mis_addr(info):
                            return ", ".join(str(x).strip() for x in (
                                info.get("address1"), info.get("ward"), info.get("district"), info.get("province")
                            ) if str(x or "").strip())

                        def _mis_df(rows):
                            return pd.DataFrame([{
                                "Mã đơn": m["code"],
                                "Tên": (m.get("info") or {}).get("name", ""),
                                "SĐT": m["phone"],
                                "Địa chỉ": _mis_addr(m.get("info") or {}),
                                "Định dạng": "Mới" if (m.get("info") or {}).get("address_format") == "new" else "Cũ",
                                "Ngày tạo": m["created_on"],
                            } for m in rows])

                        st.markdown(f"**① Có đơn nhưng CHƯA có khách — {len(_list_nocust)} đơn** (cần tạo khách)")
                        if _list_nocust:
                            st.dataframe(_mis_df(_list_nocust), hide_index=True, width="stretch",
                                         column_config={"Địa chỉ": st.column_config.TextColumn("Địa chỉ", width="large")})
                        else:
                            st.caption("— Không có —")
                        st.markdown(f"**② Đã có khách nhưng ĐỊA CHỈ chưa chuẩn (text / thiếu SĐT) — {len(_list_text)} đơn** (cần sửa địa chỉ)")
                        if _list_text:
                            st.dataframe(_mis_df(_list_text), hide_index=True, width="stretch",
                                         column_config={"Địa chỉ": st.column_config.TextColumn("Địa chỉ", width="large")})
                        else:
                            st.caption("— Không có —")
                        if st.session_state.get("ttkh_backfill_msg"):
                            st.success(st.session_state.pop("ttkh_backfill_msg"))
                        _CAP = 60
                        _n_now = min(len(_mis), _CAP)
                        st.caption(f"➡️ Tạo khách **trực tiếp từ dữ liệu đơn** (tên/SĐT/địa chỉ có sẵn), không cần lấy lại TTKH. "
                                   f"Mỗi lần xử lý tối đa {_CAP} đơn để tránh rate limit — bấm lại để tiếp tục (đơn lỗi sẽ tự thử lại lần sau).")
                        if st.button(f"⚙️ Tự động tạo khách từ đơn — xử lý {_n_now} đơn tiếp theo", key="ttkh_backfill"):
                            _batch = _mis[:_CAP]
                            _sess = build_session()
                            _prog = st.progress(0.0, text="Đang tạo khách…")
                            _ok, _fail, _fail_detail, _done_ids = 0, 0, [], []
                            _seen_phones = set()   # tránh tạo trùng SĐT trong cùng lượt (vì bỏ search)

                            def _reason_from_attempts(atts):
                                if not atts:
                                    return "Không tạo được (không rõ)"
                                _last = [str(a) for a in atts[-4:]]
                                if any("429" in a for a in _last):
                                    return "429 rate limit — nghỉ 1 phút rồi thử lại"
                                for a in reversed(_last):
                                    if any(x in a for x in ("40", "50", "Error", "error", "->")):
                                        return a[:180]
                                return _last[-1][:180]

                            _consec_429, _breaker = 0, False
                            for _i, _m in enumerate(_batch):
                                _info = _m.get("info") or {}
                                try:
                                    if not _info.get("phone") or not _info.get("name"):
                                        _fail += 1
                                        _miss = "SĐT" if not _info.get("phone") else "tên"
                                        _fail_detail.append({"Mã đơn": _m["code"], "Lý do": f"Thiếu {_miss} trên đơn"})
                                    elif _info.get("phone") in _seen_phones:
                                        _ok += 1   # cùng SĐT đã tạo ở lượt này → coi như xong
                                        _done_ids.append(str(_m["order_id"]))
                                    else:
                                        # khách địa chỉ text đã tồn tại → KHÔNG skip_search (tìm & cập nhật, tránh trùng);
                                        # khách chưa có → skip_search (tạo nhanh, ít 429)
                                        _is_text = "text" in str(_m.get("ly_do", "")).lower()
                                        _cid, _att = upsert_customer_from_info(_sess, _info, skip_search=(not _is_text),
                                                                               note=f"Backfill từ đơn {_m['code']}")
                                        _is429 = (not _cid) and any("429" in str(a) for a in (_att or []))
                                        if _cid:
                                            _ok += 1
                                            _done_ids.append(str(_m["order_id"]))
                                            _seen_phones.add(_info.get("phone"))
                                            _consec_429 = 0
                                        elif _is429:
                                            _fail += 1
                                            _consec_429 += 1
                                            _fail_detail.append({"Mã đơn": _m["code"], "Lý do": "429 — Sapo đang chặn ghi"})
                                            if _consec_429 >= 4:      # CIRCUIT BREAKER: dừng ngay, không đấm thêm
                                                _breaker = True
                                                _prog.progress((_i + 1) / len(_batch),
                                                               text="⛔ Sapo đang chặn — dừng lại để không bị phạt nặng thêm.")
                                                break
                                        else:
                                            _fail += 1
                                            _consec_429 = 0
                                            _fail_detail.append({"Mã đơn": _m["code"], "Lý do": _reason_from_attempts(_att)})
                                except Exception as _ex:
                                    _fail += 1
                                    _fail_detail.append({"Mã đơn": _m["code"], "Lý do": f"{type(_ex).__name__}: {_ex}"[:180]})
                                _prog.progress((_i + 1) / len(_batch),
                                               text=f"Đã xử lý {_i + 1}/{len(_batch)} — tạo được {_ok}, lỗi {_fail}")
                                time.sleep(1.0)   # giãn nhịp chống 429
                            _done_set = set(_done_ids)
                            _remain = [m for m in _mis if str(m["order_id"]) not in _done_set]
                            st.session_state["ttkh_audit"]["missing"] = _remain
                            try:      # cập nhật kết quả đã lưu (bớt đơn vừa xử lý)
                                if picklog.configured():
                                    picklog.save_ttkh_audit(st.session_state["ttkh_audit"])
                                    if _done_ids:
                                        picklog.update_ttkh_pending(remove_ids=_done_ids)
                            except Exception:
                                pass
                            load_customer_phone_set.clear()
                            load_ttkh_candidates.clear()
                            if _breaker:
                                st.session_state["ttkh_backfill_msg"] = (
                                    f"⛔ Sapo đang CHẶN ghi (rate limit). Đã tạo {_ok} khách rồi DỪNG để không bị phạt nặng thêm. "
                                    f"Còn {len(_remain)} đơn. **Nghỉ 5–10 phút** rồi bấm tạo lại.")
                            else:
                                _bf_time = (datetime.now(timezone.utc) + timedelta(hours=7)).strftime("%H:%M:%S %d/%m/%Y")
                                st.session_state["ttkh_backfill_msg"] = (
                                    f"✅ Đã tạo/cập nhật {_ok} khách (lỗi {_fail}) — hoàn tất lúc **{_bf_time}** (giờ VN). "
                                    f"Còn lại {len(_remain)} đơn cần tạo.")
                            st.session_state["ttkh_backfill_fail"] = _fail_detail
                            st.rerun()

                        if st.session_state.get("ttkh_backfill_fail"):
                            _fd = st.session_state["ttkh_backfill_fail"]
                            with st.expander(f"❌ Chi tiết {len(_fd)} đơn lỗi lượt gần nhất", expanded=True):
                                _n429 = sum(1 for r in _fd if "429" in str(r.get("Lý do")))
                                if _n429:
                                    st.warning(f"{_n429}/{len(_fd)} đơn lỗi do **rate limit 429** (Sapo đang chặn ghi vì hôm nay đã ghi nhiều). "
                                               "Đây KHÔNG phải lỗi dữ liệu — **nghỉ 5–10 phút** rồi bấm tạo lại, các đơn này sẽ vào.")
                                st.dataframe(pd.DataFrame(_fd), hide_index=True, width="stretch")

        # ── 🧹 KHÁCH HÀNG LƯU CHƯA CHUẨN (phân theo nhóm lỗi) ──
        st.divider()
        st.markdown("### 🧹 Khách hàng chưa chuẩn")
        st.caption("Quét toàn bộ khách, gom theo loại lỗi và bấm sửa theo nhóm. App chỉ ghi khi khớp chắc, dòng mơ hồ sẽ để riêng.")
        if "cust_audit" not in st.session_state and picklog.configured():
            try:
                _sc_saved = picklog.read_cust_audit()
                if _sc_saved:
                    st.session_state["cust_audit"] = _sc_saved
            except Exception:
                pass
        if st.button("🔄 Quét khách hàng (cập nhật)", key="cust_audit_run"):
            _keep_blocked = (st.session_state.get("cust_audit") or {}).get("auto_fix_blocked") or []
            st.session_state.pop("cust_audit", None)
            _cp = st.progress(0.0, text="Đang quét khách hàng…")
            try:
                def _cust_prog(page, tot, found):
                    _cp.progress(min(page / 120, 1.0), text=f"Trang {page} · đã xét {tot} khách · lỗi {found}")
                _res = L.audit_customers(make_fetch_json(build_session()), per_cat_keep=10000, progress_cb=_cust_prog)
                if _keep_blocked:
                    _res["auto_fix_blocked"] = _keep_blocked
                st.session_state["cust_audit"] = _res
                if picklog.configured():
                    picklog.save_cust_audit(_res)
            except Exception as _e:
                st.session_state["cust_audit"] = {"error": str(_e)[:300]}
            _cp.empty()
            st.rerun()

        _ca = st.session_state.get("cust_audit")
        if _ca:
            if _ca.get("error"):
                st.error(f"Lỗi quét khách: {_ca['error']}")
            else:
                _audit_version = str(_ca.get("schema_version") or "")
                _current_audit_version = str(getattr(L, "AUDIT_CUSTOMERS_VERSION", "") or "")
                if _current_audit_version and _audit_version != _current_audit_version:
                    st.warning("Kết quả đang hiển thị là bản quét cũ, chưa có logic gom **đơn có SĐT nhưng thiếu ghi chú**. "
                               "Bấm **🔄 Quét khách hàng (cập nhật)** để lấy lại số mới.")
                _counts = _ca.get("counts") or {}
                _tot_bad = sum(_counts.values())
                _order_note_missing = int(_ca.get("order_note_missing") or 0)
                _dash = st.columns(4)
                _dash[0].metric("Chưa chuẩn", f"{_tot_bad:,}")
                _dash[1].metric("Đã quét", f"{_ca.get('total','?')}")
                _dash[2].metric("Thiếu ghi chú", f"{_order_note_missing:,}")
                _dash[3].metric("Lần quét", str(_ca.get("ts", "?")))
                if _ca.get("hit_cap"):
                    st.warning("Có thể chưa quét hết (chạm giới hạn/429) — quét lại nếu cần.")

                # 📥 Nút tải Excel (gộp mọi nhóm; SĐT sai đánh dấu)
                _all_rows = []
                for _cat, _label in L.CUST_ERR_LABELS.items():
                    for m in (_ca.get("samples") or {}).get(_cat) or []:
                        _all_rows.append({"Nhóm": _label, "Ngày": m.get("ngay"), "Mã KH": m.get("id"), "Tên": m.get("ten"),
                                          "SĐT": m.get("sdt"), "SĐT sai?": "SAI" if m.get("sdt_xau") else "",
                                          "Địa chỉ": m.get("dia_chi")})
                if _all_rows:
                    import io as _io
                    try:
                        _buf = _io.BytesIO()
                        pd.DataFrame(_all_rows).to_excel(_buf, index=False)
                        st.download_button("📥 Tải Excel (.xlsx)", _buf.getvalue(),
                                           file_name="khach_chua_chuan.xlsx",
                                           mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
                    except Exception:      # phòng khi openpyxl chưa cài → tạm CSV
                        _csv = pd.DataFrame(_all_rows).to_csv(index=False).encode("utf-8-sig")
                        st.download_button("📥 Tải danh sách (CSV)", _csv,
                                           file_name="khach_chua_chuan.csv", mime="text/csv")
                    st.caption("File gồm tối đa 10.000 dòng/nhóm. Cần TOÀN BỘ thì dùng script `scan_customers.py`.")

                _fix_cats = list(CAF.FIXABLE_CATEGORIES)
                _blocked_rows = _ca.get("auto_fix_blocked") or []
                if isinstance(_blocked_rows, dict):
                    _blocked_rows = list(_blocked_rows.values())
                def _blocked_row_code(r):
                    code = str((r or {}).get("Mã lỗi") or (r or {}).get("reason") or "").strip()
                    if code:
                        return code
                    raw = str((r or {}).get("Lý do / cách xử lý") or "").lower()
                    if "address_unresolved" in raw or "chưa khớp chắc" in raw:
                        return "address_unresolved"
                    if "address_conflict" in raw or "mâu thuẫn" in raw:
                        return "address_conflict"
                    return ""

                def _blocked_still_current(r):
                    code = _blocked_row_code(r)
                    if code == "address_unresolved":
                        return str((r or {}).get("fix_version") or "") == str(getattr(CAF, "FIX_VERSION", ""))
                    return True

                _stale_blocked_rows = [r for r in _blocked_rows if not _blocked_still_current(r)]
                if _stale_blocked_rows:
                    _blocked_rows = [r for r in _blocked_rows if _blocked_still_current(r)]
                    _ca["auto_fix_blocked"] = _blocked_rows
                    st.session_state["cust_audit"] = _ca
                    try:
                        if picklog.configured():
                            picklog.save_cust_audit(_ca)
                    except Exception:
                        pass
                    st.info(f"Đã mở lại {len(_stale_blocked_rows):,} khách lỗi địa chỉ từ rule cũ để thử bằng rule mới.")
                _blocked_by_id = {
                    str(r.get("Mã KH") or r.get("id") or "").strip(): r
                    for r in _blocked_rows
                    if str(r.get("Mã KH") or r.get("id") or "").strip()
                }
                _blocked_ids = set(_blocked_by_id)
                _fix_rows = []
                for _cat in _fix_cats:
                    for _m in (_ca.get("samples") or {}).get(_cat) or []:
                        _mid = str(_m.get("id") or "").strip()
                        if _mid and _mid not in _blocked_ids:
                            _fix_rows.append({"cat": _cat, **_m})
                _pending_fix_cat = st.session_state.pop("cust_addr_fix_action_cat", "")
                _pending_retry_ids = {
                    str(x).strip()
                    for x in (st.session_state.pop("cust_addr_fix_retry_ids", []) or [])
                    if str(x).strip()
                }
                _retry_rows = []
                if _pending_retry_ids:
                    for _bid in _pending_retry_ids:
                        _br = _blocked_by_id.get(_bid) or {}
                        _bcat = str(_br.get("cat") or "").strip()
                        if _bcat in _fix_cats:
                            _retry_rows.append({
                                "cat": _bcat,
                                "id": _bid,
                                "ten": _br.get("Tên") or "",
                                "sdt": _br.get("SĐT") or "",
                                "dia_chi": _br.get("Địa chỉ") or "",
                            })
                if _pending_retry_ids:
                    _run_fix_rows = _retry_rows
                elif _pending_fix_cat:
                    _run_fix_rows = [r for r in _fix_rows if r.get("cat") == _pending_fix_cat]
                else:
                    _run_fix_rows = _fix_rows
                _total_fixable = (
                    sum(int(_counts.get(_cat, 0) or 0) for _cat in _fix_cats)
                    + int(_counts.get("thieu_ghi_chu", 0) or 0)
                )
                st.markdown("#### 🛠️ Sửa theo nhóm lỗi")
                _fx = st.columns([1.1, 1.1, 1.1, 1.2, 2.2])
                _fx[0].metric("Có thể sửa", f"{_total_fixable:,}")
                _fx[1].metric("Chờ sửa", f"{len(_fix_rows):,}")
                _fx[2].metric("Cần xem lại", f"{len(_blocked_ids):,}")
                _batch_n = 60
                _fx[3].metric("Mỗi lượt", f"{_batch_n}")
                _fx[4].caption("Bấm sửa theo nhóm. Nếu Sapo trả 429 liên tiếp, app tự dừng; nghỉ 5-10 phút rồi bấm tiếp.")

                def _cust_fix_reason_vi(code, detail=""):
                    text = {
                        "no_address": "Không có địa chỉ để suy ra tỉnh/phường.",
                        "address_unresolved": "Chưa khớp chắc tỉnh/quận/phường từ text địa chỉ.",
                        "address_conflict": "Địa chỉ có dấu hiệu mâu thuẫn phường/xã.",
                        "no_valid_phone": "Không có SĐT hợp lệ để lưu vào địa chỉ.",
                        "phone_conflict": "SĐT khách và SĐT địa chỉ mâu thuẫn sau khi chuẩn hóa.",
                        "unsupported_category": "Nhóm lỗi này chưa bật sửa tự động.",
                        "bad_customer": "Dữ liệu khách không hợp lệ.",
                        "customer_not_found": "Không đọc được khách từ Sapo.",
                        "rate_limited": "Sapo đang chặn ghi 429, nghỉ 5-10 phút rồi bấm tiếp.",
                        "auth_failed": "Phiên/credential Sapo hết hạn hoặc không đủ quyền.",
                        "verify_failed": "Đã gửi nhưng đọc lại chưa thấy đủ mã vùng.",
                        "missing_customer_id": "Thiếu mã khách hàng.",
                    }.get(str(code or ""), str(code or "Không rõ lỗi"))
                    return f"{text} ({detail})" if detail else text

                def _cust_fix_judgement(code, reason_text=""):
                    raw = f"{code or ''} {reason_text or ''}".lower()
                    if any(x in raw for x in ("address_unresolved", "chưa khớp chắc")):
                        return "Có thể fix code nếu địa chỉ có đủ tỉnh/quận/phường trong text."
                    if any(x in raw for x in ("address_conflict", "mâu thuẫn")):
                        return "Không auto an toàn; cần xem tay hoặc thêm rule sau khi xác nhận đúng."
                    if any(x in raw for x in ("verify_failed", "đọc lại chưa thấy")):
                        return "Có thể fix code/endpoint ghi Sapo, cần xem phản hồi và payload."
                    if any(x in raw for x in ("no_address", "không có địa chỉ")):
                        return "Không fix bằng code; thiếu địa chỉ gốc."
                    if any(x in raw for x in ("no_valid_phone", "không có sđt", "không có sdt")):
                        return "Không fix bằng code; thiếu SĐT hợp lệ."
                    if any(x in raw for x in ("phone_conflict", "mâu thuẫn sđt", "mâu thuẫn sdt")):
                        return "Không auto an toàn; cần xem tay vì có nhiều SĐT khác nhau."
                    if any(x in raw for x in ("rate_limited", "429")):
                        return "Tạm thời do Sapo chặn; chờ rồi chạy lại, không phải lỗi rule."
                    if any(x in raw for x in ("auth_failed", "401", "403")):
                        return "Lỗi phiên/credential Sapo; cần cập nhật đăng nhập."
                    if any(x in raw for x in ("customer_not_found", "không đọc được khách")):
                        return "Cần kiểm tra khách còn tồn tại trong Sapo."
                    return "Cần xem chi tiết; chưa đủ dữ liệu để kết luận."

                def _cust_fix_reason_code_from_text(reason_text=""):
                    raw = str(reason_text or "").lower()
                    if "address_unresolved" in raw or "chưa khớp chắc" in raw:
                        return "address_unresolved"
                    if "address_conflict" in raw or "mâu thuẫn" in raw:
                        return "address_conflict"
                    if "verify_failed" in raw or "đọc lại chưa thấy" in raw:
                        return "verify_failed"
                    if "no_address" in raw or "không có địa chỉ" in raw:
                        return "no_address"
                    if "no_valid_phone" in raw or "không có sđt" in raw or "không có sdt" in raw:
                        return "no_valid_phone"
                    if "phone_conflict" in raw or "mâu thuẫn sđt" in raw or "mâu thuẫn sdt" in raw:
                        return "phone_conflict"
                    if "rate_limited" in raw or "429" in raw:
                        return "rate_limited"
                    if "auth_failed" in raw or "401" in raw or "403" in raw:
                        return "auth_failed"
                    if "customer_not_found" in raw or "không đọc được khách" in raw:
                        return "customer_not_found"
                    return ""

                def _cust_fix_attempt_reason(result):
                    _attempts = [str(x) for x in (result or {}).get("attempts") or []]
                    if any("429" in x for x in _attempts):
                        return "rate_limited"
                    if any("401" in x or "403" in x for x in _attempts):
                        return "auth_failed"
                    return (result or {}).get("reason") or "verify_failed"

                def _order_code_from_order(order):
                    return str(
                        (order or {}).get("source_identifier")
                        or (order or {}).get("name")
                        or (order or {}).get("code")
                        or (order or {}).get("id")
                        or ""
                    ).strip()

                def _note_fix_reason_vi(code, detail=""):
                    text = {
                        "missing_phone": "Thiếu SĐT để tìm đơn/khách.",
                        "customer_not_found": "Không tìm thấy khách theo SĐT.",
                        "customer_ambiguous": "Một SĐT ra nhiều khách, không tự chọn.",
                        "order_not_found": "Không tìm thấy đơn theo SĐT.",
                        "order_ambiguous": "Một SĐT ra nhiều đơn, cần xem tay để chọn đúng mã đơn.",
                        "missing_customer_id": "Thiếu mã khách hàng.",
                        "rate_limited": "Sapo đang chặn ghi 429, nghỉ 5-10 phút rồi bấm tiếp.",
                        "auth_failed": "Phiên/credential Sapo hết hạn hoặc không đủ quyền.",
                        "verify_failed": "Đã gửi nhưng đọc lại chưa thấy đủ ghi chú.",
                    }.get(str(code or ""), str(code or "Không rõ lỗi"))
                    return f"{text} ({detail})" if detail else text

                def _customer_ids_by_phone(session, phone, known_customer_id=""):
                    ids = []
                    if str(known_customer_id or "").strip():
                        ids.append(str(known_customer_id).strip())
                    found = []
                    for query in dict.fromkeys([phone, _ttkh_phone_key(phone), _ttkh_phone_key(phone)[-9:]]):
                        if not query:
                            continue
                        try:
                            resp = session.get(
                                "https://vitranboutiquehcm.mysapo.net/admin/customers.json",
                                params={"query": query, "limit": 10},
                                timeout=30,
                            )
                            if resp.status_code >= 400:
                                continue
                            for customer in (resp.json().get("customers") or resp.json().get("data") or []):
                                cid = str((customer or {}).get("id") or "").strip()
                                if cid:
                                    found.append(cid)
                        except Exception:
                            pass
                    for cid in found:
                        if cid not in ids:
                            ids.append(cid)
                    return ids

                def _fix_missing_note_rows(rows):
                    _sess = build_session()
                    _batch = list(rows or [])[:int(_batch_n)]
                    _prog = st.progress(0.0, text="Đang ghi chú mã đơn…")
                    _results, _done_keys, _blocked = [], [], []

                    for _i, _row in enumerate(_batch, start=1):
                        _row_type = str(_row.get("row_type") or "customer")
                        _phone = _ttkh_phone_key(_row.get("sdt") or "")
                        _customer_id = str(_row.get("id") or "").strip() if _row_type != "order" else ""
                        _order_id = str(_row.get("order_id") or _row.get("id") or "").strip() if _row_type == "order" else ""
                        _order_code = str(_row.get("order_code") or "").strip()
                        _base = {
                            "Nhóm": L.CUST_ERR_LABELS.get("thieu_ghi_chu", "Thiếu ghi chú mã đơn"),
                            "Loại": "Đơn" if _row_type == "order" else "Khách",
                            "Mã": _order_code or _customer_id or _order_id,
                            "Mã KH": _customer_id,
                            "Tên": _row.get("ten") or "",
                            "SĐT": _phone or (_row.get("sdt") or ""),
                            "Link Sapo": (
                                f"https://vitranboutiquehcm.mysapo.net/admin/orders/{_order_id}"
                                if _row_type == "order" and _order_id
                                else f"https://vitranboutiquehcm.mysapo.net/admin/customers/{_customer_id}" if _customer_id else ""
                            ),
                        }
                        try:
                            if not _phone:
                                _code = "missing_phone"
                                _reason = _note_fix_reason_vi(_code)
                                _results.append({**_base, "Kết quả": "Bỏ qua", "Mã lỗi": _code, "Lý do / cách xử lý": _reason})
                                _blocked.append({**_base, "Kết quả": "Bỏ qua", "Mã lỗi": _code, "Lý do / cách xử lý": _reason, "cat": "thieu_ghi_chu"})
                                continue

                            if _row_type == "order":
                                _customer_ids = _customer_ids_by_phone(_sess, _phone)
                                if not _customer_ids:
                                    _code = "customer_not_found"
                                    _reason = _note_fix_reason_vi(_code)
                                    _results.append({**_base, "Kết quả": "Bỏ qua", "Mã lỗi": _code, "Lý do / cách xử lý": _reason})
                                    _blocked.append({**_base, "Kết quả": "Bỏ qua", "Mã lỗi": _code, "Lý do / cách xử lý": _reason, "cat": "thieu_ghi_chu"})
                                    continue
                                if len(set(_customer_ids)) > 1:
                                    _code = "customer_ambiguous"
                                    _reason = _note_fix_reason_vi(_code, ", ".join(_customer_ids[:5]))
                                    _results.append({**_base, "Kết quả": "Bỏ qua", "Mã lỗi": _code, "Lý do / cách xử lý": _reason})
                                    _blocked.append({**_base, "Kết quả": "Bỏ qua", "Mã lỗi": _code, "Lý do / cách xử lý": _reason, "cat": "thieu_ghi_chu"})
                                    continue
                                _customer_id = _customer_ids[0]
                                if not _order_code and _order_id:
                                    try:
                                        _order_code = _order_code_from_order(L.find_order_by_code(make_fetch_json(_sess), _order_id, days=120) or {})
                                    except Exception:
                                        pass
                                if not _order_code:
                                    _order_code = _order_id
                            else:
                                _orders, _attempts = find_orders_by_phone(_sess, _phone, limit=20)
                                if not _orders:
                                    _code = "order_not_found"
                                    _reason = _note_fix_reason_vi(_code, "; ".join(_attempts[-3:])[:180])
                                    _results.append({**_base, "Kết quả": "Bỏ qua", "Mã lỗi": _code, "Lý do / cách xử lý": _reason})
                                    _blocked.append({**_base, "Kết quả": "Bỏ qua", "Mã lỗi": _code, "Lý do / cách xử lý": _reason, "cat": "thieu_ghi_chu"})
                                    continue
                                codes = [c for c in dict.fromkeys(_order_code_from_order(o) for o in _orders) if c]
                                if len(codes) != 1:
                                    _code = "order_ambiguous"
                                    _reason = _note_fix_reason_vi(_code, ", ".join(codes[:5]))
                                    _results.append({**_base, "Kết quả": "Bỏ qua", "Mã lỗi": _code, "Lý do / cách xử lý": _reason})
                                    _blocked.append({**_base, "Kết quả": "Bỏ qua", "Mã lỗi": _code, "Lý do / cách xử lý": _reason, "cat": "thieu_ghi_chu"})
                                    continue
                                _order_code = codes[0]

                            _lines = []
                            if _phone:
                                _lines.append(f"sdt: {_phone}")
                            if _order_code:
                                _lines.append(f"đơn: {_order_code}")
                            _saved = update_customer_note_lines(_sess, _customer_id, _lines)
                            if _saved.get("ok"):
                                _done_keys.append(str(_row.get("id") or _row.get("order_id") or ""))
                                _results.append({**_base, "Mã KH": _customer_id, "Mã đơn": _order_code, "Kết quả": "Đã ghi chú", "Mã lỗi": "", "Lý do / cách xử lý": "Đã bổ sung sdt/đơn vào ghi chú khách."})
                            else:
                                _code = _cust_fix_attempt_reason(_saved)
                                _reason = _note_fix_reason_vi(_code, "; ".join([str(x) for x in (_saved.get("attempts") or [])][-3:])[:180])
                                _results.append({**_base, "Mã KH": _customer_id, "Mã đơn": _order_code, "Kết quả": "Lỗi ghi Sapo", "Mã lỗi": _code, "Lý do / cách xử lý": _reason})
                                if _code not in {"rate_limited", "auth_failed"}:
                                    _blocked.append({**_base, "Mã KH": _customer_id, "Mã đơn": _order_code, "Kết quả": "Lỗi ghi Sapo", "Mã lỗi": _code, "Lý do / cách xử lý": _reason, "cat": "thieu_ghi_chu"})
                        except Exception as _ex:
                            _reason = f"{type(_ex).__name__}: {_ex}"[:260]
                            _results.append({**_base, "Kết quả": "Lỗi app/Sapo", "Mã lỗi": "exception", "Lý do / cách xử lý": _reason})
                            _blocked.append({**_base, "Kết quả": "Lỗi app/Sapo", "Mã lỗi": "exception", "Lý do / cách xử lý": _reason, "cat": "thieu_ghi_chu"})
                        _prog.progress(_i / max(len(_batch), 1), text=f"Đã xử lý {_i}/{len(_batch)} · ghi được {sum(1 for x in _results if x.get('Kết quả') == 'Đã ghi chú')}")
                        time.sleep(0.5)
                    _prog.empty()

                    done_set = set(_done_keys)
                    if done_set or _blocked:
                        old = (_ca.get("samples") or {}).get("thieu_ghi_chu") or []
                        (_ca.setdefault("samples", {}))["thieu_ghi_chu"] = [
                            m for m in old if str(m.get("id") or m.get("order_id") or "") not in done_set
                        ]
                        _counts["thieu_ghi_chu"] = max(int(_counts.get("thieu_ghi_chu", 0) or 0) - len(done_set), 0)
                        _ca["counts"] = _counts
                        if _blocked:
                            _existing_block = list(_ca.get("auto_fix_blocked") or [])
                            _existing_block.extend(_blocked)
                            _ca["auto_fix_blocked"] = _existing_block
                        st.session_state["cust_audit"] = _ca
                        try:
                            if picklog.configured():
                                picklog.save_cust_audit(_ca)
                        except Exception:
                            pass
                    st.session_state["cust_addr_fix_result"] = {
                        "ts": (datetime.now(timezone.utc) + timedelta(hours=7)).strftime("%H:%M:%S %d/%m/%Y"),
                        "rows": _results,
                        "stopped_429": False,
                    }

                if _pending_fix_cat:
                    st.info(f"Đang chạy sửa nhóm: **{L.CUST_ERR_LABELS.get(_pending_fix_cat, _pending_fix_cat)}**")
                if _pending_retry_ids:
                    st.info(f"Đang thử sửa lại **{len(_retry_rows):,} khách đã để qua bên** bằng rule hiện tại.")
                if st.button(f"🛠️ Sửa tất cả nhóm đang sửa được — xử lý {min(len(_fix_rows), int(_batch_n))} khách",
                             key="cust_addr_fix_run", use_container_width=True) or bool(_pending_fix_cat) or bool(_pending_retry_ids):
                    if not _run_fix_rows:
                        st.info("Không có khách nào trong nhóm khả thi để xử lý.")
                    else:
                        _batch = _run_fix_rows[:int(_batch_n)]
                        _sess = build_session()
                        _prog = st.progress(0.0, text="Đang chuẩn bị sửa địa chỉ khách…")
                        _results, _done_ids, _new_blocked, _success_by_cat = [], [], [], {}
                        _consec_429, _stopped_429 = 0, False

                        def _block_customer(_base, cat, ket_qua, reason, code="", address=""):
                            return {
                                "Nhóm": _base.get("Nhóm") or L.CUST_ERR_LABELS.get(cat, cat),
                                "Mã KH": _base.get("Mã KH") or "",
                                "Tên": _base.get("Tên") or "",
                                "SĐT": _base.get("SĐT") or "",
                                "Địa chỉ": address or _base.get("Địa chỉ") or "",
                                "Kết quả": ket_qua,
                                "Mã lỗi": code or "",
                                "Lý do / cách xử lý": reason,
                                "Đánh giá fix code": _cust_fix_judgement(code, reason),
                                "Link Sapo": _base.get("Link Sapo") or "",
                                "cat": cat,
                                "fix_version": getattr(CAF, "FIX_VERSION", ""),
                                "ts": (datetime.now(timezone.utc) + timedelta(hours=7)).strftime("%H:%M:%S %d/%m/%Y"),
                            }

                        for _i, _row in enumerate(_batch, start=1):
                            _cid = str(_row.get("id") or "").strip()
                            _cat = str(_row.get("cat") or "")
                            _label = L.CUST_ERR_LABELS.get(_cat, _cat)
                            _base = {
                                "Nhóm": _label,
                                "Mã KH": _cid,
                                "Tên": _row.get("ten") or "",
                                "SĐT": _row.get("sdt") or "",
                                "Địa chỉ": _row.get("dia_chi") or "",
                                "Link Sapo": f"https://vitranboutiquehcm.mysapo.net/admin/customers/{_cid}" if _cid else "",
                            }
                            try:
                                _cust = get_customer(_sess, _cid)
                                _prep = CAF.customer_fix_info(_cust, _cat)
                                if not _prep.get("ok"):
                                    _reason_code = _prep.get("reason") or ""
                                    _reason_text = _cust_fix_reason_vi(
                                        _reason_code,
                                        _prep.get("conflict") or "",
                                    )
                                    _source_addr = _prep.get("source_address") or _base.get("Địa chỉ") or ""
                                    _judge = _cust_fix_judgement(_reason_code, _reason_text)
                                    _results.append({
                                        **_base,
                                        "Kết quả": "Bỏ qua",
                                        "Loại địa chỉ": "",
                                        "Mã tỉnh": "",
                                        "Mã quận": "",
                                        "Mã phường": "",
                                        "Mã lỗi": _reason_code,
                                        "Lý do / cách xử lý": _reason_text,
                                        "Đánh giá fix code": _judge,
                                        "Địa chỉ": _source_addr,
                                    })
                                    _new_blocked.append(_block_customer(_base, _cat, "Bỏ qua", _reason_text, _reason_code, _source_addr))
                                    _consec_429 = 0
                                else:
                                    _info = _prep["info"]
                                    _saved = update_customer_address_from_info(_sess, _cid, _info)
                                    if _saved.get("ok"):
                                        _done_ids.append(_cid)
                                        _success_by_cat[_cat] = _success_by_cat.get(_cat, 0) + 1
                                        _is_phone_only = bool(_info.get("phone_only"))
                                        _results.append({
                                            **_base,
                                            "Kết quả": "Đã sửa",
                                            "Loại địa chỉ": "Chỉ SĐT" if _is_phone_only else ("Mới" if _info.get("address_format") == "new" else "Cũ"),
                                            "Mã tỉnh": _info.get("province_code") or "",
                                            "Mã quận": "" if _is_phone_only or _info.get("address_format") == "new" else (_info.get("district_code") or ""),
                                            "Mã phường": _info.get("ward_code") or "",
                                            "Mã lỗi": "",
                                            "Lý do / cách xử lý": "Đã chuẩn hóa SĐT chính của khách." if _is_phone_only else f"{_info.get('ward') or ''}, {_info.get('district') or ''}, {_info.get('province') or ''}".strip(", "),
                                            "Đánh giá fix code": "Đã sửa được bằng rule hiện tại.",
                                            "Địa chỉ": _info.get("address1") or _base.get("Địa chỉ") or "",
                                        })
                                        _consec_429 = 0
                                    else:
                                        _reason = _cust_fix_attempt_reason(_saved)
                                        _reason_text = _cust_fix_reason_vi(_reason)
                                        _judge = _cust_fix_judgement(_reason, _reason_text)
                                        _results.append({
                                            **_base,
                                            "Kết quả": "Lỗi ghi Sapo",
                                            "Loại địa chỉ": "Chỉ SĐT" if _info.get("phone_only") else ("Mới" if _info.get("address_format") == "new" else "Cũ"),
                                            "Mã tỉnh": _info.get("province_code") or "",
                                            "Mã quận": "" if _info.get("phone_only") or _info.get("address_format") == "new" else (_info.get("district_code") or ""),
                                            "Mã phường": _info.get("ward_code") or "",
                                            "Mã lỗi": _reason,
                                            "Lý do / cách xử lý": _reason_text,
                                            "Đánh giá fix code": _judge,
                                            "Địa chỉ": _info.get("address1") or _base.get("Địa chỉ") or "",
                                        })
                                        if _reason not in {"rate_limited", "auth_failed"}:
                                            _new_blocked.append(_block_customer(_base, _cat, "Lỗi ghi Sapo", _reason_text, _reason, _info.get("address1") or ""))
                                        _consec_429 = _consec_429 + 1 if _reason == "rate_limited" else 0
                                        if _consec_429 >= 3:
                                            _stopped_429 = True
                                            break
                            except Exception as _ex:
                                _reason_text = f"{type(_ex).__name__}: {_ex}"[:260]
                                _judge = _cust_fix_judgement("exception", _reason_text)
                                _results.append({
                                    **_base,
                                    "Kết quả": "Lỗi app/Sapo",
                                    "Loại địa chỉ": "",
                                    "Mã tỉnh": "",
                                    "Mã quận": "",
                                    "Mã phường": "",
                                    "Mã lỗi": "exception",
                                    "Lý do / cách xử lý": _reason_text,
                                    "Đánh giá fix code": _judge,
                                })
                                _new_blocked.append(_block_customer(_base, _cat, "Lỗi app/Sapo", _reason_text, "exception"))
                                _consec_429 = 0
                            _prog.progress(_i / max(len(_batch), 1),
                                           text=f"Đã xử lý {_i}/{len(_batch)} · sửa được {len(_done_ids)} khách")
                            time.sleep(0.7)
                        _prog.empty()

                        if _done_ids or _new_blocked:
                            _done_set = set(_done_ids)
                            for _cat in _fix_cats:
                                _old = ((_ca.get("samples") or {}).get(_cat) or [])
                                (_ca.setdefault("samples", {}))[_cat] = [
                                    _m for _m in _old if str(_m.get("id") or "") not in _done_set
                                ]
                            for _cat, _n_ok_cat in _success_by_cat.items():
                                _counts[_cat] = max(int(_counts.get(_cat, 0) or 0) - int(_n_ok_cat), 0)
                            _ca["counts"] = _counts
                            _merged_blocked = {
                                _bid: _brow
                                for _bid, _brow in dict(_blocked_by_id).items()
                                if _bid not in _done_set
                            }
                            for _row_block in _new_blocked:
                                _bid = str(_row_block.get("Mã KH") or "").strip()
                                if _bid and _bid not in _done_set:
                                    _merged_blocked[_bid] = _row_block
                            _ca["auto_fix_blocked"] = list(_merged_blocked.values())
                            _blocked_by_id = _merged_blocked
                            _blocked_ids = set(_blocked_by_id)
                            st.session_state["cust_audit"] = _ca
                            try:
                                if picklog.configured():
                                    picklog.save_cust_audit(_ca)
                            except Exception:
                                pass
                        _now_fix = (datetime.now(timezone.utc) + timedelta(hours=7)).strftime("%H:%M:%S %d/%m/%Y")
                        st.session_state["cust_addr_fix_result"] = {
                            "ts": _now_fix,
                            "rows": _results,
                            "stopped_429": _stopped_429,
                        }

                _last_cust_fix = st.session_state.get("cust_addr_fix_result")
                if _last_cust_fix:
                    _fr = _last_cust_fix.get("rows") or []
                    _ok = sum(1 for r in _fr if r.get("Kết quả") in {"Đã sửa", "Đã ghi chú"})
                    _skip = sum(1 for r in _fr if r.get("Kết quả") == "Bỏ qua")
                    _fail = len(_fr) - _ok - _skip
                    if _last_cust_fix.get("stopped_429"):
                        st.warning(f"Đợt xử lý gần nhất ({_last_cust_fix.get('ts')}): thành công {_ok}, bỏ qua {_skip}, lỗi {_fail}. "
                                   "Đã dừng sớm vì Sapo trả 429 liên tiếp, nghỉ 5-10 phút rồi bấm tiếp.")
                    elif _fail or _skip:
                        st.warning(f"Đợt xử lý gần nhất ({_last_cust_fix.get('ts')}): thành công {_ok}, bỏ qua {_skip}, lỗi {_fail}. "
                                   "Các dòng bỏ qua là dòng chưa đủ chắc để auto sửa.")
                    else:
                        st.success(f"Đợt xử lý gần nhất ({_last_cust_fix.get('ts')}): thành công {_ok}/{len(_fr)} dòng.")
                    _detail_title = (
                        f"Chi tiết kết quả xử lý tự động gần nhất — {len(_fr)} xử lý · "
                        f"{_ok} thành công · {_skip + _fail} chưa xong"
                    )
                    with st.expander(_detail_title, expanded=bool(_skip or _fail)):
                        if _fr:
                            _show_cols = [
                                "Nhóm", "Loại", "Mã", "Mã KH", "Mã đơn", "Tên", "SĐT", "Kết quả", "Loại địa chỉ",
                                "Mã tỉnh", "Mã quận", "Mã phường", "Mã lỗi", "Đánh giá fix code",
                                "Lý do / cách xử lý", "Địa chỉ", "Link Sapo",
                            ]
                            _df_fr = pd.DataFrame(_fr)
                            if not _df_fr.empty:
                                if "Mã lỗi" not in _df_fr.columns:
                                    _df_fr["Mã lỗi"] = ""
                                if "Đánh giá fix code" not in _df_fr.columns:
                                    _df_fr["Đánh giá fix code"] = _df_fr.apply(
                                        lambda r: _cust_fix_judgement(r.get("Mã lỗi"), r.get("Lý do / cách xử lý")),
                                        axis=1,
                                    )
                            st.dataframe(
                                _df_fr[[c for c in _show_cols if c in _df_fr.columns]],
                                hide_index=True,
                                width="stretch",
                                column_config={
                                    "Link Sapo": st.column_config.LinkColumn("Link Sapo", display_text="Mở"),
                                    "Lý do / cách xử lý": st.column_config.TextColumn(width="large"),
                                    "Đánh giá fix code": st.column_config.TextColumn(width="large"),
                                    "Địa chỉ": st.column_config.TextColumn(width="large"),
                                },
                            )

                _blocked_rows = _ca.get("auto_fix_blocked") or []
                if isinstance(_blocked_rows, dict):
                    _blocked_rows = list(_blocked_rows.values())
                if _blocked_rows:
                    _retryable_blocked = [
                        r for r in _blocked_rows
                        if str((r or {}).get("cat") or "").strip() in _fix_cats
                    ]
                    _bc = st.columns([1.2, 1.2, 1.8, 2.4])
                    _bc[0].metric("Cần xem lại", f"{len(_blocked_rows):,}")
                    _bc[1].caption("Các khách này không tự chạy lại trong lượt sau.")
                    if _bc[2].button(
                        f"🛠️ Thử sửa {min(len(_retryable_blocked), int(_batch_n))} khách cần xem lại",
                        key="cust_addr_fix_retry_blocked",
                        use_container_width=True,
                        disabled=not bool(_retryable_blocked),
                    ):
                        st.session_state["cust_addr_fix_retry_ids"] = [
                            str((r or {}).get("Mã KH") or (r or {}).get("id") or "").strip()
                            for r in _retryable_blocked[:int(_batch_n)]
                            if str((r or {}).get("Mã KH") or (r or {}).get("id") or "").strip()
                        ]
                        st.rerun()
                    if _bc[3].button("🔁 Mở lại toàn bộ để chạy từ đầu", key="cust_addr_fix_unblock", use_container_width=True):
                        _ca["auto_fix_blocked"] = []
                        st.session_state["cust_audit"] = _ca
                        try:
                            if picklog.configured():
                                picklog.save_cust_audit(_ca)
                        except Exception:
                            pass
                        st.rerun()
                    with st.expander(f"Khách cần xem lại — {len(_blocked_rows):,} khách"):
                        _sample_by_id = {}
                        for _items in (_ca.get("samples") or {}).values():
                            for _m in (_items or []):
                                _sid = str(_m.get("id") or _m.get("Mã KH") or "").strip()
                                if _sid:
                                    _sample_by_id[_sid] = _m
                        _blocked_enriched = []
                        for _r in _blocked_rows:
                            _rr = dict(_r or {})
                            _sid = str(_rr.get("Mã KH") or _rr.get("id") or "").strip()
                            _sample = _sample_by_id.get(_sid) or {}
                            if not str(_rr.get("Địa chỉ") or "").strip():
                                _rr["Địa chỉ"] = _sample.get("dia_chi") or _sample.get("Địa chỉ") or ""
                            if not str(_rr.get("Mã lỗi") or "").strip():
                                _rr["Mã lỗi"] = _cust_fix_reason_code_from_text(_rr.get("Lý do / cách xử lý"))
                            if not str(_rr.get("Đánh giá fix code") or "").strip():
                                _rr["Đánh giá fix code"] = _cust_fix_judgement(_rr.get("Mã lỗi"), _rr.get("Lý do / cách xử lý"))
                            _blocked_enriched.append(_rr)
                        _df_blk = pd.DataFrame(_blocked_enriched)
                        if not _df_blk.empty:
                            if "Mã lỗi" not in _df_blk.columns:
                                _df_blk["Mã lỗi"] = ""
                            if "Đánh giá fix code" not in _df_blk.columns:
                                _df_blk["Đánh giá fix code"] = _df_blk.apply(
                                    lambda r: _cust_fix_judgement(r.get("Mã lỗi"), r.get("Lý do / cách xử lý")),
                                    axis=1,
                                )
                        _can_code_fix = 0
                        _manual_fix = 0
                        if not _df_blk.empty and "Đánh giá fix code" in _df_blk.columns:
                            _can_code_fix = int(_df_blk["Đánh giá fix code"].astype(str).str.contains("Có thể fix code", case=False, na=False).sum())
                            _manual_fix = len(_df_blk) - _can_code_fix
                            st.caption(f"Đọc lỗi nhanh: {_can_code_fix:,} khách có khả năng viết thêm rule/code; {_manual_fix:,} khách cần xem tay/thiếu dữ liệu/không nên auto.")
                        _blk_cols = ["Nhóm", "Mã KH", "Tên", "SĐT", "Kết quả", "Mã lỗi", "Địa chỉ",
                                     "Lý do / cách xử lý", "Đánh giá fix code", "fix_version", "Link Sapo", "ts"]
                        if not _df_blk.empty:
                            _csv_cols = [c for c in _blk_cols if c in _df_blk.columns]
                            _csv_blk = _df_blk[_csv_cols].to_csv(index=False).encode("utf-8-sig")
                            _dl_cols = st.columns([1.3, 3])
                            _dl_cols[0].download_button(
                                "📥 Tải CSV khách để qua bên",
                                _csv_blk,
                                file_name="khach_de_qua_ben_can_xem_lai.csv",
                                mime="text/csv",
                                key="cust_addr_blocked_csv",
                                use_container_width=True,
                            )
                            _reason_df = (
                                _df_blk.assign(**{
                                    "Mã lỗi": _df_blk.get("Mã lỗi", "").astype(str).replace("", "không rõ"),
                                    "Đánh giá fix code": _df_blk.get("Đánh giá fix code", "").astype(str).replace("", "Cần xem chi tiết"),
                                })
                                .groupby(["Mã lỗi", "Đánh giá fix code"], dropna=False)
                                .size()
                                .reset_index(name="Số khách")
                                .sort_values("Số khách", ascending=False)
                            )
                            _dl_cols[1].dataframe(_reason_df, hide_index=True, width="stretch")
                        st.dataframe(
                            _df_blk[[c for c in _blk_cols if c in _df_blk.columns]],
                            hide_index=True,
                            width="stretch",
                            column_config={
                                "Link Sapo": st.column_config.LinkColumn("Link Sapo", display_text="Mở"),
                                "Lý do / cách xử lý": st.column_config.TextColumn(width="large"),
                                "Đánh giá fix code": st.column_config.TextColumn(width="large"),
                                "Địa chỉ": st.column_config.TextColumn(width="large"),
                            },
                        )

                def _render_cust_samples(_smp, _cat=""):
                    if _smp:
                        _is_note_group = _cat == "thieu_ghi_chu"
                        _df = pd.DataFrame([{
                            "Ngày": m.get("ngay"),
                            "Loại": "Đơn" if m.get("row_type") == "order" else "Khách",
                            "Mã": m.get("order_code") if m.get("row_type") == "order" else m.get("id"),
                            "Mã KH": m.get("id"),
                            "Tên": m.get("ten"),
                            "SĐT": (_sapo_order_search_url(m.get("sdt")) if _is_note_group
                                    else ("⚠️ " + str(m.get("sdt") or "") if m.get("sdt_xau") else m.get("sdt"))),
                            "Tìm trong app": _ttkh_app_search_url(m.get("sdt")) if _is_note_group else "",
                            "Địa chỉ": m.get("dia_chi"),
                            "Auto fix": "Cần ghi chú" if _is_note_group else ("Cần xem lại" if str(m.get("id") or "").strip() in _blocked_ids else "Chờ sửa"),
                            "Mở Sapo": (f"https://vitranboutiquehcm.mysapo.net/admin/orders/{m.get('order_id') or m.get('id')}"
                                         if m.get("row_type") == "order"
                                         else f"https://vitranboutiquehcm.mysapo.net/admin/customers/{m.get('id')}"),
                        } for m in _smp])
                        _cols = ["Ngày", "Mã", "Tên", "SĐT"]
                        if _is_note_group:
                            _cols = ["Ngày", "Loại", "Mã", "Tên", "SĐT", "Tìm trong app"]
                        _cols.extend(["Địa chỉ", "Auto fix", "Mở Sapo"])
                        _config = {"Mở Sapo": st.column_config.LinkColumn("Mở Sapo", display_text="Mở")}
                        if _is_note_group:
                            _config.update({
                                "SĐT": st.column_config.LinkColumn("SĐT", display_text=r"query=([^&]+)"),
                                "Tìm trong app": st.column_config.LinkColumn("Tìm trong app", display_text="Mở DS đơn"),
                            })
                            st.caption("Nhóm này không tự sửa an toàn. Bấm **SĐT** để mở Sapo > Đơn hàng đã lọc theo số; "
                                       "hoặc bấm **Mở DS đơn** để tìm số đó trong danh sách đơn đang hiện.")
                        st.dataframe(_df[_cols], hide_index=True, width="stretch", column_config=_config)

                _cat_fix_notes = {
                    "sdt_sai": "chỉ sửa số chuẩn hóa chắc",
                    "thieu_ma_tinh": "địa chỉ text đủ tỉnh/quận/phường",
                    "thieu_ca_2": "đủ địa chỉ + lấy được SĐT hợp lệ",
                    "thieu_sdt": "copy SĐT chính vào địa chỉ",
                    "thieu_ma_phuong": "suy ra phường từ text chắc",
                    "khong_dia_chi": "không có địa chỉ gốc để suy ra",
                    "thieu_ghi_chu": "tìm đơn theo SĐT rồi ghi sdt/đơn vào note khách",
                }
                st.markdown("**Danh sách nhóm lỗi**")
                for _cat, _label in L.CUST_ERR_LABELS.items():
                    _n = _counts.get(_cat, 0)
                    if not _n:
                        continue
                    _smp = (_ca.get("samples") or {}).get(_cat) or []
                    _active_smp = [_m for _m in _smp if str(_m.get("id") or "").strip() not in _blocked_ids]
                    _blocked_in_group = len(_smp) - len(_active_smp)
                    _unit = "dòng" if _cat == "thieu_ghi_chu" else "khách"
                    _short = _cust_cat_title(_cat, _label)
                    _icon = _cust_cat_icon(_cat)
                    _erow = st.columns([3.3, 1, 1, 1, 1.35])
                    _erow[0].markdown(f"**{_icon} {_short}**")
                    _erow[1].metric("Tổng", f"{_n:,}", help=f"{_unit} trong nhóm này")
                    if _cat in _fix_cats:
                        _erow[2].metric("Chờ sửa", f"{len(_active_smp):,}")
                        _erow[3].metric("Cần xem", f"{_blocked_in_group:,}")
                        _can_run = bool(_active_smp)
                        if _erow[4].button(
                            f"🛠️ Sửa {min(len(_active_smp), int(_batch_n))}",
                            key=f"cust_addr_fix_run_{_cat}",
                            use_container_width=True,
                            disabled=not _can_run,
                        ):
                            st.session_state["cust_addr_fix_action_cat"] = _cat
                            st.rerun()
                    elif _cat == "thieu_ghi_chu":
                        _erow[2].metric("Chờ ghi", f"{len(_smp):,}")
                        _erow[3].caption(_cat_fix_notes.get(_cat, "ghi chú mã đơn"))
                        _can_note = bool(_smp)
                        if _erow[4].button(
                            f"📝 Ghi {min(len(_smp), int(_batch_n))}",
                            key="cust_note_fix_run_thieu_ghi_chu",
                            use_container_width=True,
                            disabled=not _can_note,
                        ):
                            _fix_missing_note_rows(_smp)
                            st.rerun()
                    else:
                        _erow[2].metric("Chờ xem", f"{len(_smp):,}")
                        _erow[3].caption(_cat_fix_notes.get(_cat, "cần xem tay"))
                        _erow[4].button(
                            "🚫 Không auto",
                            key=f"cust_addr_no_auto_{_cat}",
                            use_container_width=True,
                            disabled=True,
                        )
                    with st.expander(f"Xem mẫu: {_short} ({len(_smp):,})", expanded=False):
                        st.caption(_cat_fix_notes.get(_cat, "chỉ ghi khi khớp chắc"))
                        _render_cust_samples(_smp, _cat)
                st.caption("App chỉ tự ghi khi dữ liệu khớp chắc. Nhóm thiếu dữ liệu hoặc mâu thuẫn sẽ nằm ở 'Cần xem lại'.")

        with st.expander("ℹ️ Điều kiện lọc đơn"):
            st.caption("Đơn trong `Tất cả`, không hủy, tạo trong số ngày quét của tab này, ghi chú/địa chỉ SAPO chưa có SĐT khách.")

    _phone_re = re.compile(r"\b(?:\+?84|0)\d[\d\s.\-]{8,12}\b")
    _masked_phone_re = re.compile(r"(?:\+?84|0)?\d[\d\s().\-]*\*+[\d\s().\-]*\d")

    def _clean_phone(raw):
        s = str(raw or "").strip()
        if "*" in s:
            compact = re.sub(r"[\s().\-]+", "", s)
            if compact.startswith("+84"):
                compact = "0" + compact[3:]
            elif compact.startswith("84"):
                compact = "0" + compact[2:]
            return compact if "*" in compact and compact.startswith("0") else ""
        digits = re.sub(r"\D+", "", s)
        if digits.startswith("00"):               # tiền tố quay số quốc tế 00…
            digits = digits[2:]
        if digits.startswith("84"):               # mã quốc gia 84 → phần trong nước
            rest = digits[2:]
            if len(rest) == 9:                    # 84 + 9 số thuê bao   (vd 84399918102)
                digits = "0" + rest
            elif len(rest) == 10 and rest.startswith("0"):  # 84 + 0 + 9 số (dư, vd +840399918102)
                digits = rest
        digits = "0" + digits.lstrip("0")         # gộp số 0 thừa → đúng 1 số 0 ở đầu
        if len(digits) != 10:                     # SĐT VN chuẩn = đúng 10 số
            return ""
        return digits

    def _ttkh_address_code_missing(info):
        info = info or {}
        fmt = info.get("address_format") or ("old" if info.get("district") else "new")
        missing = []
        if not str(info.get("province_code") or "").strip():
            missing.append("mã tỉnh/thành")
        if fmt != "new" and not str(info.get("district_code") or "").strip():
            missing.append("mã quận/huyện")
        if not str(info.get("ward_code") or "").strip():
            missing.append("mã phường/xã")
        return missing

    def _ttkh_address_code_status(info):
        missing = _ttkh_address_code_missing(info)
        return "Đủ mã SAPO" if not missing else "Thiếu " + ", ".join(missing)

    def _ttkh_can_write(row):
        info = (row or {}).get("info") or {}
        return bool((row or {}).get("has_phone")) and (row or {}).get("status") == "Hợp lệ" and not _ttkh_address_code_missing(info)

    def _parse_tiktok_ttkh(text):
        raw = str(text or "").replace("\r", "\n").strip()
        lines = [x.strip() for x in raw.splitlines() if x.strip()]
        info = {"username": "", "name": "", "phone": "", "address1": "", "ward": "", "district": "", "province": "", "address_format": "", "raw": raw}
        if not raw:
            return info, "Chưa dán TTKH"

        def _after_label(label):
            for i, line in enumerate(lines):
                if _ascii_code(line) == _ascii_code(label) and i + 1 < len(lines):
                    return lines[i + 1]
            return ""

        info["username"] = _after_label("Tên người dùng")
        info["name"] = _after_label("Địa chỉ vận chuyển")
        phone_line = next((ln for ln in lines if _clean_phone(ln)), "")
        info["phone"] = _clean_phone(phone_line)
        if not info["phone"]:
            return info, "Không tìm thấy SĐT hợp lệ"

        phone_idx = lines.index(phone_line) if phone_line in lines else -1
        addr_lines = []
        if phone_idx >= 0:
            addr_lines = [ln for ln in lines[phone_idx + 1:] if _ascii_code(ln) not in {"TENNGUOIDUNG", "DIACHIVANCHUYEN"}]

        def _region_token(value):
            s = re.sub(r"\([^)]*$", "", str(value or "")).strip(" ,")
            return s.strip()

        def _region_name(value):
            raw = _region_token(value)
            key = _ascii_code(raw)
            special = {
                "TANANHOI": "Tân An Hội",
                "CUCHI": "Củ Chi",
                "HOCMON": "Hóc Môn",
                "BINHCHANH": "Bình Chánh",
                "NHABE": "Nhà Bè",
                "CANGIO": "Cần Giờ",
            }
            if key in special:
                return special[key]
            return " ".join(w[:1].upper() + w[1:].lower() for w in raw.split())

        def _province_name(value):
            key = _ascii_code(_region_token(value))
            if key in {"TPHCM", "HCM", "HOCHIMINH", "THANHPHOHOCHIMINH"}:
                return "Hồ Chí Minh"
            if key in {"HN", "HANOI", "THANHPHOHANOI"}:
                return "Hà Nội"
            return _region_name(value)

        def _apply_region(parts):
            parts = [_region_token(p) for p in parts if _region_token(p)]
            country = _ascii_code(parts[-1]) if parts else ""
            region_parts = parts[:-1] if country == "VIETNAM" else parts
            if len(region_parts) >= 3 and _ascii_code(region_parts[-3]) == _ascii_code(region_parts[-2]):
                info["ward"], info["district"], info["province"] = _region_name(region_parts[-3]), "", _province_name(region_parts[-1])
                info["address_format"] = "new"
                return 3 + (1 if country == "VIETNAM" else 0)
            elif len(region_parts) >= 3:
                info["ward"], info["district"], info["province"] = _region_name(region_parts[-3]), _region_name(region_parts[-2]), _province_name(region_parts[-1])
                info["address_format"] = "old"
                return 3 + (1 if country == "VIETNAM" else 0)
            elif len(region_parts) >= 2:
                info["ward"], info["district"], info["province"] = _region_name(region_parts[-2]), "", _province_name(region_parts[-1])
                info["address_format"] = "new"
                return 2 + (1 if country == "VIETNAM" else 0)
            return 0

        if addr_lines:
            if len(addr_lines) >= 2:
                info["address1"] = " ".join(addr_lines[:-1]).strip()
                parts = [p.strip() for p in re.split(r"[,，]", addr_lines[-1]) if p.strip()]
                _apply_region(parts)
            else:
                parts = [p.strip() for p in re.split(r"[,，]", addr_lines[0]) if p.strip()]
                used_tail = _apply_region(parts)
                if used_tail and len(parts) > used_tail:
                    info["address1"] = ", ".join(parts[:-used_tail]).strip()
                else:
                    info["address1"] = addr_lines[0]
        if not info["name"] or not info["address1"]:
            return info, "Thiếu tên hoặc địa chỉ giao hàng"
        info = resolve_address(info)
        missing_codes = _ttkh_address_code_missing(info)
        if missing_codes:
            return info, "Thiếu mã SAPO: " + ", ".join(missing_codes)
        return info, "Hợp lệ"

    def _ttkh_editor_rows(rows):
        return pd.DataFrame([{
            "Ngày tạo": r.get("created_on", ""),
            "Mã đơn": r.get("name", ""),
            "SL SP": r.get("qty", 0),
            "created_sort": r.get("created_sort", ""),
            "Gian hàng": r.get("store", ""),
            "Ghi chú hiện tại": r.get("note", ""),
            "products": r.get("products") or [],
            "order_value": r.get("order_value") or 0,
            "_order_id": r.get("order_id"),
            "_customer_id": r.get("customer_id"),
            "_needs_customer": bool(r.get("needs_customer")),
            "_phone": r.get("shipping_phone") or "",
        } for r in rows])

    def _money(v):
        try:
            return f"{int(round(float(v or 0))):,}".replace(",", ".") + "đ"
        except Exception:
            return "0đ"

    def _ttkh_order_url(order_code, store=""):
        code = str(order_code or "").strip()
        if not code:
            return ""
        if "shopee" in str(store or "").lower():
            return ""
        return _tiktok_order_url(code)

    def _sapo_order_url(order_id):
        oid = str(order_id or "").strip()
        return f"https://vitranboutiquehcm.mysapo.net/admin/orders/{quote_plus(oid)}" if oid else ""

    def _sapo_customer_url(customer_id):
        cid = str(customer_id or "").strip()
        return f"https://vitranboutiquehcm.mysapo.net/admin/customers/{quote_plus(cid)}" if cid else ""

    def _sapo_customer_search_url(query):
        q = str(query or "").strip()
        return f"https://vitranboutiquehcm.mysapo.net/admin/customers?query={quote_plus(q)}" if q else "https://vitranboutiquehcm.mysapo.net/admin/customers"

    def _product_tip(row):
        products = row.get("products") or []
        if not products:
            return "Chưa có chi tiết sản phẩm"
        lines = []
        for p in products:
            sku = p.get("sku") or "N/A"
            qty = p.get("qty") or 0
            price = _money(p.get("price"))
            line_total = _money(p.get("line_total") or ((p.get("qty") or 0) * (p.get("price") or 0)))
            title = str(p.get("title") or "").strip()
            variant = str(p.get("variant") or "").strip()
            desc = title[:70] if title else sku
            if variant:
                desc += f" | {variant[:50]}"
            lines.append(f"{desc}")
            lines.append(f"SKU {sku} | SL {qty} | Đơn giá {price} | Thành tiền {line_total}")
        lines.append(f"Tổng: {_money(row.get('order_value'))}")
        return "&#13;".join(_esc(x) for x in lines)

    def _ttkh_input_key(order_id):
        return f"ttkh_cell_{order_id}"

    def _collect_ttkh_rows(source_rows):
        out = []
        for source in source_rows:
            order_id = str(source.get("order_id"))
            txt = str(st.session_state.get(_ttkh_input_key(order_id)) or "").strip()
            if not txt:
                continue
            info, status = _parse_tiktok_ttkh(txt)
            has_phone = bool(info.get("phone")) and (bool(_phone_re.search(info.get("phone", ""))) or "*" in info.get("phone", ""))
            out.append({
                "order_id": order_id,
                "code": source.get("name"),
                "old_note": str(source.get("note") or "").strip(),
                "ttkh": txt,
                "info": info,
                "status": status,
                "has_phone": has_phone,
            })
        return out

    def _ttkh_address_preview(info, status):
        info = info or {}
        if status != "Hợp lệ" and not info.get("address1"):
            return status or "Chưa hợp lệ"
        fmt = "Địa chỉ mới" if info.get("address_format") == "new" else "Địa chỉ cũ"
        line_parts = [
            info.get("name") or "",
            info.get("address1") or "",
            info.get("ward") or "",
        ]
        if info.get("address_format") != "new":
            line_parts.append(info.get("district") or "")
        line_parts.extend([info.get("province") or "", "Việt Nam"])
        line = ", ".join(str(x).strip() for x in line_parts if str(x or "").strip())
        if info.get("address_format") == "new":
            codes = f" | mã: Tỉnh {info.get('province_code') or '-'} - Phường/Xã {info.get('ward_code') or '-'}"
        else:
            codes = f" | mã: Tỉnh {info.get('province_code') or '-'} - Quận/Huyện {info.get('district_code') or '-'} - Phường/Xã {info.get('ward_code') or '-'}"
        code_status = _ttkh_address_code_status(info)
        if status != "Hợp lệ":
            return f"{fmt}: {line}{codes} | {status or code_status}"
        return f"{fmt}: {line}{codes} | {code_status}"

    def _kq(r):
        return str(r.get("Kết quả") or "")

    def _ttkh_friendly(r):
        """Trả (trạng thái dễ hiểu, cần làm gì, màu) cho nhân viên."""
        kq = _kq(r)
        ly_do = str(r.get("Lý do") or "")
        is429 = "429" in ly_do or "rate limit" in ly_do.lower()
        if kq.startswith("Chưa hoàn tất"):
            if is429:
                return "⚠️ Chưa hoàn tất (Sapo bận)", "Chờ 1–2 phút rồi bấm 💾 Ghi SAPO lại. App giữ đơn trong danh sách.", "#b45309"
            return "⚠️ Chưa hoàn tất", "Mở chi tiết lỗi, kiểm tra mã tỉnh/quận/phường hoặc bấm Ghi lại. Nếu lặp lại, báo quản lý kèm mã đơn.", "#b45309"
        if kq.startswith("Đã ghi ghi chú + khách"):
            return "✅ Xong (đơn + khách)", "Không cần làm gì.", "#1e7d3c"
        if kq.startswith("Đã tạo/cập nhật khách"):
            return "⚠️ Cần kiểm tra địa chỉ", "Khách đã có/cập nhật, nhưng địa chỉ hoặc đơn chưa xác nhận đủ chuẩn. Mở khách kiểm tra mã vùng rồi Ghi lại nếu cần.", "#b45309"
        if kq.startswith("Đã ghi ghi chú,"):   # đơn OK, khách chưa tạo
            if is429:
                return "⚠️ Chưa tạo được KHÁCH (Sapo bận)", "Chờ 1–2 phút rồi bấm 💾 Ghi SAPO lại. Đơn vẫn còn trong danh sách.", "#b45309"
            return "⚠️ Chưa tạo được KHÁCH", "Bấm 💾 Ghi SAPO lại. Nếu vẫn lỗi sau 2–3 lần, báo quản lý kèm mã đơn.", "#b45309"
        if kq.startswith("Lỗi"):               # cả đơn cũng lỗi
            if is429:
                return "❌ Chưa ghi được (Sapo bận)", "Chờ 1–2 phút rồi bấm 💾 Ghi SAPO lại.", "#b91c1c"
            return "❌ Chưa ghi được", "Bấm 💾 Ghi SAPO lại. Nếu vẫn lỗi, báo quản lý kèm mã đơn.", "#b91c1c"
        if kq.startswith("Bỏ qua"):
            return "⏭️ Bỏ qua (chưa hợp lệ)", f"Kiểm lại TTKH đã dán ({ly_do}). Dán đúng block có SĐT + tên + địa chỉ rồi Ghi lại.", "#b45309"
        return "❓ Không rõ", "Bấm Ghi lại; nếu lặp lại báo quản lý.", "#6b7280"

    def _ttkh_result_by_code():
        return {str(r.get("Mã đơn")): r for r in (st.session_state.get("ttkh_write_results") or [])}

    def _ttkh_order_code_plausible(code):
        code = re.sub(r"\s+", "", str(code or ""))
        return bool(code and len(code) <= 30 and re.fullmatch(r"[A-Za-z0-9_-]+", code))

    def _ttkh_error_group_label(reason):
        text = str(reason or "").lower()
        if "429" in text or "rate limit" in text:
            return "Sapo bận / rate limit"
        if "không thấy đơn" in text or "khong thay don" in text:
            return "Không thấy đơn trong 45 ngày"
        if "thiếu sđt" in text or "thiếu sdt" in text or "thiếu sdt/tên" in text or "thiếu sđt/tên" in text:
            return "Đơn thiếu SĐT / tên"
        if "chưa đủ mã sapo" in text or "thiếu mã" in text or "mã vùng" in text:
            return "Thiếu / sai mã tỉnh-quận-phường"
        if "chưa hoàn tất" in text or "đã tạo/cập nhật khách" in text:
            return "Khách đã tạo, cần xác nhận lại địa chỉ"
        if "400" in text or "422" in text or "sapo từ chối" in text:
            return "Sapo từ chối dữ liệu"
        if "401" in text or "403" in text or "cookie" in text:
            return "Phiên Sapo hết hạn"
        return "Lỗi khác"

    def _ttkh_reason_brief(reason):
        group = _ttkh_error_group_label(reason)
        if group != "Lỗi khác":
            return group
        text = re.sub(r"\s+", " ", str(reason or "")).strip()
        return (text[:80] + "...") if len(text) > 80 else (text or "Chưa rõ")

    def _ttkh_group_icon(label):
        label = str(label or "")
        if "Đã sửa" in label:
            return "✅"
        if "Sapo bận" in label:
            return "⏳"
        if "Không thấy" in label:
            return "🔎"
        if "thiếu SĐT" in label or "SĐT" in label:
            return "📞"
        if "mã tỉnh" in label or "mã" in label:
            return "📍"
        if "từ chối" in label:
            return "⛔"
        if "Phiên" in label:
            return "🔐"
        return "⚠️"

    def _ttkh_history_row_style(row):
        status = str(row.get("Trạng thái") or "")
        group = str(row.get("Nhóm lỗi") or "")
        if status.startswith("✅"):
            color = "#ecfdf5"
        elif "Sapo bận" in group:
            color = "#fffbeb"
        else:
            color = "#fef2f2"
        return [f"background-color: {color}"] * len(row)

    def _ttkh_repair_customer_from_sapo(codes, limit=60, source_rows_by_code=None):
        """Kiểm/sửa phần khách hàng cho các mã đơn lỗi và ghi lại lý do vào nhật ký."""
        seen, clean_codes = set(), []
        raw_items = [codes] if isinstance(codes, str) else (codes or [])
        for raw in raw_items:
            for code in parse_codes(str(raw or "")):
                if code and _ttkh_order_code_plausible(code) and code not in seen:
                    seen.add(code)
                    clean_codes.append(code)
        clean_codes = clean_codes[:max(1, int(limit or 60))]
        if not clean_codes:
            return []

        source_rows_by_code = source_rows_by_code or {}
        out, log_records = [], []
        try:
            sess = build_session()
            fetch_json = make_fetch_json(sess)
        except Exception as e:
            return [{
                "Mã đơn": c,
                "phone": "",
                "ket_qua": f"❌ Không mở được phiên Sapo: {type(e).__name__}: {e}",
                "luc": "",
                "nhom": "auth",
                "dia_chi": "",
                "raw": {},
                "attempts": [],
            } for c in clean_codes]

        def _log(code, phone, ket_qua, ly_do, link_khach=""):
            now = datetime.now(timezone.utc) + timedelta(hours=7)
            log_records.append({
                "ngay": now.strftime("%Y-%m-%d"),
                "gio": now.strftime("%H:%M"),
                "ts": now.isoformat(timespec="seconds"),
                "ma_don": code,
                "sdt": phone or "",
                "ket_qua": ket_qua,
                "trang_thai": "Sửa lỗi TTKH",
                "ly_do": ly_do,
                "link_khach": link_khach or "",
                "chi_tiet": ly_do[:1800],
            })

        for code in clean_codes:
            info, raw_shipping, attempts = {}, {}, []
            row = source_rows_by_code.get(code) or source_rows_by_code.get(str(code))
            if row and not _ttkh_can_write(row):
                reason = row.get("status") or _ttkh_address_code_status(row.get("info") or {})
                why = f"❌ TTKH vừa dán chưa đủ điều kiện ghi: {reason}. Cần sửa text TTKH/mã vùng trước."
                phone = (row.get("info") or {}).get("phone") or ""
                out.append({"Mã đơn": code, "phone": phone, "ket_qua": why, "luc": "", "nhom": "ttkh_chua_hop_le",
                            "dia_chi": _ttkh_address_preview(row.get("info") or {}, row.get("status") or ""),
                            "raw": {"nguon": "TTKH vừa dán", "order_id": row.get("order_id")}, "attempts": []})
                _log(code, phone, "that_bai", why)
                continue
            if row and (row.get("info") or {}):
                info = row.get("info") or {}
                raw_shipping = {"nguon": "TTKH vừa dán", "order_id": row.get("order_id")}
            else:
                try:
                    od = L.find_order_by_code(fetch_json, code, days=45)
                except Exception as e:
                    why = f"❌ Không tra được đơn trên Sapo: {type(e).__name__}: {e}"
                    out.append({"Mã đơn": code, "phone": "", "ket_qua": why, "luc": "", "nhom": "khong_tra_duoc",
                                "dia_chi": "", "raw": {}, "attempts": []})
                    _log(code, "", "that_bai", why)
                    continue
                if not od:
                    why = "❌ Không thấy đơn trong Sapo trong 45 ngày gần nhất."
                    out.append({"Mã đơn": code, "phone": "", "ket_qua": why, "luc": "", "nhom": "khong_thay_don",
                                "dia_chi": "", "raw": {}, "attempts": []})
                    _log(code, "", "that_bai", why)
                    continue
                info = od.get("info") or {}
                raw_shipping = od.get("raw_shipping") or {}

            phone = info.get("phone") or ""
            if not phone or not info.get("name"):
                why = f"❌ Đơn thiếu SĐT/tên nên chưa tạo khách được. phone={phone or '-'}, name={info.get('name') or '-'}"
                out.append({"Mã đơn": code, "phone": phone, "ket_qua": why, "luc": "", "nhom": "thieu_sdt_ten",
                            "dia_chi": "", "raw": raw_shipping, "attempts": []})
                _log(code, phone, "that_bai", why)
                continue
            missing = _ttkh_address_code_missing(info)
            if missing:
                why = "❌ Chưa đủ mã SAPO: thiếu " + ", ".join(missing) + ". Cần sửa/chuẩn hóa text địa chỉ trước khi ghi."
                addr = ", ".join(str(x) for x in (info.get("ward"), info.get("district"), info.get("province")) if x)
                out.append({"Mã đơn": code, "phone": phone, "ket_qua": why, "luc": "", "nhom": "thieu_ma_vung",
                            "dia_chi": f"{addr}  [{info.get('address_format')}]  mã P/X {info.get('ward_code') or '-'}",
                            "raw": raw_shipping, "attempts": []})
                _log(code, phone, "that_bai", why)
                continue

            cid, attempts = upsert_customer_from_info(sess, info, note=f"Fix/cập nhật đơn {code}")
            attempts = [str(a) for a in (attempts or [])]
            blob = " ".join(attempts).lower()
            write_blob = " ".join(a for a in attempts if any(w in a for w in ("POST", "PUT", "PATCH"))).lower()
            link_khach = _sapo_customer_url(cid)
            luc = ""
            if cid:
                now = datetime.now(timezone.utc) + timedelta(hours=7)
                luc = now.strftime("%H:%M:%S %d/%m/%Y")
                why = f"✅ ĐÃ TẠO/CẬP NHẬT khách (địa chỉ Tỉnh/Quận/Phường) — lúc {luc}"
                _log(code, phone, "thanh_cong", why, link_khach)
            elif "429" in write_blob:
                why = "❌ 429 — Sapo đang chặn/rate limit. Nghỉ 5–10 phút rồi bấm sửa lại."
                _log(code, phone, "that_bai", why)
            elif "type_mismatch" in blob or "convert string value to integer" in blob:
                why = "❌ Mã vùng địa chỉ sai kiểu (Sapo cần mã số). Cần kiểm lại map tỉnh/quận/phường."
                _log(code, phone, "that_bai", why)
            elif "401" in write_blob or "403" in write_blob:
                why = "❌ Phiên/cookie Sapo hết hạn (401/403) — cần cập nhật SAPO_COOKIE."
                _log(code, phone, "that_bai", why)
            elif "422" in write_blob or "400" in write_blob:
                why = "❌ Sapo từ chối dữ liệu tạo khách (400/422). Mở chi tiết bước ghi để xem payload/lỗi."
                _log(code, phone, "that_bai", why)
            else:
                tail = "; ".join(attempts[-4:])
                why = ("❌ Vẫn không tạo được khách." + (f" Chi tiết: {tail}" if tail else ""))[:1200]
                _log(code, phone, "that_bai", why)

            addr = ", ".join(str(x) for x in (info.get("ward"), info.get("district"), info.get("province")) if x)
            out.append({
                "Mã đơn": code,
                "phone": phone,
                "ket_qua": why,
                "luc": luc,
                "nhom": "da_sua" if cid else "sapo_tu_choi",
                "dia_chi": f"{addr}  [{info.get('address_format')}]  mã P/X {info.get('ward_code') or '-'}",
                "raw": raw_shipping,
                "attempts": attempts,
                "link_khach": link_khach,
            })
            time.sleep(0.6)

        try:
            if picklog.configured() and log_records:
                picklog.log_ttkh_batch(log_records)
        except Exception:
            pass
        return out

    def _show_ttkh_write_results():
        results = st.session_state.get("ttkh_write_results") or []
        if not results:
            return
        ok_rows = [r for r in results if _kq(r).startswith("Đã ghi ghi chú + khách")]
        partial_rows = [r for r in results if _kq(r).startswith("Chưa hoàn tất") or _kq(r).startswith("Đã tạo/cập nhật khách")]
        cust_fail = [r for r in results if _kq(r).startswith("Đã ghi ghi chú,")]
        hard_fail = [r for r in results if _kq(r).startswith("Lỗi")]
        skipped_rows = [r for r in results if _kq(r).startswith("Bỏ qua")]
        _fail_rows = partial_rows + cust_fail + hard_fail
        _problem_rows = _fail_rows + skipped_rows
        ok = len(ok_rows)
        skipped = len(skipped_rows)
        failed = len(_fail_rows)

        total = len(results)
        n429 = sum(1 for r in _problem_rows if "429" in str(r.get("Lý do")) or "rate limit" in str(r.get("Lý do")).lower())
        # Lưu mã đơn cần xử lý để xem lại hoặc dùng cho các thao tác chẩn đoán sau này.
        st.session_state["ttkh_failed_codes"] = [str(r.get("Mã đơn")) for r in _problem_rows if str(r.get("Mã đơn") or "").strip()]

        if failed or skipped:
            st.warning(f"Kết quả lưu TTKH: thành công {ok}/{total}, chưa hoàn tất {failed}, bỏ qua {skipped}. Xem bảng chi tiết bên dưới để xử lý tiếp.")
        else:
            st.success(f"Đã lưu thành công {ok}/{total} đơn: khách hàng + địa chỉ chuẩn + đơn hàng đều đã cập nhật.")

        _c = st.columns([1, 1, 1, 1.8])
        _c[0].metric("Tổng xử lý", total)
        _c[1].metric("Thành công", ok)
        _c[2].metric("Cần xử lý", failed + skipped)
        if failed or skipped:
            _bad_codes = ", ".join(str(r.get("Mã đơn")) for r in _problem_rows[:10])
            _extra = f" Trong đó {n429} đơn do Sapo bận/rate limit, chờ 1–2 phút rồi Ghi lại." if n429 else ""
            _c[3].caption(f"Đơn cần xử lý: {_bad_codes}.{_extra}")
        else:
            _c[3].caption("Tất cả đã lưu đủ 2 nơi 🎉" if ok else "")

        detail_rows = []
        for r in results:
            friendly, todo, _color = _ttkh_friendly(r)
            detail_rows.append({
                "Mã đơn": r.get("Mã đơn"),
                "Trạng thái": friendly,
                "Cách xử lý": todo,
                "SĐT": r.get("SĐT", ""),
                "Loại địa chỉ": r.get("Loại địa chỉ", ""),
                "Mã tỉnh": r.get("Mã tỉnh", ""),
                "Mã quận": r.get("Mã quận", ""),
                "Mã phường": r.get("Mã phường", ""),
                "Lý do": r.get("Lý do", ""),
                "Link khách": r.get("Link khách", ""),
            })
        with st.expander("Chi tiết kết quả lưu TTKH lần gần nhất", expanded=bool(failed or skipped)):
            st.dataframe(
                pd.DataFrame(detail_rows),
                hide_index=True,
                width="stretch",
                column_config={
                    "Cách xử lý": st.column_config.TextColumn(width="large"),
                    "Lý do": st.column_config.TextColumn(width="large"),
                    "Link khách": st.column_config.LinkColumn(width="medium"),
                },
            )
            if _problem_rows:
                failed_codes = [str(r.get("Mã đơn")) for r in _problem_rows if str(r.get("Mã đơn") or "").strip()]
                last_rows = st.session_state.get("ttkh_last_write_rows_by_code") or {}
                retry_rows = [last_rows[c] for c in failed_codes if c in last_rows and _ttkh_can_write(last_rows[c])]
                a, b = st.columns([1, 1])
                if a.button(f"💾 Ghi lại dòng lỗi đủ mã ({min(len(retry_rows), 60)})",
                            key="ttkh_retry_failed_rows", disabled=not retry_rows,
                            help="Dùng lại TTKH vừa dán, ghi lại tối đa 60 dòng đã đủ mã SAPO."):
                    _write_ttkh_rows(retry_rows[:60])
                    st.rerun()
                if b.button(f"🔧 Kiểm/Sửa khách theo mã đơn ({min(len(failed_codes), 60)})",
                            key="ttkh_repair_failed_customers", disabled=not failed_codes,
                            help="Tra lại Sapo theo mã đơn rồi tạo/cập nhật khách hàng. Lỗi còn lại sẽ được lưu lý do vào lịch sử."):
                    with st.spinner("Đang kiểm/sửa khách theo mã đơn lỗi…"):
                        st.session_state["ttkh_inline_fix_result"] = _ttkh_repair_customer_from_sapo(
                            failed_codes, limit=60, source_rows_by_code=last_rows)
                    load_customer_phone_set.clear()
                if skipped_rows and not retry_rows:
                    st.caption("Các dòng bị bỏ qua thường là TTKH thiếu/không map được mã tỉnh-quận-phường; app sẽ không ghi bừa vào Sapo.")
                if st.session_state.get("ttkh_inline_fix_result"):
                    diag = st.session_state["ttkh_inline_fix_result"]
                    ok_diag = [d for d in diag if d.get("luc")]
                    bad_diag = [d for d in diag if not d.get("luc")]
                    if ok_diag:
                        st.success(f"Đã sửa được {len(ok_diag)} khách. Các dòng còn lỗi đã được ghi lý do vào lịch sử.")
                    if bad_diag:
                        st.warning(f"Còn {len(bad_diag)} dòng chưa sửa được; xem cột Kết quả để biết lý do.")
                    st.dataframe(
                        pd.DataFrame([{
                            "Mã đơn": d.get("Mã đơn"),
                            "SĐT": d.get("phone"),
                            "Kết quả": d.get("ket_qua"),
                            "Địa chỉ app gửi": d.get("dia_chi"),
                            "Link khách": d.get("link_khach", ""),
                        } for d in diag]),
                        hide_index=True,
                        width="stretch",
                        column_config={
                            "Kết quả": st.column_config.TextColumn(width="large"),
                            "Địa chỉ app gửi": st.column_config.TextColumn(width="large"),
                            "Link khách": st.column_config.LinkColumn(width="medium"),
                        },
                    )

    def _write_ttkh_rows(rows_to_write):
        session = build_session()
        now_note = (datetime.now(timezone.utc) + timedelta(hours=7)).strftime("%d/%m/%Y %H:%M")
        results = []
        ok_count = 0
        written_ids = []
        st.session_state["ttkh_last_write_rows_by_code"] = {
            str(r.get("code")): r for r in (rows_to_write or []) if str(r.get("code") or "").strip()
        }
        st.session_state.pop("ttkh_inline_fix_result", None)

        def _note_phone_key(value):
            raw = str(value or "").strip()
            return re.sub(r"[^0-9*]+", "", raw)

        def _result_row(src, ket_qua, customer_url="", ly_do=""):
            info = (src or {}).get("info") or {}
            fmt = info.get("address_format") or ("old" if info.get("district") else "new")
            return {
                "Mã đơn": (src or {}).get("code"),
                "SĐT": info.get("phone", ""),
                "Loại địa chỉ": "Mới" if fmt == "new" else "Cũ",
                "Mã tỉnh": info.get("province_code", ""),
                "Mã quận": "" if fmt == "new" else info.get("district_code", ""),
                "Mã phường": info.get("ward_code", ""),
                "Kết quả": ket_qua,
                "Link khách": customer_url,
                "Lý do": ly_do,
            }

        for r in rows_to_write:
            if not _ttkh_can_write(r):
                reason = r.get("status") or ""
                if r.get("has_phone") and reason == "Hợp lệ":
                    reason = _ttkh_address_code_status(r.get("info") or {})
                results.append(_result_row(r, "Bỏ qua", ly_do=reason))
                continue
            old_note = r["old_note"]
            info = r["info"]
            block_lines = []
            if info.get("username"):
                block_lines.append(str(info["username"]).strip())
            block_lines.append(f"sdt: {info['phone']}")
            block = "\n".join(block_lines)
            old_note_phone = _note_phone_key(old_note)
            phone_norm = _note_phone_key(info["phone"])
            if phone_norm and phone_norm in old_note_phone:
                new_note = old_note
            else:
                clean_old_note = re.sub(
                    r"(?is)\n?📝\s*Ghi chú cũ SAPO:\s*(?:.*?)(?=\n\S|\Z)",
                    "",
                    old_note,
                ).strip()
                new_note = f"{block}\n📝 Ghi chú cũ SAPO:\n{clean_old_note}".strip() if clean_old_note else block
            note_saved = False
            note_error = ""
            customer_url = ""
            customer_tail = ""
            try:
                update_order_note(session, r["order_id"], new_note)
                note_saved = True
            except Exception as e:
                note_error = str(e)[:900]
            try:
                saved = update_order_customer_info(session, r["order_id"], info, new_note)
                note_saved = bool(note_saved or (isinstance(saved, dict) and saved.get("_ttkh_order_saved")))
                customer_id = saved.get("_ttkh_customer_id") if isinstance(saved, dict) else ""
                customer_url = _sapo_customer_url(customer_id)
                if isinstance(saved, dict) and saved.get("_ttkh_customer_saved") and saved.get("_ttkh_address_saved") and saved.get("_ttkh_order_saved"):
                    ok_count += 1
                    written_ids.append(str(r["order_id"]))
                    results.append(_result_row(r, "Đã ghi ghi chú + khách hàng", customer_url=customer_url))
                elif isinstance(saved, dict) and saved.get("_ttkh_customer_saved"):
                    customer_tail = "; ".join(saved.get("_ttkh_attempts", [])[-10:])
                    results.append(_result_row(
                        r,
                        "Chưa hoàn tất: đã tạo/cập nhật khách nhưng địa chỉ/đơn chưa xác nhận đủ chuẩn",
                        customer_url=customer_url,
                        ly_do=customer_tail[:1600],
                    ))
                else:
                    customer_tail = "; ".join(saved.get("_ttkh_attempts", [])[-8:]) if isinstance(saved, dict) else ""
            except Exception as e:
                customer_tail = str(e)[:1200]
            if not any(x.get("Mã đơn") == r["code"] for x in results):
                if note_saved:
                    results.append(_result_row(
                        r,
                        "Đã ghi ghi chú, chưa ghi được khách/contact",
                        customer_url=customer_url,
                        ly_do=(customer_tail or note_error)[:1600],
                    ))
                else:
                    results.append(_result_row(
                        r,
                        "Lỗi",
                        customer_url=customer_url,
                        ly_do=("Ghi chú đơn hàng chưa lưu. " + note_error + " | " + customer_tail).strip(" |")[:1600],
                    ))
        st.session_state["ttkh_write_results"] = results
        # Ghi LỊCH SỬ lưu TTKH vào Gist để thống kê theo ngày (không được làm hỏng luồng ghi)
        try:
            _phone_by_code = {r["code"]: (r["info"].get("phone") or "") for r in rows_to_write}

            def _ttkh_result_cat(kq):
                kq = str(kq or "")
                if kq.startswith("Đã ghi ghi chú + khách"):
                    return "thanh_cong"
                if kq.startswith("Bỏ qua"):
                    return "bo_qua"
                return "that_bai"

            _log_ts = datetime.now(timezone.utc) + timedelta(hours=7)
            _log_records = [{
                "ngay": _log_ts.strftime("%Y-%m-%d"),
                "gio": _log_ts.strftime("%H:%M"),
                "ts": _log_ts.isoformat(timespec="seconds"),
                "ma_don": res.get("Mã đơn"),
                "sdt": _phone_by_code.get(res.get("Mã đơn"), ""),
                "ket_qua": _ttkh_result_cat(res.get("Kết quả")),
                "trang_thai": str(res.get("Kết quả") or ""),
                "ly_do": str(res.get("Lý do") or ""),
                "link_khach": str(res.get("Link khách") or ""),
                "chi_tiet": (
                    str(res.get("Kết quả") or "")
                    + (f" | {str(res.get('Lý do') or '')}" if str(res.get("Lý do") or "").strip() else "")
                )[:1800],
            } for res in results]
            if picklog.configured() and _log_records:
                picklog.log_ttkh_batch(_log_records)
            # Cập nhật danh sách "chờ tạo khách": thành công → gỡ ra; thất bại → giữ lại
            _oid_by_code = {r["code"]: str(r["order_id"]) for r in rows_to_write}
            _pending_add, _pending_remove = {}, []
            for res in results:
                _cat = _ttkh_result_cat(res.get("Kết quả"))
                _oid = _oid_by_code.get(res.get("Mã đơn"))
                if not _oid or _cat == "bo_qua":
                    continue
                if _cat == "thanh_cong":
                    _pending_remove.append(_oid)
                else:
                    _pending_add[_oid] = {
                        "ma_don": res.get("Mã đơn"),
                        "sdt": _phone_by_code.get(res.get("Mã đơn"), ""),
                        "ly_do": str(res.get("Kết quả") or ""),
                        "ts": _log_ts.isoformat(timespec="seconds"),
                    }
            if picklog.configured() and (_pending_add or _pending_remove):
                picklog.update_ttkh_pending(add=_pending_add, remove_ids=_pending_remove)
        except Exception:
            pass
        if ok_count:
            _clear_ids = set(st.session_state.get("ttkh_clear_ids") or [])
            for _oid in written_ids:
                st.session_state["ttkh_pending_inputs"].pop(_oid, None)
                _clear_ids.add(_oid)
            st.session_state["ttkh_clear_ids"] = sorted(_clear_ids)
            load_ttkh_candidates.clear()
            load_customer_phone_set.clear()   # vừa tạo khách → làm mới tập SĐT khách
        st.rerun()

    def _ttkh_table(label, rows):
        st.markdown(f"#### {label} — {len(rows)} đơn")
        df = _ttkh_editor_rows(rows)
        if df.empty:
            st.caption("Không có đơn.")
            return df
        h = st.columns([1.0, 1.8, .7, 1.7, 3.2, 4.2])
        h[0].markdown("**Ngày tạo**")
        h[1].markdown("**Mã đơn**")
        h[2].markdown("**SL SP**")
        h[3].markdown("**Gian hàng**")
        h[4].markdown("**Địa chỉ chuẩn SAPO**  \n<small>Cũ: tỉnh/quận/phường · Mới: tỉnh/phường</small>", unsafe_allow_html=True)
        h[5].markdown("**TTKH dán vào**  \n<small>App sẽ kiểm đủ mã SAPO trước khi ghi</small>", unsafe_allow_html=True)
        st.markdown("<hr style='margin:4px 0 8px;border:0;border-top:1px solid #e5e7eb'>", unsafe_allow_html=True)
        _res_map = _ttkh_result_by_code()   # kết quả Ghi SAPO lần gần nhất, theo mã đơn
        for _, r in df.iterrows():
            oid = str(r.get("_order_id"))
            key = _ttkh_input_key(oid)
            _clear_ids = set(st.session_state.get("ttkh_clear_ids") or [])
            if oid in _clear_ids:
                st.session_state[key] = ""
                _clear_ids.discard(oid)
                st.session_state["ttkh_clear_ids"] = sorted(_clear_ids)
            if key not in st.session_state:
                st.session_state[key] = (st.session_state.get("ttkh_pending_inputs") or {}).get(oid, "")
            c = st.columns([1.0, 1.8, .7, 1.7, 3.2, 4.2])
            c[0].markdown(str(r.get("Ngày tạo") or ""))
            code = str(r.get("Mã đơn") or "")
            typed_ttkh = c[5].text_area(
                "TTKH dán vào",
                key=key,
                height=96,
                label_visibility="collapsed",
                placeholder="Dán nguyên block TTKH từ sàn. App sẽ phân địa chỉ cũ/mới và kiểm mã tỉnh/quận/phường.",
            )
            row_pending = []
            if str(typed_ttkh or "").strip():
                _info, _status = _parse_tiktok_ttkh(typed_ttkh)
                _has_phone = bool(_info.get("phone")) and (bool(_phone_re.search(_info.get("phone", ""))) or "*" in _info.get("phone", ""))
                row_pending = [{
                    "order_id": oid,
                    "code": code,
                    "old_note": str(r.get("Ghi chú hiện tại") or "").strip(),
                    "ttkh": typed_ttkh,
                    "info": _info,
                    "status": _status,
                    "has_phone": _has_phone,
                }]
            url = _ttkh_order_url(code, r.get("Gian hàng"))
            sapo_url = _sapo_order_url(oid)
            customer_url = _sapo_customer_url(r.get("_customer_id"))
            # Tìm khách theo SĐT (không phải mã đơn — Sapo tìm khách theo số/tên)
            customer_query = str(r.get("_phone") or "").strip()
            if row_pending:
                _info = row_pending[0].get("info") or {}
                customer_query = _info.get("phone") or customer_query or _info.get("name") or code
            customer_query = customer_query or code
            def _lnk(txt, href):   # mở tab mới (Shift+Click để mở CỬA SỔ Chrome riêng)
                href = _normalize_shopee_order_link(_normalize_tiktok_order_link(href))
                return f"<a href='{href}' target='_blank' rel='noopener'>{txt}</a>"
            code_link = _lnk(_esc(str(code)), url) if url else _esc(str(code))
            sapo_link = f" · {_lnk('Sapo', sapo_url)}" if sapo_url else ""
            customer_link = (f" · {_lnk('Khách', customer_url)}" if customer_url
                             else f" · {_lnk('🔎 Tìm khách theo SĐT', _sapo_customer_search_url(customer_query))}")
            _needs_cust = bool(r.get("_needs_customer"))
            _warn_badge = ("<div style='color:#b91c1c;font-weight:800;font-size:.8rem'>⚠️ Đã ghi đơn nhưng "
                           "CHƯA tạo được khách — ghi lại dòng này</div>") if _needs_cust else ""
            # Kết quả Ghi SAPO lần gần nhất — hiện NGAY tại dòng đơn cho nhân viên dễ coi
            _res_badge = ""
            _res = _res_map.get(code)
            if _res:
                _rst, _rtodo, _rcolor = _ttkh_friendly(_res)
                if not _rst.startswith("✅"):   # đơn xong tự mất rồi → chỉ hiện đơn lỗi/chờ
                    _res_badge = (f"<div style='margin-top:3px;font-size:.82rem;line-height:1.3;color:{_rcolor};font-weight:800'>{_esc(_rst)}"
                                  f"<div style='font-weight:500;color:#374151;font-size:.78rem'>➡ {_esc(_rtodo)}</div></div>")
            c[1].markdown(code_link + sapo_link + customer_link + _warn_badge + _res_badge, unsafe_allow_html=True)
            c[2].markdown(
                f"<abbr title='{_product_tip(r)}' style='cursor:help;font-weight:800;text-decoration:underline dotted #6b7280'>{int(r.get('SL SP') or 0)} SP ⓘ</abbr>",
                unsafe_allow_html=True,
            )
            c[3].markdown(str(r.get("Gian hàng") or ""))
            if row_pending:
                rp = row_pending[0]
                preview = _ttkh_address_preview(rp["info"], rp["status"])
                color = "#0f766e" if _ttkh_can_write(rp) else "#b45309"
                c[4].markdown(
                    f"<div style='font-size:.82rem;line-height:1.35;color:{color};font-weight:700'>{_esc(preview)}</div>",
                    unsafe_allow_html=True,
                )
            else:
                c[4].caption("Dán TTKH để app phân loại địa chỉ cũ/mới.")
            btn_cols = c[5].columns([1.1, 4])
            if btn_cols[0].button("💾 Ghi dòng này", key=f"ttkh_save_row_{oid}", use_container_width=True):
                if row_pending:
                    _write_ttkh_rows(row_pending)
                else:
                    st.warning(f"Chưa dán TTKH cho đơn {code}.")
            if row_pending:
                _st = row_pending[0]["status"]
                _label = "Sẵn sàng ghi" if _ttkh_can_write(row_pending[0]) else _st
                btn_cols[1].caption(f"Trạng thái dòng: {_label}")
            old_note = str(r.get("Ghi chú hiện tại") or "").strip()
            if old_note:
                c[5].caption(f"Ghi chú cũ: {old_note[:120]}" + ("..." if len(old_note) > 120 else ""))
        pending_here = _collect_ttkh_rows(rows)
        ready_here = sum(1 for r in pending_here if _ttkh_can_write(r))
        save_cols = st.columns([1.6, 1, 5])
        if ready_here:
            save_cols[0].caption(f"Sẵn sàng ghi: {ready_here} đơn trong bảng này")
        if save_cols[1].button("💾 Ghi SAPO", key=f"ttkh_save_{label}", use_container_width=True):
            if pending_here:
                _write_ttkh_rows(pending_here)
            else:
                st.warning("Chưa có dòng TTKH nào được dán trong bảng này.")
        return df


    with _tabA:
        if "ttkh_pending_inputs" not in st.session_state:
            st.session_state["ttkh_pending_inputs"] = {}

        _top = st.columns([1, 1.3, 1, 4.7])
        _days = _top[0].number_input("Số ngày gần nhất", min_value=1, max_value=30, value=15, step=1)
        _channel_label = _top[1].selectbox("Kênh", ["TikTok Shop", "Shopee", "Tất cả"], index=0)
        _channel_filter = {"TikTok Shop": "tiktok", "Shopee": "shopee", "Tất cả": "all"}[_channel_label]
        if _top[2].button("🔄 Tải lại", use_container_width=True):
            st.cache_data.clear()
            st.rerun()

        try:
            _tt = load_ttkh_candidates(int(_days), _channel_filter)
        except Exception as _e:
            st.error(f"❌ Lỗi lọc đơn TTKH: `{_e}`")
            _tt = {"multi": [], "single": [], "total": 0, "generated_at_vn": "Lỗi tải"}

        st.markdown("##### 🔎 Đơn cần lấy TTKH")
        _m = st.columns(4)
        _m[0].metric("Tổng cần lấy", _tt["total"])
        _m[1].metric("Đơn ≥ 2 SP", len(_tt["multi"]))
        _m[2].metric("Đơn 1 SP", len(_tt["single"]))
        _m[3].metric("Cập nhật", _tt["generated_at_vn"])

        # ── HÀNG SỐ LIỆU: bên trái = đơn CẦN lấy, bên phải = đã LƯU 30 ngày (luôn hiện) ──
        # Gom số liệu thống kê 30 ngày trước để hiện metric (bảng chi tiết để trong expander)
        _stat_rows, _tot_saved, _tot_ok, _tot_fail = [], 0, 0, 0
        _fail_log, _latest_log, _ok_codes, _had_fail_codes = {}, {}, set(), set()
        _stat_msg = ""
        if not picklog.configured():
            _stat_msg = "⚠️ Chưa bật kho lưu Gist (`[picklog].github_token`) nên chưa thống kê được."
        else:
            try:
                _logs = picklog.read_ttkh_logs()
            except Exception as _e:
                _logs, _stat_msg = [], f"Không đọc được lịch sử: `{_e}`"
            _today_vn = (datetime.now(timezone.utc) + timedelta(hours=7)).date()
            _from = (_today_vn - timedelta(days=29)).isoformat()
            _rows_by_day = {}
            _fail_log = {}   # ma_don -> lỗi gần nhất từng phát sinh
            _latest_log = {} # ma_don -> log mới nhất trong 30 ngày
            _had_fail_codes = set()
            _ok_codes = set()
            _logs_30d = []
            for _lg in _logs:
                _d = str(_lg.get("ngay") or "")
                if _d < _from:
                    continue
                _logs_30d.append(_lg)
            for _lg in sorted(_logs_30d, key=lambda x: str(x.get("ts") or f"{x.get('ngay') or ''} {x.get('gio') or ''}")):
                _d = str(_lg.get("ngay") or "")
                _kq = _lg.get("ket_qua")
                _code = str(_lg.get("ma_don") or "")
                if _code and not _ttkh_order_code_plausible(_code):
                    continue
                _agg = _rows_by_day.setdefault(_d, {"Ngày": _d, "Thành công": 0, "Thất bại": 0, "Bỏ qua": 0})
                if _code:
                    _latest_log[_code] = _lg
                if _kq == "thanh_cong":
                    _agg["Thành công"] += 1
                    _ok_codes.add(_code)
                elif _kq == "bo_qua":
                    _agg["Bỏ qua"] += 1
                else:
                    _agg["Thất bại"] += 1
                    if _code:
                        _had_fail_codes.add(_code)
                        _fail_log[_code] = {"Mã đơn": _code, "SĐT": _lg.get("sdt") or "",
                                            "Lúc": f"{_lg.get('gio') or ''} {_d}".strip(),
                                            "Lý do": _lg.get("ly_do") or _lg.get("chi_tiet") or "",
                                            "Link khách": _lg.get("link_khach") or ""}
            for _d in sorted(_rows_by_day, reverse=True):
                _a = _rows_by_day[_d]
                _a["Tổng đã lưu"] = _a["Thành công"] + _a["Thất bại"]
                _stat_rows.append(_a)
            _tot_saved = sum(r["Tổng đã lưu"] for r in _stat_rows)
            _tot_ok = sum(r["Thành công"] for r in _stat_rows)
            _tot_fail = sum(r["Thất bại"] for r in _stat_rows)

        # (Metric "Đơn cần lấy TTKH" đã chuyển sang tab "Lấy - lưu TTKH")
        # Chỉ tính lỗi CHƯA xử lý (đơn đã ghi lại OK thì không báo lỗi ở trên nữa)
        def _latest_ok(_code):
            return str((_latest_log.get(_code) or {}).get("ket_qua") or "") == "thanh_cong"

        _unresolved_codes = [c for c in _fail_log if not _latest_ok(c)]
        _n_unresolved = len(_unresolved_codes)
        _n_resolved = sum(1 for c in _had_fail_codes if _latest_ok(c))
        st.markdown("##### 📊 Đã lưu TTKH — 30 ngày (nhật ký)")
        _sc = st.columns(4)
        _sc[0].metric("Tổng đã lưu", _tot_saved, help="Tổng số LƯỢT ghi SAPO trong 30 ngày (nhật ký).")
        _sc[1].metric("Thành công", _tot_ok, help="Số lượt tạo được khách.")
        _sc[2].metric("Lỗi đã xử lý", _n_resolved, help="Đơn từng lỗi nhưng ĐÃ ghi/tạo lại được khách.")
        _sc[3].metric("Lỗi chưa xử lý", _n_unresolved,
                      help="Đơn lỗi CHƯA khắc phục. Bấm nút bên dưới để xem danh sách + cách xử lý.")
        if _n_unresolved:
            _sc[3].button("👉 Xem & xử lý", key="ttkh_goto_unresolved", use_container_width=True,
                          on_click=lambda: st.session_state.update(ttkh_show_unresolved=True))
        if st.session_state.get("ttkh_show_unresolved") and _n_unresolved:
            st.warning(f"Còn **{_n_unresolved} đơn lỗi chưa xử lý**. Mở lịch sử bên dưới rồi bấm **Sửa** theo nhóm lỗi.")
        if _stat_msg:
            st.caption(_stat_msg)

        # "1 đơn lỗi" là đơn nào → liệt kê mã đơn lỗi trong nhật ký + link kiểm khách
        if _fail_log:
            _fl_rows = []
            for _c, _rec in _fail_log.items():
                _latest = _latest_log.get(_c) or {}
                _is_latest_ok = _latest_ok(_c)
                _latest_status = "✅ OK" if _is_latest_ok else "❌ Còn lỗi"
                _latest_reason = _latest.get("ly_do") or _latest.get("chi_tiet") or _rec.get("Lý do") or ""
                _group_label = "Đã sửa" if _is_latest_ok else _ttkh_reason_brief(_latest_reason)
                _fl_rows.append({
                    **_rec,
                    "Lúc": f"{_latest.get('gio') or ''} {_latest.get('ngay') or ''}".strip() or _rec.get("Lúc"),
                    "Trạng thái": _latest_status,
                    "Nhóm lỗi": f"{_ttkh_group_icon(_group_label)} {_group_label}",
                    "Lý do": _latest_reason,
                    "Kiểm khách": (f"https://vitranboutiquehcm.mysapo.net/admin/customers?query={quote_plus(_rec['SĐT'])}"
                                   if _rec.get("SĐT") else ""),
                    "Mở đơn": f"https://vitranboutiquehcm.mysapo.net/admin/orders?query={quote_plus(_c)}" if _c else "",
                })
            with st.expander(f"🔎 Lịch sử lỗi ({len(_fl_rows)} đơn)",
                             expanded=_n_unresolved > 0 and _n_unresolved <= 5):
                _history_df = pd.DataFrame(_fl_rows)[["Mã đơn", "SĐT", "Lúc", "Trạng thái", "Nhóm lỗi", "Kiểm khách", "Mở đơn"]]
                st.dataframe(
                    _history_df.style.apply(_ttkh_history_row_style, axis=1),
                    hide_index=True, width="stretch",
                    column_config={
                        "Trạng thái": st.column_config.TextColumn(width="small"),
                        "Nhóm lỗi": st.column_config.TextColumn(width="medium"),
                        "Kiểm khách": st.column_config.LinkColumn("Kiểm khách", display_text="Mở khách"),
                        "Mở đơn": st.column_config.LinkColumn("Mở đơn", display_text="Mở đơn"),
                    })

                _still_bad = [c for c in _fail_log if not _latest_ok(c)]
                _bad_by_group = {}
                for _row in _fl_rows:
                    _code = str(_row.get("Mã đơn") or "").strip()
                    if not _code or _code not in _still_bad:
                        continue
                    _group = _ttkh_error_group_label(_row.get("Lý do"))
                    _bad_by_group.setdefault(_group, []).append(_code)
                if _bad_by_group:
                    st.markdown("**⚡ Sửa nhanh theo nhóm lỗi:**")
                    for _i, (_group, _codes) in enumerate(sorted(_bad_by_group.items(), key=lambda x: (-len(x[1]), x[0]))):
                        _cols_fix = st.columns([3, 1])
                        _cols_fix[0].caption(f"{_group}: {len(_codes)} đơn")
                        if _cols_fix[1].button(f"Sửa {min(len(_codes), 60)}", key=f"ttkh_fix_group_{_i}", use_container_width=True):
                            with st.spinner(f"Đang sửa nhóm '{_group}' ({min(len(_codes), 60)} đơn)…"):
                                st.session_state["ttkh_diag_result"] = _ttkh_repair_customer_from_sapo(_codes[:60], limit=60)
                            load_customer_phone_set.clear()
                with st.expander("Chọn lẻ / xem lý do chi tiết", expanded=False):
                    st.caption("Dùng khi muốn xử lý vài mã cụ thể hoặc cần xem nguyên văn lỗi kỹ thuật.")
                    _detail_df = pd.DataFrame(_fl_rows)[["Mã đơn", "Trạng thái", "Lý do"]]
                    st.dataframe(
                        _detail_df,
                        hide_index=True,
                        width="stretch",
                        column_config={"Lý do": st.column_config.TextColumn(width="large")},
                    )
                    st.caption("Link nhanh: 'Mở khách' tìm theo SĐT, 'Mở đơn' lọc danh sách đơn theo mã.")
                    _allowed_bad = set(_still_bad)
                    st.session_state.pop("ttkh_diag_code", None)
                    _selected_bad = st.multiselect(
                        "Chọn mã lỗi cần sửa",
                        options=_still_bad,
                        default=[],
                        key="ttkh_diag_codes_select",
                        help="Chỉ chọn được mã đang nằm trong lịch sử lỗi phía trên.",
                    )
                    _run_diag = st.button("🔧 Sửa mã đã chọn / tất cả còn lỗi", key="ttkh_diag_fail")
                    if _run_diag:
                        _codes_to_fix = [c for c in _selected_bad if c in _allowed_bad and _ttkh_order_code_plausible(c)][:60] if _selected_bad else _still_bad[:60]
                        if not _codes_to_fix:
                            st.info("Không có đơn lỗi nào để xử lý.")
                        else:
                            with st.spinner(f"Đang kiểm/sửa {len(_codes_to_fix)} đơn lỗi…"):
                                st.session_state["ttkh_diag_result"] = _ttkh_repair_customer_from_sapo(_codes_to_fix, limit=60)
                            load_customer_phone_set.clear()
                if st.session_state.get("ttkh_diag_result"):
                    _diag_result = st.session_state["ttkh_diag_result"]
                    _ok_list = [d for d in _diag_result if d.get("luc")]
                    _bad_list = [d for d in _diag_result if not d.get("luc")]
                    st.markdown("**Kết quả sửa gần nhất:**")
                    _dm = st.columns(3)
                    _dm[0].metric("Đã sửa", len(_ok_list))
                    _dm[1].metric("Còn lỗi", len(_bad_list))
                    _dm[2].metric("Tổng chạy", len(_diag_result))
                    if _ok_list:
                        _last_time = max(d["luc"] for d in _ok_list)
                        st.success(f"Đã cập nhật {len(_ok_list)} khách, hoàn tất lúc {_last_time}.")
                    if _bad_list:
                        st.warning(f"Còn {len(_bad_list)} dòng chưa sửa được. Xem nhóm lỗi trong bảng dưới.")

                    _diag_rows = []
                    for _dg in _diag_result:
                        _k = _dg.get("ket_qua") or _dg.get("Kết quả") or ""
                        _ok = bool(_dg.get("luc"))
                        _brief = "Đã sửa" if _ok else _ttkh_reason_brief(_k)
                        _diag_rows.append({
                            "Mã đơn": _dg.get("Mã đơn"),
                            "SĐT": _dg.get("phone", ""),
                            "Kết quả": f"✅ {_brief}" if _ok else f"{_ttkh_group_icon(_brief)} {_brief}",
                            "Địa chỉ": re.sub(r"\s+", " ", str(_dg.get("dia_chi") or "")).strip()[:120],
                            "Link khách": _dg.get("link_khach", ""),
                        })
                    if _diag_rows:
                        st.dataframe(
                            pd.DataFrame(_diag_rows),
                            hide_index=True,
                            width="stretch",
                            column_config={
                                "Kết quả": st.column_config.TextColumn(width="medium"),
                                "Địa chỉ": st.column_config.TextColumn(width="large"),
                                "Link khách": st.column_config.LinkColumn(width="small"),
                            },
                        )

                    with st.expander("Chi tiết kỹ thuật khi cần kiểm tra", expanded=False):
                        for _dg in _diag_result:
                            _k = _dg.get("ket_qua") or _dg.get("Kết quả") or ""
                            st.markdown(f"**{_dg.get('Mã đơn')}** · SĐT {_dg.get('phone','')} → {_k}")
                            if _dg.get("raw"):
                                _rw = _dg["raw"]
                                st.caption("Dữ liệu thô: "
                                           f"ward={_rw.get('ward_name') or _rw.get('ward') or '-'!r} · "
                                           f"district={_rw.get('district_name') or _rw.get('district') or '-'!r} · "
                                           f"province={_rw.get('province_name') or _rw.get('province') or '-'!r} · "
                                           f"address1={_rw.get('address1') or '-'!r}")
                            _ats = [str(a) for a in (_dg.get("attempts") or ([_dg.get("Chi tiết")] if _dg.get("Chi tiết") else []))]
                            if _ats:
                                st.code("\n".join(_ats[-12:]), language="text")
        with st.expander("📅 Xem lịch sử theo từng ngày (30 ngày)", expanded=False):
            if _stat_rows:
                _daily = pd.DataFrame(_stat_rows).rename(columns={"Thất bại": "Lỗi"})
                st.dataframe(
                    _daily[["Ngày", "Tổng đã lưu", "Thành công", "Lỗi"]],
                    hide_index=True, width="stretch",
                )
                st.caption("Thành công = đã tạo/cập nhật được khách. Lỗi = ghi được ghi chú nhưng chưa tạo được khách.")
            else:
                st.caption("Chưa có lượt lưu TTKH nào trong 30 ngày.")


        st.divider()
        st.markdown("### 🧾 Danh sách đơn — dán TTKH & Ghi SAPO")
        st.info(
            "Bản lưu TTKH mới: chỉ ghi SAPO khi địa chỉ đã phân loại cũ/mới và map đủ mã tỉnh/quận/phường. "
            "Sau khi bấm Ghi SAPO sẽ hiện bảng kết quả: thành công, chưa hoàn tất, lý do lỗi và cách xử lý.",
            icon="✅",
        )
        _show_ttkh_write_results()
        st.caption("Dán nguyên block TTKH vào cột `TTKH dán vào` của đúng mã đơn. Rê chuột vào cột `SL SP` để xem SKU, SL, giá từng món và tổng tiền.")

        # 🔎 Tìm mã đơn → chỉ hiện đúng dòng cần lấy TTKH
        def _clear_ttkh_search():
            st.session_state["ttkh_search"] = ""
            try:
                st.query_params.pop("ttkh_phone", None)
                st.query_params.pop("page_ttkh", None)
            except Exception:
                pass

        _sc = st.columns([3, 1])
        _phone_from_link = _ttkh_phone_key(st.query_params.get("ttkh_phone") or "")
        if _phone_from_link and not str(st.session_state.get("ttkh_search") or "").strip():
            st.session_state["ttkh_search"] = _phone_from_link
        _search = _sc[0].text_input("🔎 Tìm mã đơn / SĐT", key="ttkh_search",
                                    placeholder="Dán/nhập mã đơn hoặc SĐT để nhảy tới đúng dòng…",
                                    label_visibility="collapsed")
        _sc[1].button("Xóa tìm", use_container_width=True, on_click=_clear_ttkh_search)

        def _norm_code(v):
            return re.sub(r"\s+", "", str(v or "")).lower()

        _q = _norm_code(_search)
        _q_phone = _ttkh_phone_key(_search)

        def _match(row):
            if not _q:
                return True
            hay = " ".join(_norm_code(row.get(k)) for k in ("name", "sapo_name", "source_identifier", "shipping_phone"))
            if _q in hay:
                return True
            if _q_phone:
                row_phone = _ttkh_phone_key(row.get("shipping_phone") or "")
                return bool(row_phone and _q_phone == row_phone)
            return False

        _multi = [r for r in _tt["multi"] if _match(r)]
        _single = [r for r in _tt["single"] if _match(r)]
        st.session_state.pop("ttkh_show_failed_only", None)   # bỏ bộ lọc cũ (gây ẩn hết đơn)

        if _q:
            _found = len(_multi) + len(_single)
            if _found:
                st.success(f"🔎 Tìm thấy {_found} đơn khớp `{_search}` — dán TTKH vào dòng bên dưới.")
            else:
                st.warning(f"Không thấy đơn `{_search}` trong danh sách CẦN lấy TTKH. "
                           "Có thể đơn đã lưu đủ 2 nơi, hoặc đã ghi ĐƠN nhưng CHƯA tạo KHÁCH, hoặc bị hủy/ngoài số ngày lọc.")
                st.caption("Đơn đã ghi phần đơn hàng nhưng thiếu khách hàng sẽ bị ẩn. Bấm nút dưới để tra thẳng trong Sapo và đưa nó trở lại danh sách để hoàn tất.")
                if st.button("🔧 Tra Sapo & đưa đơn về danh sách để tạo khách", key="ttkh_lookup_fix"):
                    with st.spinner("Đang tra đơn trong Sapo…"):
                        try:
                            _od = L.find_order_by_code(make_fetch_json(build_session()), _search,
                                                       days=max(int(_days), 30))
                        except Exception as _e:
                            _od = None
                            st.error(f"Lỗi tra cứu: `{_e}`")
                    if _od is None:
                        st.warning("Không tìm thấy đơn này trong Sapo (trong ~30 ngày gần nhất).")
                    elif _od.get("cancelled"):
                        st.info(f"Đơn `{_od['code']}` đã HỦY — không cần lấy TTKH.")
                    elif not _od.get("phone"):
                        st.info(f"Đơn `{_od['code']}` CHƯA có SĐT trên đơn → thuộc diện cần lấy TTKH bình thường. "
                                "Tăng 'Số ngày gần nhất' rồi tìm lại, đơn sẽ hiện trong danh sách.")
                    else:
                        with st.spinner("Đang kiểm tra khách theo SĐT…"):
                            try:
                                _exists = customer_exists_by_phone(build_session(), _od["phone"])
                            except Exception:
                                _exists = False
                        if _exists:
                            st.success(f"✅ Đơn `{_od['code']}` đã ĐỦ 2 nơi — khách SĐT `{_od['phone']}` đã có "
                                       "trong mục Khách hàng. Không cần lấy nữa.")
                        else:
                            try:
                                _ts = (datetime.now(timezone.utc) + timedelta(hours=7)).isoformat(timespec="seconds")
                                picklog.update_ttkh_pending(add={str(_od["order_id"]): {
                                    "ma_don": _od["code"], "sdt": _od["phone"],
                                    "ly_do": "Đã ghi đơn, khách chưa tạo (tra cứu tay)", "ts": _ts}})
                                load_ttkh_candidates.clear()
                                st.success(f"Đã đưa đơn `{_od['code']}` (SĐT `{_od['phone']}`) về danh sách. "
                                           "Đang tải lại — dán TTKH rồi Ghi SAPO để tạo khách.")
                                st.rerun()
                            except Exception as _e:
                                st.error(f"Không đưa được vào danh sách: `{_e}`")

        _df_multi = _ttkh_table("Đơn ≥ 2 SP", _multi)
        _df_single = _ttkh_table("Đơn 1 SP", _single)
        _all_rows = list(_tt["multi"]) + list(_tt["single"])
        if not _all_rows:
            st.caption("Không có đơn để dán TTKH.")

        _pending_write = _collect_ttkh_rows(_all_rows)
        _ready_all = sum(1 for r in _pending_write if _ttkh_can_write(r))
        _invalid_all = len(_pending_write) - _ready_all
        with st.container(key="ttkh_save_float"):
            st.markdown("**💾 Lưu TTKH SAPO**")
            st.caption(f"Sẵn sàng ghi: {_ready_all} · Cần sửa/thiếu mã: {_invalid_all}")
            if st.button("💾 Ghi SAPO", key="ttkh_float_save", use_container_width=True):
                if _pending_write:
                    _write_ttkh_rows(_pending_write)
                else:
                    st.warning("Chưa có dòng TTKH nào được dán.")
            st.caption("Nút này luôn nổi khi cuộn trang.")

        if _pending_write:
            _preview = pd.DataFrame([{
                "Mã đơn": r["code"],
                "Trạng thái": "Sẵn sàng ghi" if _ttkh_can_write(r) else r["status"],
                "Tên": r["info"].get("name", ""),
                "SĐT": r["info"].get("phone", ""),
                "Loại địa chỉ": "Mới" if r["info"].get("address_format") == "new" else "Cũ",
                "Mã SAPO": _ttkh_address_code_status(r["info"]),
                "Mã tỉnh": r["info"].get("province_code", ""),
                "Mã quận": "" if r["info"].get("address_format") == "new" else r["info"].get("district_code", ""),
                "Mã phường": r["info"].get("ward_code", ""),
                "Địa chỉ chuẩn SAPO": _ttkh_address_preview(r["info"], r["status"]),
                "Địa chỉ": ", ".join(x for x in [
                    r["info"].get("address1", ""), r["info"].get("ward", ""),
                    r["info"].get("district", ""), r["info"].get("province", "")
                ] if x),
            } for r in _pending_write])
            st.markdown("#### Kiểm tra TTKH đã dán")
            st.caption("Bảng này là bước chặn trước khi ghi: chỉ dòng `Sẵn sàng ghi` và `Đủ mã SAPO` mới được đẩy sang Sapo.")
            st.dataframe(
                _preview,
                hide_index=True,
                width="stretch",
                column_config={
                    "Địa chỉ chuẩn SAPO": st.column_config.TextColumn(width="large"),
                    "Địa chỉ": st.column_config.TextColumn(width="large"),
                },
            )
            _bad = [r for r in _pending_write if not _ttkh_can_write(r)]
            if _bad:
                st.warning("Một số dòng đã dán TTKH nhưng chưa đủ điều kiện ghi SAPO, app sẽ bỏ qua các dòng đó: "
                           + ", ".join(str(r["code"]) for r in _bad[:10]))
            _ready_preview = sum(1 for r in _pending_write if _ttkh_can_write(r))
            if _ready_preview:
                st.success(f"Sẵn sàng ghi SAPO: {_ready_preview}/{len(_pending_write)} đơn đã đủ mã địa chỉ.")
            else:
                st.warning("Chưa có dòng nào đủ điều kiện ghi SAPO. Kiểm tra lại TTKH hoặc mã tỉnh/quận/phường.")
            if st.button("🧹 Xóa toàn bộ danh sách chờ ghi"):
                st.session_state["ttkh_pending_inputs"] = {}
                _clear_ids = set(st.session_state.get("ttkh_clear_ids") or [])
                for _src in _all_rows:
                    _clear_ids.add(str(_src.get("order_id")))
                st.session_state["ttkh_clear_ids"] = sorted(_clear_ids)
                st.rerun()

    st.stop()


# ════════════════ TRANG BÁO CÁO CUỐI NGÀY (A4) ════════════════
def _render_daily():
    st.title("📄 Báo cáo vận hành cuối ngày")
    st.caption("Tổng hợp tự động từ Sapo + Dohana — bấm **In báo cáo A4** trong khung để in/lưu PDF.  "
               "🎥 *Video Dohana lấy trực tiếp mỗi lần xem (cache ~5 phút); bấm “Tải lại số liệu” để cập nhật ngay.*")
    with st.expander("🔌 Kiểm tra kết nối Dohana (bấm khi video không lên)"):
        st.caption("Bấm để dò Dohana theo TỪNG loại (inbound/package) + xem loại THẬT Dohana trả về.")
        if st.button("Gửi thử tới Dohana", key="dohana_ping_btn"):
            import requests as _rq, time as _tm
            from collections import Counter as _Ct
            try:
                _dk = st.secrets["dohana"]["x_api_key"]
            except Exception:
                _dk = None
            if not _dk:
                st.error("❌ Chưa có key Dohana trong Secrets `[dohana].x_api_key`.")
            else:
                st.caption(f"Key …{str(_dk)[-6:]}")
                _rows, _all_types = [], None
                for _ty in ("inbound", "package", None):
                    _params = {"page": 0, "limit": 30}
                    if _ty:
                        _params["type"] = _ty
                    try:
                        _tm.sleep(0.2)
                        _pr = _rq.get("https://backend.dhn.io.vn/dpm/v1/partner/video/search",
                                      params=_params, headers={"x-api-key": _dk}, timeout=20)
                        if _pr.status_code == 200:
                            _data = (_pr.json() or {}).get("data") or []
                            _codes = ", ".join(str(v.get("orderCode") or "?") for v in _data[:3])
                            _dts = ", ".join(sorted({str(v.get("createdAt") or "")[:10] for v in _data}, reverse=True)[:3])
                            _rows.append({"Lọc type": _ty or "(không lọc)", "HTTP": 200,
                                          "Số video": len(_data), "Mã mẫu": _codes, "Ngày mới": _dts})
                            if _ty is None:
                                _all_types = _Ct(str(v.get("type")) for v in _data)
                        else:
                            _rows.append({"Lọc type": _ty or "(không lọc)", "HTTP": _pr.status_code,
                                          "Số video": "—", "Mã mẫu": _pr.text[:50], "Ngày mới": ""})
                    except Exception as _pe:
                        _rows.append({"Lọc type": _ty or "(không lọc)", "HTTP": "lỗi",
                                      "Số video": "—", "Mã mẫu": str(_pe)[:50], "Ngày mới": ""})
                st.dataframe(pd.DataFrame(_rows), hide_index=True, use_container_width=True)
                if _all_types:
                    st.info("Loại `type` Dohana đang trả (không lọc): " +
                            " · ".join(f"**{_k}** ×{_v}" for _k, _v in _all_types.items()))
                try:
                    _tag_map = dohana._fetch_tag_names()
                except Exception:
                    _tag_map = {}
                if _tag_map:
                    _sample_tags = " · ".join(f"{_name} ({str(_tid)[:8]})"
                                               for _tid, _name in list(_tag_map.items())[:6])
                    st.success(f"✅ Đọc được **{len(_tag_map)} tag** từ DHN API: {_sample_tags}")
                else:
                    st.warning("⚠️ Chưa đọc được danh sách tag từ DHN API `/tag`; app sẽ hiện `Tag chưa map tên (id...)`.")
                st.caption("📸 Chụp bảng + dòng xanh gửi Claude. inbound=0 mà package/không-lọc>0 → clip khui hàng "
                           "nằm ở loại KHÁC → sửa cách lấy. Toàn 401/429 → key/tốc độ.")
        st.divider()
        st.caption("**Kho video** (cột Vid/Tag ở bảng Tổng hợp 30 ngày) chỉ có video ĐÃ fetch được. Dohana vừa bị "
                   "429 nên kho THIẾU → bấm nút này hút lại **~25 ngày** (Dohana chỉ giữ 25 ngày) gộp vào kho.")
        if st.button("🔄 Đồng bộ Dohana ~25 ngày (lấp đầy kho video)", key="dohana_backfill"):
            if not picklog.configured():
                st.error("Chưa cấu hình kho lưu (token picklog).")
            else:
                with st.spinner("Đang lấy ~25 ngày video từ Dohana (có thể ~30 giây)…"):
                    _n0 = len(picklog.read_dohana_videos())
                    _new = []
                    for _fn in (dohana.today_package_videos, dohana.inbound_videos):
                        try:
                            _r = _fn(days_match=25, max_pages=80)
                            if _r:
                                _new += _r.get("records") or []
                        except Exception:
                            pass
                    _merged = picklog.merge_dohana_videos(_new)
                    st.cache_data.clear()
                st.success(f"✅ Đồng bộ xong — kho có **{len(_merged)}** video (thêm {len(_merged) - _n0}). "
                           "Mở lại bảng '📅 Tổng hợp 30 ngày' để thấy Vid/Tag cập nhật.")
                from collections import Counter as _Ct2
                _tc, _sp, _tn = _Ct2(), {}, {}
                for _v in _merged:
                    _tid = _video_tag_id(_v)
                    if _tid:
                        _tc[_tid] += 1
                        _sp.setdefault(_tid, _v.get("code"))
                        _tn.setdefault(_tid, _video_tag_name(_v))
                if _tc:
                    st.markdown("**Tag trong kho** — dòng tên *⚠️ Tag chưa map tên* = CHƯA map được tên tag:")
                    st.dataframe(pd.DataFrame([{
                        "Tên": dohana._tag_name(_t, _tn.get(_t)), "Số video": _c,
                        "Mã mẫu (tra trên Dohana)": _sp.get(_t), "tag_id": _t}
                        for _t, _c in _tc.most_common()]), hide_index=True, use_container_width=True)
                    st.caption("Tra 'Mã mẫu' trên Dohana để biết tên tag → nhắn Claude map giúp, hoặc tự thêm vào "
                               "Secrets `[dohana.tags]`  \"tag_id\" = \"Tên tag\".")
        st.divider()
        _lvq = st.text_input("🔍 Tra 1 mã video trên Dohana (LIVE) — xem LOẠI (type) thật của clip",
                             key="dohana_lookup_code", placeholder="VD: VTPVN9046037201")
        if _lvq and _lvq.strip():
            import requests as _rq2
            try:
                _dk2 = st.secrets["dohana"]["x_api_key"]
            except Exception:
                _dk2 = None
            if not _dk2:
                st.error("Chưa có key Dohana.")
            else:
                try:
                    _pr2 = _rq2.get("https://backend.dhn.io.vn/dpm/v1/partner/video/search",
                                    params={"page": 0, "limit": 20, "orderCode": _lvq.strip()},
                                    headers={"x-api-key": _dk2}, timeout=20)
                    if _pr2.status_code == 200:
                        _dd = (_pr2.json() or {}).get("data") or []
                        if _dd:
                            st.dataframe(pd.DataFrame([{
                                "orderCode": v.get("orderCode"), "type": v.get("type"),
                                "Ngày quay (VN)": dohana._vn_dt(v.get("createdAt")),
                                "thời lượng(s)": v.get("duration"), "status": v.get("status"),
                                "tagId": v.get("tagId")} for v in _dd]),
                                hide_index=True, use_container_width=True)
                            _types = ", ".join(sorted({str(v.get("type")) for v in _dd}))
                            st.info(f"Loại (type) Dohana trả cho mã này: **{_types}**")
                            st.caption("Nếu **type=package** mà đây là clip KHUI HÀNG (nhập hàng hoàn) → NV quay ở "
                                       "chế độ/tài khoản 'ĐÓNG HÀNG'. Báo cáo hoàn chỉ đọc type=**inbound** nên KHÔNG thấy "
                                       "→ cần công cụ ĐỔI LOẠI (Part 4) để clip lên đúng mục hoàn.")
                        else:
                            st.warning(f"Dohana KHÔNG có video mã '{_lvq.strip()}' (kiểm tra lại mã, hoặc ngoài 25 ngày).")
                    else:
                        st.warning(f"Dohana trả mã {_pr2.status_code}: {_pr2.text[:120]}")
                except Exception as _e2:
                    st.error(f"Lỗi tra: {_e2}")
    if not credential_present():
        st.warning("⚠️ Cần kết nối Sapo (API LIVE).")
        return

    # ===== Tổng hợp 7 NGÀY QUA (số cố định sau ngày — query lại là ra số cuối) =====
    # Mở sẵn để bảng tổng hợp và bảng khớp mã bên dưới không bị người dùng bỏ sót.
    with st.expander("📅 Tổng hợp 30 ngày (1 tháng) — đóng gói & đơn hoàn", expanded=True):
        if st.button("🔄 Cập nhật video Dohana ngay", key="week_dohana_refresh_btn",
                     help="Dùng khi app đóng hàng đã có clip mới nhưng bảng 30 ngày vẫn báo thiếu; nút này xoá cache và hút lại Dohana."):
            load_week_summary.clear()
            for _clear_fn in (load_dohana, load_dohana_inbound, load_dohana_videos, load_dohana_video_store):
                try:
                    _clear_fn.clear()
                except Exception:
                    pass
            st.rerun()
        try:
            _wk = load_week_summary()
            _bld = getattr(L, "WEEK_SUMMARY_BUILD", "⚠️ CHƯA nạp code mới — cần Reboot")
            st.caption(f"🔧 Bản dữ liệu: `{_bld}` · cột **Hoàn (đơn)** đếm theo MÃ ĐƠN "
                       "(nhiều kiện/1 đơn chỉ tính 1) — khớp với 'Đã nhận hàng trả' ở báo cáo A4.")
            if _RELOAD_ERR:
                st.warning("Không nạp lại được module (đang chạy bản cũ):\n" + _RELOAD_ERR)
            _NOTE_FILE = "vitran_ghichu_ngay.json"
            _notes = {}
            if picklog.configured():
                try:
                    _notes = picklog._read_gist_file(_NOTE_FILE) or {}
                except Exception:
                    _notes = {}
            for _d in _wk.get("days", []):
                _d["ghi_chu"] = _notes.get(_d.get("iso"), "")
            st.markdown(_week_table_html(_wk), unsafe_allow_html=True)
            _render_week_video_audit(_wk)
            st.caption('Badge cạnh số — **Đóng gói (video):** 🔴 **▼ thiếu** = đơn đã soạn mà chưa gói/quay video · '
                       '🔵 **▲ dư** = quay dư/lộn.  ·  '
                       '**Vid hoàn:** 🔴 **⚠ chưa quay** (đỏ) = còn đơn hoàn CHƯA quay clip khui — số này ĐÃ CỘNG BÙ '
                       'phần tráo/đã dùng (vốn có quay mà không nhập kho) nên **không bị giấu dù Vid hoàn = Hoàn đơn**; '
                       'mở báo cáo A4 ngày đó để biết ĐƠN nào chưa quay · '
                       '🔵 **▲ video lẻ** (xanh) = video khui dư hơn cả đơn hoàn lẫn tráo → NV quay LỘN bên đóng hàng / '
                       'quay dư / quên gắn tag. '
                       '👉 Đơn **tráo / đã dùng / hư** (KHÔNG nhập kho là ĐÚNG) xem ở cột **Tag hoàn**. '
                       'Công thức thiếu clip = **Tag tranh chấp + Hoàn nhập kho − Vid hoàn**. '
                       '**Shipper nhận** nên = **Soạn (đơn) − Hủy sau soạn** (lệch → cảnh báo). '
                       '2 cột hủy (tổng = báo cáo): **Hủy sau soạn** (đỏ) ưu tiên theo mã hủy có nằm trong phiếu nhặt '
                       '(kể cả hôm nay); ngày cũ thiếu mã thì suy ra từ **Soạn − Shipper nhận**, kẹp trong [0, tổng Hủy]. '
                       '**Hủy trước soạn** = Hủy − Hủy sau soạn (khách hủy sớm). '
                       'Nếu Đóng gói(video) *thiếu* đúng bằng Vid hoàn *dư* (hoặc ngược lại) → gần chắc là quay lộn 2 bên. '
                       'Cột **⚠️ Mất hàng (đóng)** (đỏ) = video đóng bị gắn tag *đóng thiếu/sai SP*: soạn & quay đủ '
                       'nhưng cuối bị thiếu → **mất hàng khi đóng**, cần truy. Vạch dọc đậm ngăn khối **Đóng hàng** (xanh) '
                       'với khối **Hoàn hàng** (cam).')
            st.caption('🔑 **Luồng đóng hàng:** **Soạn** (nhặt hàng theo phiếu nhặt — **SL SP** = tổng sản phẩm, '
                       '**SL đơn** = tổng đơn) → **Đóng gói (video)** = số đơn ĐÓNG GÓI THẬT có video → '
                       'Shipper nhận → Giao khách. Soạn (SP/đơn) lấy từ đợt phiếu nhặt đã lưu.')
            st.caption('ℹ️ Cột **Đóng gói (video) / Vid hoàn** tự đồng bộ ~28 ngày gần nhất từ Dohana mỗi khi mở bảng, '
                       'lưu bền vào kho. **Dohana chỉ giữ ~25 ngày** → ngày cũ hơn 25 ngày không đồng bộ lại được: '
                       'nếu kho lúc đó chưa lưu kịp thì badge hiện ⬜ **"kho cũ" (xám)** thay vì "thiếu" đỏ — '
                       'KHÔNG phải NV quên quay. Chỉ đếm video **có gắn mã đơn/mã vận đơn** '
                       '(video không gắn mã không được tính).')
            if picklog.configured():
                st.caption("✏️ Gõ ghi chú theo ngày rồi bấm **Lưu** — sẽ hiện vào cột *Ghi chú* của bảng trên (lưu bền, lần sau mở vẫn còn).")
                _ndf = pd.DataFrame([{"Ngày": d["ngay"], "Thứ": d["thu"], "iso": d["iso"],
                                      "Ghi chú": _notes.get(d["iso"], "")} for d in _wk.get("days", [])])
                _ed = st.data_editor(
                    _ndf, hide_index=True, use_container_width=True, key="week_note_editor",
                    disabled=["Ngày", "Thứ", "iso"],
                    column_config={"iso": None,
                                   "Ngày": st.column_config.TextColumn("Ngày", width="small"),
                                   "Thứ": st.column_config.TextColumn("Thứ", width="small"),
                                   "Ghi chú": st.column_config.TextColumn("Ghi chú", width="large")})
                if st.button("💾 Lưu ghi chú", key="save_week_note"):
                    _out = {r["iso"]: str(r.get("Ghi chú") or "").strip()
                            for r in _ed.to_dict("records") if str(r.get("Ghi chú") or "").strip()}
                    if picklog._write_gist_file(_NOTE_FILE, _out):
                        st.success("✅ Đã lưu ghi chú.")
                        st.rerun()
                    else:
                        st.error("❌ Lưu lỗi (thiếu token picklog?).")
            else:
                st.caption("Ghi chú theo ngày cần cấu hình kho lưu (token picklog).")
        except Exception as e:
            st.warning(f"Chưa lấy được tổng hợp: `{e}`")

    # ===== Chọn ngày xem báo cáo A4 chi tiết =====
    _vn_today = (datetime.now(timezone.utc) + timedelta(hours=7)).date()
    _pick_date = st.date_input("📅 Xem báo cáo A4 ngày (chọn trên LỊCH — tối đa 30 ngày gần nhất)",
                               value=_vn_today, min_value=_vn_today - timedelta(days=30),
                               max_value=_vn_today, format="DD/MM/YYYY", key="daily_pick_date")
    _is_today = (_pick_date == _vn_today)
    _disp = _pick_date.strftime("%d/%m/%Y")
    _sign_on = "1"   # phần ký tên LUÔN đặt ở Trang 1 (mặt trước)

    # ---- Xem báo cáo NGÀY CŨ (query lại Sapo + Dohana theo ngày, số đã cố định) ----
    if not _is_today:
        _iso = _pick_date.isoformat()
        try:
            _rep = load_daily_report(_iso)
        except Exception as e:
            st.error(f"❌ Lỗi tổng hợp báo cáo ngày {_disp}: `{e}`")
            return
        _dvr = load_dohana_date(_iso) if dohana.configured() else None
        _inb = load_dohana_inbound_date(_iso) if dohana.configured() else None
        _enrich_daily(_rep, _dvr, _inb)
        if picklog.configured():
            _ps = picklog.read_date_summary(_iso)
            _apply_picklog_soan_to_daily(_rep, _ps.get("rows") or [], _dvr, _ps.get("dup_orders") or 0)
        _inject_huy_soan(_rep, _iso)
        st.info(f"🗂️ Báo cáo ngày **{_disp}** — query lại từ Sapo, **video lấy từ kho đã lưu** "
                "(Dohana chỉ giữ ~30 ngày; kho Gist lưu bền cả năm). Ngày trước khi bật lưu có thể trống video.")
        _nrep = f"{_disp} (xem lại)"
        _nrec = len((_rep.get("nhap_kho") or {}).get("recon_rows") or [])
        _h = (1 + max(1, (_nrec + 14) // 15 + 1)) * 1140 + 120   # 1 trang 1 + N tờ trang 2 (~15 đơn/tờ, tờ đầu 10)
        components.html(daily_report.report_html(_rep, _dvr, _nrep, sign_on=_sign_on), height=_h, scrolling=True)
        return

    # ---- Hôm nay (trực tiếp) ----
    if st.button("🔄 Tải lại số liệu", key="daily_reload"):
        st.cache_data.clear()
        st.rerun()
    try:
        _rep = load_daily_report()
    except Exception as e:
        st.error(f"❌ Lỗi tổng hợp báo cáo: `{e}`")
        return
    _dvr = load_dohana() if dohana.configured() else None
    _inb = load_dohana_inbound() if dohana.configured() else None
    if (isinstance(_dvr, dict) and _dvr.get("_from_store")) or (isinstance(_inb, dict) and _inb.get("_from_store")):
        st.warning("⚠️ Dohana tạm không phản hồi — đang dùng **video đã lưu trong kho** (có thể thiếu clip "
                   "quay trong vài phút gần nhất). Bấm **🔄 Tải lại số liệu** để thử lấy trực tiếp lại.")
    _enrich_daily(_rep, _dvr, _inb)   # gắn clip khui hàng + đối chiếu video đóng gói
    if picklog.configured():
        _ps = picklog.read_date_summary(_today_iso_vn())
        _apply_picklog_soan_to_daily(_rep, _ps.get("rows") or [], _dvr, _ps.get("dup_orders") or 0)
    _inject_huy_soan(_rep, _today_iso_vn())
    _now_vn = datetime.now(timezone.utc) + timedelta(hours=7)
    _nrep = _now_vn.strftime("%H:%M %d/%m/%Y")
    _nrec = len((_rep.get("nhap_kho") or {}).get("recon_rows") or [])
    _h = (1 + max(1, (_nrec + 14) // 15 + 1)) * 1140 + 120   # 1 trang 1 + N tờ trang 2 (~15 đơn/tờ, tờ đầu 10)
    # Còn xót lại LUÔN rút gọn 5 đơn/ĐVVC cho dễ đọc (collapse_xot mặc định True)
    try:
        components.html(daily_report.report_html(_rep, _dvr, _nrep, sign_on=_sign_on),
                        height=_h, scrolling=True)
    except Exception as _e:   # báo cáo A4 lỗi KHÔNG được làm BIẾN MẤT mục đơn trả hàng bên dưới
        import traceback as _tb
        st.error(f"❌ Lỗi dựng báo cáo A4 (mục đơn trả hàng bên dưới vẫn hiển thị): `{_e}`")
        with st.expander("Chi tiết lỗi (gửi Claude để sửa)"):
            st.code(_tb.format_exc())
    return   # HẾT trang "Báo cáo cuối ngày" — mục đơn trả hàng đã TÁCH sang TRANG RIÊNG (sidebar)


# ═════════════ HÀM RENDER: ĐƠN TRẢ HÀNG ĐANG XỬ LÝ (dùng trong tab Vận hành) ═════════════
def _render_returns():
    st.title("📦 Đơn trả hàng đang xử lý (chưa nhập kho)")


    def _blank_value(value):
        if value is None:
            return True
        try:
            if pd.isna(value):
                return True
        except Exception:
            pass
        return isinstance(value, str) and value.strip() == ""

    def _text_value(value):
        return "" if _blank_value(value) else str(value).strip()

    def _clip_duration_text(value):
        if _blank_value(value):
            return ""
        text = _text_value(value)
        try:
            return f"{int(float(text))}s"
        except Exception:
            return text if text.endswith("s") else text

    def _clip_recorded_text(date_value="", time_value=""):
        date_text = _text_value(date_value)
        time_text = _text_value(time_value)
        if not date_text and not time_text:
            return ""

        # Dohana stores date/time separately, but cached rows may already have a combined value.
        if date_text and not time_text:
            parts = re.split(r"[ T]+", date_text, maxsplit=1)
            if len(parts) == 2:
                date_text, time_text = parts[0].strip(), parts[1].strip()

        date_out = date_text
        m = re.match(r"^(\d{4})[-/](\d{1,2})[-/](\d{1,2})$", date_text)
        if m:
            date_out = f"{int(m.group(3)):02d}/{int(m.group(2)):02d}"
        else:
            m = re.match(r"^(\d{1,2})[-/](\d{1,2})(?:[-/]\d{2,4})?$", date_text)
            if m:
                date_out = f"{int(m.group(1)):02d}/{int(m.group(2)):02d}"

        time_text = re.sub(r"\.\d+$", "", time_text.rstrip("Z")).strip()
        return " ".join(x for x in (date_out, time_text) if x)

    def _clip_recorded_or_missing(row):
        d = row or {}
        recorded = d.get("clip_time")
        if _blank_value(recorded):
            recorded = d.get("clip_recorded")
        text = _clip_recorded_text(recorded)
        if text:
            return text
        has_clip_code = (not _blank_value(d.get("clip_code"))) or (not _blank_value(d.get("_dohana_code")))
        return "không có video" if not has_clip_code else ""

    def _can_edit_return_notes():
        return _auth_configured() and str(CUR_ROLE or "").strip().lower() == "admin"

    def _return_info(text, label="ⓘ"):
        text = str(text or "").strip()
        if not text:
            return
        st.markdown(
            f"<details class='return-info' style='margin:.15rem 0 .35rem'>"
            f"<summary style='cursor:pointer;color:#64748b;font-weight:700'>{_esc(label)}</summary>"
            f"<div style='color:#64748b;font-size:.86rem;line-height:1.35;margin:.25rem 0 .35rem;white-space:pre-wrap'>{_esc(text)}</div>"
            f"</details>",
            unsafe_allow_html=True,
        )

    if not credential_present():
        st.warning("⚠️ Cần kết nối Sapo (API LIVE).")
        return
    if st.button("🔄 Tải lại số liệu", key="returns_reload"):
        st.cache_data.clear()
        st.rerun()
    _return_info(
        "Đơn trả CHƯA nhập kho (năm nay), chia theo loại trả và tình trạng vận chuyển. "
        "Bấm 📋 để copy mã. Dòng tô vàng là đơn cần khiếu nại hoặc chưa có ghi chú chuẩn."
    )
    _return_top_search_slot = st.container()
    _return_top_drill_slot = st.container()

    def _note_has_result(note):
        compact = _note_prefix_compact(note)
        return (
            any(t in compact for t in ("THANG", "THUA", "HUY", "HETHAN"))
            or _compact_is_khong_can_kn(compact)
            or _compact_is_can_kn(compact)
        )

    def _note_has_final_result(note):
        compact = _note_prefix_compact(note)
        return any(t in compact for t in ("THANG", "THUA", "HUY", "HETHAN")) or _compact_is_khong_can_kn(compact)

    def _note_first_line(note):
        lines = [line.strip() for line in str(note or "").splitlines() if line.strip()]
        if not lines:
            return ""
        return lines[0].strip()

    def _note_matches_existing(old_note, new_note):
        old_first = _ascii_code(_note_first_line(old_note))
        new_first = _ascii_code(_note_first_line(new_note))
        if old_first and new_first and old_first == new_first:
            return True
        old_flat = _ascii_code(old_note)
        new_flat = _ascii_code(new_note)
        return bool(new_flat and new_flat in old_flat)

    def _compose_return_note(old_note, new_note, replace_result=False):
        old_note = str(old_note or "").strip()
        new_note = str(new_note or "").strip()
        if not new_note:
            return None, "Thiếu ghi chú"
        if _note_matches_existing(old_note, new_note):
            return None, "Đã khớp, không cần cập nhật"
        if old_note and _note_has_result(old_note) and not replace_result:
            return None, "Bỏ qua vì đã có ghi chú kết quả"
        lines = [line.strip() for line in new_note.splitlines() if line.strip()]
        update_line = ""
        if lines and _ascii_code(lines[-1]).startswith("CAPNHAT"):
            update_line = lines.pop()
        combined_lines = lines
        if old_note:
            combined_lines.append(f"📝 Ghi chú cũ SAPO: {old_note[:180]}")
        if update_line:
            combined_lines.append(update_line)
        combined = "\n".join(combined_lines) if combined_lines else new_note
        if len(combined) > 500 and old_note:
            fixed_tail = f"\n{update_line}" if update_line else ""
            head = "\n".join(lines)
            available = 500 - len(head) - len("\n📝 Ghi chú cũ SAPO: ") - len(fixed_tail)
            clipped_old = (old_note[:max(0, available - 1)] + "…") if available > 1 else ""
            combined_lines = lines
            if clipped_old:
                combined_lines.append(f"📝 Ghi chú cũ SAPO: {clipped_old}")
            if update_line:
                combined_lines.append(update_line)
            combined = "\n".join(combined_lines)
        return combined[:500], "Sẽ ghi"

    def _note_is_bulk_write_result(note):
        compact = _note_prefix_compact(note)
        return (
            any(t in compact for t in ("THANG", "THUA", "HUY", "HETHAN"))
            or _compact_is_khong_can_kn(compact)
            or _compact_is_can_kn(compact)
        )

    _RETURN_NOTE_TEMPLATES = [
        {
            "group": "KHÔNG CẦN KN",
            "label": "Đã nhận hàng hoàn ở Sapo cũ",
            "template": "Không cần KN | Đã nhận hàng hoàn ở Sapo cũ",
        },
        {
            "group": "KHÔNG CẦN KN",
            "label": "Có ảnh/kho xác nhận đã nhận hoàn",
            "template": "Không cần KN | 0đ thất thoát | Có ảnh nhận hoàn",
        },
        {
            "group": "KHÔNG CẦN KN",
            "label": "Shop đóng thiếu thật",
            "template": "Không cần KN | {amount} | Shop đóng thiếu {qty} SP",
        },
        {
            "group": "KHÔNG CẦN KN",
            "label": "Shipper/sàn đã bồi thường",
            "template": "Không cần KN | Shipper đã bồi thường {comp_amount} | Lỗ chênh {loss_amount}",
        },
        {
            "group": "KHÔNG CẦN KN",
            "label": "Yêu cầu hoàn bị hủy",
            "template": "Không cần KN | 0đ | Yêu cầu {platform} bị hủy",
        },
        {
            "group": "THẮNG",
            "label": "KN sàn thành công",
            "template": "✅ THẮNG | Thu hồi {amount} | {platform} KN thành công",
        },
        {
            "group": "THẮNG",
            "label": "Sàn chấp nhận KN theo chat",
            "template": "✅ THẮNG | Thu hồi đủ theo chat {platform} | {platform} KN được chấp nhận",
        },
        {
            "group": "THẮNG",
            "label": "Thu hồi theo lý do khác",
            "template": "✅ THẮNG | Thu hồi {amount} | {reason}",
        },
        {
            "group": "THUA",
            "label": "Đã KN nhưng sàn bác",
            "template": "Thua | Mất {amount} | Đã KN nhưng {platform} bác",
        },
        {
            "group": "THUA",
            "label": "KN không thành công",
            "template": "Thua | {platform} KN không thành công | Mất {amount}",
        },
        {
            "group": "CẦN KN",
            "label": "Cần KN gấp",
            "template": "Cần KN gấp | {amount} | {reason}",
        },
        {
            "group": "CẦN KN",
            "label": "Tiếp tục KN/theo dõi",
            "template": "Cần KN | {amount} | {reason}",
        },
        {
            "group": "HẾT HẠN",
            "label": "Hoàn tiền khách, không bồi thường",
            "template": "Hết hạn | Mất {amount} | Hoàn tiền khách, không bồi thường",
        },
        {
            "group": "HẾT HẠN",
            "label": "Đã giao hoàn, không bồi thường",
            "template": "Hết hạn | Mất {amount} | Đã giao hoàn, không bồi thường",
        },
        {
            "group": "HẾT HẠN",
            "label": "Quá 30 ngày chưa có kết quả thu hồi",
            "template": "Hết hạn | Mất {amount} | Quá 30 ngày chưa có kết quả thu hồi",
        },
        {
            "group": "TỰ NHẬP",
            "label": "Tự nhập nhưng phải đúng prefix chuẩn",
            "template": "{custom_note}",
        },
    ]
    _RETURN_NOTE_TEMPLATE_LABELS = [x["label"] for x in _RETURN_NOTE_TEMPLATES]
    _RETURN_NOTE_TEMPLATE_BY_LABEL = {x["label"]: x for x in _RETURN_NOTE_TEMPLATES}
    _CLOSED_RETURN_NOTE_FILE = "vitran_closed_return_notes.json"
    _CLOSED_RETURN_CONFIRMED_RECEIVED_NOTE = (
        "⚪ KHÔNG CẦN KN | Đã nhận hàng\n"
        "Shipper hoàn: SPX Express; kho đã tìm thấy/đã nhận các kiện hoàn theo VĐ trả về.\n"
        "KQ: Tạm chấp nhận không cần khiếu nại do đơn đã lâu.\n"
        "Cập nhật: 14/07/2026"
    )
    _CLOSED_RETURN_CONFIRMED_RECEIVED = [
        ("260401MFDGA4KF", "2604020QV8QWE3C", "SPXVN060411817964"),
        ("260402QTCDNFKU", "2604040V5QWNXPQ", "SPXVN063847852774"),
        ("260330G8HPXU6D", "2604040V72EKGE8", "SPXVN064399056714"),
        ("260402Q95JW6KP", "26040706NVD20NN", "SPXVN065531264794"),
        ("260402Q62GUA4S", "26040706XXYDXAD", "SPXVN066191637154"),
        ("2604064A4D25RU", "26040707BHT665A", "SPXVN069956421424"),
        ("260402PE53M9GJ", "2604030RWD5H8UC", "SPXVN060517091514"),
        ("260403T7DMM822", "2604080975NJ4Y1", "SPXVN068228865454"),
    ]

    def _closed_return_note_keys(d):
        keys = []
        for field in ("return_code", "order_code", "vd_tra", "vd_di"):
            value = str((d or {}).get(field) or "").strip()
            if value:
                key = f"{field}:{value}"
                if key not in keys:
                    keys.append(key)
        return keys

    def _closed_return_note_key(d):
        keys = _closed_return_note_keys(d)
        return keys[0] if keys else ""

    def _closed_return_app_note_text(rec):
        note = _standard_result_note_text(rec.get("note") if isinstance(rec, dict) else rec or "")
        if not note:
            return ""
        lines = note.splitlines()
        first = lines[0].strip() if lines else ""
        compact_first = _note_prefix_compact(first)
        compact_all = _ascii_code(note)
        is_old_canceled_note = (
            _compact_is_khong_can_kn(compact_first)
            and "SHOPEE" in compact_all
            and any(t in compact_all for t in ("YEUCAUDAHUY", "YEUCAUBIHUY", "DAHUYYEUCAU"))
        )
        if is_old_canceled_note:
            suffix = first.split("|", 1)[1].strip() if "|" in first else "Shopee yêu cầu trả hàng đã hủy"
            lines[0] = f"🚫 HỦY | {suffix}"
            return "\n".join(lines).strip()
        compact_first_full = _ascii_code(first)
        old_received_bad_markers = (
            "THIEU", "SAI", "LOI", "HONG", "VO", "RACH", "GIA", "MAT",
            "CHUANHAN", "CHUADU", "KHONGDU", "KHONGDUNG", "CANBOITHUONG",
        )
        is_final_non_received = any(t in compact_first for t in ("THANG", "THUA", "HUY", "HETHAN"))
        is_received_no_claim_note = (
            "DANHANHANG" in compact_first_full
            and not is_final_non_received
            and not any(t in compact_first_full for t in old_received_bad_markers)
        )
        if is_received_no_claim_note:
            suffix = first.split("|", 1)[1].strip() if "|" in first else "Đã nhận hàng"
            if _ascii_code(suffix) in ("DANHANHANG", "DANHANHANGHOAN"):
                suffix = "Đã nhận hàng"
            lines[0] = f"⚪ KHÔNG CẦN KN | {suffix}"
            return "\n".join(lines).strip()
        return note

    def _load_closed_return_app_notes():
        if not picklog.configured():
            out = {}
        else:
            raw = picklog._read_gist_file(_CLOSED_RETURN_NOTE_FILE) or {}
            notes = raw.get("notes") if isinstance(raw, dict) else {}
            if notes is None and isinstance(raw, dict):
                notes = raw
            if not isinstance(notes, dict):
                notes = {}
            out = {}
            for key, rec in notes.items():
                note = _closed_return_app_note_text(rec)
                if not note:
                    continue
                item = dict(rec) if isinstance(rec, dict) else {}
                item["note"] = note
                out[str(key)] = item
        for order_code, return_code, vd_tra in _CLOSED_RETURN_CONFIRMED_RECEIVED:
            item = {
                "note": _CLOSED_RETURN_CONFIRMED_RECEIVED_NOTE,
                "order_code": order_code,
                "return_code": return_code,
                "vd_tra": vd_tra,
                "updated_at": "2026-07-14 15:00:00",
            }
            out[f"return_code:{return_code}"] = item
            out[f"vd_tra:{vd_tra}"] = item
            out[f"order_code:{order_code}"] = item
        return out

    def _save_closed_return_app_notes(notes):
        if not picklog.configured():
            return False
        clean = {}
        for key, rec in (notes or {}).items():
            note = _closed_return_app_note_text(rec)
            if not note:
                continue
            item = dict(rec) if isinstance(rec, dict) else {}
            item["note"] = note
            clean[str(key)] = item
        payload = {
            "updated_at": (datetime.now(timezone.utc) + timedelta(hours=7)).strftime("%Y-%m-%d %H:%M:%S"),
            "notes": clean,
        }
        return picklog._write_gist_file(_CLOSED_RETURN_NOTE_FILE, payload)

    def _apply_closed_return_app_notes(rows, notes):
        for d in rows or []:
            keys = _closed_return_note_keys(d)
            key = keys[0] if keys else ""
            if key:
                d["_app_note_key"] = key
            note = ""
            for lookup_key in keys:
                note = _closed_return_app_note_text((notes or {}).get(lookup_key))
                if note:
                    break
            if not note:
                continue
            d["sapo_note"] = str(d.get("note") or "").strip()
            d["app_note"] = note
            d["_note_source"] = "App"
            d["note"] = note
        return rows

    def _render_closed_return_app_note_editor(rows, notes):
        if not rows:
            return
        st.markdown("**✍️ Ghi chú app cho đơn Sapo đã đóng**")
        _return_info("Phiếu đã đóng/hủy trên Sapo không ghi chú được nữa, nên ghi chú ở đây sẽ được app dùng để lọc Cần KN.")
        if not _can_edit_return_notes():
            _return_info("Chỉ tài khoản admin mới được ghi hoặc sửa ghi chú app/SAPO. Tài khoản khác chỉ xem dữ liệu.")
            return
        if not picklog.configured():
            st.warning("Chưa cấu hình kho lưu picklog/Gist nên chưa lưu được ghi chú app.")
            return
        row_map = {}
        choices = []
        for d in rows:
            key = d.get("_app_note_key") or _closed_return_note_key(d)
            if key and key not in row_map:
                row_map[key] = d
                choices.append(key)
        if not choices:
            return

        def _note_meta(row, note_text):
            return {
                "note": str(note_text or "").strip(),
                "order_code": row.get("order_code") or "",
                "return_code": row.get("return_code") or "",
                "vd_tra": row.get("vd_tra") or "",
                "vd_di": row.get("vd_di") or "",
                "updated_at": (datetime.now(timezone.utc) + timedelta(hours=7)).strftime("%Y-%m-%d %H:%M:%S"),
            }

        def _upsert_closed_note_aliases(store, row, note_text):
            item = _note_meta(row, note_text)
            keys = _closed_return_note_keys(row)
            if not keys:
                return 0
            for key in keys:
                store[key] = dict(item)
            return len(keys)

        def _delete_closed_note_aliases(store, row):
            removed = 0
            for key in _closed_return_note_keys(row):
                if key in store:
                    store.pop(key, None)
                    removed += 1
            return removed

        def _match_closed_note_keys(text):
            tokens = re.findall(r"[A-Za-z0-9][A-Za-z0-9_\-]{4,}", str(text or ""))
            lookup = {}
            for key, d in row_map.items():
                for field in ("order_code", "return_code", "vd_tra", "vd_di"):
                    val = str(d.get(field) or "").strip()
                    if val:
                        lookup.setdefault(_ascii_code(val), set()).add(key)
            found, missing = [], []
            seen = set()
            for token in tokens:
                keys = lookup.get(_ascii_code(token)) or set()
                if not keys:
                    missing.append(token)
                    continue
                for key in keys:
                    if key not in seen:
                        found.append(key)
                        seen.add(key)
            return found, missing

        def _fmt_choice(key):
            d = row_map.get(key) or {}
            parts = [d.get("created"), d.get("order_code"), d.get("return_code"), d.get("vd_tra")]
            return " · ".join(str(x) for x in parts if str(x or "").strip())

        with st.expander("🧾 Ghi chú hàng loạt", expanded=False):
            _return_info("Dùng khi nhiều đơn cùng một kết luận. Dán mã đơn / mã trả / vận đơn, mỗi dòng một hoặc nhiều mã đều được.")
            quick_codes = st.text_area(
                "Ghi nhanh app - danh sách mã",
                height=80,
                placeholder="VD:\n2607100AM010FE4\nSPXVN069948080037",
                key="closed_return_quick_note_codes",
            )
            quick_note = st.text_area(
                "Ghi nhanh app - ghi chú",
                height=120,
                placeholder="VD: Không cần KN | 0đ | Shopee yêu cầu trả hàng bị hủy\nCập nhật: 13/07/2026",
                key="closed_return_quick_note_text",
            )
            if st.button("🚀 Ghi nhanh app note theo mã", key="closed_return_quick_note_btn", use_container_width=True):
                quick_note = str(quick_note or "").strip()
                if not quick_note or not _note_has_result(quick_note):
                    st.error("Ghi chú nhanh chưa đúng prefix chuẩn.")
                else:
                    keys, missing = _match_closed_note_keys(quick_codes)
                    if not keys:
                        st.error("Chưa khớp được mã nào trong bảng.")
                    else:
                        new_notes = dict(notes or {})
                        for key in keys:
                            _upsert_closed_note_aliases(new_notes, row_map.get(key) or {}, quick_note)
                        if _save_closed_return_app_notes(new_notes):
                            msg = f"Đã lưu ghi chú app cho {len(keys)} đơn."
                            if missing:
                                msg += f" Có {len(missing)} mã không khớp bảng."
                            st.success(msg)
                            st.rerun()
                        else:
                            st.error("Lưu ghi chú app lỗi. Kiểm tra token picklog/Gist.")
            with st.form("closed_return_bulk_same_note_form"):
                bulk_codes = st.text_area(
                    "Danh sách mã cần ghi",
                    height=110,
                    placeholder="VD:\n584904315938637052\n4041276438705046780\nVTPVN9036194182",
                    key="closed_return_bulk_note_codes",
                )
                bulk_note = st.text_area(
                    "Ghi chú áp dụng cho các mã trên",
                    height=120,
                    placeholder="VD: 🚨 CẦN KN | 200.760đ | Khách chưa hoàn đủ hàng\n🕘 Cập nhật: 13/07/2026",
                    key="closed_return_bulk_note_text",
                )
                bulk_save = st.form_submit_button("💾 Lưu hàng loạt theo danh sách mã")
            if bulk_save:
                bulk_note = str(bulk_note or "").strip()
                if not bulk_note or not _note_has_result(bulk_note):
                    st.error("Ghi chú hàng loạt chưa đúng prefix chuẩn.")
                else:
                    keys, missing = _match_closed_note_keys(bulk_codes)
                    if not keys:
                        st.error("Chưa khớp được mã nào trong bảng.")
                    else:
                        new_notes = dict(notes or {})
                        for key in keys:
                            _upsert_closed_note_aliases(new_notes, row_map.get(key) or {}, bulk_note)
                        if _save_closed_return_app_notes(new_notes):
                            msg = f"Đã lưu ghi chú app cho {len(keys)} đơn."
                            if missing:
                                msg += f" Có {len(missing)} mã không khớp bảng."
                            st.success(msg)
                            st.rerun()
                        else:
                            st.error("Lưu ghi chú app lỗi. Kiểm tra token picklog/Gist.")

            _return_info("Hoặc sửa nhiều dòng trực tiếp trong bảng dưới rồi bấm lưu một lần.")
            edit_rows = []
            for key in choices:
                d = row_map.get(key) or {}
                app_note = _closed_return_app_note_text((notes or {}).get(key))
                sapo_note = str(d.get("sapo_note") or ("" if app_note else d.get("note") or "")).strip()
                edit_rows.append({
                    "_key": key,
                    "Ngày tạo": d.get("created") or "",
                    "Mã đơn": d.get("order_code") or "",
                    "Mã trả": _display_return_code(d),
                    "VĐ trả về": d.get("vd_tra") or "",
                    "Ngày giờ quay": _clip_recorded_or_missing(d),
                    "Thời lượng": _clip_duration_text(d.get("clip_dur")),
                    "Ghi chú app": app_note,
                    "Ghi chú Sapo": sapo_note,
                })
            edited_df = st.data_editor(
                pd.DataFrame(edit_rows),
                hide_index=True,
                use_container_width=True,
                key="closed_return_bulk_note_editor",
                disabled=["Ngày tạo", "Mã đơn", "Mã trả", "VĐ trả về", "Ngày giờ quay", "Thời lượng", "Ghi chú Sapo", "_key"],
                column_config={
                    "_key": None,
                    "Ngày tạo": st.column_config.TextColumn("Ngày tạo", width="small"),
                    "Mã đơn": st.column_config.TextColumn("Mã đơn", width="medium"),
                    "Mã trả": st.column_config.TextColumn("Mã trả", width="medium"),
                    "VĐ trả về": st.column_config.TextColumn("VĐ trả về", width="medium"),
                    "Ngày giờ quay": st.column_config.TextColumn("Ngày giờ quay", width="medium"),
                    "Thời lượng": st.column_config.TextColumn("Thời lượng", width="small"),
                    "Ghi chú app": st.column_config.TextColumn("Ghi chú app", width="large"),
                    "Ghi chú Sapo": st.column_config.TextColumn("Ghi chú Sapo", width="large"),
                },
            )
            if st.button("💾 Lưu tất cả dòng đã sửa", key="closed_return_bulk_table_save"):
                new_notes = dict(notes or {})
                invalid = []
                changed = 0
                for rec in edited_df.to_dict("records"):
                    key = str(rec.get("_key") or "")
                    if not key:
                        continue
                    new_note = str(rec.get("Ghi chú app") or "").strip()
                    old_note = _closed_return_app_note_text((notes or {}).get(key))
                    if new_note == old_note:
                        continue
                    if new_note and not _note_has_result(new_note):
                        invalid.append(_fmt_choice(key))
                        continue
                    if new_note:
                        _upsert_closed_note_aliases(new_notes, row_map.get(key) or {}, new_note)
                    else:
                        _delete_closed_note_aliases(new_notes, row_map.get(key) or {})
                    changed += 1
                if invalid:
                    st.error("Có dòng chưa đúng prefix chuẩn, chưa lưu: " + "; ".join(invalid[:6]))
                elif changed == 0:
                    st.info("Không có dòng nào thay đổi.")
                elif _save_closed_return_app_notes(new_notes):
                    st.success(f"Đã lưu {changed} dòng ghi chú app.")
                    st.rerun()
                else:
                    st.error("Lưu ghi chú app lỗi. Kiểm tra token picklog/Gist.")

        with st.expander("✍️ Ghi/chỉnh từng đơn", expanded=False):
            selected = st.selectbox("Chọn đơn cần ghi/chỉnh", choices, format_func=_fmt_choice,
                                    key="closed_return_app_note_select")
            row = row_map.get(selected) or {}
            old_note = _closed_return_app_note_text((notes or {}).get(selected))
            sapo_note = str(row.get("sapo_note") or ("" if old_note else row.get("note") or "")).strip()
            with st.form("closed_return_app_note_form"):
                if sapo_note:
                    st.markdown(
                        f"<details><summary>ⓘ Ghi chú Sapo đang có</summary>"
                        f"<pre style='white-space:pre-wrap;margin:.5rem 0 0'>{_esc(sapo_note)}</pre></details>",
                        unsafe_allow_html=True,
                    )
                note_text = st.text_area(
                    "Ghi chú app",
                    value=old_note,
                    height=140,
                    placeholder="VD: 🚨 CẦN KN | 200.760đ | Khách chưa hoàn đủ hàng\n🕘 Cập nhật: 13/07/2026",
                    key=f"closed_return_app_note_text_{_ascii_code(selected)[:48]}",
                )
                st.markdown(
                    "<details><summary>ⓘ Quy tắc prefix</summary>"
                    "Prefix hợp lệ: THẮNG, THUA, HỦY, HẾT HẠN, KHÔNG CẦN KN, CẦN KN. "
                    "THẮNG/THUA/HỦY/KHÔNG CẦN KN/HẾT HẠN sẽ rớt khỏi Cần KN; CẦN KN vẫn nằm trong bảng Cần KN."
                    "</details>",
                    unsafe_allow_html=True,
                )
                c1, c2, _ = st.columns([1, 1, 4])
                save_btn = c1.form_submit_button("💾 Lưu ghi chú")
                clear_btn = c2.form_submit_button("🧹 Xóa ghi chú app")
            if save_btn or clear_btn:
                new_notes = dict(notes or {})
                if clear_btn:
                    _delete_closed_note_aliases(new_notes, row)
                else:
                    note_text = str(note_text or "").strip()
                    if note_text and not _note_has_result(note_text):
                        st.error("Ghi chú app chưa đúng prefix chuẩn, nên app chưa lưu. Dòng đầu phải có THẮNG / THUA / HẾT HẠN / KHÔNG CẦN KN / CẦN KN.")
                        return
                    if note_text:
                        _upsert_closed_note_aliases(new_notes, row, note_text)
                    else:
                        _delete_closed_note_aliases(new_notes, row)
                if _save_closed_return_app_notes(new_notes):
                    st.success("Đã lưu ghi chú app. Bảng sẽ lọc lại theo ghi chú này.")
                    st.rerun()
                else:
                    st.error("Lưu ghi chú app lỗi. Kiểm tra token picklog/Gist.")

    def _money_text(value, default="0đ"):
        value = str(value or "").strip()
        if not value:
            return default
        return value if value.endswith("đ") else f"{value}đ"

    def _build_return_note_text(template, values, extra, shipper_return="", customer_refund="", compensation="", note_date=""):
        values = dict(values or {})
        for key in ("amount", "comp_amount", "loss_amount"):
            values[key] = _money_text(values.get(key))
        lines = [template.format(**values).strip()]
        shipper_return = str(shipper_return or "").strip()
        customer_refund = str(customer_refund or "").strip()
        compensation = str(compensation or "").strip()
        extra = str(extra or "").strip()
        note_date = str(note_date or "").strip() or (datetime.now(timezone.utc) + timedelta(hours=7)).strftime("%d/%m/%Y")
        if shipper_return:
            lines.append(f"🚚 Shipper hoàn: {shipper_return}")
        if customer_refund or compensation:
            money_parts = []
            if customer_refund:
                money_parts.append(f"Hoàn khách {customer_refund}")
            if compensation:
                money_parts.append(f"Bồi thường shop {compensation}")
            lines.append("💸 " + "; ".join(money_parts))
        if extra:
            lines.append(extra)
        lines.append(f"🕘 Cập nhật: {note_date}")
        note = "\n".join(lines)
        if len(note) <= 500:
            return note
        suffix = f"\n🕘 Cập nhật: {note_date}"
        body = "\n".join(lines[:-1])
        return body[:max(0, 500 - len(suffix))].rstrip() + suffix

    def _note_from_editor_row(row, default_template_label, default_date):
        label = str(row.get("Mẫu ghi chú") or default_template_label or "").strip()
        tpl = _RETURN_NOTE_TEMPLATE_BY_LABEL.get(label) or _RETURN_NOTE_TEMPLATE_BY_LABEL.get(default_template_label)
        template = (tpl or {}).get("template") or "⚪ KHÔNG CẦN KN | Đã nhận hàng hoàn ở Sapo cũ"
        platform = str(row.get("Sàn") or "TikTok").strip() or "TikTok"
        qty_raw = row.get("SL thiếu")
        try:
            qty = int(qty_raw) if not pd.isna(qty_raw) else 1
        except Exception:
            qty = 1
        values = {
            "amount": row.get("Số tiền") or "0đ",
            "comp_amount": row.get("Bồi thường") or "0đ",
            "loss_amount": row.get("Lỗ chênh") or "0đ",
            "qty": qty,
            "platform": platform,
            "reason": str(row.get("Lý do") or "Khách trả sai hàng").strip() or "Khách trả sai hàng",
            "custom_note": str(row.get("Tự nhập") or "").strip(),
        }
        return _build_return_note_text(
            template,
            values,
            str(row.get("Chi tiết") or "").strip(),
            shipper_return=str(row.get("Shipper hoàn") or "").strip(),
            customer_refund=str(row.get("Hoàn khách") or "").strip(),
            compensation=str(row.get("Bồi thường") or "").strip(),
            note_date=str(row.get("Ngày") or default_date or "").strip(),
        )

    def _build_individual_editor_rows(rows, default_template_label, default_date):
        out = []
        for row in rows:
            if row.get("Kết quả") != "Tìm thấy":
                continue
            out.append({
                "Ghi": True,
                "Ngày tạo": row.get("Ngày tạo") or "",
                "Mã đơn": row.get("Mã đơn") or "",
                "Mã trả": _display_return_code(row, order_code=row.get("Mã đơn"), return_code=row.get("Mã trả")),
                "VĐ đi": row.get("VĐ đi") or "",
                "VĐ trả về": row.get("VĐ trả về") or "",
                "_return_id": row.get("_return_id") or "",
                "Sapo ID": row.get("Sapo ID") or row.get("_return_id") or "",
                "Mẫu ghi chú": default_template_label,
                "Sàn": "TikTok",
                "Số tiền": "",
                "Shipper hoàn": "",
                "Hoàn khách": "",
                "Bồi thường": "",
                "Lỗ chênh": "",
                "SL thiếu": 1,
                "Lý do": "",
                "Chi tiết": "",
                "Tự nhập": "Không cần KN | Đã nhận hàng hoàn ở Sapo cũ",
                "Ngày": default_date,
                "Ghi chú hiện tại": row.get("Ghi chú hiện tại") or "",
                "Link hồ sơ trả": row.get("Link hồ sơ trả") or "",
                "_requires_shipper": row.get("_requires_shipper", False),
            })
        return out

    def _full_note_row_keys(row):
        keys = []
        for field in ("Mã trả", "Mã đơn", "VĐ đi", "VĐ trả về", "Sapo ID", "_return_id"):
            value = str((row or {}).get(field) or "").strip()
            if value:
                keys.extend(parse_codes(value))
        return [k for k in dict.fromkeys(keys) if k]

    def _parse_full_note_blocks(text):
        out = {}
        for block in re.split(r"(?m)^\s*-{3,}\s*$", str(text or "")):
            lines = [line.rstrip() for line in block.strip().splitlines()]
            lines = [line for line in lines if line.strip()]
            if len(lines) < 2:
                continue
            codes = parse_codes(lines[0])
            if not codes:
                continue
            note = "\n".join(lines[1:]).strip()
            if note:
                out[codes[0]] = note
        return out

    def _pasted_full_note_for_row(row, note_map):
        note_map = note_map or {}
        for key in _full_note_row_keys(row):
            note = note_map.get(key)
            if note:
                return note
        return ""

    def _build_full_note_editor_rows(rows, allow_final=False, note_map=None):
        out = []
        for row in rows:
            if row.get("Kết quả") != "Tìm thấy":
                continue
            if not allow_final and _note_has_final_result(row.get("Ghi chú hiện tại")):
                continue
            pasted_note = _pasted_full_note_for_row(row, note_map)
            out.append({
                "Ghi": True,
                "Ngày tạo": row.get("Ngày tạo") or "",
                "Mã đơn": row.get("Mã đơn") or "",
                "Mã trả": _display_return_code(row, order_code=row.get("Mã đơn"), return_code=row.get("Mã trả")),
                "VĐ đi": row.get("VĐ đi") or "",
                "VĐ trả về": row.get("VĐ trả về") or "",
                "Hồ sơ": row.get("Link hồ sơ trả") or "",
                "Sapo ID": row.get("Sapo ID") or row.get("_return_id") or "",
                "Ghi chú hiện tại": row.get("Ghi chú hiện tại") or "",
                "Ghi chú mới": pasted_note,
                "_return_id": row.get("_return_id") or "",
                "_requires_shipper": row.get("_requires_shipper", False),
            })
        return out

    def _return_note_rows(codes, max_pages):
        session = build_session()
        matches = find_order_returns_by_codes(session, codes, max_pages=max_pages)
        rows = []
        for code in codes:
            found = matches.get(code) or []
            if not found:
                rows.append({
                    "Kết quả": "Không tìm thấy", "Ngày tạo": "", "Mã đơn": code, "Mã trả": "",
                    "VĐ đi": "", "VĐ trả về": "", "_return_id": "", "Sapo ID": "", "Link hồ sơ trả": "",
                    "Ghi chú hiện tại": "",
                })
                continue
            for r in found:
                rid = r.get("id") or ""
                detail = r
                if rid:
                    try:
                        detail = {**r, **(get_order_return(session, rid) or {})}
                    except Exception:
                        detail = r
                order = r.get("order") or {}
                if not order and detail.get("order"):
                    order = detail.get("order") or {}
                si = detail.get("shipping_info") or r.get("shipping_info") or {}
                created_raw = detail.get("created_on") or r.get("created_on") or ""
                try:
                    created_disp = (datetime.fromisoformat(str(created_raw).replace("Z", "").split(".")[0])
                                    + timedelta(hours=7)).strftime("%d/%m %H:%M")
                except Exception:
                    created_disp = ""
                rows.append({
                    "Kết quả": "Tìm thấy",
                    "Ngày tạo": created_disp,
                    "Mã đơn": order.get("name") or "",
                    "Mã trả": detail.get("name") or r.get("name") or "",
                    "VĐ đi": ((si.get("fulfillment_tracking_numbers") or [None])[0]) or "",
                    "VĐ trả về": si.get("tracking_number") or "",
                    "_return_id": str(rid or ""),
                    "Sapo ID": str(rid or ""),
                    "Link hồ sơ trả": f"https://vitranboutiquehcm.mysapo.net/admin/order_returns/{rid}" if rid else "",
                    "Ghi chú hiện tại": detail.get("note") or "",
                    "_requires_shipper": _row_requires_return_shipper(detail),
                })
        return rows, matches

    def _row_requires_return_shipper(row):
        si = row.get("shipping_info") or {}
        return (row.get("return_type") == "return_and_refund") and bool(si.get("tracking_number"))

    def _build_return_note_preview_rows(rows, note_text, replace_result, shipper_return):
        out = []
        for row in rows:
            row = dict(row)
            old_note = row.get("Ghi chú hiện tại") or ""
            if row.get("Kết quả") != "Tìm thấy":
                row["Đối chiếu"] = row.get("Kết quả") or ""
                row["Ghi chú mới dự kiến"] = ""
            elif row.get("_requires_shipper") and not str(shipper_return or "").strip():
                row["Đối chiếu"] = "Thiếu tên shipper hoàn"
                row["Ghi chú mới dự kiến"] = ""
            else:
                new_note, status = _compose_return_note(old_note, note_text, replace_result)
                row["Đối chiếu"] = status
                row["Ghi chú mới dự kiến"] = new_note or ""
            out.append(row)
        return out

    with st.expander("📝 Ghi chú SAPO hàng loạt"):
        _can_write_sapo = _can_edit_return_notes()
        _return_info("Dùng khi đã đối chiếu xong bên ngoài app. App sẽ dò phiếu trả theo mã đơn/mã trả hàng/mã vận đơn rồi ghi note vào SAPO qua API.")
        if not _can_write_sapo:
            st.warning("Chức năng ghi SAPO chỉ mở cho tài khoản admin khi app đã cấu hình đăng nhập.")
        _default_codes = ""
        _code_col, _lookup_col = st.columns([5, 1])
        with _lookup_col:
            if st.button("🧹 Xóa", key="return_note_clear_btn", use_container_width=True):
                st.session_state["return_note_codes"] = ""
                st.session_state.pop("return_note_preview_rows", None)
                st.session_state.pop("return_note_preview_key", None)
                st.session_state.pop("return_note_write_rows", None)
                st.rerun()
        with _code_col:
            _codes_text = st.text_area("Dán mã đơn / mã trả hàng / mã vận đơn", value=_default_codes,
                                        placeholder="VD: 260204RBTMYA9C 582422766280803724 ...",
                                        height=100, key="return_note_codes", disabled=not _can_write_sapo)
        _codes = parse_codes(_codes_text)
        _codes_key = " ".join(_codes)
        with _lookup_col:
            _max_pages = st.number_input("Số trang dò", min_value=10, max_value=300, value=120, step=10,
                                         key="return_note_max_pages")
            if st.button(f"🔎 Dò trước ({len(_codes)} mã)", disabled=(not _codes or not _can_write_sapo),
                         key="return_note_preview_btn", use_container_width=True):
                try:
                    rows, _ = _return_note_rows(_codes, int(_max_pages))
                    st.session_state["return_note_preview_rows"] = rows
                    st.session_state["return_note_preview_key"] = _codes_key
                    st.session_state.pop("return_note_write_rows", None)
                except Exception as e:
                    st.error(f"Dò phiếu trả lỗi: {e}")
        _preview_ready = bool(_codes) and st.session_state.get("return_note_preview_key") == _codes_key
        if _codes and not _preview_ready:
            st.warning("Phải bấm 🔎 Dò trước cho danh sách mã hiện tại rồi mới ghi chú SAPO.")
        _full_note_plan, _full_note_valid = {}, True
        _full_note_mode = False
        _allow_final = False
        _full_note_quick_count = 0
        _quick_write_now = False
        if _preview_ready and st.session_state.get("return_note_preview_rows"):
            _lookup_rows = st.session_state["return_note_preview_rows"]
            _hidden_final_count = sum(
                1 for _r in _lookup_rows
                if _r.get("Kết quả") == "Tìm thấy" and _note_has_final_result(_r.get("Ghi chú hiện tại"))
            )
            _not_found_count = sum(1 for _r in _lookup_rows if _r.get("Kết quả") != "Tìm thấy")
            st.markdown("**Dò mã và ghi chú mới**")
            _full_note_mode = st.checkbox(
                "Ghi full note riêng từng phiếu",
                value=True,
                disabled=not _preview_ready,
                key="return_note_full_note_mode",
            )
            _allow_final = False
            if _full_note_mode:
                _allow_final = st.checkbox(
                    "🔓 Cho ghi chú lại cả phiếu ĐÃ có kết quả cuối (thắng / thua / hết hạn…)",
                    value=False,
                    key="return_note_allow_final",
                    help="Mặc định ẩn phiếu đã có kết quả để khỏi ghi đè nhầm. Bật để sửa / ghi chú lại các phiếu đó.",
                )
            _notice = []
            if _hidden_final_count:
                if _allow_final:
                    _notice.append(f"cho ghi lại {_hidden_final_count} phiếu đã có kết quả cuối")
                else:
                    _notice.append(f"ẩn {_hidden_final_count} phiếu đã có kết quả cuối (tick 🔓 để ghi lại)")
            if _not_found_count:
                _notice.append(f"{_not_found_count} mã không tìm thấy")
            _notice.append("tắt checkbox này nếu muốn dùng phần tạo ghi chú theo mẫu bên dưới")
            _return_info(" · ".join(_notice))
            if _full_note_mode:
                _full_note_blocks = st.text_area(
                    "Dán ghi chú nhanh theo mã",
                    value="",
                    placeholder=(
                        "4041276438705046780\n"
                        "✅ THẮNG | Thu hồi 169.092đ | TikTok đóng yêu cầu trả hàng\n"
                        "Shipper hoàn: J&T Express - 854150388808; đã giao 10/07/2026 11:03.\n"
                        "Cập nhật: 13/07/2026\n"
                        "---\n"
                        "4040980030353606200\n"
                        "✅ THẮNG | Thu hồi 186.760đ | TikTok tranh chấp ủng hộ người bán"
                    ),
                    height=170,
                    key=f"return_note_full_blocks_{_ascii_code(_codes_key)[:50]}",
                    help="Mỗi block: dòng đầu là mã trả/mã đơn/vận đơn/Sapo ID; các dòng sau là ghi chú. Ngăn các block bằng dòng ---.",
                )
                _full_note_map = _parse_full_note_blocks(_full_note_blocks)
                _full_note_blocks_key = _ascii_code(_full_note_blocks)[:32]
                if _full_note_map:
                    _full_note_quick_count = len(_full_note_map)
                    _return_info(f"Đã nhận {len(_full_note_map)} ghi chú dán nhanh; app tự map theo mã trả/mã đơn/vận đơn/Sapo ID.")
                _full_seed_rows = _build_full_note_editor_rows(_lookup_rows, _allow_final, _full_note_map)
                if not _full_seed_rows:
                    _msg = "Không còn phiếu nào cần nhập ghi chú mới: tất cả đã có kết quả cuối hoặc không tìm thấy."
                    if _hidden_final_count and not _allow_final:
                        _msg += " 👉 Tick ô 🔓 ở trên để ghi chú lại các phiếu đã có kết quả."
                    st.info(_msg)
                else:
                    _return_info("Dán nguyên ghi chú chuẩn vào cột `Ghi chú mới`. Mỗi dòng ghi đúng một hồ sơ trả, không gom chung.")
                    _full_editor_df = st.data_editor(
                        pd.DataFrame(_full_seed_rows),
                        use_container_width=True,
                        hide_index=True,
                        height=min(520, 50 * (len(_full_seed_rows) + 1) + 40),
                        key=f"return_note_full_editor_{int(_allow_final)}_{_ascii_code(_codes_key)[:50]}_{_full_note_blocks_key}",
                        disabled=["Ngày tạo", "Mã đơn", "Mã trả", "VĐ đi", "VĐ trả về", "Hồ sơ", "Sapo ID", "Ghi chú hiện tại", "_return_id", "_requires_shipper"],
                        column_config={
                            "Ghi": st.column_config.CheckboxColumn("Ghi", width="small"),
                            "Ngày tạo": st.column_config.TextColumn("Ngày tạo", width="small"),
                            "Mã đơn": st.column_config.TextColumn("Mã đơn", width="small"),
                            "Mã trả": st.column_config.TextColumn("Mã trả", width="small"),
                            "VĐ đi": st.column_config.TextColumn("VĐ đi", width="small"),
                            "VĐ trả về": st.column_config.TextColumn("VĐ trả về", width="small"),
                            "Hồ sơ": st.column_config.LinkColumn("Mở", width="small", display_text="Mở"),
                            "Sapo ID": st.column_config.TextColumn("Sapo ID", width="small"),
                            "Ghi chú hiện tại": st.column_config.TextColumn("Ghi chú hiện tại", width="large"),
                            "Ghi chú mới": st.column_config.TextColumn("Ghi chú mới", width="large"),
                            "_return_id": None,
                            "_requires_shipper": None,
                        },
                    )
                    for _row in _full_editor_df.to_dict("records"):
                        _rid = str(_row.get("_return_id") or "")
                        if not _rid or not bool(_row.get("Ghi")):
                            continue
                        _row_note = str(_row.get("Ghi chú mới") or "").strip()
                        if not _row_note:
                            continue
                        _note_ascii = _ascii_code(_row_note)
                        if not _note_is_bulk_write_result(_row_note):
                            _status, _new_note = "Ghi chú chưa đúng prefix chuẩn", ""
                            _full_note_valid = False
                        elif _row.get("_requires_shipper") and "SHIPPER" not in _note_ascii:
                            _status, _new_note = "Thiếu dòng/tên shipper hoàn", ""
                            _full_note_valid = False
                        else:
                            _new_note, _status = _compose_return_note(_row.get("Ghi chú hiện tại"), _row_note, True)
                        _full_note_plan[_rid] = {
                            "note": _row_note,
                            "shipper": "co" if "SHIPPER" in _note_ascii else "",
                            "status": _status,
                            "new_note": _new_note or "",
                            "row": _row,
                        }
                    _ready_count = sum(1 for _p in _full_note_plan.values() if _p.get("new_note"))
                    if _ready_count:
                        _return_info(f"Đã sẵn sàng ghi {_ready_count} phiếu. App vẫn kiểm tra prefix chuẩn và tên shipper trước khi cho ghi.")
                    _quick_write_now = st.button(
                        f"🚀 Ghi nhanh {_ready_count} block vào SAPO",
                        disabled=(not _ready_count or not _full_note_valid or not _can_write_sapo),
                        key=f"return_note_quick_write_{_ascii_code(_codes_key)[:50]}_{_full_note_blocks_key}",
                        use_container_width=True,
                    )
        if (not _full_note_mode) and _preview_ready:
            st.markdown("**Tự tạo ghi chú đúng mẫu**")
            _return_info("Dùng phần này khi chị muốn tự soạn bằng mẫu có sẵn. Chỉ ghi Cần KN/Cần KN gấp khi đã kiểm tra sàn và chị duyệt.")
        _groups = []
        for _tpl in _RETURN_NOTE_TEMPLATES:
            if _tpl["group"] not in _groups:
                _groups.append(_tpl["group"])
        if _full_note_mode or not _preview_ready:
            _note_group = _groups[0]
        else:
            _cfg_cols = st.columns([1, 2, 1])
            _note_group = _cfg_cols[0].selectbox("Nhóm kết luận", _groups, key="return_note_group")
        _group_templates = [x for x in _RETURN_NOTE_TEMPLATES if x["group"] == _note_group]
        if _full_note_mode or not _preview_ready:
            _note_label = _group_templates[0]["label"]
            _show_note_details = False
        else:
            _note_label = _cfg_cols[1].selectbox("Mẫu ghi chú chuẩn", [x["label"] for x in _group_templates], key=f"return_note_template_label_{_note_group}")
            _show_note_details = _cfg_cols[2].checkbox("Hiện chi tiết", value=False, key="return_note_show_details")
        _template_row = next(x for x in _group_templates if x["label"] == _note_label)
        _template = _template_row["template"]
        _note_values = {
            "amount": "0đ",
            "comp_amount": "0đ",
            "loss_amount": "0đ",
            "qty": 1,
            "platform": "TikTok",
            "reason": "Khách trả sai hàng",
            "custom_note": "Không cần KN | Đã nhận hàng hoàn ở Sapo cũ",
        }
        _needs_amount = "{amount}" in _template
        _needs_comp = "{comp_amount}" in _template
        _needs_loss = "{loss_amount}" in _template
        _needs_qty = "{qty}" in _template
        _needs_platform = "{platform}" in _template
        _needs_reason = "{reason}" in _template
        _needs_custom = "{custom_note}" in _template
        _return_has_code = False
        _shipper_return = ""
        _note_date = (datetime.now(timezone.utc) + timedelta(hours=7)).strftime("%d/%m/%Y")
        _customer_refund = ""
        _compensation = ""
        _extra_note = ""
        if _show_note_details or _needs_custom:
            _fields = st.columns(3)
            if _needs_amount:
                _note_values["amount"] = _fields[0].text_input("Số tiền", value="0đ", key="return_note_amount")
            if _needs_comp:
                _note_values["comp_amount"] = _fields[0].text_input("Tiền bồi thường", value="0đ", key="return_note_comp_amount")
            if _needs_loss:
                _note_values["loss_amount"] = _fields[1].text_input("Lỗ chênh", value="0đ", key="return_note_loss_amount")
            if _needs_qty:
                _note_values["qty"] = _fields[1].number_input("Số SP thiếu", min_value=1, max_value=99, value=1, step=1, key="return_note_qty")
            if _needs_platform:
                _note_values["platform"] = _fields[2].selectbox("Sàn", ["TikTok", "Shopee", "Sàn"], key="return_note_platform")
            if _needs_reason:
                _note_values["reason"] = st.text_input("Lý do ngắn", value="Khách trả sai hàng", key="return_note_reason")
            if _needs_custom:
                _note_values["custom_note"] = st.text_area(
                    "Ghi chú tự nhập",
                    value="Không cần KN | Đã nhận hàng hoàn ở Sapo cũ",
                    height=70,
                    key="return_note_custom",
                )
            _common = st.columns(3)
            _return_has_code = _common[0].checkbox("Có mã vận đơn hoàn về", value=False, key="return_note_has_return_waybill")
            _shipper_return = _common[1].text_input("Tên shipper hoàn", value="", placeholder="VD: Hồ Hữu Thành - 0382854410 (Viettel Post, giao 27/06)", key="return_note_shipper_return")
            _note_date = _common[2].text_input(
                "Ngày ghi chú",
                value=_note_date,
                key="return_note_update_date",
            )
            _money_common = st.columns(2)
            _customer_refund = _money_common[0].text_input("Hoàn khách", value="", placeholder="VD: 158.746đ", key="return_note_customer_refund")
            _compensation = _money_common[1].text_input("Bồi thường shop", value="", placeholder="VD: 149.408đ hoặc chưa thấy", key="return_note_compensation")
            _extra_note = st.text_area(
                "Chi tiết bổ sung sau dòng kết luận (không bắt buộc)",
                value="",
                placeholder="VD: 🚩 Khách: Mặt hàng quá lớn/quá nhỏ. / ✅ Ảnh kho: ... / 📌 Cần làm: ...",
                height=70,
                key="return_note_extra",
            )
        _note_text = _build_return_note_text(
            _template, _note_values, _extra_note,
            shipper_return=_shipper_return,
            customer_refund=_customer_refund,
            compensation=_compensation,
            note_date=_note_date,
        )
        if _show_note_details:
            st.markdown("**Xem trước ghi chú chung**")
            st.code(_note_text, language="text")
        _note_valid = _note_is_bulk_write_result(_note_text)
        _shipper_valid = (not _return_has_code) or bool(str(_shipper_return or "").strip())
        if _full_note_mode or not _preview_ready:
            _replace_result = bool(_full_note_mode and _allow_final)   # full-note: theo ô 🔓 "cho ghi lại"
            _individual_mode = False
        else:
            _replace_result = st.checkbox("Cho phép đổi các ghi chú kết quả cũ sang ghi chú mới", value=False,
                                          key="return_note_replace_result")
            _individual_mode = st.checkbox(
                "Tự ghi theo mẫu từng mã",
                value=False,
                disabled=not _preview_ready,
                key="return_note_individual_mode",
            )
        _individual_plan, _individual_valid = {}, True
        if _individual_mode and _preview_ready and st.session_state.get("return_note_preview_rows"):
            _seed_rows = _build_individual_editor_rows(
                st.session_state["return_note_preview_rows"], _note_label, _note_date
            )
            _return_info("Chỉ sửa các cột cần thiết. Ghi chú đầy đủ được ẩn bên dưới trong mục xem trước.")
            _editor_df = st.data_editor(
                pd.DataFrame(_seed_rows),
                use_container_width=True,
                hide_index=True,
                height=min(420, 38 * (len(_seed_rows) + 1) + 40),
                key=f"return_note_individual_editor_{_ascii_code(_codes_key)[:50]}",
                disabled=["Ngày tạo", "Mã đơn", "Mã trả", "VĐ đi", "VĐ trả về", "Sapo ID", "_return_id", "Ghi chú hiện tại", "Link hồ sơ trả", "_requires_shipper"],
                column_config={
                    "Ghi": st.column_config.CheckboxColumn("Ghi"),
                    "Mẫu ghi chú": st.column_config.SelectboxColumn("Mẫu ghi chú", options=_RETURN_NOTE_TEMPLATE_LABELS),
                    "Sàn": st.column_config.SelectboxColumn("Sàn", options=["TikTok", "Shopee", "Sàn"]),
                    "SL thiếu": st.column_config.NumberColumn("SL thiếu", min_value=1, max_value=99, step=1),
                    "Sapo ID": st.column_config.TextColumn("Sapo ID", width="small"),
                    "Ghi chú hiện tại": st.column_config.TextColumn("Ghi chú hiện tại", width="large"),
                    "Link hồ sơ trả": st.column_config.LinkColumn("Link hồ sơ trả"),
                    "_return_id": None,
                    "_requires_shipper": None,
                },
            )
            _preview_individual = []
            for _row in _editor_df.to_dict("records"):
                _rid = str(_row.get("_return_id") or "")
                if not _rid or not bool(_row.get("Ghi")):
                    continue
                _row_note = _note_from_editor_row(_row, _note_label, _note_date)
                if _row.get("_requires_shipper") and not str(_row.get("Shipper hoàn") or "").strip():
                    _status, _new_note = "Thiếu tên shipper hoàn", ""
                    _individual_valid = False
                elif not _note_is_bulk_write_result(_row_note):
                    _status, _new_note = "Ghi chú chưa đúng prefix chuẩn", ""
                    _individual_valid = False
                else:
                    _new_note, _status = _compose_return_note(_row.get("Ghi chú hiện tại"), _row_note, _replace_result)
                _individual_plan[_rid] = {
                    "note": _row_note,
                    "shipper": str(_row.get("Shipper hoàn") or "").strip(),
                    "status": _status,
                    "new_note": _new_note or "",
                    "row": _row,
                }
                _preview_individual.append({
                    "Ngày tạo": _row.get("Ngày tạo") or "",
                    "Mã đơn": _row.get("Mã đơn") or "",
                    "Mã trả": _row.get("Mã trả") or "",
                    "Sapo ID": _row.get("Sapo ID") or _row.get("_return_id") or "",
                    "VĐ đi": _row.get("VĐ đi") or "",
                    "VĐ trả về": _row.get("VĐ trả về") or "",
                    "Đối chiếu": _status,
                    "Ghi chú sẽ ghi": _new_note or "",
                })
            with st.expander("👁️ Xem ghi chú sẽ ghi từng dòng", expanded=False):
                if _preview_individual:
                    st.dataframe(
                        pd.DataFrame(_preview_individual),
                        use_container_width=True,
                        hide_index=True,
                        column_config={"Ghi chú sẽ ghi": st.column_config.TextColumn("Ghi chú sẽ ghi", width="large")},
                    )
                else:
                    _return_info("Chưa chọn dòng nào để ghi.")
        if not _note_valid:
            st.error("Ghi chú chưa đúng chuẩn. Dòng đầu phải bắt đầu bằng ✅ THẮNG / Thua / Hết hạn / Không cần KN / Cần KN.")
        if not _shipper_valid:
            st.error("Nếu có mã vận đơn hoàn về thì bắt buộc điền tên shipper hoàn. Nếu chưa có tên shipper, đơn vẫn phải để nhóm CẦN KN/theo dõi, chưa chốt kết quả.")
        if _individual_mode and not _individual_valid:
            st.error("Bảng ghi chú riêng từng mã còn dòng thiếu thông tin hoặc sai prefix chuẩn.")
        if _full_note_mode and not _full_note_valid:
            st.error("Bảng agent còn dòng thiếu thông tin hoặc sai prefix chuẩn.")
        _return_info("Khi ghi thật, app sẽ tự chèn ghi chú cũ SAPO của từng phiếu vào dòng kế cuối, ngay trước dòng Cập nhật. "
                     "Tool này chỉ ghi vào ghi chú hồ sơ trả hàng, là nơi bảng KN đang đọc kết quả.")
        _confirm_write = st.checkbox("Tôi xác nhận ghi chú các phiếu tìm thấy vào SAPO", value=False,
                                     key="return_note_confirm_write")
        _confirm_ready = _confirm_write or bool(_full_note_mode and _full_note_quick_count)
        if _full_note_mode and _full_note_quick_count:
            _return_info("Đã dán ghi chú nhanh theo mã nên có thể bấm ghi trực tiếp; không cần tick ô xác nhận.")
        _write_clicked = st.button(
            "✍️ Ghi chú vào SAPO",
            disabled=(not _codes or not _preview_ready or not _confirm_ready or not _can_write_sapo
                      or (_full_note_mode and (not _full_note_plan or not _full_note_valid))
                      or ((not _full_note_mode) and (not _individual_mode) and (not _note_valid or not _shipper_valid))
                      or ((not _full_note_mode) and _individual_mode and (not _individual_plan or not _individual_valid))),
            key="return_note_write_btn",
        )
        if _quick_write_now or _write_clicked:
            results = []
            try:
                rows, matches = _return_note_rows(_codes, int(_max_pages))
                targets = {}
                for code in _codes:
                    for r in matches.get(code) or []:
                        rid = str(r.get("id") or "")
                        if not rid:
                            continue
                        targets.setdefault(rid, {"row": r, "codes": []})["codes"].append(code)
                session = build_session()
                for rid, info in targets.items():
                    r = info["row"]
                    try:
                        r = {**r, **(get_order_return(session, rid) or {})}
                    except Exception:
                        pass
                    order = r.get("order") or {}
                    order_name = order.get("name") or ""
                    return_name = r.get("name") or ""
                    display_return_name = _display_return_code({}, order_name, return_name)
                    if _full_note_mode:
                        _plan = _full_note_plan.get(str(rid))
                        if not _plan:
                            results.append({
                                "Mã đơn": order_name or ", ".join(info["codes"]),
                                "Mã trả": display_return_name,
                                "Sapo ID": rid,
                                "Link hồ sơ trả": f"https://vitranboutiquehcm.mysapo.net/admin/order_returns/{rid}",
                                "Kết quả": "Bỏ qua: đã có kết quả cuối hoặc chưa nhập ghi chú mới",
                            })
                            continue
                        _note_to_write = _plan["note"]
                        _shipper_for_row = _plan.get("shipper") or ""
                    elif _individual_mode:
                        _plan = _individual_plan.get(str(rid))
                        if not _plan:
                            results.append({
                                "Mã đơn": order_name or ", ".join(info["codes"]),
                                "Mã trả": display_return_name,
                                "Sapo ID": rid,
                                "Link hồ sơ trả": f"https://vitranboutiquehcm.mysapo.net/admin/order_returns/{rid}",
                                "Kết quả": "Bỏ qua: chưa tick ghi dòng này",
                            })
                            continue
                        _note_to_write = _plan["note"]
                        _shipper_for_row = _plan.get("shipper") or ""
                    else:
                        _note_to_write = _note_text
                        _shipper_for_row = _shipper_return
                    if _note_matches_existing(r.get("note"), _note_to_write):
                        results.append({
                            "Mã đơn": order_name or ", ".join(info["codes"]),
                            "Mã trả": display_return_name,
                            "Sapo ID": rid,
                            "Link hồ sơ trả": f"https://vitranboutiquehcm.mysapo.net/admin/order_returns/{rid}",
                            "Kết quả": "Đã khớp, không cần cập nhật",
                        })
                        continue
                    if _row_requires_return_shipper(r) and not str(_shipper_for_row or "").strip():
                        results.append({
                            "Mã đơn": order_name or ", ".join(info["codes"]),
                            "Mã trả": display_return_name,
                            "Sapo ID": rid,
                            "Link hồ sơ trả": f"https://vitranboutiquehcm.mysapo.net/admin/order_returns/{rid}",
                            "Kết quả": "Bỏ qua: phiếu trả hàng hoàn tiền có VĐ trả về nhưng chưa nhập tên shipper hoàn",
                        })
                        continue
                    new_note, status = _compose_return_note(r.get("note"), _note_to_write, _replace_result)
                    if not new_note:
                        results.append({
                            "Mã đơn": order_name or ", ".join(info["codes"]),
                            "Mã trả": display_return_name,
                            "Sapo ID": rid,
                            "Link hồ sơ trả": f"https://vitranboutiquehcm.mysapo.net/admin/order_returns/{rid}",
                            "Kết quả": status,
                        })
                        continue
                    try:
                        update_order_return_note(session, rid, new_note)
                        results.append({
                            "Mã đơn": order_name or ", ".join(info["codes"]),
                            "Mã trả": display_return_name,
                            "Sapo ID": rid,
                            "Link hồ sơ trả": f"https://vitranboutiquehcm.mysapo.net/admin/order_returns/{rid}",
                            "Kết quả": "Đã ghi và xác nhận",
                        })
                    except Exception as e:
                        results.append({
                            "Mã đơn": order_name or ", ".join(info["codes"]),
                            "Mã trả": display_return_name,
                            "Sapo ID": rid,
                            "Link hồ sơ trả": f"https://vitranboutiquehcm.mysapo.net/admin/order_returns/{rid}",
                            "Kết quả": f"Lỗi ghi hồ sơ trả: {e}",
                        })
                missing = [c for c in _codes if not matches.get(c)]
                for code in missing:
                    results.append({"Mã đơn": code, "Mã trả": "", "Sapo ID": "", "Link hồ sơ trả": "", "Kết quả": "Không tìm thấy"})
                st.session_state["return_note_write_rows"] = results
                st.cache_data.clear()
                st.toast(f"Đã xử lý {len(results)} dòng — xem bảng 📋 Kết quả ghi SAPO.", icon="✅")
            except Exception as e:
                st.error(f"Ghi SAPO lỗi: {e}")
        if (not _full_note_mode) and _preview_ready and st.session_state.get("return_note_preview_rows"):
            _preview_rows = _build_return_note_preview_rows(
                st.session_state["return_note_preview_rows"], _note_text, _replace_result, _shipper_return
            )
            _preview_df = pd.DataFrame(_preview_rows)
            if not _preview_df.empty and {"Mã đơn", "Mã trả"}.issubset(_preview_df.columns):
                _preview_df["Mã trả"] = _preview_df.apply(
                    lambda r: _display_return_code({}, r.get("Mã đơn"), r.get("Mã trả")),
                    axis=1,
                )
            _preview_df = _preview_df.drop(columns=[c for c in ["_requires_shipper", "_return_id", "Link hồ sơ trả"] if c in _preview_df.columns])
            with st.expander("Đối chiếu theo mẫu ghi chú đang chọn", expanded=False):
                st.dataframe(_preview_df,
                             use_container_width=True, hide_index=True,
                             column_config={
                                 "Ghi chú hiện tại": st.column_config.TextColumn("Ghi chú hiện tại", width="large"),
                                 "Ghi chú mới dự kiến": st.column_config.TextColumn("Ghi chú mới dự kiến", width="large"),
                                 "Đối chiếu": st.column_config.TextColumn("Đối chiếu", width="medium"),
                             })
        if st.session_state.get("return_note_write_rows"):
            _res = st.session_state["return_note_write_rows"]

            def _res_icon(k):
                k = str(k or "")
                if k == "Đã ghi và xác nhận":
                    return "✅"
                if k.startswith("Lỗi"):
                    return "❌"
                if k == "Không tìm thấy":
                    return "🔍"
                return "⏭️"
            _n_ok = sum(1 for x in _res if x.get("Kết quả") == "Đã ghi và xác nhận")
            _n_err = sum(1 for x in _res if str(x.get("Kết quả") or "").startswith("Lỗi"))
            _n_nf = sum(1 for x in _res if x.get("Kết quả") == "Không tìm thấy")
            _n_skip = len(_res) - _n_ok - _n_err - _n_nf
            st.markdown("### 📋 Kết quả ghi SAPO")
            _k1, _k2, _k3, _k4 = st.columns(4)
            _k1.metric("✅ Đã ghi", _n_ok)
            _k2.metric("⏭️ Bỏ qua", _n_skip)
            _k3.metric("🔍 Không thấy", _n_nf)
            _k4.metric("❌ Lỗi", _n_err)
            if _n_ok:
                st.success(f"✅ Đã ghi thành công **{_n_ok}** phiếu vào SAPO.")
            if _n_skip:
                st.info(f"⏭️ Bỏ qua **{_n_skip}** phiếu (đã khớp / đã có kết quả mà chưa tick 🔓 / chưa tick Ghi).")
            if _n_nf:
                st.warning(f"🔍 **{_n_nf}** mã không tìm thấy (thử tăng 'Số trang dò' hoặc kiểm tra lại mã).")
            if _n_err:
                st.error(f"❌ **{_n_err}** phiếu ghi LỖI — xem cột Kết quả bên dưới.")
            _write_df = pd.DataFrame([{
                "": _res_icon(x.get("Kết quả")),
                "Mã đơn": x.get("Mã đơn", ""),
                "Mã trả": x.get("Mã trả", ""),
                "Sapo ID": x.get("Sapo ID", ""),
                "Kết quả": x.get("Kết quả", ""),
                "Hồ sơ": x.get("Link hồ sơ trả", "") or x.get("Hồ sơ", ""),
            } for x in _res])
            st.dataframe(_write_df,
                         use_container_width=True, hide_index=True,
                         column_config={
                             "": st.column_config.TextColumn("", width="small"),
                             "Sapo ID": st.column_config.TextColumn("Sapo ID", width="small"),
                             "Kết quả": st.column_config.TextColumn("Kết quả", width="large"),
                             "Hồ sơ": st.column_config.LinkColumn("Mở", width="small", display_text="Mở"),
                         })

    try:
        _rip = load_returns_inprogress()
    except Exception as _e:
        _rip = None
        st.warning(f"Chưa lấy được đơn trả đang xử lý: `{_e}`")
    if _rip:
        # KẾT QUẢ KHIẾU NẠI (đang xử lý năm nay): Thắng/Thua/Không cần KN/Hết hạn theo prefix note;
        # CẦN KN = TỰ TÍNH (đơn đang xử lý hơn 5 ngày, chưa có ghi chú kết quả).
        _oc = _rip.get("outcomes") or {}

        def _vnd(m):
            return f"{int(m or 0):,}".replace(",", ".") + "đ"

        def _ocard(col, label, cat):
            o = _oc.get(cat)
            if not isinstance(o, dict):     # chống cache cũ (số phẳng) → không vỡ trang
                o = {"n": int(o or 0), "money": 0}
            col.metric(label, f"{o.get('n', 0):,} đơn")
            col.caption(f"💰 {_vnd(o.get('money', 0))}")

        def _note_is_khong_can_kn(d):
            compact = _note_prefix_compact(d.get("note"))
            return bool(d.get("khong_can_kn_note")) or _compact_is_khong_can_kn(compact)

        def _has_return_waybill(d):
            return bool(str((d or {}).get("vd_tra") or "").strip())

        def _is_refund_only(d):
            return (str((d or {}).get("loai_tra_code") or "").strip().lower() == "refund"
                    and str((d or {}).get("ship_code") or "").strip().lower() == "no_return")

        def _is_need_kn_shape(d):
            return _has_return_waybill(d) or _is_refund_only(d) or bool((d or {}).get("_restock_novideo"))

        def _drop_need_kn_without_return_waybill(rows):
            for d in rows or []:
                if not _has_return_waybill(d) and not _is_refund_only(d):
                    d["need_kn"] = False
            return rows

        _detail_rows = _drop_need_kn_without_return_waybill(_rip.get("detail") or [])
        _khong_can_kn_list = [d for d in _detail_rows if _note_is_khong_can_kn(d)]
        _ckn_list = [d for d in _detail_rows if d.get("need_kn") and _is_need_kn_shape(d)]
        _no_return_list = [d for d in _detail_rows if d.get("ship_code") == "no_return"]
        _khong_can_kn_money = sum(int(d.get("khong_can_kn_money")
                                      if d.get("khong_can_kn_money") is not None
                                      else d.get("money") or 0)
                                  for d in _khong_can_kn_list)
        _ckn_money = sum(int(d.get("money") or 0) for d in _ckn_list)
        _oc = dict(_oc)
        _oc["khong_kn"] = {"n": len(_khong_can_kn_list), "money": _khong_can_kn_money}
        _oc["can_kn"] = {"n": len(_ckn_list), "money": _ckn_money}
        _tabs = st.tabs(["📊 Đang xử lý", "📈 Thống kê", "🎥 Kho video"])
        with _tabs[1]:
            st.markdown("##### 🧾 Kết quả khiếu nại (đang xử lý năm nay)")
            _mo = st.columns(5)
            _ocard(_mo[0], "🟢 Thắng (thu hồi)", "thang")
            _ocard(_mo[1], "🔴 Thua (mất tiền)", "thua")
            _ocard(_mo[2], "⛔ Không cần KN (đã xử lý)", "khong_kn")
            _ocard(_mo[3], "🚨 Cần KN (tự tính)", "can_kn")
            _ocard(_mo[4], "⚫ Hết hạn (mất tiền)", "het_han")
            _mo[2].markdown(f"[👉 Xem {len(_khong_can_kn_list)} đơn](#don-khong-can-kn)")
            _mo[3].markdown(f"[👉 Lấy {len(_ckn_list)} đơn KN](#don-can-kn)")
            _total_returns = int(_rip.get("total_returns") or _rip.get("total") or len(_rip.get("detail") or []))

            def _note_amount(note, fallback=0):
                import re
                m = re.search(r"(\d[\d.]*)\s*đ", str(note or ""))
                if not m:
                    return int(fallback or 0)
                try:
                    return int(m.group(1).replace(".", ""))
                except Exception:
                    return int(fallback or 0)

            def _stock_group(d):
                sc = str(d.get("stock_code") or "").lower()
                if sc in ("stocked", "restocked"):
                    return "Đã nhập kho"
                if "partial" in sc or "partially" in sc:
                    return "Nhập kho 1 phần"
                if sc in ("unstocked", "unrestock", "not_stocked", "not_restocked", "no_stock", "no_restock"):
                    return "Không nhập kho"
                return "Chưa nhập kho"

            def _note_compact(d):
                pre = _ascii_code(str(d.get("note") or "").split("|")[0])
                return "".join(ch for ch in pre if ch.isalnum())

            def _is_closed_kn_result(d):
                compact = _note_compact(d)
                return ("THANG" in compact or "THUA" in compact or "HUY" in compact or "HETHAN" in compact
                        or _compact_is_khong_can_kn(compact))

            def _return_outcome(d):
                if _stock_group(d) == "Đã nhập kho":
                    return "Đã nhập kho"
                compact = _note_compact(d)
                if "THANG" in compact:
                    return "Thắng"
                if "THUA" in compact:
                    return "Thua"
                if "HUY" in compact:
                    return "Hủy"
                if "HETHAN" in compact:
                    return "Hết hạn"
                if "KHONGCANKN" in compact or "KHONGCANKHIEUNAI" in compact:
                    return "Không cần KN"
                if "DANGKN" in compact or "DANGKHANGNGHI" in compact or "DANGXULY" in compact:
                    return "Đang KN"
                if d.get("need_kn"):
                    return "Cần KN"
                return "Chưa chốt"

            _all_returns_detail = _drop_need_kn_without_return_waybill(_rip.get("all_detail") or _detail_rows)
            _canceled_returns_detail = _drop_need_kn_without_return_waybill(_rip.get("canceled_detail") or [])
            _closed_returns_loaded_full_year = bool(st.session_state.get("closed_returns_full_year_loaded"))
            _closed_returns_capped = bool(_rip.get("canceled_capped"))
            if _closed_returns_loaded_full_year:
                try:
                    _closed_rip = load_closed_returns_full_year()
                    _canceled_returns_detail = _drop_need_kn_without_return_waybill(_closed_rip.get("canceled_detail") or [])
                    _closed_returns_capped = bool(_closed_rip.get("canceled_capped"))
                except Exception as _e:
                    st.warning(f"Chưa quét được đơn trả bị đóng cả năm: `{_e}`")
                    st.session_state["closed_returns_full_year_loaded"] = False
            _closed_return_app_notes = _load_closed_return_app_notes()
            _apply_closed_return_app_notes(_canceled_returns_detail, _closed_return_app_notes)

            def _restock_novideo_rows():
                # NGUỒN DUY NHẤT: đúng danh sách còn lại sau cột Chốt video của Báo cáo vận hành cuối ngày.
                # API/Sapo chỉ dùng để bổ sung metadata, không tự quyết định đơn nào vào bảng này.
                if hasattr(_restock_novideo_rows, "_cache"):
                    return [dict(r) for r in _restock_novideo_rows._cache]
                try:
                    _report = load_week_summary()
                    _missing = _report.get("report_return_video_missing") or []
                    _candidates = load_restock_novideo(days=30).get("candidates") or []
                except Exception:
                    return []

                def _ids(value):
                    out = []
                    for token in re.findall(r"[A-Za-z0-9À-ỹĐđ]+", str(value or "")):
                        code = _ascii_code(token)
                        if len(code) >= 6 and any(ch.isdigit() for ch in code):
                            out.append(code)
                    return list(dict.fromkeys(out))

                _candidate_by_code = {}
                for _candidate in _candidates:
                    _codes = list(_candidate.get("codes") or [])
                    _codes += [_candidate.get(k) for k in ("order_code", "return_code", "vd_di", "vd_tra")]
                    for _code in _ids(" ".join(str(v or "") for v in _codes)):
                        _candidate_by_code.setdefault(_code, []).append(_candidate)

                def _label_field(label, pattern):
                    match = re.search(pattern, str(label or ""), flags=re.I)
                    if not match:
                        return ""
                    return " · ".join(_ids(match.group(1)))

                _rows, _used_candidates = [], set()
                for _entry in _missing:
                    _label = str(_entry.get("label") or "")
                    _candidate = None
                    for _code in _ids(_label):
                        _candidate = next((c for c in _candidate_by_code.get(_code, [])
                                           if id(c) not in _used_candidates), None)
                        if _candidate:
                            break
                    if _candidate:
                        _used_candidates.add(id(_candidate))
                        _row = _nv_row_restock(_candidate)
                    else:
                        _row = _nv_row_restock({
                            "order_code": _label_field(_label, r"(?:Mã đơn|Ma don)\s*:\s*([^|]+)"),
                            "return_code": _label_field(_label, r"(?:Mã trả|Ma tra)\s*:\s*([^|]+)"),
                            "vd_di": _label_field(_label, r"(?:VĐ đi/đóng|VD di/dong|VĐ đi|VD di)\s*:\s*([^|]+)"),
                            "vd_tra": _label_field(_label, r"(?:VĐ hoàn|VD hoan)\s*:\s*([^|]+)"),
                            "ngay_tao": _entry.get("date") or "",
                            "restock_date": _entry.get("date") or "",
                        })
                    _row["_reason_label"] = "❌ Nhân viên nhập kho sai"
                    _row["_report_video_age"] = _entry.get("age") or ""
                    _row["_report_video_missing"] = True
                    _rows.append(_row)
                _apply_closed_return_app_notes(_rows, _closed_return_app_notes)
                # KÉO ghi chú CHUẨN từ CÁC BẢNG KHÁC: nếu đơn (mã trả/mã đơn/VĐ) TRÙNG 1 dòng ở bảng khác
                # mà dòng đó ĐÃ có ghi chú chuẩn → dùng luôn ghi chú đó (hết tô vàng + tự rớt khỏi Cần KN).
                _pool_note = {}
                for _pd in (_return_match_detail or []):
                    _pn = str(_pd.get("note") or "").strip()
                    if not (_pn and _note_is_standard(_pn)):
                        continue
                    _concl = _note_is_concluded(_pn)
                    for _pf in ("return_code", "order_code", "vd_tra", "vd_di"):
                        _pv = _search_norm(_pd.get(_pf))
                        if not _pv:
                            continue
                        _old = _pool_note.get(_pv)
                        if _old is None or (_concl and not _note_is_concluded(_old)):
                            _pool_note[_pv] = _pn          # ưu tiên ghi chú ĐÃ KẾT LUẬN
                for _d in _rows:
                    if _note_is_concluded(_d.get("note", "")):
                        continue                          # đã kết luận rồi → khỏi kéo
                    for _pf in ("return_code", "order_code", "vd_tra", "vd_di"):
                        _pv = _search_norm(_d.get(_pf))
                        if _pv and _pv in _pool_note:
                            _d["note"] = _pool_note[_pv]   # kéo ghi chú (kết luận nếu có; không thì "CẦN KN")
                            break
                for _d in _rows:
                    # HẾT tô vàng / rớt Cần KN CHỈ khi ĐÃ KẾT LUẬN. Note "CẦN KN" = vẫn cần KN → GIỮ vàng.
                    _d["need_kn"] = not _note_is_concluded(_d.get("note", ""))
                _restock_novideo_rows._cache = [dict(r) for r in _rows]
                return _rows
            _closed_returns_with_waybill_detail = [
                d for d in _canceled_returns_detail
                if str(d.get("vd_tra") or "").strip()
            ]
            _closed_returns_need_kn_detail = []
            for _d in _closed_returns_with_waybill_detail:
                if not _is_closed_kn_result(_d):
                    _d["need_kn"] = True
                    _d["_location"] = "Đơn trả hàng bị đóng có VĐ trả về"
                    _d["_kn_priority"] = 0
                    _reason = str(_d.get("reason") or "").strip()
                    _extra = "chưa có ghi chú chốt"
                    _d["reason"] = (_reason if _extra in _reason.lower()
                                    else (f"{_reason} — {_extra}" if _reason else f"Đơn trả hàng bị đóng có VĐ trả về — {_extra}"))
                    _closed_returns_need_kn_detail.append(_d)
            _return_match_detail = _all_returns_detail + _canceled_returns_detail
            _stock_order = ["Đã nhập kho", "Chưa nhập kho", "Nhập kho 1 phần", "Không nhập kho"]
            _stock_colors = {
                "Đã nhập kho": "#1D9E75",
                "Chưa nhập kho": "#F59E0B",
                "Nhập kho 1 phần": "#378ADD",
                "Không nhập kho": "#E24B4A",
            }
            _stock_rows = []
            for _label in _stock_order:
                _n = sum(1 for d in _all_returns_detail if _stock_group(d) == _label)
                _stock_rows.append({
                    "Nhóm": _label,
                    "Số đơn": _n,
                    "Tỉ lệ": (_n / _total_returns * 100) if _total_returns else 0,
                    "Màu": _stock_colors[_label],
                })
            _stock_df = pd.DataFrame(_stock_rows)
            st.markdown("##### 📈 Cơ cấu tổng đơn trả")
            _summary_cols = st.columns(5)
            _summary_cols[0].metric("Tổng đơn trả (tab Tất cả)", f"{_total_returns:,} đơn")
            _summary_cols[0].caption("Lấy toàn bộ phiếu trả năm nay trong tab Tất cả, loại phiếu hủy/gạch ngang và loại năm 2025.")
            if not _stock_df.empty:
                for _idx, _row in enumerate(_stock_rows, start=1):
                    _summary_cols[_idx].metric(_row["Nhóm"], f"{_row['Số đơn']:,} đơn")
                    _summary_cols[_idx].caption(f"{_row['Tỉ lệ']:.1f}% tổng đơn trả")

            _month_map = {}
            for _d in _all_returns_detail:
                _raw = str(_d.get("created_on") or "")
                try:
                    _dt = datetime.fromisoformat(_raw.replace("Z", "").split(".")[0]) + timedelta(hours=7)
                except Exception:
                    continue
                _key = _dt.strftime("%Y-%m")
                _label = _dt.strftime("%m/%Y")
                _mrow = _month_map.setdefault(_key, {
                    "Tháng": _label,
                    "Tổng đơn trả": 0,
                    "Đã nhập kho": 0,
                    "Chưa nhận/chưa nhập đủ": 0,
                    "Chưa nhập kho": 0,
                    "Nhập kho 1 phần": 0,
                    "Không nhập kho": 0,
                    "Thắng": 0,
                    "Thua": 0,
                    "Hết hạn": 0,
                    "Không cần KN": 0,
                    "Cần KN": 0,
                    "Đang KN": 0,
                    "Chưa chốt": 0,
                    "Mất tiền": 0,
                })
                _mrow["Tổng đơn trả"] += 1
                _sg = _stock_group(_d)
                _mrow[_sg] += 1
                if _sg != "Đã nhập kho":
                    _mrow["Chưa nhận/chưa nhập đủ"] += 1
                    _outcome = _return_outcome(_d)
                    if _outcome in _mrow:
                        _mrow[_outcome] += 1
                    if _outcome in ("Thua", "Hết hạn"):
                        _mrow["Mất tiền"] += _note_amount(_d.get("note"), _d.get("money") or 0)
            _month_rows = [_month_map[k] for k in sorted(_month_map)]
            if _month_rows:
                st.markdown("##### 📅 Thống kê đơn trả theo tháng")
                _month_df = pd.DataFrame(_month_rows)
                _month_show_df = _month_df.copy()
                _month_show_df["Mất tiền"] = _month_show_df["Mất tiền"].map(_vnd)
                st.dataframe(
                    _month_show_df,
                    use_container_width=True,
                    hide_index=True,
                )
                _volume_fig = go.Figure()
                _total_pct = ["100%" for _ in _month_df["Tổng đơn trả"]]
                _received_pct = [
                    f"{(v / t * 100):.1f}%" if t else ""
                    for v, t in zip(_month_df["Đã nhập kho"], _month_df["Tổng đơn trả"])
                ]
                _open_pct = [
                    f"{(v / t * 100):.1f}%" if t else ""
                    for v, t in zip(_month_df["Chưa nhận/chưa nhập đủ"], _month_df["Tổng đơn trả"])
                ]
                _volume_fig.add_bar(
                    x=_month_df["Tháng"], y=_month_df["Tổng đơn trả"], name="Tổng đơn trả",
                    marker_color="#94A3B8", text=_total_pct, textposition="outside",
                )
                _volume_fig.add_bar(
                    x=_month_df["Tháng"], y=_month_df["Đã nhập kho"], name="Đã nhận/đã nhập kho",
                    marker_color="#1D9E75", text=_received_pct, textposition="outside",
                )
                _volume_fig.add_bar(
                    x=_month_df["Tháng"], y=_month_df["Chưa nhận/chưa nhập đủ"], name="Chưa nhận/chưa nhập đủ",
                    marker_color="#F59E0B", text=_open_pct, textposition="outside",
                )
                _volume_fig.update_layout(
                    title="Sản lượng đơn trả theo tháng",
                    height=340,
                    barmode="group",
                    margin=dict(t=54, b=20, l=10, r=10),
                    yaxis=dict(title="Số đơn"),
                    legend=dict(orientation="h", y=1.12, x=0),
                )
                st.plotly_chart(_volume_fig, width="stretch")

                _outcome_fig = go.Figure()
                _outcome_fig.add_bar(x=_month_df["Tháng"], y=_month_df["Thắng"], name="Thắng", marker_color="#1D9E75")
                _outcome_fig.add_bar(x=_month_df["Tháng"], y=_month_df["Thua"], name="Thua", marker_color="#E24B4A")
                _outcome_fig.add_bar(x=_month_df["Tháng"], y=_month_df["Hết hạn"], name="Hết hạn", marker_color="#6B7280")
                _outcome_fig.add_bar(x=_month_df["Tháng"], y=_month_df["Không cần KN"], name="Không cần KN", marker_color="#534AB7")
                _outcome_fig.add_bar(x=_month_df["Tháng"], y=_month_df["Cần KN"], name="Cần KN", marker_color="#F59E0B")
                _outcome_fig.add_bar(x=_month_df["Tháng"], y=_month_df["Đang KN"], name="Đang KN", marker_color="#378ADD")
                _outcome_fig.add_bar(x=_month_df["Tháng"], y=_month_df["Chưa chốt"], name="Chưa chốt", marker_color="#CBD5E1")
                _outcome_fig.add_scatter(
                    x=_month_df["Tháng"], y=_month_df["Mất tiền"], name="Mất tiền",
                    mode="lines+markers+text",
                    text=[_vnd(v) if v else "" for v in _month_df["Mất tiền"]],
                    textposition="top center",
                    yaxis="y2",
                    line=dict(color="#7F1D1D", width=3),
                    marker=dict(size=8),
                )
                _outcome_fig.update_layout(
                    title="Kết quả KN và tiền mất theo tháng",
                    height=390,
                    barmode="stack",
                    margin=dict(t=42, b=20, l=10, r=10),
                    yaxis=dict(title="Số đơn", rangemode="tozero"),
                    yaxis2=dict(title="Mất tiền", overlaying="y", side="right", showgrid=False, rangemode="tozero"),
                    legend=dict(orientation="h", y=1.14, x=0),
                )
                st.plotly_chart(_outcome_fig, width="stretch")

                # Drilldown filter is rendered near the top of the page via _return_top_drill_slot.
            # 🚨 THỐNG KÊ MẤT HÀNG theo ĐVVC + Shipper (Thua + Hết hạn — CHỈ hàng chưa về kho, khớp card)
            _ls = _rip.get("lost_stats") or {}
            _lt = _ls.get("total") or {}
            if _lt.get("n"):
                def _fm(v):
                    return f"{int(v or 0):,}".replace(",", ".") + "đ"
                st.markdown("##### 🚨 Mất hàng theo ĐVVC / Shipper (Thua + Hết hạn)")
                st.markdown(f"**{_lt['n']} đơn** hàng CHƯA về kho · thất thoát **{_fm(_lt['money'])}** "
                            f"_(năm nay — khớp Thua+Hết hạn ở card trên)_")
                _return_info("Tổng theo ĐVVC")
                _dvr = _ls.get("by_dvvc") or []
                st.dataframe(pd.DataFrame([{"ĐVVC": r["dvvc"], "Đơn": r["n"],
                    "Thua/Hết": f"{r['thua']}/{r['het']}", "Tiền mất": _fm(r["money"])}
                    for r in _dvr]), hide_index=True, width="stretch")
                _return_info("Từng shipper & các đơn làm mất (gộp nhóm theo shipper; trong nhóm: mới → cũ)")
                _ords = _ls.get("orders") or []
                if _ords:
                    _dvc = {"J&T Express": "#DC2626", "SPX (Shopee)": "#F97316", "Viettel Post": "#7C3AED",
                            "GHN": "#2563EB", "GHTK": "#16A34A", "Ninja Van": "#DB2777"}
                    _dvbg = {"J&T Express": "#FEF2F2", "SPX (Shopee)": "#FFF7ED", "Viettel Post": "#F5F3FF",
                             "GHN": "#EFF6FF", "GHTK": "#F0FDF4", "Ninja Van": "#FDF2F8"}
                    _thead = "".join(f"<th{s}>{c}</th>" for c, s in
                                     [("STT", ""), ("Shipper", ""), ("SĐT", ""), ("ĐVVC", ""), ("Mã trả", ""),
                                      ("Mã VĐ", ""), ("Ngày", ""), ("KQ", ""), ("Tiền mất", " style='text-align:right'")])
                    _body, _prev, _sn = [], None, 0
                    for o in _ords:
                        _grp = (o["shipper"] != _prev)
                        _sn = 1 if _grp else _sn + 1          # STT reset theo từng shipper (biết mỗi người mấy đơn)
                        _clr = _dvc.get(o["dvvc"], "#94A3B8")
                        _bg = _dvbg.get(o["dvvc"], "#F8FAFC")
                        _sep = "border-top:2px solid #334155;" if (_grp and _prev is not None) else ""
                        _rc = _display_return_code(o, order_code=o.get("order_code") or o.get("code"), return_code=o.get("return_code"))
                        _wb = o.get("waybill") or ""
                        _rccell = (f"{_rc} <span class='cp' onclick=\"cpx('{_rc}',this)\">📋</span>") if _rc else "—"
                        _wbcell = (f"{_wb} <span class='cp' onclick=\"cpx('{_wb}',this)\">📋</span>") if _wb else "—"
                        _kqc = "#DC2626" if o["kind"] == "Thua" else "#6B7280"
                        _body.append(
                            f"<tr style='{_sep}background:{_bg};border-left:4px solid {_clr}'>"
                            f"<td style='color:#64748b'>{_sn}</td>"
                            f"<td style='font-weight:700'>{o['shipper'] if _grp else ''}</td>"
                            f"<td>{(o['phone'] or '—') if _grp else ''}</td>"
                            f"<td style='color:{_clr};font-weight:600'>{o['dvvc'] if _grp else ''}</td>"
                            f"<td>{_rccell}</td><td>{_wbcell}</td>"
                            f"<td>{o['date']}</td>"
                            f"<td style='color:{_kqc};font-weight:600'>{o['kind']}</td>"
                            f"<td style='text-align:right;font-weight:600'>{_fm(o['money'])}</td></tr>")
                        _prev = o["shipper"]
                    _css = ("<style>body{margin:0;font-family:Tahoma,Arial,sans-serif;color:#1f2937}"
                            "table{border-collapse:collapse;font-size:12.5px;width:100%}"
                            "th,td{border:1px solid #e2e6ec;padding:5px 8px;text-align:left;white-space:nowrap}"
                            "th{background:#e2e8f0;font-weight:700}"
                            ".cp{cursor:pointer;opacity:.5;font-size:11px;user-select:none}.cp:hover{opacity:1}</style>")
                    _js = ("<script>function cpx(t,el){var a=document.createElement('textarea');a.value=t;"
                           "a.style.position='fixed';a.style.opacity=0;document.body.appendChild(a);a.focus();a.select();"
                           "try{document.execCommand('copy');}catch(e){}a.remove();"
                           "if(el){var o=el.textContent;el.textContent='✅';setTimeout(function(){el.textContent=o;},900);}}</script>")
                    _doc = ("<!DOCTYPE html><html><head><meta charset='utf-8'>" + _css + "</head><body>"
                            "<div style='overflow-x:auto'><table><thead><tr>" + _thead + "</tr></thead><tbody>"
                            + "".join(_body) + "</tbody></table></div>" + _js + "</body></html>")
                    components.html(_doc, height=min(70 + len(_ords) * 33, 900), scrolling=True)
                _return_info("Bấm nút 📋 để copy mã trả / mã VĐ. STT đếm theo từng shipper, màu = ĐVVC, vạch = đổi shipper. "
                             "Shopee/SPX không ghi tên shipper nên cột Shipper hiện ĐVVC; mã VĐ lấy từ 'VĐ về' trong ghi chú nếu field trống; vài đơn Shopee sàn ẩn sẽ hiện '—'.")
                st.divider()
        with _tabs[0]:
            st.markdown("##### 📊 Đang xử lý (chưa nhập kho)")
            _old_n = sum(1 for d in _rip["detail"] if (d.get("age") or 0) > 5)
            _m = st.columns(5)
            _m[0].metric("Tổng đang xử lý", f"{_rip['total']:,}")
            _m[1].metric("🚚 Đang hoàn hàng", f"{_rip['tot_returning']:,}")
            _m[2].metric("📥 Đã giao người bán", f"{_rip['tot_returned']:,}")
            _m[3].metric("🚫 Không có hàng hoàn về", f"{len(_no_return_list):,}")
            _m[4].metric("🟡 Hơn 5 ngày", f"{_old_n:,}")
            _return_info("🟡 Dòng tô vàng = đơn CẦN KN (hơn 5 ngày và chưa có ghi chú kết quả). "
                         "VĐ đi = mã vận đơn giao đi. VĐ trả về = mã vận đơn hoàn về. "
                         "Giao thất bại: 2 mã trùng nhau; chỉ hoàn tiền: không có kiện hàng hoàn về."
                         + (" Đã chạm giới hạn quét, có thể còn đơn cũ hơn." if _rip.get("capped") else ""))

            def _jss(s):       # escape chuỗi cho onclick JS
                return str(s or "").replace("\\", "\\\\").replace("'", "\\'")

            def _cp(val):      # nút copy 📋 (bấm 1 phát copy mã)
                return (f"<span class='cp' onclick=\"cp('{_jss(val)}',this)\" title='Copy mã'>📋</span>"
                        if val else "")

            def _code_cell(val, link=None, link_copy=None, link_title=None):    # mã + nút copy (kèm link nếu có)
                link = _normalize_shopee_order_link(_normalize_tiktok_order_link(link))
                tiktok_return = bool(link and "seller-vn.tiktok.com/order/return" in link)
                if link and "seller-vn.tiktok.com/order" in link and not tiktok_return and "main_order_id=" not in link:
                    link = _tiktok_order_url(val)
                shopee_detail = bool(link and re.search(r"/portal/sale/order/\d+", link))
                if link and "banhang.shopee.vn/portal/sale/order" in link and not shopee_detail and "search=" not in link:
                    link = _shopee_order_url(val)
                v = _esc(str(val or ""))
                if _is_shopee_chrome_launcher_url(link):
                    disp = (
                        f"<a href='{_esc(link)}' target='_blank' onclick=\"cp('{_jss(val)}',this)\" "
                        f"title='Mo Chrome rieng dung shop Shopee; dong thoi copy ma'>{v}</a>"
                    )
                elif link and "banhang.shopee.vn/portal/sale/order" in link and not shopee_detail:
                    disp = (
                        f"<a href='{_esc(link)}' target='_blank' onclick=\"cp('{_jss(val)}',this)\" "
                        f"title='Shopee khong tu loc tu URL; bam link se copy ma don'>{v}</a>"
                    )
                elif link and "dhn.io.vn/order/inbound" in link:
                    copy_val = str(link_copy if link_copy not in (None, "") else val)
                    title = link_title or "Mo Dohana nhap hang hoan; dong thoi copy ma de dan vao o tim kiem"
                    disp = (
                        f"<a href='{_esc(link)}' target='_blank' onclick=\"cp('{_jss(copy_val)}',this)\" "
                        f"title='{_esc(title)}'>{v}</a>"
                    )
                else:
                    disp = f"<a href='{_esc(link)}' target='_blank'>{v}</a>" if link else v
                return f"{disp} {_cp(val)}" if val else ""

            def _return_code_cell(d):
                code = _display_return_code(d)
                if (d or {}).get("_restock_novideo"):   # bảng nhập-kho-không-video: link đã dựng sẵn (cnsc_shop_id, KHÔNG launcher)
                    return _code_cell(code, str((d or {}).get("return_link") or "")) if code else ""
                link = _normalize_shopee_return_link((d or {}).get("return_link"), code)
                if link and "banhang.shopee.vn/portal/sale/return" in link:
                    is_direct = bool(re.search(r"/portal/sale/return/\d+", link))
                    return_id = str((d or {}).get("sapo_return_id") or "").strip()
                    if not is_direct and return_id:
                        try:
                            detail = load_return_detail_for_link(return_id)
                            direct = L.shopee_return_detail_url(detail, d, keyword=code)
                            if re.search(r"/portal/sale/return/\d+", str(direct or "")):
                                link = direct
                        except Exception:
                            pass
                    link = _shopee_chrome_launcher_url(link, d)
                return _code_cell(code, link) if code else ""

            def _return_waybill_cell(d):
                val = str((d or {}).get("vd_tra") or "").strip()
                code = _dohana_inbound_code_for_row(d)
                link = _dohana_inbound_link_for_row(d)
                title = f"Mo Dohana nhap hang hoan; copy ma {code}" if code else None
                return _code_cell(val or code, link, link_copy=code, link_title=title)

            def _order_link_for_row(d):
                link = str((d or {}).get("order_link") or "").strip()
                if (d or {}).get("_restock_novideo") and link:   # link đã dựng sẵn (cnsc_shop_id, KHÔNG launcher)
                    return link
                src = " ".join(str((d or {}).get(k) or "") for k in (
                    "order_source", "gian_hang", "order_link", "return_link"
                )).lower()
                if "tiktok" in src:
                    code = (
                        (d or {}).get("order_code")
                        or (d or {}).get("Mã đơn")
                        or (d or {}).get("ma_don")
                        or (d or {}).get("order_no")
                    )
                    return _tiktok_order_url(code)
                if "shopee" in src:
                    code = (
                        (d or {}).get("order_code")
                        or (d or {}).get("MÃ£ Ä‘Æ¡n")
                        or (d or {}).get("ma_don")
                        or (d or {}).get("order_no")
                    )
                    return _shopee_chrome_launcher_url(_shopee_order_url(code), d)
                return link

            def _search_norm(s):
                return "".join(ch for ch in _ascii_code(s) if ch.isalnum())

            def _dohana_inbound_url():
                return "https://dhn.io.vn/order/inbound/"

            def _dohana_inbound_code_for_row(d):
                for key in ("clip_code", "_dohana_code", "vd_tra"):
                    val = str((d or {}).get(key) or "").strip()
                    if val:
                        return val
                return ""

            def _dohana_inbound_link_for_row(d):
                code = _dohana_inbound_code_for_row(d)
                return _with_url_query(_dohana_inbound_url(), q=code, orderCode=code) if code else ""

            # Đọc nhanh kho video đã lưu; không gọi live Dohana khi mở trang trả hàng.
            try:
                _dvids = load_dohana_video_store()
            except Exception:
                _dvids = []
            _dohana_inbound_videos = [r for r in _dvids if r.get("type") == "inbound"]

            def _dohana_video_recorded_text(video_row):
                return _clip_recorded_text((video_row or {}).get("date"), (video_row or {}).get("time"))

            def _dohana_inbound_video_for_return_row(d):
                field_order = ("vd_tra", "return_code", "order_code", "vd_di")
                row_codes = [(idx, _search_norm((d or {}).get(key))) for idx, key in enumerate(field_order)]
                row_codes = [(idx, code) for idx, code in row_codes if code]
                if not row_codes:
                    return None
                candidates = []
                for r in _dohana_inbound_videos:
                    code = _search_norm((r or {}).get("code"))
                    if not code:
                        continue
                    exact = [idx for idx, row_code in row_codes if code == row_code]
                    if exact:
                        score = min(exact)
                    else:
                        fuzzy = [
                            idx for idx, row_code in row_codes
                            if len(code) >= 8 and len(row_code) >= 8 and (code in row_code or row_code in code)
                        ]
                        if not fuzzy:
                            continue
                        score = 20 + min(fuzzy)
                    candidates.append((score, _dohana_video_recorded_text(r), r))
                if not candidates:
                    return None
                candidates.sort(key=lambda item: item[1], reverse=True)
                candidates.sort(key=lambda item: item[0])
                return candidates[0][2]

            def _annotate_rows_with_dohana_inbound_video(rows):
                for d in rows or []:
                    video = _dohana_inbound_video_for_return_row(d)
                    if not video:
                        continue
                    d["clip_code"] = str(video.get("code") or "").strip()
                    d["clip_time"] = _dohana_video_recorded_text(video)
                    d["clip_dur"] = video.get("dur")
                    d["clip_link"] = str(video.get("link") or "").strip()
                    d["clip_tag_id"] = _video_tag_id(video)
                    d["clip_tag"] = _video_tag_label(video)

            for _clip_rows in (
                _all_returns_detail,
                _canceled_returns_detail,
                _closed_returns_with_waybill_detail,
                _closed_returns_need_kn_detail,
                _return_match_detail,
            ):
                _annotate_rows_with_dohana_inbound_video(_clip_rows)

            def _row_matches_code(d, needle):
                q = _search_norm(needle)
                if not q:
                    return False
                fields = [
                    d.get("order_code"), d.get("return_code"), d.get("vd_di"), d.get("vd_tra"),
                    d.get("sku"), d.get("note"), d.get("return_shipper"),
                ]
                return any(q in _search_norm(x) for x in fields if x)

            def _row_location(d):
                if d.get("is_canceled"):
                    return "Sapo đã hủy (đối chiếu sàn)"
                if str(d.get("stock_code") or "").lower() in ("stocked", "restocked"):
                    return "Đã nhận/đã nhập kho"
                if _note_is_khong_can_kn(d):
                    return "Không cần KN"
                if d.get("need_kn") and _is_refund_only(d):
                    return "Cần KN — chỉ hoàn tiền chưa có kết luận"
                if not _has_return_waybill(d):
                    return "Không có VĐ trả về / không cần KN"
                if d.get("need_kn"):
                    return "Cần KN"
                if d.get("ship_code") == "no_return":
                    return "Không có hàng hoàn về / chỉ hoàn tiền"
                if d.get("loai_tra_code") == "return_and_refund":
                    return "Trả hàng hoàn tiền"
                if d.get("loai_tra_code") == "delivery_failed":
                    return "Giao hàng thất bại"
                return "Khác"

            def _doisoat(d):   # 1 LINK đối soát TikTok/Shopee, tự chọn tab: note CÓ kết quả KN
                oc = d.get("order_code") or ""              # (🟢✅🔴❌⛔⚪⚫) → "Đã thanh toán"; còn lại → "Chưa thanh toán"
                src = " ".join(str(d.get(k) or "") for k in ("order_source", "gian_hang", "order_link")).lower()
                if oc and "tiktok" in src:                  # channel_type/connection_ids account-specific
                    app, conn, ch = "tiktok-channel", "11589%2C12966%2C19313", "6"
                elif oc and "shopee" in src:
                    app, conn, ch = "shopee-channel", "11588%2C12082%2C12405", "1"
                else:
                    return "<span style='color:#cbd5e1'>—</span>"
                _done = any(m in (d.get("note") or "") for m in ("🟢", "✅", "🔴", "❌", "⛔", "⚪", "⚫"))
                paid, tab = ("true", "Đã") if _done else ("false", "Chờ")
                u = (f"https://vitranboutiquehcm.mysapo.net/admin/apps/{app}/home/"
                     "automation-delivery-collations?query=" + oc +
                     "&connection_ids=" + conn + "&channel_type=" + ch +
                     "&created_on_min=2024-01-01&created_on_max=2027-12-31&paid=" + paid)
                return f"<a href='{_esc(u)}' target='_blank' title='Mở đối soát — tab {tab} thanh toán'>🔍 {tab}</a>"

            def _ticket_cell(d):
                order_code = str((d or {}).get("order_code") or "").strip()
                source = " ".join(str((d or {}).get(k) or "") for k in
                                  ("order_source", "gian_hang", "order_link")).lower()
                if not order_code or "tiktok" not in source:
                    return "<span class='muted'>—</span>"
                ticket_url = _with_url_query(
                    TIKTOK_TICKET_LIST_URL,
                    order_id=order_code,
                    search_type="order_id",
                    tab="all",
                )
                return (
                    f"<a href='{_esc(ticket_url)}' target='_blank' "
                    "onclick=\"var w=window.open(this.href,'_blank');if(w){w.focus();}return false;\" "
                    f"title='Mở tất cả phiếu của đơn {_esc(order_code)}; nếu chưa có thì tạo phiếu ngay'>"
                    "📨 Xem / tạo</a>"
                )

            def _sub_table(items, h, show_type=False, show_reason=False, show_clip=False, merge_delivery_vd=False, show_location=False, pg_key=None, per_page=14, show_ticket=False):
                if not items:
                    st.caption("— Không có —")
                    return
                show_clip = True
                if show_type:   # NHÓM theo LOẠI TRẢ (Chỉ hoàn tiền → Giao thất bại → Trả hàng hoàn tiền)
                    _lt_ord = {"refund": 0, "delivery_failed": 1, "return_and_refund": 2}
                    items = sorted(items, key=lambda d: _lt_ord.get(str((d or {}).get("loai_tra_code") or ""), 9))
                _PER = int(per_page or 14)                  # tối đa N đơn/trang, còn lại qua trang sau
                _start = 0
                if pg_key and len(items) > _PER:
                    _total = len(items)
                    _npages = (_total + _PER - 1) // _PER
                    _pc = st.columns([2, 3])
                    _pg = int(_pc[0].number_input(
                        f"Trang ({_PER} đơn/trang · tổng {_total} đơn · {_npages} trang)",
                        min_value=1, max_value=_npages, value=1, step=1, key=f"rpg_{pg_key}"))
                    _start = (_pg - 1) * _PER
                    items = items[_start:_start + _PER]
                    h = min(h, 92 + 42 * len(items))
                    _pc[1].caption(f"Đang xem đơn {_start + 1}–{_start + len(items)} / {_total}")
                def _safe(v, default=""):
                    return _esc(str(v if v not in (None, "") else default))
                cols = ["STT"]
                if show_reason:
                    cols += ["Lý do KN"]
                if show_ticket:
                    cols += ["Phiếu yêu cầu"]
                cols += ["Ngày tạo", "Mã đơn"]
                cols += ["Mã trả hàng"]
                cols += ["Vận đơn"] if merge_delivery_vd else ["VĐ đi", "VĐ trả về"]
                if show_clip:
                    cols += ["Ngày giờ quay", "Thời lượng"]
                cols += ["Shipper hoàn", "Gian hàng"]
                if show_type:
                    cols += ["Loại trả"]
                cols += ["SKU", "SL", "Tổng tiền", "Nhập kho"]
                cols += ["Đối soát", "Ghi chú"]
                _sticky_n = cols.index("Mã trả hàng") + 1   # cố định các cột đầu → hết "Mã trả hàng"
                thead = "".join(f"<th>{c}</th>" for c in cols)
                def _note_details_cell(text):
                    note_text = str(text or "").strip()
                    if not note_text:
                        return "<span class='muted'>—</span>"
                    first = next((line.strip() for line in note_text.replace("\r", "\n").split("\n") if line.strip()), "xem ghi chú")
                    summary = first if len(first) <= 42 else first[:39].rstrip() + "..."
                    return (
                        f"<details class='note-detail'><summary>{_safe(summary)}</summary>"
                        f"<div>{_safe(note_text)}</div></details>"
                    )
                def _reason_brief_cell(d):
                    _forced = str((d or {}).get("_reason_label") or "").strip()
                    if _forced:      # nhãn ÉP (vd bảng nhập-kho-thiếu-video: cả cột = "NV nhập kho sai")
                        return f"<span class='reason-badge' title='{_safe(_forced)}'>{_safe(_forced)}</span>"
                    raw_reason = str((d or {}).get("reason") or "").strip()
                    raw_location = str((d or {}).get("_location") or _row_location(d) or "").strip()
                    full = " · ".join(x for x in (raw_reason, raw_location) if x) or "Cần kiểm tra"
                    compact = _search_norm(full + " " + str((d or {}).get("_dohana_tag_label") or ""))
                    ship_code = str((d or {}).get("ship_code") or "").strip().lower()
                    stock_code = str((d or {}).get("stock_code") or "").strip().lower()
                    return_type = str((d or {}).get("loai_tra_code") or "").strip().lower()
                    def _age_label():
                        age = (d or {}).get("age")
                        try:
                            age = int(age)
                        except Exception:
                            m = re.search(r"(\d+)\s*ngày", full, flags=re.IGNORECASE)
                            age = int(m.group(1)) if m else 0
                        return f"⏳ Quá hạn {age}n" if age > 0 else "⏳ Hoàn quá hạn"
                    if "DONGTHIEU" in compact:
                        label = "📦 Đóng thiếu"
                    elif "HUHONG" in compact or "HANGHONG" in compact:
                        label = "💥 Hư hỏng"
                    elif "TRATHIEU" in compact or "THIEU" in compact:
                        label = "➖ Trả thiếu"
                    elif "TRAO" in compact or "SAIHANG" in compact or "SAISP" in compact or "KHACVOMOTA" in compact:
                        label = "🔁 Tráo/sai hàng"
                    elif "DASUDUNG" in compact or "DADUNG" in compact or "SUDUNG" in compact:
                        label = "♻️ Đã sử dụng"
                    elif "BITDONG" in compact or "DONGCOVD" in compact or "SAPODAHUY" in compact:
                        label = "🧭 Đơn bị đóng"
                    elif "NHAPKHO1PHAN" in compact or "PARTIAL" in stock_code:
                        label = "📦 Nhập thiếu"
                    elif return_type == "delivery_failed":
                        label = "📕 Giao thất bại"
                    elif ship_code == "returning":
                        label = _age_label()
                    elif ship_code == "returned":
                        label = "📍 Đã giao shop"
                    elif return_type == "refund" and ship_code == "no_return":
                        label = "💸 Chỉ hoàn tiền"
                    elif stock_code in ("unstocked", "unrestock", "not_stocked", "not_restocked", "no_stock", "no_restock"):
                        label = "📦 Kho chưa nhận"
                    elif "QUA5NGAY" in compact or "QUA7NGAY" in compact or "DANGHOAN" in compact:
                        label = _age_label()
                    elif "DOHANATAG" in compact or "CHUACOGHICHUCHUAN" in compact:
                        label = "🏷 Tag chưa chốt"
                    elif "CANKN" in compact:
                        label = _age_label() if (d or {}).get("age") else "⚠️ Chưa chốt KQ"
                    else:
                        label = "⚠️ Chưa có KQ"
                    if len(label) > 20:
                        label = label[:19].rstrip() + "…"
                    return f"<span class='reason-badge' title='{_safe(full)}'>{_safe(label)}</span>"
                body = ""
                _prev_lt = None
                for i, d in enumerate(items, _start + 1):
                    _lt = str(d.get("loai_tra_code") or "")
                    if show_type and _lt != _prev_lt:      # GẠCH NGANG ĐẬM + tên loại khi ĐỔI loại trả
                        body += (f"<tr class='grp-sep'><td colspan='{len(cols)}' style='border-top:3px solid "
                                 f"#334155;background:#e5e7eb;padding:5px 8px'>"
                                 f"<span style='position:sticky;left:8px;display:inline-block;font-weight:800;"
                                 f"color:#111827'>▸ {_safe(d.get('loai_tra') or _lt or '—')}</span></td></tr>")
                        _prev_lt = _lt
                    bg = "background:#fff3cd" if d.get("need_kn") and _is_need_kn_shape(d) else ""
                    note = d.get("note") or ""
                    note_display = f"📝 APP · {note}" if d.get("app_note") else note
                    tds = [f"<td class='r'>{i}</td>"]
                    if show_reason:
                        tds.append(f"<td>{_reason_brief_cell(d)}</td>")
                    if show_ticket:
                        tds.append(f"<td>{_ticket_cell(d)}</td>")
                    tds += [
                        f"<td>{_safe(d.get('created'))}</td>",
                        f"<td>{_code_cell(d['order_code'], _order_link_for_row(d))}</td>",
                    ]
                    tds.append(f"<td>{_return_code_cell(d)}</td>")
                    if merge_delivery_vd:
                        _vd_val = d.get('vd_di') or d.get('vd_tra')
                        if str(d.get("vd_tra") or "").strip():
                            _vd_code = _dohana_inbound_code_for_row(d)
                            tds.append(f"<td>{_code_cell(_vd_val, _dohana_inbound_link_for_row(d), link_copy=_vd_code)}</td>")
                        else:
                            tds.append(f"<td>{_code_cell(_vd_val)}</td>")
                    else:
                        tds.append(f"<td>{_code_cell(d['vd_di'])}</td>")
                        tds.append(f"<td>{_return_waybill_cell(d)}</td>")
                    if show_clip:
                        _clip_title = _safe(d.get("clip_code") or d.get("_dohana_code") or "")
                        _clip_time = _clip_recorded_or_missing(d)
                        _clip_dur = _clip_duration_text(d.get("clip_dur"))
                        _clip_time_html = (
                            f"<span class='no-video'>{_safe(_clip_time)}</span>"
                            if _clip_time == "không có video" else _safe(_clip_time)
                        )
                        tds.append(f"<td title='{_clip_title}'>{_clip_time_html}</td>")
                        tds.append(f"<td class='r' title='{_clip_title}'>{_safe(_clip_dur)}</td>")
                    tds += [
                        f"<td>{_safe(d.get('return_shipper'), 'Chưa có')}</td>",
                        f"<td>{_safe(d.get('gian_hang'))}</td>",
                    ]
                    if show_type:
                        tds.append(f"<td>{_safe(d.get('loai_tra'))}</td>")
                    tds += [f"<td>{_safe(d.get('sku'))}</td>",
                            f"<td class='r'>{int(d.get('qty') or 0)}</td>",
                            f"<td class='r'>{int(d.get('money') or 0):,}đ</td>",
                            f"<td>{_safe(d.get('stock_status'), 'Chưa rõ')}</td>"]
                    tds.append(f"<td>{_doisoat(d)}</td>")
                    tds.append(f"<td class='note'>{_note_details_cell(note_display)}</td>")
                    body += f"<tr style='{bg}'>" + "".join(tds) + "</tr>"
                html = f"""<style>
 body{{margin:0;font-family:Tahoma,Arial,sans-serif;color:#1f2937}}
 table{{border-collapse:collapse;font-size:12.5px;width:max-content;min-width:100%}}
 th,td{{border:1px solid #e2e6ec;padding:4px 8px;text-align:left;white-space:nowrap}}
 th{{background:#eef1f6;position:sticky;top:0;z-index:4;font-weight:700}}
 td.r{{text-align:right}}
 .muted{{color:#cbd5e1}}
 .no-video{{color:#dc2626;font-weight:700}}
 .reason-badge{{display:inline-block;max-width:150px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-weight:700;color:#7c2d12}}
 td.note{{max-width:240px;white-space:normal}}
 .note-detail summary{{cursor:pointer;color:#1d4ed8;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:220px}}
 .note-detail div{{margin-top:4px;white-space:pre-wrap;min-width:260px;max-width:520px;line-height:1.35;color:#111827}}
 a{{color:#1d4ed8;text-decoration:none}} a:hover{{text-decoration:underline}}
 .cp{{cursor:pointer;opacity:.55;font-size:11px;user-select:none}} .cp:hover{{opacity:1}}
</style>
<table><thead><tr>{thead}</tr></thead><tbody>{body}</tbody></table>
<script>
 function cp(t,el){{const a=document.createElement('textarea');a.value=t;a.style.position='fixed';a.style.opacity=0;
  document.body.appendChild(a);a.focus();a.select();try{{document.execCommand('copy');}}catch(e){{}}a.remove();
  if(el){{const o=el.textContent;el.textContent='✅';setTimeout(()=>{{el.textContent=o;}},900);}}}}
 (function(){{  // CỐ ĐỊNH các cột đầu (đến hết "Mã trả hàng") khi cuộn ngang
  var N={_sticky_n}, tbl=document.querySelector('table'); if(!tbl) return;
  var head=tbl.querySelector('thead tr'); if(!head) return;
  var offs=[]; for(var i=0;i<N;i++){{offs.push(head.children[i].offsetLeft);}}
  tbl.querySelectorAll('tr').forEach(function(tr){{
   if(tr.classList && tr.classList.contains('grp-sep')) return;   // dòng tiêu đề loại: chữ đã sticky riêng
   var isHead=tr.parentElement.tagName==='THEAD';
   for(var i=0;i<N && i<tr.children.length;i++){{
    var c=tr.children[i];
    c.style.position='sticky'; c.style.left=offs[i]+'px'; c.style.zIndex=isHead?6:3;
    if(!isHead){{c.style.background=tr.style.backgroundColor||'#ffffff';}}
    if(i===N-1){{c.style.boxShadow='2px 0 4px -1px rgba(0,0,0,.2)';}}
   }}
  }});
 }})();
</script>"""
                components.html(html, height=h, scrolling=True)

            def _type_block(title, code):
                items = [d for d in _rip["detail"] if d["loai_tra_code"] == code and (code == "refund" or d["ship_code"] != "no_return")]
                if not items:
                    return
                hoan = [d for d in items if d["ship_code"] == "returning"]
                giao = [d for d in items if d["ship_code"] == "returned"]
                khong_hoan = [d for d in items if d["ship_code"] == "no_return"]
                st.markdown(f"### {title} — {len(items)} đơn")
                if hoan:
                    st.markdown(f"**🚚 Đang hoàn hàng — {len(hoan)} đơn**")
                    _sub_table(hoan, 260, show_reason=True, merge_delivery_vd=(code == "delivery_failed"), pg_key=f"{code}_hoan")
                if giao:
                    st.markdown(f"**📥 Đã giao người bán — {len(giao)} đơn**")
                    _sub_table(giao, 260, show_reason=True, merge_delivery_vd=(code == "delivery_failed"), pg_key=f"{code}_giao")
                if khong_hoan:
                    st.markdown(f"**🚫 Không có hàng hoàn về — {len(khong_hoan)} đơn**")
                    _sub_table(khong_hoan, 260, show_reason=True, pg_key=f"{code}_khong")

            with _return_top_search_slot:
                st.markdown("##### 🔎 Tìm nhanh mã đơn / mã trả / vận đơn")
                with st.form("return_detail_search_form", clear_on_submit=False):
                    _s_cols = st.columns([5, 1])
                    _search_input = _s_cols[0].text_input(
                        "Dán hoặc quét mã",
                        value=st.session_state.get("return_detail_search_code", ""),
                        placeholder="Quét mã đơn, mã trả hàng, VĐ đi hoặc VĐ trả về",
                        label_visibility="collapsed",
                    )
                    _search_submit = _s_cols[1].form_submit_button("🔎 Tìm", use_container_width=True)
                if _search_submit:
                    st.session_state["return_detail_search_code"] = str(_search_input or "").strip()
                _active_search = str(st.session_state.get("return_detail_search_code") or "").strip()
                if _active_search:
                    _search_matches = []
                    for _d in _return_match_detail:
                        if _row_matches_code(_d, _active_search):
                            _r = dict(_d)
                            _r["_location"] = _row_location(_d)
                            _search_matches.append(_r)
                    st.markdown('<div id="ket-qua-tim-ma"></div>', unsafe_allow_html=True)
                    if _search_matches:
                        st.success(f"Tìm thấy {len(_search_matches)} dòng khớp `{_active_search}`. Xem trạng thái ngay bên dưới.")
                        _merge_search_vd = all(d.get("loai_tra_code") == "delivery_failed" for d in _search_matches)
                        _sub_table(
                            _search_matches,
                            min(360, 86 + 42 * len(_search_matches)),
                            show_type=True,
                            show_reason=True,
                            show_location=True,
                            merge_delivery_vd=_merge_search_vd,
                        )
                    else:
                        st.warning(f"Không tìm thấy mã `{_active_search}` trong danh sách đơn trả đang xử lý.")

            with _return_top_drill_slot:
                if _month_rows:
                    with st.expander("🔍 Bấm xem lý do từng đơn theo tháng / trạng thái nhập kho", expanded=False):
                        _month_options = ["Tất cả"] + list(_month_df["Tháng"])
                        _drill_cols = st.columns(3)
                        _drill_month = _drill_cols[0].selectbox(
                            "Tháng",
                            _month_options,
                            index=0,
                            key="return_month_drill_month",
                        )
                        _drill_stock = _drill_cols[1].selectbox(
                            "Trạng thái nhập kho",
                            ["Tất cả", "Không nhập kho", "Nhập kho 1 phần", "Chưa nhập kho", "Đã nhập kho"],
                            key="return_month_drill_stock",
                        )
                        _drill_outcome = _drill_cols[2].selectbox(
                            "Kết quả",
                            ["Tất cả", "Thắng", "Thua", "Hủy", "Hết hạn", "Không cần KN", "Cần KN", "Đang KN", "Chưa chốt", "Đã nhập kho"],
                            key="return_month_drill_outcome",
                        )
                        _drill_rows = []
                        for _d in _all_returns_detail:
                            _raw = str(_d.get("created_on") or "")
                            try:
                                _dt = datetime.fromisoformat(_raw.replace("Z", "").split(".")[0]) + timedelta(hours=7)
                            except Exception:
                                continue
                            if _drill_month != "Tất cả" and _dt.strftime("%m/%Y") != _drill_month:
                                continue
                            _sg = _stock_group(_d)
                            _outcome = _return_outcome(_d)
                            if _drill_stock != "Tất cả" and _sg != _drill_stock:
                                continue
                            if _drill_outcome != "Tất cả" and _outcome != _drill_outcome:
                                continue
                            _drill_rows.append({
                                "Ngày tạo": _d.get("created") or "",
                                "Mã đơn": _d.get("order_code") or "",
                                "Mã trả": _display_return_code(_d),
                                "Loại trả": _d.get("loai_tra") or "",
                                "VĐ đi": _d.get("vd_di") or "",
                                "VĐ trả về": _d.get("vd_tra") or "",
                                "Ngày giờ quay": _clip_recorded_or_missing(_d),
                                "Thời lượng": _clip_duration_text(_d.get("clip_dur")),
                                "Shipper hoàn": _d.get("return_shipper") or "Chưa có",
                                "Kết quả": _outcome,
                                "Nhập kho": _d.get("stock_status") or "",
                                "Tổng tiền": _vnd(_d.get("money") or 0),
                                "Ghi chú": _d.get("note") or "",
                            })
                        _desc = []
                        if _drill_month != "Tất cả":
                            _desc.append(f"tháng {_drill_month}")
                        if _drill_stock != "Tất cả":
                            _desc.append(_drill_stock.lower())
                        if _drill_outcome != "Tất cả":
                            _desc.append(f"kết quả {_drill_outcome.lower()}")
                        _filter_desc = ", ".join(_desc) if _desc else "tất cả đơn trả"
                        if _drill_rows:
                            st.caption(f"{len(_drill_rows)} đơn: {_filter_desc}.")
                            _drill_df = pd.DataFrame(_drill_rows)
                            st.dataframe(
                                _drill_df.style.map(
                                    lambda v: "color:#dc2626;font-weight:700" if v == "không có video" else "",
                                    subset=["Ngày giờ quay"],
                                ),
                                use_container_width=True,
                                hide_index=True,
                            )
                        else:
                            st.caption(f"Không có đơn phù hợp: {_filter_desc}.")

            # ── VIDEO DOHANA (metadata tích luỹ ở Gist → LƯU CẢ NĂM; khui hàng có tag=cần KN, đóng hàng có tag=không) ──
            try:
                _dvids = load_dohana_video_store()
            except Exception:
                _dvids = []
            _dohana_inbound_videos = [r for r in _dvids if r.get("type") == "inbound"]

            def _dohana_video_recorded_text(video_row):
                return _clip_recorded_text((video_row or {}).get("date"), (video_row or {}).get("time"))

            def _dohana_inbound_video_for_return_row(d):
                field_order = ("vd_tra", "return_code", "order_code", "vd_di")
                row_codes = [(idx, _search_norm((d or {}).get(key))) for idx, key in enumerate(field_order)]
                row_codes = [(idx, code) for idx, code in row_codes if code]
                if not row_codes:
                    return None
                candidates = []
                for r in _dohana_inbound_videos:
                    code = _search_norm((r or {}).get("code"))
                    if not code:
                        continue
                    exact = [idx for idx, row_code in row_codes if code == row_code]
                    if exact:
                        score = min(exact)
                    else:
                        fuzzy = [
                            idx for idx, row_code in row_codes
                            if len(code) >= 8 and len(row_code) >= 8 and (code in row_code or row_code in code)
                        ]
                        if not fuzzy:
                            continue
                        score = 20 + min(fuzzy)
                    candidates.append((score, _dohana_video_recorded_text(r), r))
                if not candidates:
                    return None
                candidates.sort(key=lambda item: item[1], reverse=True)
                candidates.sort(key=lambda item: item[0])
                return candidates[0][2]

            def _annotate_rows_with_dohana_inbound_video(rows):
                for d in rows or []:
                    video = _dohana_inbound_video_for_return_row(d)
                    if not video:
                        continue
                    d["clip_code"] = str(video.get("code") or "").strip()
                    d["clip_time"] = _dohana_video_recorded_text(video)
                    d["clip_dur"] = video.get("dur")
                    d["clip_link"] = str(video.get("link") or "").strip()
                    d["clip_tag_id"] = _video_tag_id(video)
                    d["clip_tag"] = _video_tag_label(video)

            _annotate_rows_with_dohana_inbound_video(_closed_returns_with_waybill_detail)
            _dtag_kn = [r for r in _dvids if _video_tag_id(r) and r.get("type") == "inbound"]     # khui hàng có tag → CẦN KN
            _dtag_nokn = [r for r in _dvids if _video_tag_id(r) and r.get("type") == "package"]   # đóng hàng có tag → KHÔNG cần KN

            def _detail_note_outcome(d):
                compact = _note_compact(d)
                if "THANG" in compact:
                    return "Thắng"
                if "THUA" in compact:
                    return "Thua"
                if "HUY" in compact:
                    return "Hủy"
                if "HETHAN" in compact:
                    return "Hết hạn"
                if "KHONGCANKN" in compact or "KHONGCANKHIEUNAI" in compact:
                    return "Không cần KN"
                if "DANGKN" in compact or "DANGKHANGNGHI" in compact or "DANGXULY" in compact:
                    return "Đang KN"
                if d.get("need_kn"):
                    return "Cần KN"
                return _row_location(d)

            def _detail_first_note(d):
                note = str(d.get("note") or "").strip()
                if not note:
                    return ""
                first = note.replace("\r", "\n").split("\n")[0]
                return first[:120] + ("..." if len(first) > 120 else "")

            def _dohana_detail_match_rows(code, source_rows):
                q = _search_norm(code)
                if not q:
                    return []
                rows = []
                for d in (source_rows or []):
                    fields = (d.get("order_code"), d.get("return_code"), d.get("vd_di"), d.get("vd_tra"))
                    norms = [_search_norm(x) for x in fields if x]
                    exact = q in norms
                    fuzzy = (not exact) and any(q in n or n in q for n in norms if n)
                    if exact or fuzzy:
                        item = dict(d)
                        item["_match_exact"] = exact
                        rows.append(item)
                return rows

            def _dohana_row_missing_info(d):
                if not d:
                    return True
                required = ("gian_hang", "sku", "qty", "money", "stock_status")
                for key in required:
                    val = d.get(key)
                    if val in (None, ""):
                        return True
                    if key in ("qty", "money"):
                        try:
                            if float(val or 0) <= 0:
                                return True
                        except Exception:
                            return True
                return False

            def _dohana_same_sapo_row(a, b):
                a_codes = [_search_norm((a or {}).get(k)) for k in ("vd_di", "vd_tra")]
                b_codes = [_search_norm((b or {}).get(k)) for k in ("vd_di", "vd_tra")]
                arc, brc = _search_norm((a or {}).get("return_code")), _search_norm((b or {}).get("return_code"))
                if arc and brc:
                    return arc == brc
                aoc, boc = _search_norm((a or {}).get("order_code")), _search_norm((b or {}).get("order_code"))
                if aoc and boc and aoc == boc:
                    return any(x and y and (x == y or x in y or y in x) for x in a_codes for y in b_codes)
                return any(x and y and (x == y or x in y or y in x) for x in a_codes for y in b_codes)

            def _dohana_merge_detail_row(base, extra):
                merged = dict(base or {})
                for key in (
                    "order_code", "order_link", "return_code", "return_link", "created", "created_on",
                    "vd_di", "vd_tra", "return_shipper", "gian_hang", "sku", "qty", "money",
                    "loai_tra", "loai_tra_code", "ship_code", "stock_status", "stock_code", "order_source",
                ):
                    cur = merged.get(key)
                    new = (extra or {}).get(key)
                    missing = cur in (None, "") or (key in ("qty", "money") and not cur)
                    if missing and new not in (None, ""):
                        merged[key] = new
                if not str(merged.get("note") or "").strip() and str((extra or {}).get("note") or "").strip():
                    merged["note"] = extra.get("note")
                if not str(merged.get("reason") or "").strip() and str((extra or {}).get("reason") or "").strip():
                    merged["reason"] = extra.get("reason")
                return merged

            def _dohana_is_closed_note(note):
                lines = [line.strip() for line in str(note or "").splitlines() if line.strip()]
                if not lines:
                    return False
                first = lines[0]
                compact = _note_prefix_compact(first)
                return any(t in compact for t in (
                    "THANG", "THUA", "HUY", "HETHAN", "KHONGCANKN", "KHONGCANKHIEUNAI",
                ))

            def _dohana_is_can_kn_note(note):
                compact = _note_prefix_compact(note)
                return _compact_is_can_kn(compact)

            _dohana_extra_detail_by_code = {}
            try:
                _tag_codes = [str(r.get("code") or "").strip() for r in (_dtag_kn + _dtag_nokn)]
                _missing_codes = [
                    c for c in _tag_codes
                    if c and (
                        not _dohana_detail_match_rows(c, _return_match_detail)
                        or any(_dohana_row_missing_info(d) for d in _dohana_detail_match_rows(c, _return_match_detail))
                    )
                ]
                if st.session_state.get("returns_dohana_deep_lookup"):
                    _dohana_extra_detail_by_code = load_return_rows_by_codes(tuple(sorted(set(_missing_codes))))
            except Exception:
                _dohana_extra_detail_by_code = {}

            def _dohana_detail_matches(code):
                q = _search_norm(code)
                rows = _dohana_detail_match_rows(code, _return_match_detail)
                if q and _dohana_extra_detail_by_code.get(q):
                    for d in _dohana_extra_detail_by_code.get(q) or []:
                        item = dict(d)
                        item["_match_exact"] = True
                        merged = False
                        for idx, old in enumerate(rows):
                            if _dohana_same_sapo_row(old, item):
                                rows[idx] = _dohana_merge_detail_row(old, item)
                                rows[idx]["_match_exact"] = old.get("_match_exact") or item.get("_match_exact")
                                merged = True
                                break
                        if not merged:
                            rows.append(item)
                rank = {
                    "Thắng": 0,
                    "Thua": 0,
                    "Hết hạn": 1,
                    "Không cần KN": 2,
                    "Cần KN": 3,
                    "Đang KN": 4,
                    "Đã nhận/đã nhập kho": 5,
                    "Trả hàng hoàn tiền": 6,
                    "Giao hàng thất bại": 7,
                    "Không có hàng hoàn về / chỉ hoàn tiền": 8,
                }
                rows.sort(key=lambda d: (
                    0 if d.get("_match_exact") else 1,
                    0 if d.get("order_code") else 1,
                    0 if not _dohana_row_missing_info(d) else 1,
                    rank.get(_detail_note_outcome(d), 99),
                    str(d.get("created_on") or ""),
                ))
                return rows

            def _dohana_row_key(d):
                for key in ("return_code", "order_code"):
                    val = _search_norm((d or {}).get(key))
                    if val:
                        return f"{key}:{val}"
                vals = [_search_norm((d or {}).get(k)) for k in ("vd_tra", "vd_di", "_dohana_code")]
                vals = [v for v in vals if v]
                return "vd:" + "|".join(vals) if vals else ""

            def _append_reason_text(old, extra):
                old = str(old or "").strip()
                extra = str(extra or "").strip()
                if not extra:
                    return old
                if old and _search_norm(extra) in _search_norm(old):
                    return old
                return f"{old} · {extra}" if old else extra

            def _dohana_tag_icon(tag):
                compact = _search_norm(tag)
                if "HUHONG" in compact or "HANGHONG" in compact:
                    return "💥"
                if "THIEU" in compact or "TRATHIEU" in compact or "DONGTHIEU" in compact:
                    return "➖"
                if "TRAO" in compact or "SAIHANG" in compact or "SAISP" in compact:
                    return "🔁"
                if "DASUDUNG" in compact or "DADUNG" in compact or "SUDUNG" in compact:
                    return "♻️"
                if "DONG" in compact or "DONGHANG" in compact:
                    return "📦"
                return "🏷️"

            def _dohana_tag_with_icon(tag):
                tag = str(tag or "").strip()
                if not tag:
                    return ""
                if tag.startswith(("🏷️", "💥", "➖", "🔁", "♻️", "📦", "⚠️")):
                    return tag
                return f"{_dohana_tag_icon(tag)} {tag}"

            def _dohana_tag_reason(video_row):
                tag = str(_video_tag_label(video_row) or "").strip()
                return f"Tag Dohana: {_dohana_tag_with_icon(tag)}" if tag else "🏷️ Tag Dohana"

            def _annotate_detail_rows_with_dohana_tags(video_rows, detail_rows):
                for r in video_rows or []:
                    code = str(r.get("code") or "").strip()
                    if not code:
                        continue
                    tag = str(_video_tag_label(r) or "").strip()
                    reason = _dohana_tag_reason(r)
                    for d in _dohana_detail_match_rows(code, detail_rows):
                        key = _dohana_row_key(d)
                        for target in detail_rows or []:
                            if key and _dohana_row_key(target) == key:
                                target["reason"] = _append_reason_text(target.get("reason"), reason)
                                if tag:
                                    target["_dohana_tag_label"] = tag

            def _dohana_in_detail(code):
                return bool(_dohana_detail_match_rows(code, _return_match_detail))

            def _dohana_items_not_in_detail(items):
                return [r for r in (items or []) if not _dohana_in_detail(str(r.get("code") or ""))]

            def _dohana_yellow_need_kn_rows(items):
                rows = []
                for r in items or []:
                    code = str(r.get("code") or "").strip()
                    matches = _dohana_detail_matches(code)
                    tag = str(_video_tag_label(r) or "").strip()
                    tag_text = _dohana_tag_with_icon(tag)
                    match_rows = [dict(d) for d in matches] if matches else [{}]
                    for d in match_rows:
                        note = str(d.get("note") or "").strip() if matches else "Chưa thấy trong chi tiết"
                        if matches and _dohana_is_closed_note(note):
                            continue
                        if matches and _dohana_is_can_kn_note(note):
                            reason = f"Dohana tag {tag_text} — Sapo ghi CẦN KN" if tag_text else "🏷️ Sapo ghi CẦN KN"
                        else:
                            reason = f"Dohana tag {tag_text} — chưa có ghi chú chuẩn" if tag_text else "🏷️ Dohana có tag — chưa có ghi chú chuẩn"
                        if not d.get("vd_tra") and code:
                            d["vd_tra"] = code
                        for key in (
                            "order_code", "order_link", "return_code", "return_link", "created", "created_on",
                            "vd_di", "return_shipper", "gian_hang", "sku", "qty", "money",
                            "loai_tra", "loai_tra_code", "ship_code", "stock_status", "stock_code", "order_source",
                        ):
                            d.setdefault(key, "")
                        d.update({
                            "need_kn": True,
                            "reason": reason,
                            "_location": "Dohana tag chưa có ghi chú chuẩn",
                            "_kn_priority": 10,
                            "_dohana_code": code,
                            "_dohana_tag_label": tag_text or tag,
                            "clip_code": code,
                            "clip_time": _dohana_video_recorded_text(r),
                            "clip_dur": r.get("dur"),
                        })
                        if not str(d.get("note") or "").strip():
                            d["note"] = note
                        rows.append(d)
                return rows

            def _merge_need_kn_rows(base_rows, dohana_rows):
                def _priority(d):
                    try:
                        return int((d or {}).get("_kn_priority", 50))
                    except Exception:
                        return 50
                merged = [dict(d) for d in (base_rows or [])]
                by_key = {_dohana_row_key(d): idx for idx, d in enumerate(merged) if _dohana_row_key(d)}
                for extra in dohana_rows or []:
                    key = _dohana_row_key(extra)
                    if key and key in by_key:
                        idx = by_key[key]
                        old = dict(merged[idx])
                        new = _dohana_merge_detail_row(old, extra)
                        new["need_kn"] = True
                        new["_location"] = old.get("_location") or extra.get("_location")
                        new["_kn_priority"] = min(_priority(old), _priority(extra))
                        if str(extra.get("reason") or "").strip():
                            old_reason = str(old.get("reason") or "").strip()
                            extra_reason = str(extra.get("reason") or "").strip()
                            new["reason"] = _append_reason_text(old_reason, extra_reason)
                        merged[idx] = new
                    else:
                        merged.append(dict(extra))
                        if key:
                            by_key[key] = len(merged) - 1
                merged.sort(key=lambda d: str(d.get("created_on") or d.get("created") or ""), reverse=True)
                return merged

            def _dohana_detail_note(code):
                matches = _dohana_detail_matches(code)
                if not matches:
                    return "Chưa thấy trong bảng chi tiết"
                d = matches[0]
                outcome = _detail_note_outcome(d)
                rc = str(d.get("return_code") or "").strip()
                note = _detail_first_note(d)
                if outcome in ("Thắng", "Thua", "Hết hạn", "Không cần KN", "Đang KN"):
                    msg = f"Đã có kết luận: {outcome}"
                elif outcome == "Cần KN":
                    msg = "Trùng DS Cần KN — chưa chốt thắng/thua"
                else:
                    msg = f"Có trong bảng chi tiết: {outcome}"
                if rc:
                    msg += f" · mã trả {rc}"
                if note:
                    msg += f" · ghi chú: {note}"
                if len(matches) > 1:
                    msg += f" · còn {len(matches) - 1} dòng khớp khác"
                return msg

            def _dohana_tag_tbl(items):
                if not items:
                    st.caption("— (Dohana) chưa ghi nhận đơn gắn tag —")
                    return

                def _safe(v, default=""):
                    return _esc(str(v if v not in (None, "") else default))

                def _money_cell(v):
                    try:
                        return f"{int(v or 0):,}đ"
                    except Exception:
                        return ""

                def _note_details_cell(text):
                    note_text = str(text or "").strip()
                    if not note_text:
                        return "<span class='muted'>—</span>"
                    first = next((line.strip() for line in note_text.replace("\r", "\n").split("\n") if line.strip()), "xem ghi chú")
                    summary = first if len(first) <= 42 else first[:39].rstrip() + "..."
                    return (
                        f"<details class='note-detail'><summary>{_safe(summary)}</summary>"
                        f"<div>{_safe(note_text)}</div></details>"
                    )

                def _video_link_cell(text, video_row):
                    text = str(text or "").strip()
                    if not text:
                        return ""
                    code = str((video_row or {}).get("code") or "").strip()
                    link = _with_url_query(_dohana_inbound_url(), q=code, orderCode=code) if code else ""
                    body = _safe(text)
                    if link:
                        return (f"<a href='{_esc(link)}' target='_blank' rel='noopener' "
                                f"onclick=\"cp('{_jss(code)}',this)\" "
                                f"title='Mo Dohana nhap hang hoan; dong thoi copy ma'>{body}</a>")
                    return body

                def _return_type_label(d):
                    label = str((d or {}).get("loai_tra") or "").strip()
                    if label:
                        return label
                    code = str((d or {}).get("loai_tra_code") or "").strip()
                    return {
                        "return_and_refund": "Trả hàng hoàn tiền",
                        "delivery_failed": "Giao hàng thất bại",
                        "refund": "Chỉ hoàn tiền / không có hàng hoàn về",
                    }.get(code, code)

                def _vd_ve_dohana_cell(vd_tra, dohana_code):
                    vd = str(vd_tra or "").strip()
                    dh = str(dohana_code or "").strip()
                    link = _with_url_query(_dohana_inbound_url(), q=dh, orderCode=dh) if dh else ""
                    if vd and dh and _search_norm(vd) != _search_norm(dh):
                        return (f"{_code_cell(vd, link, link_copy=dh)}<br>"
                                f"<span class='sub'>Dohana: {_code_cell(dh, link, link_copy=dh)}</span>")
                    return _code_cell(vd or dh, link, link_copy=dh)

                def _tag_reason_cell(video_row, detail_row):
                    tag = _dohana_tag_with_icon(_video_tag_label(video_row))
                    reason = str((detail_row or {}).get("reason") or "").strip()
                    # BỎ phần "· Tag Dohana: ..." lặp ở cuối (tag đã hiện ở dòng đầu) → chỉ còn tag + lý do trả
                    reason = re.sub(r"\s*·?\s*Tag Dohana:.*$", "", reason, flags=re.IGNORECASE).strip()
                    if tag and reason and _search_norm(tag) != _search_norm(reason):
                        return f"{_safe(tag)}<br><span class='sub'>{_safe(reason)}</span>"
                    return _safe(tag or reason)

                cols = [
                    "STT", "Ngày tạo", "Mã đơn", "Mã trả", "VĐ đi", "VĐ về / Dohana",
                    "Ngày giờ quay", "Thời lượng", "Tag / lý do vào KN", "Loại trả", "Shipper hoàn",
                    "Gian hàng", "SKU", "SL", "Tổng tiền", "Nhập kho", "Đối soát", "Ghi chú",
                ]
                thead = "".join(f"<th>{_esc(c)}</th>" for c in cols)
                body = ""
                sorted_items = sorted(items, key=lambda x: (x.get("date") or "", x.get("time") or ""), reverse=True)
                for i, r in enumerate(sorted_items, 1):
                    code = r.get("code") or ""
                    matches = _dohana_detail_matches(code)
                    d = matches[0] if matches else {}
                    note = str(d.get("note") or "").strip() if matches else "Chưa thấy trong chi tiết"
                    filmed_at = _clip_recorded_text(r.get("date"), r.get("time")) or "không có video"
                    duration = _clip_duration_text(r.get("dur"))
                    shipper = d.get("return_shipper") or ("Chưa có" if matches else "")
                    bg = "" if (matches and _dohana_is_closed_note(note)) else "background:#fff3cd"
                    filmed_html = (
                        f"<span class='no-video'>{_safe(filmed_at)}</span>"
                        if filmed_at == "không có video" else _safe(filmed_at)
                    )
                    tds = [
                        f"<td class='r'>{i}</td>",
                        f"<td>{_safe(d.get('created'))}</td>",
                        f"<td>{_code_cell(d.get('order_code'), _order_link_for_row(d))}</td>",
                        f"<td>{_return_code_cell(d)}</td>",
                        f"<td>{_code_cell(d.get('vd_di'))}</td>",
                        f"<td>{_vd_ve_dohana_cell(d.get('vd_tra'), code)}</td>",
                        f"<td>{filmed_html}</td>",
                        f"<td class='r'>{_safe(duration)}</td>",
                        f"<td>{_tag_reason_cell(r, d)}</td>",
                        f"<td>{_safe(_return_type_label(d))}</td>",
                        f"<td class='shipper' title='{_safe(shipper)}'>{_safe(shipper)}</td>",
                        f"<td>{_safe(d.get('gian_hang'))}</td>",
                        f"<td>{_safe(d.get('sku'))}</td>",
                        f"<td class='r'>{_safe(d.get('qty'))}</td>",
                        f"<td class='r'>{_safe(_money_cell(d.get('money')))}</td>",
                        f"<td>{_safe(d.get('stock_status'))}</td>",
                        f"<td>{_doisoat(d)}</td>",
                        f"<td class='note'>{_note_details_cell(note)}</td>",
                    ]
                    body += f"<tr style='{bg}'>" + "".join(tds) + "</tr>"

                _sticky_n = cols.index("Mã trả") + 1
                html = f"""<style>
 body{{margin:0;font-family:Tahoma,Arial,sans-serif;color:#1f2937}}
 table{{border-collapse:collapse;font-size:12.5px;width:100%;min-width:1820px}}
 th,td{{border:1px solid #e2e6ec;padding:4px 8px;text-align:left;white-space:nowrap}}
 th{{background:#eef1f6;position:sticky;top:0;z-index:4;font-weight:700}}
 td{{vertical-align:top}}
 td.r{{text-align:right}}
 .muted{{color:#cbd5e1}}
 .no-video{{color:#dc2626;font-weight:700}}
 .sub{{color:#64748b;font-size:11px}}
 td.shipper{{max-width:230px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}}
 td.note{{max-width:260px;white-space:normal}}
 .note-detail summary{{cursor:pointer;color:#1d4ed8;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:240px}}
 .note-detail div{{margin-top:4px;white-space:pre-wrap;min-width:260px;max-width:520px;line-height:1.35;color:#111827}}
 a{{color:#1d4ed8;text-decoration:none}} a:hover{{text-decoration:underline}}
 .cp{{cursor:pointer;opacity:.55;font-size:11px;user-select:none}} .cp:hover{{opacity:1}}
</style>
<table><thead><tr>{thead}</tr></thead><tbody>{body}</tbody></table>
<script>
 function cp(t,el){{const a=document.createElement('textarea');a.value=t;a.style.position='fixed';a.style.opacity=0;
  document.body.appendChild(a);a.focus();a.select();try{{document.execCommand('copy');}}catch(e){{}}a.remove();
  if(el){{const o=el.textContent;el.textContent='✅';setTimeout(()=>{{el.textContent=o;}},900);}}}}
 (function(){{
  var N={_sticky_n}, tbl=document.querySelector('table'); if(!tbl) return;
  var head=tbl.querySelector('thead tr'); if(!head) return;
  var offs=[]; for(var i=0;i<N;i++){{offs.push(head.children[i].offsetLeft);}}
  tbl.querySelectorAll('tr').forEach(function(tr){{
   if(tr.classList && tr.classList.contains('grp-sep')) return;   // dòng tiêu đề loại: chữ đã sticky riêng
   var isHead=tr.parentElement.tagName==='THEAD';
   for(var i=0;i<N && i<tr.children.length;i++){{
    var c=tr.children[i];
    c.style.position='sticky'; c.style.left=offs[i]+'px'; c.style.zIndex=isHead?6:3;
    if(!isHead){{c.style.background=tr.style.backgroundColor||'#ffffff';}}
    if(i===N-1){{c.style.boxShadow='2px 0 4px -1px rgba(0,0,0,.2)';}}
   }}
  }});
 }})();
</script>"""
                components.html(html, height=min(92 + len(sorted_items) * 34, 520), scrolling=True)

            # ── DANH SÁCH ĐƠN CẦN KN (bấm ô "Cần KN" ở trên sẽ nhảy tới đây) ──
            _annotate_detail_rows_with_dohana_tags(_dtag_kn + _dtag_nokn, _rip.get("detail") or [])
            _annotate_detail_rows_with_dohana_tags(_dtag_kn + _dtag_nokn, _all_returns_detail)
            _annotate_detail_rows_with_dohana_tags(_dtag_kn + _dtag_nokn, _canceled_returns_detail)
            _dtag_kn_only = _dohana_items_not_in_detail(_dtag_kn)
            _dtag_nokn_only = _dohana_items_not_in_detail(_dtag_nokn)
            _dohana_yellow_ckn = _dohana_yellow_need_kn_rows(_dtag_kn + _dtag_nokn)
            _ckn_with_closed_returns = _merge_need_kn_rows(_ckn_list, _closed_returns_need_kn_detail)
            _ckn_render_raw_list = _merge_need_kn_rows(_ckn_with_closed_returns, _dohana_yellow_ckn)
            # + Đơn ĐÃ NHẬP KHO thiếu video khui mà CHƯA có ghi chú chuẩn → cũng đưa vào Cần KN (tới khi
            #   có ghi chú chuẩn thì tự rớt khỏi đây & mất màu vàng). Dùng chung _nv_row_restock cho đồng nhất.
            _nv_ckn_added = 0
            try:
                # APPEND thẳng (KHÔNG merge) → KHÔNG trộn ghi chú/lý do với đơn Cần KN khác. Bỏ đơn đã
                # có sẵn trong Cần KN (theo mã trả/mã đơn/VĐ) để không lặp.
                _ckn_keys = {_dohana_row_key(d) for d in _ckn_render_raw_list if _dohana_row_key(d)}
                _nv_ckn = [d for d in _restock_novideo_rows()
                           if d.get("need_kn") and _dohana_row_key(d) not in _ckn_keys]
                if _nv_ckn:
                    _nv_ckn_added = len(_nv_ckn)
                    _ckn_render_raw_list = _ckn_render_raw_list + _nv_ckn
            except Exception:
                pass
            _ckn_render_list = [
                d for d in _ckn_render_raw_list
                if _is_need_kn_shape(d) and not _is_closed_kn_result(d)
            ]
            _ckn_render_list.sort(key=lambda d: str(d.get("created_on") or d.get("created") or ""), reverse=True)
            st.subheader("🚨 Đơn cần KN — lấy làm khiếu nại", anchor="don-can-kn")
            _need_kn_info = ("Gồm các đơn chưa chốt THẮNG / THUA / KHÔNG CẦN KN. "
                             "Note CẦN KN vẫn nằm ở bảng này để nhân viên tiếp tục xử lý. "
                             "Đơn có VĐ trả về: đã giao người bán chưa nhập kho, hoặc đang hoàn hơn 5 ngày. "
                             "Riêng đơn CHỈ HOÀN TIỀN không có VĐ hoàn vẫn tô vàng và đưa vào Cần KN cho tới khi có kết luận chuẩn. "
                             "Đây chính là các dòng tô vàng — NV lấy làm khiếu nại.")
            if _closed_returns_need_kn_detail:
                _added_closed = max(0, len(_ckn_with_closed_returns) - len(_ckn_list))
                _need_kn_info += (f"\nCó {len(_closed_returns_need_kn_detail)} đơn trả hàng bị đóng có VĐ trả về chưa chốt "
                                  f"(thêm mới {_added_closed} dòng, dòng trùng thì ghép vào Cần KN sẵn có). Bảng đang xếp theo ngày tạo mới nhất.")
            if _dohana_yellow_ckn:
                _added = max(0, len(_ckn_render_list) - len(_ckn_with_closed_returns))
                _need_kn_info += (f"\nDohana có {len(_dohana_yellow_ckn)} dòng đang tô vàng vì chưa có ghi chú chuẩn "
                                  f"(thêm mới {_added} dòng, dòng trùng thì ghép vào Cần KN sẵn có).")
            if _nv_ckn_added:
                _need_kn_info += (f"\nCó {_nv_ckn_added} đơn ĐÃ nhập kho nhưng THIẾU video khui (nghi NV nhập kho "
                                  "sai) — đưa vào đây tới khi có ghi chú chuẩn thì tự rớt.")
            _need_kn_info += ("\nVới đơn TikTok, bấm Xem / tạo trong cột Phiếu yêu cầu để mở thẳng tab Tất cả "
                              "với ID đơn hàng đã điền sẵn. Nếu chưa có phiếu thì tạo ngay; nếu có nhiều phiếu "
                              "TikTok sẽ hiện đầy đủ.")
            _return_info(_need_kn_info)
            if '_missing_codes' in locals() and _missing_codes and not st.session_state.get("returns_dohana_deep_lookup"):
                st.caption(f"Dohana còn {len(set(_missing_codes))} mã thiếu thông tin Sapo. Mặc định không quét sâu để trang mở nhanh.")
                if st.button("🔎 Đối chiếu sâu Dohana/Sapo cho các mã thiếu", key="returns_dohana_deep_lookup_btn"):
                    st.session_state["returns_dohana_deep_lookup"] = True
                    st.rerun()
            _sub_table(_ckn_render_list, 520, show_reason=True, show_location=True,
                       show_type=True, pg_key="ckn", per_page=50, show_ticket=True)
            st.subheader("⛔ Đơn không cần KN — đã có kết luận", anchor="don-khong-can-kn")
            _return_info("Các đơn trong bảng detail đã có ghi chú KHÔNG CẦN KN: đã nhận hàng, đã nhận/được đền tiền, hoặc shop đóng thiếu thật. Nhóm này không trộn vào danh sách CẦN KN.")
            _sub_table(_khong_can_kn_list, 300, show_reason=True, show_type=True, pg_key="khong_can_kn")
            st.markdown(f"**🏷️ + Đơn Dohana gắn tag ĐÓNG HÀNG (đóng thiếu SP) — {len(_dtag_nokn)} đơn** "
                        f"<span style='color:#6b7280'>(trong đó {len(_dtag_nokn_only)} chưa khớp bảng chi tiết)</span>",
                        unsafe_allow_html=True)
            _dohana_tag_tbl(_dtag_nokn)
            st.divider()
            st.markdown("### 📋 Chi tiết còn hàng hoàn về theo loại")
            # ── 🏷️ Dohana gắn tag KHUI HÀNG (dời từ Cần KN xuống — là 1 loại đơn hoàn về) ──
            st.markdown(f"**🏷️ + Đơn Dohana gắn tag KHUI HÀNG (tráo · đã dùng · trả thiếu · hư hỏng) — {len(_dtag_kn)} đơn** "
                        f"<span style='color:#6b7280'>(trong đó {len(_dtag_kn_only)} chưa khớp bảng chi tiết)</span>",
                        unsafe_allow_html=True)
            _dohana_tag_tbl(_dtag_kn)
            # ── 🚫 Đơn ĐÃ NHẬP KHO nhưng KHÔNG có video khui (đơn đã nhập kho — render bằng _sub_table cho đồng nhất) ──
            _nvhelp = ("Danh sách lấy trực tiếp từ cột Chốt video của Báo cáo vận hành cuối ngày: chỉ gồm các "
                       "dòng còn thiếu video khui hoàn sau khi đã trừ mã quay lộn mục. SAPO chỉ bổ sung thông tin mã đơn/mã trả/vận đơn. "
                       "Tô vàng = đơn chưa có ghi chú chuẩn (cần KN).")
            st.markdown('**🚫 + Đơn ĐÃ NHẬP KHO nhưng KHÔNG có video khui** '
                        f'<abbr title="{_esc(_nvhelp)}" style="cursor:help;color:#2563eb;text-decoration:none">ⓘ</abbr>',
                        unsafe_allow_html=True)
            try:
                _nvrows = _restock_novideo_rows()      # đúng danh sách badge báo cáo + metadata SAPO
                if not _nvrows:
                    st.caption("✅ Không có đơn nhập kho nào thiếu video khui trong 30 ngày.")
                else:
                    _nvrows = sorted(_nvrows, key=lambda r: str(r.get("created_on") or ""), reverse=True)
                    _nvrows = sorted(_nvrows, key=lambda r: 0 if r.get("need_kn") else 1)   # vàng (cần KN) lên đầu
                    _nvneed = sum(1 for r in _nvrows if r.get("need_kn"))
                    st.warning(f"⚠️ **{len(_nvrows)}** đơn ĐÃ nhập kho nhưng KHÔNG có video khui"
                               + (f" · 🟡 **{_nvneed}** chưa có ghi chú chuẩn (tô vàng, cần KN)" if _nvneed else ""))

                    _sub_table(_nvrows, 520, show_reason=True, show_type=True,
                               show_location=True, pg_key="restock_novideo", per_page=50)
            except Exception as _env:
                st.caption(f"Chưa dò được đơn nhập kho thiếu video: {_env}")
            _type_block("💸 Trả hàng hoàn tiền", "return_and_refund")
            _type_block("📕 Giao hàng thất bại", "delivery_failed")
            _type_block("🚫 Chỉ hoàn tiền / không có hàng hoàn về", "refund")
            _other = [d for d in _rip["detail"]
                      if d["loai_tra_code"] not in ("return_and_refund", "delivery_failed", "refund")
                      and d["ship_code"] != "no_return"]
            if _other:
                st.markdown(f"### Khác — {len(_other)} đơn")
                _sub_table(_other, 200, show_reason=True, show_type=True, pg_key="other")
            if _closed_returns_with_waybill_detail:
                st.markdown(f"### 🧭 Đơn trả hàng bị đóng có VĐ trả về — {len(_closed_returns_with_waybill_detail)} đơn")
                if _closed_returns_loaded_full_year:
                    _return_info("Đang hiển thị dữ liệu đã quét đủ năm nay. Dòng chưa chốt THẮNG / THUA / KHÔNG CẦN KN sẽ tô vàng và được đưa lên bảng Cần KN.")
                else:
                    _return_info("Đang hiển thị nhanh từ dữ liệu đã quét sẵn. Bấm nút dưới để quét đủ năm nay; app sẽ cache lại sau khi quét xong.")
                    if st.button("🔄 Quét đủ năm nay", key="load_closed_returns_full_year_btn"):
                        st.session_state["closed_returns_full_year_loaded"] = True
                        st.rerun()
                if _closed_returns_capped:
                    st.warning("Đã chạm giới hạn quét 500 trang phiếu bị đóng; có thể còn phiếu cũ hơn trong năm nay.")
                _render_closed_return_app_note_editor(_closed_returns_with_waybill_detail, _closed_return_app_notes)
                _sub_table(
                    _closed_returns_with_waybill_detail,
                    300,
                    show_type=True,
                    show_reason=True,
                    show_clip=True,
                    show_location=True,
                    pg_key="closed_return_refund_with_waybill",
                    per_page=50,
                )
            if _canceled_returns_detail:
                with st.expander(f"🗂️ Tất cả phiếu Sapo đã hủy — {len(_canceled_returns_detail)} dòng", expanded=False):
                    _return_info("Nhóm này không tính vào KPI đang xử lý, nhưng vẫn hiện khi tìm mã đơn/mã trả để kiểm tra trên sàn.")
                    _sub_table(_canceled_returns_detail, 260, show_type=True, show_reason=True, show_location=True, pg_key="sapo_cancelled")

            # ── 🔍 KIỂM TRA MÃ TRẢ TRÙNG trong từng bảng (đếm mã trả xuất hiện >1 lần) ──
            st.divider()
            with st.expander("🔍 Kiểm tra đơn TRÙNG (① trong 1 bảng · ② chéo giữa các bảng)", expanded=True):
                from collections import Counter as _Cnt

                def _row_id(d):   # danh tính đơn = mã trả / mã đơn / VĐ (CÙNG key với lúc gộp Cần KN)
                    k = _dohana_row_key(d)
                    return k.split(":", 1)[-1] if k else ""
                _dup_tables = [
                    ("🚨 Cần KN", _ckn_render_list),
                    ("⛔ Không cần KN", _khong_can_kn_list),
                    ("🏷️ Dohana tag KHUI", _dtag_kn),
                    ("🏷️ Dohana tag ĐÓNG", _dtag_nokn),
                    ("🚫 Nhập kho không video", _restock_novideo_rows()),
                    ("📋 Chi tiết (đang xử lý)", _rip.get("detail") or []),
                ]
                if _closed_returns_with_waybill_detail:
                    _dup_tables.append(("🧭 Đơn bị đóng có VĐ", _closed_returns_with_waybill_detail))
                if _canceled_returns_detail:
                    _dup_tables.append(("🗂️ Phiếu đã hủy", _canceled_returns_detail))
                # ① TRÙNG TRONG TỪNG BẢNG (cùng 1 đơn > 1 dòng trong CÙNG bảng)
                _dup_out, _tot_dup, _table_ids = [], 0, {}
                for _nm, _rws in _dup_tables:
                    _ids = [i for i in (_row_id(d) for d in (_rws or [])) if i]
                    _cnt = _Cnt(_ids)
                    _dd = {k: v for k, v in _cnt.items() if v > 1}
                    _ndup = sum(v - 1 for v in _dd.values())
                    _tot_dup += _ndup
                    _table_ids[_nm] = set(_cnt)
                    _dup_out.append({"Bảng": _nm, "Số dòng": len(_rws or []), "Đơn khác nhau": len(_cnt),
                                     "⚠️ TRÙNG trong bảng": _ndup,
                                     "Ví dụ": ", ".join(f"{k}×{v}" for k, v in list(_dd.items())[:5]) or "—"})
                st.markdown("**① Trùng TRONG từng bảng** (1 đơn hiện >1 dòng trong CÙNG bảng — đây mới là lỗi thật):")
                st.dataframe(pd.DataFrame(_dup_out), hide_index=True, use_container_width=True,
                             column_config={"Ví dụ": st.column_config.TextColumn(width="large")})
                if _tot_dup:
                    st.warning(f"⚠️ Có **{_tot_dup}** dòng TRÙNG trong bảng (cột ⚠️ > 0) — cần xử lý.")
                else:
                    st.success("✅ Không bảng nào bị trùng dòng bên trong.")
                # ② TRÙNG CHÉO giữa các bảng (cùng 1 đơn nằm ở NHIỀU bảng)
                _cross, _where = _Cnt(), {}
                for _nm, _ids in _table_ids.items():
                    for _i in _ids:
                        _cross[_i] += 1
                        _where.setdefault(_i, []).append(_nm)
                _cross_dups = sorted([(i, _where[i]) for i, c in _cross.items() if c > 1],
                                     key=lambda x: -len(x[1]))
                st.markdown(f"**② Trùng CHÉO giữa các bảng** — {len(_cross_dups)} đơn nằm ở >1 bảng:")
                if _cross_dups:
                    st.dataframe(pd.DataFrame([{"Đơn (mã)": i, "Số bảng": len(w), "Các bảng": " · ".join(w)}
                                              for i, w in _cross_dups[:50]]),
                                 hide_index=True, use_container_width=True,
                                 column_config={"Các bảng": st.column_config.TextColumn(width="large")})
                    st.caption("Trùng CHÉO thường KHÔNG phải lỗi: bảng **Cần KN** GOM đơn cần khiếu nại từ các "
                               "bảng khác, nên 1 đơn vừa ở bảng gốc vừa ở Cần KN. Chỉ lo mục ① (trùng trong 1 bảng).")
                else:
                    st.caption("Không có đơn nào nằm ở nhiều bảng.")

        with _tabs[2]:
            # ── 🎥 KHO VIDEO DOHANA (lưu CẢ NĂM, vượt hạn 30 ngày của Dohana) — tra cứu metadata ──
            st.divider()
            st.subheader("🎥 Kho video Dohana (lưu cả năm)")
            if st.button("🔄 Cập nhật Dohana từ DHN ngay", key="returns_refresh_dohana_live_btn"):
                try:
                    load_dohana_videos.clear()
                    _fresh_dvids = load_dohana_videos()
                    load_dohana_video_store.clear()
                    st.success(f"Đã cập nhật kho Dohana: {len(_fresh_dvids)} video.")
                    st.rerun()
                except Exception as _e:
                    st.warning(f"Chưa cập nhật được Dohana live: `{_e}`")
            _return_info(f"Đã lưu {len(_dvids)} video (đóng hàng + khui hàng): trạng thái, ngày quay, giờ, "
                         "thời lượng, tag. Tag đã từng thấy sẽ được khóa trong kho, DHN gỡ tag sau này cũng không mất. "
                         "Dohana chỉ giữ 30 ngày; kho này gom dần (13/16/19h) nên đọc được đến cuối năm.")
            _vq = st.text_input("Tra video theo mã đơn", key="dohana_vid_q", placeholder="Dán/nhập mã đơn…")
            if _vq and _vq.strip():
                _q = _vq.strip()
                _hits = [r for r in _dvids if _q in str(r.get("code") or "")]
                if _hits:
                    st.dataframe(pd.DataFrame([{
                        "Mã đơn": r.get("code"),
                        "Loại": "Khui hàng" if r.get("type") == "inbound" else "Đóng hàng",
                        "Trạng thái": r.get("status"),
                        "Ngày quay": r.get("date"),
                        "Giờ": r.get("time"),
                        "Thời lượng(s)": r.get("dur"),
                        "Tag": _video_tag_label(r) if _video_tag_id(r) else "",
                    } for r in _hits]), width="stretch", hide_index=True)
                else:
                    st.caption("Không thấy trong kho (có thể chưa tới mốc lấy 13/16/19h, hoặc video ngoài phạm vi đã gom).")
    return


# ───────────────────────── Tiện ích ─────────────────────────
def _evidence_need(o):
    """Phân loại bằng chứng NV kho cần up cho 1 đơn đã đẩy VC → hủy."""
    f = (o.get("fulfillments") or [{}])[0]
    if f.get("packed_status") == "packed":
        return "📦 Ảnh đơn có chữ «HỦY» (cần lấy lại hàng)"
    if f.get("picked_on") or f.get("sorted_on"):
        return "🏷️ Phiếu vận đơn + ảnh SL/SKU (đối chiếu SKU)"
    if f.get("shipping_label_slip_url"):
        return "📄 Chụp / quét mã phiếu vận đơn"
    return "✔️ Chỉ cần xác nhận hủy"


def cancel_table(orders):
    return pd.DataFrame([{
        "Mã đơn": o.get("name"),
        "Mã vận đơn": (o.get("fulfillments") or [{}])[0].get("tracking_number"),
        "SKU": ", ".join(f'{li.get("sku")} x{li.get("quantity")}'
                         for li in (o.get("line_items") or [])),
        "SL": sum(li.get("quantity", 0) for li in (o.get("line_items") or [])),
        "ĐVVC": (o.get("fulfillments") or [{}])[0].get("tracking_company")
                or (o.get("shipping_lines") or [{}])[0].get("carrier_name"),
        "Ngày hủy": (o.get("cancelled_on") or "")[:10],
        "📸 Bằng chứng cần up": _evidence_need(o),
    } for o in orders])


# ───────────────────────── Tải dữ liệu (cache 5 phút) ─────────────────────────
@st.cache_data(ttl=300, show_spinner="Đang tải dữ liệu Sapo…")
def load_live():
    session = build_session()
    return L.load_live(make_fetch_json(session))


@st.cache_data(ttl=300)
def load_demo():
    return L.demo_payload()


@st.cache_data(ttl=300)
def load_snap():
    return L.load_snapshot()


# ═════════════ TRANG RIÊNG: TỔNG QUAN ĐIỀU HÀNH (chỉ chủ shop + zenzen197) ═════════════
if _page == PAGE_OVERVIEW:
    _render_overview()
    st.stop()

# ═════════════ TRANG VẬN HÀNH: Báo cáo cuối ngày + Đơn trả + Phiếu nhặt (tab ngang) ═════════════
# CSKH (nv không phải kho) chỉ thấy Báo cáo cuối ngày; kho/admin thấy đủ 3 tab.
if _page == PAGE_OPS:
    if _is_cskh:
        _render_daily()
    else:
        _ops_tab = st.radio(
            "Tab vận hành",
            ["📄 Báo cáo cuối ngày", "📦 Đơn trả hàng", "🧾 Phiếu nhặt hàng"],
            horizontal=True,
            label_visibility="collapsed",
            key="ops_active_tab",
        )
        if _ops_tab.startswith("📄"):
            _render_daily()
        elif _ops_tab.startswith("📦"):
            _render_returns()
        else:
            _render_pick()
    st.stop()


# ───────────────────────── Sidebar: chọn nguồn dữ liệu ─────────────────────────
has_cred = credential_present()
has_snap = L.snapshot_exists()

OPT_LIVE = "🟢 LIVE — gọi API Sapo"
OPT_SNAP = "📸 Snapshot — dữ liệu thật đã chụp"
OPT_DEMO = "🔵 DEMO — số liệu mẫu"

# Thứ tự ưu tiên (mặc định chọn cái đầu): LIVE > Snapshot > DEMO
options = []
if has_cred:
    options.append(OPT_LIVE)
if has_snap:
    options.append(OPT_SNAP)
options.append(OPT_DEMO)

with st.sidebar:
    st.header("⚙️ Nguồn dữ liệu")
    source = st.radio("Chọn nguồn", options, index=0)
    st.caption(
        "🔑 Có credential — dùng được LIVE." if has_cred
        else "⚠️ Chưa có credential LIVE (xem README để gọi API trực tiếp)."
    )
    if st.button("🔄 Làm mới dữ liệu", width="stretch"):
        st.cache_data.clear()
        st.rerun()
    auto_refresh = st.toggle(
        "⏱️ Tự làm mới mỗi 5 phút", value=True,
        help="Tự tải lại số liệu mới nhất sau mỗi 5 phút (giữ tab luôn mới).",
    )
    st.caption("🖨️ In hoặc lưu PDF khổ A4:")
    components.html(
        """
        <button onclick="(function(){try{window.parent.print()}catch(e){try{window.top.print()}catch(e2){window.print()}}})()"
          style="width:100%;padding:9px 12px;border:0;background:#BA7517;color:#fff;border-radius:8px;
                 font-size:14px;font-weight:700;cursor:pointer;font-family:inherit;">
          🖨️ In A4 / Lưu PDF
        </button>
        """,
        height=48,
    )

# ───────────────────────── Lấy dữ liệu ─────────────────────────
snap_time = None
if source == OPT_LIVE:
    try:
        data = load_live()
    except SapoAuthError as e:
        st.error(f"❌ {e}")
        st.stop()
    except requests.HTTPError as e:
        st.error(f"❌ Lỗi gọi API Sapo: `{e}`. Cookie có thể đã hết hạn — lấy lại cookie mới.")
        st.stop()
    except requests.RequestException as e:
        st.error(f"❌ Lỗi kết nối Sapo: `{e}`.")
        st.stop()
    st.success("🟢 Đang hiển thị **dữ liệu LIVE** từ Sapo.")
elif source == OPT_SNAP:
    data = load_snap()
    snap_time = data.get("generated_at_vn")
    st.success(f"📸 Đang hiển thị **dữ liệu thật** đã chụp lúc **{snap_time}** (giờ VN). "
               "Chạy lại script chụp để cập nhật.")
else:
    data = load_demo()
    st.info("🔵 **Chế độ DEMO** — số liệu mẫu. Chọn nguồn khác ở sidebar để xem dữ liệu thật.")

p, c, r = data["pending"], data["cancelled"], data["returns"]

# ───────────────────────── Header ─────────────────────────
left, right = st.columns([3, 1])
left.title("🛍️ VITRAN BOUTIQUE")
left.caption("Báo cáo vận hành đơn hàng")
if snap_time:
    right.metric("Dữ liệu chụp lúc", snap_time[11:16], snap_time[:10])
else:
    vn_now = datetime.now(timezone.utc) + timedelta(hours=7)
    right.metric("Cập nhật (giờ VN)", vn_now.strftime("%H:%M"), vn_now.strftime("%d/%m/%Y"))


# ── 🚨 TỔNG KẾT TRONG NGÀY: đơn đã đẩy VC → hủy hôm nay (nổi bật, đầu trang) ──
def _vn_day(iso):
    s = (iso or "").replace("Z", "").replace("+00:00", "").split(".")[0]
    try:
        return (datetime.fromisoformat(s) + timedelta(hours=7)).date()
    except Exception:
        return None


_today_vn = (datetime.now(timezone.utc) + timedelta(hours=7)).date()
_cancel_today = [o for o in (c["packed"] + c["not_packed"]) if _vn_day(o.get("cancelled_on")) == _today_vn]
if _cancel_today:
    _pk = sum(1 for o in _cancel_today
              if (o.get("fulfillments") or [{}])[0].get("packed_status") == "packed")
    _names = ", ".join(o.get("name", "") for o in _cancel_today[:20]) + ("…" if len(_cancel_today) > 20 else "")
    st.error(f"🚨 **{len(_cancel_today)} đơn ĐÃ ĐẨY VC → HỦY trong HÔM NAY** — "
             f"{_pk} đơn đã đóng gói (cần LẤY LẠI hàng ngay), {len(_cancel_today) - _pk} chưa đóng gói. "
             f"Mã đơn: {_names}")
else:
    st.success("✅ Hôm nay chưa có đơn đã đẩy VC bị hủy.")

# ═══════════════════════ PHẦN 1 — CHỜ XÁC NHẬN ═══════════════════════
st.markdown(
    f'<div class="sec sec-orange">Chờ xác nhận'
    f'<span class="ic" title="Đơn mới từ sàn (TikTok/Shopee) đã đồng bộ về Sapo, đang chờ shop bấm «Xác nhận» để bắt đầu xử lý/đóng gói. Cần xác nhận trong ngày (trước 18h giờ VN) để không bị tính trễ với sàn.">&#9432;</span> '
    f'<span class="sub">— {p["total"]} đơn · {p["total_items"]} SP · {p["sku_count"]} SKU</span></div>',
    unsafe_allow_html=True,
)

k = st.columns(5)
k[0].metric("Tổng đơn", p["total"], help="Tổng số đơn đang chờ xác nhận (mỗi mã đơn tính 1 đơn).")
k[1].metric("Sản phẩm", p["total_items"], help="Tổng số lượng sản phẩm trong các đơn chờ (cộng số lượng từng dòng hàng).")
k[2].metric("SKU", p["sku_count"], help="Số mã SKU khác nhau trong các đơn chờ (1 SKU có thể nằm trong nhiều đơn).")
k[3].metric("🟠 Đặt hôm nay", p["today"], help="Đơn được KHÁCH đặt trong hôm nay (từ 00:00 giờ VN).")
k[4].metric("Đặt hôm qua", p["yesterday"], help="Đơn được khách đặt trong ngày hôm qua (giờ VN).")

k2 = st.columns(5)
k2[0].metric("Giao nhanh", p["fast"], help="Đơn dùng dịch vụ giao tiêu chuẩn/nhanh (không phải hỏa tốc).")
k2[1].metric("Hỏa tốc", p["express"], help="Đơn dịch vụ HỎA TỐC — giao siêu nhanh, cần ưu tiên nhặt & đóng trước.")

g1, g2 = st.columns(2)
with g1:
    st.markdown('**Sàn TMĐT** <span class="ic" title="Đơn đến từ sàn nào: TikTok Shop (đen), Shopee (cam).">&#9432;</span>',
                unsafe_allow_html=True)
    src_keys = list(p["sources"].keys())
    st.plotly_chart(
        donut(
            [SOURCE_LABEL.get(k_, k_) for k_ in src_keys],
            list(p["sources"].values()),
            [COLOR_SOURCE.get(k_, "#CCCCCC") for k_ in src_keys],
            str(p["total"]),
        ),
        width="stretch",
    )
with g2:
    st.markdown('**Gian hàng** <span class="ic" title="Mỗi sàn có thể có nhiều gian hàng (VITRAN BOUTIQUE, SMOSS, MUN-AI...). Đây là số đơn chờ xác nhận theo từng gian hàng.">&#9432;</span>',
                unsafe_allow_html=True)
    store_keys = list(p.get("stores", {}).keys())
    st.plotly_chart(
        donut(
            store_keys,
            list(p.get("stores", {}).values()),
            [PALETTE[i % len(PALETTE)] for i in range(len(store_keys))],
            str(p["total"]),
        ),
        width="stretch",
    )

st.markdown('**Đơn vị vận chuyển** <span class="ic" title="Đơn vị giao hàng (J&amp;T, SPX, GHN...). «NB tự VC» = «Vận hành bởi nhà bán hàng» — shop tự sắp xếp giao, Sapo chưa gắn hãng cụ thể (không phải lỗi).">&#9432;</span>',
            unsafe_allow_html=True)
car_keys = list(p["carriers"].keys())
st.plotly_chart(
    donut(
        car_keys,
        list(p["carriers"].values()),
        [COLOR_CARRIER.get(k_, "#CCCCCC") for k_ in car_keys],
        str(p["total"]),
    ),
    width="stretch",
)

st.markdown('**Chi tiết SKU chờ xác nhận** <span class="ic" title="Số lượng cần nhặt theo từng mã SKU. SKU cùng «mã đầu» (vd SD-, OL-) được nhóm lại & tô cùng màu để dễ gom hàng.">&#9432;</span>',
            unsafe_allow_html=True)

if p["skus"]:
    sku_df = pd.DataFrame(p["skus"])
    sku_df["nhom"] = sku_df["sku"].astype(str).str.split("-").str[0]
    grp = sku_df.groupby("nhom")["qty"].sum().sort_values(ascending=False)

    cc = st.columns([2, 3])
    with cc[0]:
        st.markdown("Tỉ trọng theo **nhóm SKU**")
        gk = list(grp.index)
        st.plotly_chart(
            donut(gk, [int(v) for v in grp.values],
                  [PALETTE[i % len(PALETTE)] for i in range(len(gk))], str(int(grp.sum()))),
            width="stretch",
        )
    with cc[1]:
        view = sku_df.sort_values(["nhom", "qty"], ascending=[True, False]).rename(
            columns={"sku": "SKU", "name": "Sản phẩm", "qty": "SL", "orders": "Đơn", "nhom": "Nhóm"}
        )[["Nhóm", "SKU", "Sản phẩm", "SL", "Đơn"]]
        _groups = list(dict.fromkeys(view["Nhóm"]))
        _light = ["#FDF1E7", "#E9F5EF", "#FBF3DF", "#FDEBEA", "#E8F1FB", "#EFF4E6", "#F3E9F6", "#E6F2F0"]
        _cmap = {g: _light[i % len(_light)] for i, g in enumerate(_groups)}
        _styler = view.style.apply(
            lambda row: [f"background-color:{_cmap.get(row['Nhóm'], '#ffffff')}"] * len(row), axis=1
        )
        st.dataframe(_styler, width="stretch", hide_index=True)
        st.markdown('<div class="print-only">' + view.to_html(index=False, border=0) + '</div>',
                    unsafe_allow_html=True)
else:
    st.info("Không có SKU chờ xác nhận.")

# ═══════════════════════ PHẦN 2 — ĐÃ ĐẨY VC → HỦY (7 NGÀY) ═══════════════════════
st.markdown(
    f'<div class="sec sec-red">Đã đẩy VC → hủy (7 ngày)'
    f'<span class="ic" title="Đơn đã bàn giao/đẩy cho đơn vị vận chuyển nhưng SAU ĐÓ bị hủy (trong 7 ngày). Nếu đã đóng gói thì kho phải LẤY LẠI hàng khỏi kiện. Đã loại các đơn kháng nghị thành công.">&#9432;</span> '
    f'<span class="sub">— loại trừ {c["excluded_appeal"]} đơn kháng nghị thành công</span></div>',
    unsafe_allow_html=True,
)

m = st.columns(3)
m[0].metric("Tổng đơn hủy", c["total"], help="Tổng đơn đã đẩy VC rồi bị hủy trong 7 ngày (đã loại kháng nghị thành công).")
m[1].metric("⚠ Đã đóng gói (lấy lại)", len(c["packed"]), help="Đơn đã ĐÓNG GÓI mà bị hủy → kho cần LẤY LẠI hàng khỏi kiện.")
m[2].metric("Chưa đóng gói", len(c["not_packed"]), help="Đơn bị hủy khi CHƯA đóng gói → không phải lấy lại hàng.")

st.info("🚨 **NV kho:** mỗi đơn dưới đây cần **xác nhận + up ảnh bằng chứng** theo cột «📸 Bằng chứng cần up». "
        "(Ô bấm xác nhận & up ảnh lên Google Drive đang được thêm ở bước kế tiếp.)")

st.markdown("**⚠ Đã đóng gói — cần lấy lại hàng**")
packed_df = cancel_table(c["packed"])
if packed_df.empty:
    st.success("Không có đơn đã đóng gói nào bị hủy. 👍")
else:
    st.dataframe(packed_df, width="stretch", hide_index=True)
    st.markdown('<div class="print-only">' + packed_df.to_html(index=False, border=0) + '</div>',
                unsafe_allow_html=True)

st.markdown("**Chưa đóng gói**")
np_df = cancel_table(c["not_packed"])
if np_df.empty:
    st.info("Không có đơn chưa đóng gói.")
else:
    st.dataframe(np_df, width="stretch", hide_index=True)
    st.markdown('<div class="print-only">' + np_df.to_html(index=False, border=0) + '</div>',
                unsafe_allow_html=True)

# ═══════════════════════ PHẦN 3 — ĐƠN TRẢ HÀNG (7 NGÀY) ═══════════════════════
st.markdown(
    f'<div class="sec sec-blue">Đơn trả hàng (7 ngày)'
    f'<span class="ic" title="Phiếu khách yêu cầu trả hàng trong 7 ngày. Đã bỏ các phiếu «canceled» = kháng nghị thành công / khách tự đóng yêu cầu.">&#9432;</span> '
    f'<span class="sub">— đã loại {r["canceled"]} phiếu canceled (khách đóng yêu cầu)</span></div>',
    unsafe_allow_html=True,
)

rm = st.columns(4)
rm[0].metric("Tổng phiếu (7 ngày)", r["recent7d_total"], help="Tổng phiếu trả hàng tạo trong 7 ngày (gồm cả đã/đang xử lý).")
rm[1].metric("🟢 Đang xử lý (open)", r["open"], help="Phiếu trả đang mở, CHƯA xử lý xong.")
rm[2].metric("Đã trả xong (closed)", r["closed"], help="Phiếu trả đã đóng/hoàn tất.")
rm[3].metric("Cần xử lý (active)", r["active"], help="Tổng phiếu cần để mắt = open + closed (đã loại canceled).")

st.plotly_chart(
    donut(
        ["Đang xử lý (open)", "Đã trả xong (closed)"],
        [r["open"], r["closed"]],
        [ACCENT_BLUE, "#1D9E75"],
        str(r["active"]),
    ),
    width="stretch",
)

# ── #8 Đơn trả CẦN THEO DÕI năm nay (tải riêng khi bấm để giữ trang nhanh) ──
st.markdown('**📋 Đơn trả cần theo dõi (năm nay)** '
            '<span class="ic" title="Phiếu trả của NĂM NAY mà CHƯA nhận lại hàng (chưa nhập kho), CHƯA có ghi chú «THẮNG» (kháng nghị thắng) và chưa bị hủy. Là các đơn còn phải xử lý / đòi hàng về.">&#9432;</span>',
            unsafe_allow_html=True)
if st.checkbox("Hiện danh sách (quét đơn trả cả năm — mất vài giây)", value=False):
    fu = load_returns_followup() if credential_present() else r.get("followup", [])
    if fu:
        st.caption(f"**{len(fu)} đơn** cần theo dõi.")
        fu_df = pd.DataFrame(fu).rename(columns={
            "name": "Mã đơn", "note": "Ghi chú (lý do)", "status": "Trạng thái",
            "loai": "Loại trả", "SL": "SL", "ngay_tao": "Ngày tạo"})
        st.dataframe(fu_df, width="stretch", hide_index=True)
        st.markdown('<div class="print-only">' + fu_df.to_html(index=False, border=0) + '</div>',
                    unsafe_allow_html=True)
    else:
        st.success("Không có đơn trả nào cần theo dõi năm nay. 👍")

st.caption("Cache 5 phút · tự làm mới mỗi 5 phút (bật/tắt ở sidebar) · múi giờ VN (UTC+7).")

# Tự làm mới: reload trang sau 5 phút (đăng nhập nhớ cookie nên không bị đăng xuất)
if auto_refresh:
    components.html(
        "<script>setTimeout(function(){parent.window.location.reload();}, 300000);</script>",
        height=0,
    )
