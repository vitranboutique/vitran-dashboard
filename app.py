"""
app.py — Dashboard "Báo cáo sáng" VITRAN BOUTIQUE HCM (Sapo → Streamlit + Plotly).

Chạy:  streamlit run app.py
DEMO:  tự bật khi chưa cấu hình credential (xem README để chuyển sang LIVE).
"""
import os
import re
import unicodedata
from datetime import datetime, timedelta, timezone
from html import escape as _esc
from urllib.parse import quote_plus

import pandas as pd
import plotly.graph_objects as go
import requests
import streamlit as st
import streamlit.components.v1 as components
import streamlit_authenticator as stauth

import sapo_logic as L
import picklog
import dohana
import daily_report
import cham_cong
import cham_cong_ui
from sapo_address import resolve_address
from sapo_client import (
    SapoAuthError, build_session, credential_present, make_fetch_json,
    find_order_returns_by_codes, get_order_return, parse_codes,
    update_order_customer_info, update_order_note, update_order_return_note,
)
from picking_render import picking_html

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

# ───────────────────────── CSS nhẹ (viền trái màu, tiêu đề mục) ─────────────────────────
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
            # ── ĐÓNG HÀNG (xanh) ──
            ("dong_goi", "Đóng gói"), ("vid_dong", "Vid đóng"), ("tag_dong", "Tag đóng"),
            ("huy", "Hủy"), ("soan", "Soạn"), ("shipper_nhan", "Shipper nhận"), ("giao_khach", "Giao khách"),
            # ── HOÀN HÀNG (cam) ──
            ("hoan_don", "Hoàn (đơn)"), ("hoan_sp", "Hoàn SP"), ("vid_hoan", "Vid hoàn"),
            ("thieu", "Thiếu SP"), ("tag_hoan", "Tag hoàn"),
            ("ghi_chu", "Ghi chú")]
    _bd = "border:1px solid #aab2c2;"
    _tagcols = ("tag_dong", "tag_hoan")
    _txt = ("ngay", "thu", "tag_dong", "tag_hoan", "ghi_chu")
    _dong = ("dong_goi", "vid_dong", "tag_dong", "huy", "soan", "shipper_nhan", "giao_khach")   # ĐÓNG → XANH
    _hoan = ("hoan_don", "hoan_sp", "vid_hoan", "thieu", "tag_hoan")                            # HOÀN → CAM
    _redkeys = ("huy", "thieu")             # > 0 = có vấn đề → tô đỏ
    _numkeys = ("dong_goi", "vid_dong", "huy", "soan", "shipper_nhan", "giao_khach",
                "hoan_don", "hoan_sp", "vid_hoan", "thieu")

    def _bg(k, kind):                       # kind: head | cell | tot
        if k in _dong:
            return {"head": "#cfe0f3", "cell": "#eef4fb", "tot": "#dbe7f6"}[kind]
        if k in _hoan:
            return {"head": "#f9dcb8", "cell": "#fdf3e6", "tot": "#f6e2c6"}[kind]
        return {"head": "#dfe4ec", "cell": "#ffffff", "tot": "#eef1f6"}[kind]

    def _red(k, v):
        return "color:#dc2626;font-weight:800;" if (k in _redkeys and isinstance(v, (int, float)) and v > 0) else ""

    head = "".join(
        f'<th style="position:sticky;top:0;z-index:3;text-align:{"left" if k in _txt else "right"};'
        f'padding:6px 8px;{_bd}background:{_bg(k, "head")};color:#16233f'
        f'{";min-width:130px" if k == "ghi_chu" else ""}">{lbl}</th>'
        for k, lbl in cols)

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
        for k, _ in cols:
            al = "left" if k in _txt else "right"
            if k == "ghi_chu" or k in _tagcols:
                v = str(r.get(k, "") or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            else:
                v = r.get(k, "")
            mw = "min-width:110px;" if (k == "ghi_chu" or k in _tagcols) else ""
            _nay = (' <span style="color:#E24B4A;font-size:11px">• nay</span>'
                    if hot and k == "ngay" else "")
            _tagclr = "color:#7c3aed;font-weight:700;" if (k in _tagcols and v) else ""
            wt = "font-weight:800;" if hot else ""
            bg = "#fff2e0" if hot else _bg(k, "cell")     # hôm nay: nền cam nhạt cả dòng
            cells += (f'<td style="text-align:{al};padding:5px 8px;{_bd}{wtop}{mw}background:{bg};{wt}{_red(k, v)}{_tagclr}">'
                      f'{v}{_nay}</td>')
        body += f'<tr>{cells}</tr>'

    def _tot_row(label, src, label_bg):
        cells = f'<td colspan="2" style="text-align:left;padding:6px 8px;{_bd}background:{label_bg}">{label}</td>'
        for k, _ in cols[2:]:
            if k == "ghi_chu":
                cells += f'<td style="padding:6px 8px;{_bd}background:#ffffff"></td>'
                continue
            if k in _tagcols:
                tv = str(src.get(k, "") or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
                cells += (f'<td style="text-align:left;padding:6px 8px;{_bd}background:{_bg(k, "tot")};'
                          f'{"color:#7c3aed;" if tv else ""}">{tv}</td>')
                continue
            v = src.get(k, 0)
            cells += (f'<td style="text-align:right;padding:6px 8px;{_bd}background:{_bg(k, "tot")};'
                      f'{_red(k, v)}">{v}</td>')
        return f'<tr style="font-weight:800;color:#16233f">{cells}</tr>'

    tot_all = {k: sum(r.get(k, 0) for r in wk) for k in _numkeys}
    tots = _tot_row(f"TỔNG {len(wk)} ngày qua", tot_all, "#eef1f6")
    if month:
        tots += _tot_row(f"TỔNG tháng {mlabel}", month, "#e0e7ff")
    # Tổng ĐEM LÊN ĐẦU (ngay dưới tiêu đề); tiêu đề STICKY (position:sticky) → trượt không mất.
    return (f'<div style="max-height:540px;overflow:auto;border:1px solid #aab2c2;border-radius:6px">'
            f'<table style="width:100%;border-collapse:collapse;font-size:11.5px">'
            f'<thead><tr>{head}</tr></thead><tbody>{tots}{body}</tbody></table></div>')


def _ascii_code(s):
    """Chuẩn hoá mã để khớp: BỎ DẤU tiếng Việt (do app Dohana lỗi phông biến YX→Ỹ…),
    in HOA, chỉ giữ chữ-số. VD 'GỸQMQTD' -> 'GYQMQTD'."""
    s = unicodedata.normalize("NFKD", str(s or ""))
    s = "".join(c for c in s if not unicodedata.combining(c))
    return "".join(c for c in s.upper() if c.isalnum())


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


def _enrich_daily(rep, dvr, inb):
    """Gắn đối chiếu CLIP KHUI HÀNG (inbound) + VIDEO ĐÓNG GÓI (package) vào rep.
    Dùng chung cho cả báo cáo hôm nay và xem lại ngày cũ."""
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
            d["clip_tag"] = m.get("tag") if m else ""
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
                    d["clip_tag"] = m.get("tag")
                    d["clip_staff"] = m.get("staff")
        nk["clip_available"] = True
        nk["clip_co"] = sum(1 for d in nk.get("detail", []) if d.get("clip"))
        nk["clip_total"] = inb.get("total", 0)
        nk["clip_unmatched"] = sorted(inb.get("today_codes", set()) - consumed)
        # Kèm TAG (vd Khách tráo!) + thời lượng/giờ cho clip dư — đơn có tag thường bị giữ lại
        # xử lý tranh chấp nên KHÔNG nhập kho (đúng quy trình) → cần hiện rõ tag để theo dõi.
        nk["clip_unmatched_detail"] = [
            {"code": c, "tag": (meta.get(c) or {}).get("tag", ""),
             "dur": (meta.get(c) or {}).get("dur"),
             "recorded": (meta.get(c) or {}).get("recorded", ""),
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
    # BẢNG ĐỐI CHIẾU: DỰNG LUÔN LUÔN (kể cả khi Dohana lỗi/429) → đơn trả hàng KHÔNG biến mất;
    # không lấy được clip thì cột clip để trống. Đơn ĐÃ nhập kho (Sapo) + clip DƯ (chưa nhập kho).
    recon = []
    for d in nk.get("detail", []):
        recon.append({
            "clip_code": d.get("clip_code"), "clip_time": d.get("clip_time"),
            "clip_dur": d.get("clip_dur"), "clip_tag": d.get("clip_tag"),
            "clip_alt": d.get("clip_altcode"), "has_clip": bool(d.get("clip")),
            "order_code": d.get("order_code"), "recv_time": d.get("recv_time"),
            "vd_gui": d.get("tracking"),   # mã VĐ GIAO ĐI (tra Sapo/sàn được)
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
            "clip_dur": u.get("dur"), "clip_tag": u.get("tag"),
            "clip_alt": False, "has_clip": True,
            "order_code": info.get("order_code") or "", "recv_time": "", "vd_gui": info.get("vd_gui") or "",
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

    users = st.secrets["auth"]["users"]
    ck = st.secrets["auth"].get("cookie", {})
    credentials = {"usernames": {}}
    for uname, info in users.items():
        credentials["usernames"][uname] = {
            "name": info.get("name", uname),
            "password": info["password"],          # plaintext -> auto_hash bên dưới
            "email": info.get("email", f"{uname}@vitran.local"),
            "roles": [info.get("role", "viewer")],
        }

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
PAGE_CHAMCONG = "🕘 Chấm công"
PAGE_LUONG = "💰 Lương của tôi"
PAGE_QRSHOP = "📲 QR chấm công (shop)"
PAGE_QLCC = "🛠️ Quản lý chấm công"

# Phân quyền theo tài khoản.
#  · Tổng quan + Báo cáo cuối ngày: AI CŨNG xem được.
#  · Kho: thêm Phiếu nhặt + Đơn trả.  · CSKH: thêm Lấy-lưu TTKH.
#  · Chấm công/Lương: của ai người nấy.  · Admin: xem hết + QR shop + quản lý chấm công.
_cc_role = cham_cong.role_of(CUR_USER)
_cc_emp = cham_cong.emp_of(CUR_USER)
if _cc_role == "nv":
    _rolepg = [PAGE_PICK, PAGE_RETURNS] if _cc_emp == "kho" else [PAGE_TTKH]
    _opts = [PAGE_DAILY, PAGE_OVERVIEW] + _rolepg + [PAGE_CHAMCONG, PAGE_LUONG]
    _default = PAGE_CHAMCONG if st.query_params.get("tk") else PAGE_DAILY   # quét QR → về Chấm công
elif _cc_role == "shop":                    # máy shop: CHỈ thấy trang hiện mã QR chấm công
    _opts = [PAGE_QRSHOP]
    _default = PAGE_QRSHOP
elif _cc_role == "admin":
    _opts = [PAGE_OVERVIEW, PAGE_PICK, PAGE_TTKH, PAGE_DAILY, PAGE_RETURNS,
             PAGE_QRSHOP, PAGE_QLCC]
    _default = PAGE_OVERVIEW
else:
    _opts = [PAGE_OVERVIEW, PAGE_PICK, PAGE_TTKH, PAGE_DAILY, PAGE_RETURNS]
    _default = PAGE_OVERVIEW
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
    # Đơn đã ghi nhưng CHƯA tạo được khách → giữ hiện (chưa đủ 2 nơi). Đọc từ Gist.
    try:
        _pending_ids = set(picklog.read_ttkh_pending().keys()) if picklog.configured() else set()
    except Exception:
        _pending_ids = set()
    return L.get_tt_customer_candidates(make_fetch_json(build_session()), days=days,
                                        channel_filter=channel_filter, pending_ids=_pending_ids)


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
    recs = [r for r in picklog.read_dohana_videos() if r.get("type") == "package"]
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
    recs = [r for r in picklog.read_dohana_videos() if r.get("type") == "inbound"]
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
                       "tag_id": r.get("tag_id"), "tag": dohana._tag_name(r.get("tag_id")),
                       "staff": r.get("staff") or ""}
    return {"total": len(day), "count": count, "match": set(count),
            "today_codes": {r.get("code") for r in day if r.get("code")},
            "dup": {}, "meta": meta, "records": [], "_from_store": True}


def _today_iso_vn():
    return (datetime.now(timezone.utc) + timedelta(hours=7)).date().isoformat()


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


@st.cache_data(ttl=1800, show_spinner=False)  # video ngày cũ không đổi → cache dài, đỡ gọi Dohana
def load_dohana_date(date_iso):
    from datetime import date as _date
    live = dohana.today_package_videos(target_date=_date.fromisoformat(date_iso))
    if live is not None:
        return _dohana_merge(live)
    return _dohana_pkg_from_store(date_iso) if picklog.configured() else None


@st.cache_data(ttl=1800, show_spinner=False)  # video ngày cũ không đổi → cache dài, đỡ gọi Dohana
def load_dohana_inbound_date(date_iso):
    from datetime import date as _date
    live = dohana.inbound_videos(target_date=_date.fromisoformat(date_iso))
    if live is not None:
        return _dohana_merge(live)
    return _dohana_inb_from_store(date_iso) if picklog.configured() else None


@st.cache_data(ttl=180, show_spinner="Đang tổng hợp báo cáo cuối ngày…")
def load_daily_report(date_iso=None):
    from datetime import date as _date
    td = _date.fromisoformat(date_iso) if date_iso else None
    return L.get_daily_report(make_fetch_json(build_session()), target_date=td)


@st.cache_data(ttl=600, show_spinner="Đang tổng hợp 30 ngày (1 tháng)…")
def load_week_summary():
    data = L.get_week_summary(make_fetch_json(build_session()), days=30)
    # SỐ VIDEO đóng/hoàn + TAG (Khách tráo / Đã sử dụng / Hư hỏng...) từ kho video Dohana, theo NGÀY.
    for day in data.get("days", []):
        for _k, _v in (("vid_dong", 0), ("vid_hoan", 0), ("tag_dong", ""), ("tag_hoan", "")):
            day.setdefault(_k, _v)
    if isinstance(data.get("month"), dict):
        for _k, _v in (("vid_dong", 0), ("vid_hoan", 0), ("tag_dong", ""), ("tag_hoan", "")):
            data["month"].setdefault(_k, _v)
    try:
        if picklog.configured():
            from collections import Counter as _Ct
            recs = picklog.read_dohana_videos()
            vdong, vhoan, tdong, thoan = {}, {}, {}, {}   # tag TÁCH theo loại video: đóng vs khui
            for r in recs:
                d, ty = r.get("date"), r.get("type")
                if not d:
                    continue
                tn = dohana._tag_name(r.get("tag_id")) if r.get("tag_id") else ""
                if ty == "package":          # đóng hàng → tag đóng (vd đóng thiếu SP)
                    vdong[d] = vdong.get(d, 0) + 1
                    if tn:
                        tdong.setdefault(d, _Ct())[tn] += 1
                elif ty == "inbound":        # khui hàng → tag hoàn (tráo / mất / hư hỏng / đã dùng)
                    vhoan[d] = vhoan.get(d, 0) + 1
                    if tn:
                        thoan.setdefault(d, _Ct())[tn] += 1
            _mpref = (data.get("days") or [{}])[0].get("iso", "")[:7]   # 'YYYY-MM' tháng này

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
                day["vid_hoan"] = vhoan.get(iso, 0)
                day["tag_dong"] = _tagstr(tdong.get(iso))
                day["tag_hoan"] = _tagstr(thoan.get(iso))
            if isinstance(data.get("month"), dict):
                m = data["month"]
                m["vid_dong"], m["vid_hoan"] = _msum(vdong), _msum(vhoan)
                m["tag_dong"], m["tag_hoan"] = _mtag(tdong), _mtag(thoan)
    except Exception:
        pass
    return data


@st.cache_data(ttl=180, show_spinner=False)
def load_alerts():
    return L.get_alerts(make_fetch_json(build_session()))


def render_alert_popup():
    """Popup CẢNH BÁO cố định, hiện ở MỌI trang (position:fixed)."""
    if not credential_present():
        return
    try:
        a = load_alerts()
    except Exception:
        return
    # (label, value, [danh sách dòng phụ con])
    items = [
        ("🕒 Xác nhận sau 18h", a["conf_after18"], None),
        # Đơn xác nhận trễ = đặt TRƯỚC 18h (trong giờ) nhưng mãi SAU 18h mới xác nhận
        ("📌 Đơn xác nhận trễ", a["late_confirm"], None),
        ("📦 Đơn xót lại (chờ shipper)", a["chua_giao"], [
            ("chưa đóng hàng", a.get("xot_chua_dong", 0)),
            ("đã đóng hàng", a.get("xot_da_dong", 0)),
        ]),
        ("🔴 Hỏa tốc chưa giao", a["express_pending"], None),
        ("↩️ Hủy sau gói cần LẤY LẠI", a["cancel_retrieve"], [
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
    _cache_ver = 11  # bump khi đổi cấu trúc trả về → buộc tính lại (tránh cache cũ gây lỗi)
    return L.get_returns_in_progress(make_fetch_json(build_session()))


# Popup cảnh báo cố định — hiện ở MỌI trang
render_alert_popup()


# ════════════════ TRANG TỔNG QUAN ĐIỀU HÀNH ════════════════
if _page == PAGE_OVERVIEW:
    _l, _r = st.columns([3, 1])
    _l.title("🛍️ VITRAN BOUTIQUE")
    _l.caption("Tổng quan điều hành")
    _vn = datetime.now(timezone.utc) + timedelta(hours=7)
    _r.metric("Cập nhật (giờ VN)", _vn.strftime("%H:%M"), _vn.strftime("%d/%m/%Y"))
    if not credential_present():
        st.warning("⚠️ Trang này cần kết nối Sapo (LIVE).")
        st.stop()
    if st.button("🔄 Tải lại số liệu"):
        st.cache_data.clear()
        st.rerun()
    try:
        ov = load_overview()
    except Exception as e:
        st.error(f"❌ Lỗi tải tổng quan: `{e}`")
        st.stop()

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
    st.stop()


if _page == PAGE_PICK:
    st.title("🧾 Phiếu nhặt hàng")
    st.caption("Tự kéo từ Sapo: đơn **đã in phiếu giao hàng** + **chờ đóng gói**. "
               "Hỏa tốc ưu tiên nhặt trước. Đếm cũ/mới theo **Ngày xử lý** (Sapo), cảnh báo xử lý trễ.")
    if not credential_present():
        st.warning("⚠️ Trang này cần kết nối Sapo (API LIVE) — hiện chưa có credential.")
        st.stop()
    if st.button("🔄 Tải lại đơn cần nhặt"):
        st.cache_data.clear()
        st.rerun()
    try:
        pdata = load_picking()
    except Exception as e:
        st.error(f"❌ Lỗi kéo đơn từ Sapo: `{e}`")
        st.stop()

    exp, nor = pdata["express"], pdata["normal"]
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

    # ── 📦 Số ĐỢT SOẠN HÀNG hôm nay (đếm theo phiếu đã lưu) ──
    if picklog.configured():
        _ps = st.columns(3)
        _ps[0].metric("📦 Số đợt soạn hôm nay", len(_picklog_today),
                      help="Số lần bấm 'Lưu đợt vừa in' hôm nay = số đợt soạn/in phiếu.")
        _ps[1].metric("Tổng đơn đã soạn", sum(r.get("so_don", 0) for r in _picklog_today))
        _ps[2].metric("Tổng SP đã soạn", sum(r.get("so_sp", 0) for r in _picklog_today))
    else:
        st.info("📦 **Số đợt soạn hàng hôm nay** — bật lưu lịch sử in (mục ⚙️ bên phải phiếu) "
                "để đếm theo số phiếu bạn lưu.")

    # ── ⚠️ SP bị HỦY sau khi đã in phiếu nhặt (quan trọng, trên cùng) ──
    cp = pdata.get("cancel_pick", {})
    st.markdown('<div class="sec sec-red">⚠️ SP bị HỦY sau khi đã in phiếu nhặt</div>',
                unsafe_allow_html=True)
    if cp.get("rows"):
        st.error(f"**{cp['tong_don']} đơn · {cp['tong_sp']} SP** đã in phiếu nhặt rồi BỊ HỦY hôm nay "
                 "— cần lấy lại hàng / kiểm kho ngay.")
        render_compact_table(pd.DataFrame(cp["rows"]))
        st.caption("Đơn đã có vận đơn (đã in phiếu) rồi bị hủy. Dò **mã vận đơn + đợt in phiếu** để thu hồi hàng đúng đợt.")
    else:
        st.success("✅ Hôm nay chưa có đơn nào hủy sau khi in phiếu nhặt.")

    # ── 🔍 Đối chiếu SP soạn hàng vs xuất kho hôm nay (theo SKU) ──
    rec = pdata.get("reconcile", {})
    if rec.get("rows"):
        st.markdown("#### 🔍 Đối chiếu SP soạn hàng vs xuất kho hôm nay")
        rc = st.columns(3)
        rc[0].metric("📦 SP đã soạn (đóng gói)", rec["tong_soan"])
        rc[1].metric("🚚 SP đã xuất kho (giao VC)", rec["tong_xuat"])
        rc[2].metric("⚠️ SKU lệch", rec["so_sku_lech"], help="Số SKU có SL soạn ≠ SL xuất kho.")
        if rec["so_sku_lech"] == 0 and rec["tong_soan"] == rec["tong_xuat"]:
            st.success("✅ KHỚP hoàn toàn — số SP soạn = số SP xuất kho hôm nay.")
        else:
            st.warning(f"⚠️ Lệch tổng **{rec['tong_soan'] - rec['tong_xuat']:+d} SP** · "
                       f"**{rec['so_sku_lech']} SKU** chưa khớp (xem các dòng tô đỏ).")
        _rdf = pd.DataFrame(rec["rows"])
        render_compact_table(_rdf, red_mask=(_rdf["Lệch"] != 0).tolist())
        st.caption("**Soạn** = đóng gói hôm nay. **Xuất kho** = giao ĐVVC hôm nay. "
                   "Lệch > 0 = đã soạn chưa xuất (chờ shipper); < 0 = xuất từ đơn soạn hôm trước. "
                   "Cột **Lý do lệch** ghi rõ đơn nào.")

    # ── 🎥 Video đóng hàng (Dohana): đối chiếu video vs đơn đã đóng + video trùng ──
    st.markdown('<div class="sec sec-orange">🎥 Video đóng hàng (Dohana)</div>', unsafe_allow_html=True)
    if not dohana.configured():
        st.info("Chưa bật API Dohana — thêm key để đối chiếu video đóng hàng.")
        with st.expander("⚙️ Cách bật (dán 1 dòng vào Secrets)"):
            st.markdown(_DOHANA_SETUP)
    else:
        _dv = load_dohana() or {"total": 0, "codes": {}, "dup": {}, "match": set()}
        _packed_ids = pdata.get("packed_ids", [])
        _mset = _dv.get("match", set())
        # Khớp CHỊU LỖI PHÔNG (mã video méo/dính), thay vì giao tập tuyệt đối.
        _vmatch, _vfont = match_packing_videos(_packed_ids, _mset)
        _missing = [ids for i, ids in enumerate(_packed_ids) if i not in _vmatch]
        _dup = _dv["dup"]
        _vc = st.columns(3)
        _vc[0].metric("🎥 Video đóng hàng hôm nay", _dv["total"],
                      help="Số video type=package tạo hôm nay trên Dohana.")
        _vc[1].metric("📦 Đơn đã đóng (Sapo)", len(_packed_ids))
        _vc[2].metric("⚠️ Đơn THIẾU video", len(_missing),
                      help="Đơn đã đóng gói (Sapo) nhưng chưa tìm thấy video (khớp cả mã vận đơn + mã đơn, 3 ngày).")
        if not _missing and not _dup and _packed_ids:
            st.success("✅ KHỚP — mọi đơn đã đóng đều có video, không trùng.")
        if _vfont:
            _fl = ", ".join(f"{v}↔{o}" for v, o in _vfont[:8])
            st.info(f"ℹ️ **{len(_vfont)} clip mã bị lỗi phông / dính mã** — đã TỰ khớp (NV quay đủ): {_fl}"
                    + ("" if len(_vfont) <= 8 else f" …(+{len(_vfont) - 8})")
                    + ". Nên sửa app đóng hàng để mã chuẩn, tránh phải dò tay.")
        if _dup:
            st.warning(f"⚠️ **{len(_dup)} mã có VIDEO TRÙNG** (quay ≥2 lần):")
            render_compact_table(pd.DataFrame(
                [{"Mã đơn": k, "Số video": v} for k, v in sorted(_dup.items(), key=lambda x: -x[1])]))
        if _missing:
            st.warning(f"⚠️ **{len(_missing)} đơn đã đóng nhưng THIẾU video** "
                       "(chưa tìm thấy clip — có thể chưa quay / quay nhầm mục / mã lỗi phông nặng):")
            render_compact_table(pd.DataFrame([{"Mã đơn": (ids[0] if ids else "")} for ids in _missing]))
        st.caption("Đối chiếu Sapo (đóng hôm nay) ↔ video Dohana — khớp theo **mã vận đơn + mã đơn**, "
                   "video **3 ngày** (bắt cả đơn sót). Trùng = 1 mã có ≥2 video. Thiếu = đã đóng mà chưa quay.")

    # ── Phiếu in (trái) + Lịch sử in & nút Lưu (phải, KẾ BÊN phiếu) ──
    _cslip, _clog = st.columns([3, 2])
    with _cslip:
        # Nút IN + TỰ LƯU ĐỢT: lưu picklog phía server (không vướng CORS) → rerun tự bung hộp in.
        if pdata["total"] > 0 and picklog.configured():
            if st.button("🖨️ In phiếu nhặt + tự lưu đợt", type="primary", width="stretch"):
                _allsku = {s for s, _ in exp["skus"]} | {s for s, _ in nor["skus"]}
                _ok, _msg = picklog.log_batch({
                    "ngay": (datetime.now(timezone.utc) + timedelta(hours=7)).strftime("%Y-%m-%d"),
                    "gio": now_str[:5],
                    "so_don": exp["total_orders"] + nor["total_orders"],
                    "so_sp": exp["total_qty"] + nor["total_qty"], "so_sku": len(_allsku),
                    "ht_don": exp["total_orders"], "th_don": nor["total_orders"],
                })
                if _ok:
                    st.session_state["_pick_autoprint"] = True
                    st.rerun()
                else:
                    st.error(_msg)
        elif pdata["total"] > 0 and not picklog.configured():
            st.caption("⚙️ Bật kho lưu (mục bên phải) để dùng **In + tự lưu đợt**.")
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
            st.caption("✅ Bấm **🖨️ In K80 + tự lưu đợt** ở phiếu là TỰ LƯU. Nút dưới chỉ để lưu THỦ CÔNG (nếu cần):")
            if st.button("💾 Lưu đợt thủ công", disabled=not picklog.configured()):
                _now_vn = datetime.now(timezone.utc) + timedelta(hours=7)
                _allsku = {s for s, _ in exp["skus"]} | {s for s, _ in nor["skus"]}
                ok, msg = picklog.log_batch({
                    "ngay": _now_vn.strftime("%Y-%m-%d"), "gio": _now_vn.strftime("%H:%M"),
                    "so_don": exp["total_orders"] + nor["total_orders"],
                    "so_sp": exp["total_qty"] + nor["total_qty"], "so_sku": len(_allsku),
                    "ht_don": exp["total_orders"], "th_don": nor["total_orders"],
                })
                (st.success(msg + " Bấm 🔄 Tải lại để thấy.") if ok else st.error(msg))
            if not picklog.configured():
                st.caption("⚠️ Cần bật kho lưu (xem hướng dẫn trên).")

    with st.expander("📄 Hoặc: tạo phiếu từ file Excel (upload thủ công)"):
        _html_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "picking_slip.html")
        with open(_html_path, encoding="utf-8") as _f:
            components.html(_f.read(), height=1300, scrolling=True)
    st.stop()


# ════════════════ TRANG LẤY - LƯU TTKH ════════════════
if _page == PAGE_TTKH:
    st.title("📞 Lấy - lưu TTKH")
    st.caption("Lọc đơn chưa có SĐT trong ghi chú SAPO để nhân viên lấy TTKH từ TikTok, dán vào app rồi ghi ngược vào SAPO.")
    st.caption("Phiên bản TTKH: 2026-07-02-ttkh-v4")
    if not credential_present():
        st.warning("⚠️ Trang này cần kết nối Sapo (API LIVE).")
        st.stop()

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
        st.stop()

    _m = st.columns(4)
    _m[0].metric("Tổng cần lấy", _tt["total"])
    _m[1].metric("Đơn ≥ 2 SP", len(_tt["multi"]))
    _m[2].metric("Đơn 1 SP", len(_tt["single"]))
    _m[3].metric("Cập nhật", _tt["generated_at_vn"])

    st.info("Điều kiện lọc: đơn trong `Tất cả`, không hủy, tạo trong số ngày chọn, ghi chú/địa chỉ SAPO chưa có SĐT.")

    # ── 📊 THỐNG KÊ LƯU TTKH THEO NGÀY (30 ngày, lưu bền trên Gist) ──
    with st.expander("📊 Thống kê lưu TTKH theo ngày (30 ngày gần nhất)", expanded=False):
        if not picklog.configured():
            st.caption("⚠️ Chưa bật kho lưu Gist (secrets `[picklog].github_token`) nên chưa thống kê được. "
                       "Xem hướng dẫn ở trang Phiếu nhặt hàng.")
        else:
            try:
                _logs = picklog.read_ttkh_logs()
            except Exception as _e:
                _logs = []
                st.caption(f"Không đọc được lịch sử: `{_e}`")
            _today_vn = (datetime.now(timezone.utc) + timedelta(hours=7)).date()
            _from = (_today_vn - timedelta(days=29)).isoformat()
            _rows_by_day = {}
            for _lg in _logs:
                _d = str(_lg.get("ngay") or "")
                if _d < _from:
                    continue
                _agg = _rows_by_day.setdefault(_d, {"Ngày": _d, "Thành công": 0, "Thất bại": 0, "Bỏ qua": 0})
                _kq = _lg.get("ket_qua")
                if _kq == "thanh_cong":
                    _agg["Thành công"] += 1
                elif _kq == "bo_qua":
                    _agg["Bỏ qua"] += 1
                else:
                    _agg["Thất bại"] += 1
            if not _rows_by_day:
                st.caption("Chưa có lượt lưu TTKH nào trong 30 ngày (hoặc chưa lưu lần nào sau khi bật kho).")
            else:
                _stat_rows = []
                for _d in sorted(_rows_by_day, reverse=True):
                    _a = _rows_by_day[_d]
                    _a["Tổng đã lưu"] = _a["Thành công"] + _a["Thất bại"]
                    _stat_rows.append(_a)
                _sc = st.columns(3)
                _sc[0].metric("Tổng đã lưu (30 ngày)", sum(r["Tổng đã lưu"] for r in _stat_rows))
                _sc[1].metric("Thành công", sum(r["Thành công"] for r in _stat_rows))
                _sc[2].metric("Thất bại", sum(r["Thất bại"] for r in _stat_rows))
                st.dataframe(
                    pd.DataFrame(_stat_rows)[["Ngày", "Tổng đã lưu", "Thành công", "Thất bại", "Bỏ qua"]],
                    hide_index=True, width="stretch",
                )
                st.caption("Thành công = đã tạo/cập nhật được khách hàng. Thất bại = ghi được ghi chú nhưng "
                           "chưa tạo được khách, hoặc lỗi. Bỏ qua = dòng chưa hợp lệ (thiếu SĐT/địa chỉ).")

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
            return f"https://banhang.shopee.vn/portal/sale?search={quote_plus(code)}"
        return f"https://seller-vn.tiktok.com/order/detail?order_no={quote_plus(code)}&shop_region=VN"

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
        if status != "Hợp lệ":
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
        codes = ""
        if info.get("address_format") != "new":
            codes = f" | mã: P/T {info.get('province_code') or '-'} - Q/H {info.get('district_code') or '-'} - X/P {info.get('ward_code') or '-'}"
        return f"{fmt}: {line}{codes}"

    def _show_ttkh_write_results():
        results = st.session_state.get("ttkh_write_results") or []
        if not results:
            return

        def _kq(r):
            return str(r.get("Kết quả") or "")

        ok = sum(1 for r in results if _kq(r).startswith("Đã ghi ghi chú + khách") or _kq(r).startswith("Đã tạo/cập nhật khách"))
        cust_fail = [r for r in results if _kq(r).startswith("Đã ghi ghi chú,")]   # đơn OK, KHÁCH lỗi
        hard_fail = [r for r in results if _kq(r).startswith("Lỗi")]               # cả đơn cũng lỗi
        skipped = sum(1 for r in results if _kq(r).startswith("Bỏ qua"))
        failed = len(cust_fail) + len(hard_fail)

        if failed:
            _bad_codes = ", ".join(str(r.get("Mã đơn")) for r in (cust_fail + hard_fail)[:20])
            st.error(
                f"⚠️ Ghi SAPO CHƯA ĐỦ 2 NƠI ở {failed} đơn "
                f"({len(cust_fail)} đơn chưa tạo được KHÁCH, {len(hard_fail)} đơn lỗi cả đơn hàng). "
                f"Các đơn này **vẫn nằm trong danh sách** (có gắn ⚠️) để bạn **ghi lại**: {_bad_codes}. "
                f"Đã lưu đủ 2 nơi: {ok} đơn. Bỏ qua: {skipped}."
            )
        else:
            st.success(f"✅ Đã lưu đủ 2 nơi (đơn + khách): {ok} đơn. Bỏ qua {skipped} đơn chưa hợp lệ.")
        st.dataframe(
            pd.DataFrame(results),
            hide_index=True,
            width="stretch",
            column_config={"Link khách": st.column_config.LinkColumn("Link khách", display_text="Mở khách")},
        )

    def _write_ttkh_rows(rows_to_write):
        session = build_session()
        now_note = (datetime.now(timezone.utc) + timedelta(hours=7)).strftime("%d/%m/%Y %H:%M")
        results = []
        ok_count = 0
        written_ids = []

        def _note_phone_key(value):
            raw = str(value or "").strip()
            return re.sub(r"[^0-9*]+", "", raw)

        for r in rows_to_write:
            if not r["has_phone"] or r["status"] != "Hợp lệ":
                results.append({"Mã đơn": r["code"], "Kết quả": "Bỏ qua", "Link khách": "", "Lý do": r["status"]})
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
                    results.append({"Mã đơn": r["code"], "Kết quả": "Đã ghi ghi chú + khách hàng", "Link khách": customer_url, "Lý do": ""})
                elif isinstance(saved, dict) and saved.get("_ttkh_customer_saved"):
                    ok_count += 1
                    written_ids.append(str(r["order_id"]))
                    customer_tail = "; ".join(saved.get("_ttkh_attempts", [])[-10:])
                    results.append({
                        "Mã đơn": r["code"],
                        "Kết quả": "Đã tạo/cập nhật khách, kiểm tra lại địa chỉ đơn",
                        "Link khách": customer_url,
                        "Lý do": customer_tail[:1600],
                    })
                else:
                    customer_tail = "; ".join(saved.get("_ttkh_attempts", [])[-8:]) if isinstance(saved, dict) else ""
            except Exception as e:
                customer_tail = str(e)[:1200]
            if not any(x.get("Mã đơn") == r["code"] for x in results):
                if note_saved:
                    results.append({
                        "Mã đơn": r["code"],
                        "Kết quả": "Đã ghi ghi chú, chưa ghi được khách/contact",
                        "Link khách": customer_url,
                        "Lý do": (customer_tail or note_error)[:1600],
                    })
                else:
                    results.append({
                        "Mã đơn": r["code"],
                        "Kết quả": "Lỗi",
                        "Link khách": customer_url,
                        "Lý do": ("Ghi chú đơn hàng chưa lưu. " + note_error + " | " + customer_tail).strip(" |")[:1600],
                    })
        st.session_state["ttkh_write_results"] = results
        # Ghi LỊCH SỬ lưu TTKH vào Gist để thống kê theo ngày (không được làm hỏng luồng ghi)
        try:
            _phone_by_code = {r["code"]: (r["info"].get("phone") or "") for r in rows_to_write}

            def _ttkh_result_cat(kq):
                kq = str(kq or "")
                if kq.startswith("Đã ghi ghi chú + khách") or kq.startswith("Đã tạo/cập nhật khách"):
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
                "chi_tiet": str(res.get("Kết quả") or ""),
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
        h[4].markdown("**Địa chỉ chuẩn SAPO**")
        h[5].markdown("**TTKH dán vào**")
        st.markdown("<hr style='margin:4px 0 8px;border:0;border-top:1px solid #e5e7eb'>", unsafe_allow_html=True)
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
                placeholder="Dán nguyên block TTKH từ sàn vào đây",
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
            customer_query = code
            if row_pending:
                _info = row_pending[0].get("info") or {}
                customer_query = _info.get("phone") or _info.get("name") or code
            code_link = f"[{code}]({url})" if url else code
            sapo_link = f" · [Sapo]({sapo_url})" if sapo_url else ""
            customer_link = f" · [Khách]({customer_url})" if customer_url else f" · [Tìm khách]({_sapo_customer_search_url(customer_query)})"
            _needs_cust = bool(r.get("_needs_customer"))
            _warn_badge = ("<div style='color:#b91c1c;font-weight:800;font-size:.8rem'>⚠️ Đã ghi đơn nhưng "
                           "CHƯA tạo được khách — ghi lại dòng này</div>") if _needs_cust else ""
            c[1].markdown(code_link + sapo_link + customer_link + _warn_badge, unsafe_allow_html=True)
            c[2].markdown(
                f"<abbr title='{_product_tip(r)}' style='cursor:help;font-weight:800;text-decoration:underline dotted #6b7280'>{int(r.get('SL SP') or 0)} SP ⓘ</abbr>",
                unsafe_allow_html=True,
            )
            c[3].markdown(str(r.get("Gian hàng") or ""))
            if row_pending:
                rp = row_pending[0]
                preview = _ttkh_address_preview(rp["info"], rp["status"])
                color = "#0f766e" if rp["status"] == "Hợp lệ" else "#b45309"
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
                _label = "Hợp lệ" if row_pending[0]["has_phone"] and _st == "Hợp lệ" else _st
                btn_cols[1].caption(f"Trạng thái dòng: {_label}")
            old_note = str(r.get("Ghi chú hiện tại") or "").strip()
            if old_note:
                c[5].caption(f"Ghi chú cũ: {old_note[:120]}" + ("..." if len(old_note) > 120 else ""))
        pending_here = _collect_ttkh_rows(rows)
        ready_here = sum(1 for r in pending_here if r["has_phone"] and r["status"] == "Hợp lệ")
        save_cols = st.columns([1.6, 1, 5])
        if ready_here:
            save_cols[0].caption(f"Sẵn sàng ghi: {ready_here} đơn trong bảng này")
        if save_cols[1].button("💾 Ghi SAPO", key=f"ttkh_save_{label}", use_container_width=True):
            if pending_here:
                _write_ttkh_rows(pending_here)
            else:
                st.warning("Chưa có dòng TTKH nào được dán trong bảng này.")
        return df

    st.caption("Dán nguyên block TTKH trực tiếp vào cột `TTKH dán vào` của đúng mã đơn. Rê chuột vào cột `SL SP` để xem SKU, SL, giá từng món và tổng tiền.")
    if "ttkh_pending_inputs" not in st.session_state:
        st.session_state["ttkh_pending_inputs"] = {}
    _show_ttkh_write_results()
    _df_multi = _ttkh_table("Đơn ≥ 2 SP", _tt["multi"])
    _df_single = _ttkh_table("Đơn 1 SP", _tt["single"])
    _all_rows = list(_tt["multi"]) + list(_tt["single"])
    if not _all_rows:
        st.caption("Không có đơn để dán TTKH.")

    _pending_write = _collect_ttkh_rows(_all_rows)
    _ready_all = sum(1 for r in _pending_write if r["has_phone"] and r["status"] == "Hợp lệ")
    _invalid_all = len(_pending_write) - _ready_all
    with st.container(key="ttkh_save_float"):
        st.markdown("**💾 Lưu TTKH SAPO**")
        st.caption(f"Hợp lệ: {_ready_all} · Chưa hợp lệ: {_invalid_all}")
        if st.button("💾 Ghi SAPO", key="ttkh_float_save", use_container_width=True):
            if _pending_write:
                _write_ttkh_rows(_pending_write)
            else:
                st.warning("Chưa có dòng TTKH nào được dán.")
        st.caption("Nút này luôn nổi khi cuộn trang.")

    if _pending_write:
        _preview = pd.DataFrame([{
            "Mã đơn": r["code"],
            "Trạng thái": r["status"],
            "Tên": r["info"].get("name", ""),
            "SĐT": r["info"].get("phone", ""),
            "Loại địa chỉ": "Mới" if r["info"].get("address_format") == "new" else "Cũ",
            "Địa chỉ chuẩn SAPO": _ttkh_address_preview(r["info"], r["status"]),
            "Địa chỉ": ", ".join(x for x in [
                r["info"].get("address1", ""), r["info"].get("ward", ""),
                r["info"].get("district", ""), r["info"].get("province", "")
            ] if x),
        } for r in _pending_write])
        st.markdown("#### Kiểm tra TTKH đã dán")
        st.dataframe(_preview, hide_index=True, width="stretch")
        _bad = [r for r in _pending_write if not r["has_phone"] or r["status"] != "Hợp lệ"]
        if _bad:
            st.warning("Một số dòng đã dán TTKH nhưng chưa hợp lệ, app sẽ chưa ghi các dòng đó: "
                       + ", ".join(str(r["code"]) for r in _bad[:10]))
        st.markdown(f"**Sẵn sàng ghi:** {sum(1 for r in _pending_write if r['has_phone'] and r['status'] == 'Hợp lệ')} đơn")
        if st.button("🧹 Xóa toàn bộ danh sách chờ ghi"):
            st.session_state["ttkh_pending_inputs"] = {}
            _clear_ids = set(st.session_state.get("ttkh_clear_ids") or [])
            for _src in _all_rows:
                _clear_ids.add(str(_src.get("order_id")))
            st.session_state["ttkh_clear_ids"] = sorted(_clear_ids)
            st.rerun()

    st.stop()


# ════════════════ TRANG BÁO CÁO CUỐI NGÀY (A4) ════════════════
if _page == PAGE_DAILY:
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
                _tc, _sp = _Ct2(), {}
                for _v in _merged:
                    _tid = _v.get("tag_id")
                    if _tid:
                        _tc[_tid] += 1
                        _sp.setdefault(_tid, _v.get("code"))
                if _tc:
                    st.markdown("**Tag trong kho** — dòng tên *⚠️ Có tag* = CHƯA map tên:")
                    st.dataframe(pd.DataFrame([{
                        "Tên": dohana._tag_name(_t), "Số video": _c,
                        "Mã mẫu (tra trên Dohana)": _sp.get(_t), "tag_id": _t}
                        for _t, _c in _tc.most_common()]), hide_index=True, use_container_width=True)
                    st.caption("Tra 'Mã mẫu' trên Dohana để biết tên tag → nhắn Claude map giúp, hoặc tự thêm vào "
                               "Secrets `[dohana.tags]`  \"tag_id\" = \"Tên tag\".")
    if not credential_present():
        st.warning("⚠️ Cần kết nối Sapo (API LIVE).")
        st.stop()

    # ===== Tổng hợp 7 NGÀY QUA (số cố định sau ngày — query lại là ra số cuối) =====
    # Ẩn mặc định — bấm mới mở (đỡ rối, chỉ xem khi cần).
    with st.expander("📅 Tổng hợp 30 ngày (1 tháng) — đóng gói & đơn hoàn", expanded=False):
        try:
            _wk = load_week_summary()
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
            st.stop()
        _dvr = load_dohana_date(_iso) if dohana.configured() else None
        _inb = load_dohana_inbound_date(_iso) if dohana.configured() else None
        _enrich_daily(_rep, _dvr, _inb)
        if picklog.configured() and isinstance(_rep.get("funnel"), dict):
            _pl = picklog.read_date(_iso)
            _rep["funnel"]["soan"] = sum(r.get("so_don", 0) or 0 for r in _pl) or None
            _rep["funnel"]["soan_sp"] = sum(r.get("so_sp", 0) or 0 for r in _pl) or None
        st.info(f"🗂️ Báo cáo ngày **{_disp}** — query lại từ Sapo, **video lấy từ kho đã lưu** "
                "(Dohana chỉ giữ ~30 ngày; kho Gist lưu bền cả năm). Ngày trước khi bật lưu có thể trống video.")
        _nrep = f"{_disp} (xem lại)"
        _nrec = len((_rep.get("nhap_kho") or {}).get("recon_rows") or [])
        _h = (1 + max(1, (_nrec + 19) // 20)) * 1140 + 120   # 1 trang 1 + N tờ trang 2 (20 đơn/tờ)
        components.html(daily_report.report_html(_rep, _dvr, _nrep, sign_on=_sign_on), height=_h, scrolling=True)
        st.stop()

    # ---- Hôm nay (trực tiếp) ----
    if st.button("🔄 Tải lại số liệu"):
        st.cache_data.clear()
        st.rerun()
    try:
        _rep = load_daily_report()
    except Exception as e:
        st.error(f"❌ Lỗi tổng hợp báo cáo: `{e}`")
        st.stop()
    _dvr = load_dohana() if dohana.configured() else None
    _inb = load_dohana_inbound() if dohana.configured() else None
    if (isinstance(_dvr, dict) and _dvr.get("_from_store")) or (isinstance(_inb, dict) and _inb.get("_from_store")):
        st.warning("⚠️ Dohana tạm không phản hồi — đang dùng **video đã lưu trong kho** (có thể thiếu clip "
                   "quay trong vài phút gần nhất). Bấm **🔄 Tải lại số liệu** để thử lấy trực tiếp lại.")
    _enrich_daily(_rep, _dvr, _inb)   # gắn clip khui hàng + đối chiếu video đóng gói
    if picklog.configured() and isinstance(_rep.get("funnel"), dict):
        _pl = picklog.read_today()
        _rep["funnel"]["soan"] = sum(r.get("so_don", 0) or 0 for r in _pl) or None
        _rep["funnel"]["soan_sp"] = sum(r.get("so_sp", 0) or 0 for r in _pl) or None
    _now_vn = datetime.now(timezone.utc) + timedelta(hours=7)
    _nrep = _now_vn.strftime("%H:%M %d/%m/%Y")
    _nrec = len((_rep.get("nhap_kho") or {}).get("recon_rows") or [])
    _h = (1 + max(1, (_nrec + 19) // 20)) * 1140 + 120   # 1 trang 1 + N tờ trang 2 (20 đơn/tờ)
    # Còn xót lại LUÔN rút gọn 5 đơn/ĐVVC cho dễ đọc (collapse_xot mặc định True)
    try:
        components.html(daily_report.report_html(_rep, _dvr, _nrep, sign_on=_sign_on),
                        height=_h, scrolling=True)
    except Exception as _e:   # báo cáo A4 lỗi KHÔNG được làm BIẾN MẤT mục đơn trả hàng bên dưới
        import traceback as _tb
        st.error(f"❌ Lỗi dựng báo cáo A4 (mục đơn trả hàng bên dưới vẫn hiển thị): `{_e}`")
        with st.expander("Chi tiết lỗi (gửi Claude để sửa)"):
            st.code(_tb.format_exc())
    st.stop()   # HẾT trang "Báo cáo cuối ngày" — mục đơn trả hàng đã TÁCH sang TRANG RIÊNG (sidebar)


# ═════════════ TRANG RIÊNG: ĐƠN TRẢ HÀNG ĐANG XỬ LÝ (nút chọn trên sidebar) ═════════════
if _page == PAGE_RETURNS:
    st.title("📦 Đơn trả hàng đang xử lý (chưa nhập kho)")
    st.caption("Đơn trả CHƯA nhập kho (năm nay) — chia theo loại trả + tình trạng vận chuyển. "
               "Bấm 📋 để copy mã · dòng tô vàng = cần khiếu nại.")
    if not credential_present():
        st.warning("⚠️ Cần kết nối Sapo (API LIVE).")
        st.stop()
    if st.button("🔄 Tải lại số liệu"):
        st.cache_data.clear()
        st.rerun()
    _return_top_search_slot = st.container()
    _return_top_drill_slot = st.container()

    def _note_has_result(note):
        pre = _ascii_code(str(note or "").split("|")[0])
        compact = "".join(ch for ch in pre if ch.isalnum())
        return any(t in compact for t in ("THANG", "THUA", "HETHAN", "CANKN", "KHONGCANKN", "KHONGCANKHIEUNAI"))

    def _note_has_final_result(note):
        pre = _ascii_code(str(note or "").split("|")[0])
        compact = "".join(ch for ch in pre if ch.isalnum())
        return any(t in compact for t in ("THANG", "THUA", "HETHAN", "KHONGCANKN", "KHONGCANKHIEUNAI"))

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
        pre = _ascii_code(str(note or "").split("|")[0])
        compact = "".join(ch for ch in pre if ch.isalnum())
        return any(t in compact for t in ("THANG", "THUA", "HETHAN", "KHONGCANKN", "KHONGCANKHIEUNAI"))

    _RETURN_NOTE_TEMPLATES = [
        {
            "group": "KHÔNG CẦN KN",
            "label": "Đã nhận hàng hoàn ở Sapo cũ",
            "template": "⚪ KHÔNG CẦN KN | Đã nhận hàng hoàn ở Sapo cũ",
        },
        {
            "group": "KHÔNG CẦN KN",
            "label": "Có ảnh/kho xác nhận đã nhận hoàn",
            "template": "⛔ KHÔNG CẦN KN | 0đ thất thoát | Có ảnh nhận hoàn",
        },
        {
            "group": "KHÔNG CẦN KN",
            "label": "Shop đóng thiếu thật",
            "template": "⛔ KHÔNG CẦN KN | {amount} | Shop đóng thiếu {qty} SP",
        },
        {
            "group": "KHÔNG CẦN KN",
            "label": "Shipper/sàn đã bồi thường",
            "template": "⛔ KHÔNG CẦN KN | Shipper đã bồi thường {comp_amount} | Lỗ chênh {loss_amount}",
        },
        {
            "group": "KHÔNG CẦN KN",
            "label": "Yêu cầu hoàn bị hủy",
            "template": "⚪ KHÔNG CẦN KN | 0đ | Yêu cầu {platform} bị hủy",
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
            "template": "🟢 THẮNG | Thu hồi {amount} | {reason}",
        },
        {
            "group": "THUA",
            "label": "Đã KN nhưng sàn bác",
            "template": "❌ THUA | Mất {amount} | Đã KN nhưng {platform} bác",
        },
        {
            "group": "THUA",
            "label": "KN không thành công",
            "template": "🔴 THUA | {platform} KN không thành công | Mất {amount}",
        },
        {
            "group": "HẾT HẠN",
            "label": "Hoàn tiền khách, không bồi thường",
            "template": "⚫ HẾT HẠN | Mất {amount} | Hoàn tiền khách, không bồi thường",
        },
        {
            "group": "HẾT HẠN",
            "label": "Đã giao hoàn, không bồi thường",
            "template": "⚫ HẾT HẠN | Mất {amount} | Đã giao hoàn, không bồi thường",
        },
        {
            "group": "HẾT HẠN",
            "label": "Quá 30 ngày chưa có kết quả thu hồi",
            "template": "⚫ HẾT HẠN | Mất {amount} | Quá 30 ngày chưa có kết quả thu hồi",
        },
        {
            "group": "TỰ NHẬP",
            "label": "Tự nhập nhưng phải đúng prefix chuẩn",
            "template": "{custom_note}",
        },
    ]
    _RETURN_NOTE_TEMPLATE_LABELS = [x["label"] for x in _RETURN_NOTE_TEMPLATES]
    _RETURN_NOTE_TEMPLATE_BY_LABEL = {x["label"]: x for x in _RETURN_NOTE_TEMPLATES}

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
                "Mã trả": row.get("Mã trả") or "",
                "VĐ đi": row.get("VĐ đi") or "",
                "VĐ trả về": row.get("VĐ trả về") or "",
                "_return_id": row.get("_return_id") or "",
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
                "Tự nhập": "⚪ KHÔNG CẦN KN | Đã nhận hàng hoàn ở Sapo cũ",
                "Ngày": default_date,
                "Ghi chú hiện tại": row.get("Ghi chú hiện tại") or "",
                "Link hồ sơ trả": row.get("Link hồ sơ trả") or "",
                "_requires_shipper": row.get("_requires_shipper", False),
            })
        return out

    def _build_full_note_editor_rows(rows, allow_final=False):
        out = []
        for row in rows:
            if row.get("Kết quả") != "Tìm thấy":
                continue
            if not allow_final and _note_has_final_result(row.get("Ghi chú hiện tại")):
                continue
            out.append({
                "Ghi": True,
                "Ngày tạo": row.get("Ngày tạo") or "",
                "Mã đơn": row.get("Mã đơn") or "",
                "Mã trả": row.get("Mã trả") or "",
                "VĐ đi": row.get("VĐ đi") or "",
                "VĐ trả về": row.get("VĐ trả về") or "",
                "Hồ sơ": row.get("Link hồ sơ trả") or "",
                "Ghi chú hiện tại": row.get("Ghi chú hiện tại") or "",
                "Ghi chú mới": "",
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
                    "VĐ đi": "", "VĐ trả về": "", "_return_id": "", "Link hồ sơ trả": "",
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
        _can_write_sapo = _auth_configured() and CUR_ROLE == "admin"
        st.caption("Dùng khi đã đối chiếu xong bên ngoài app. App sẽ dò phiếu trả theo mã đơn/mã trả hàng/mã vận đơn rồi ghi note vào SAPO qua API.")
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
                                       height=100, key="return_note_codes")
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
            st.caption(" · ".join(_notice))
            if _full_note_mode:
                _full_seed_rows = _build_full_note_editor_rows(_lookup_rows, _allow_final)
                if not _full_seed_rows:
                    _msg = "Không còn phiếu nào cần nhập ghi chú mới: tất cả đã có kết quả cuối hoặc không tìm thấy."
                    if _hidden_final_count and not _allow_final:
                        _msg += " 👉 Tick ô 🔓 ở trên để ghi chú lại các phiếu đã có kết quả."
                    st.info(_msg)
                else:
                    st.caption("Dán nguyên ghi chú chuẩn vào cột `Ghi chú mới`. Mỗi dòng ghi đúng một hồ sơ trả, không gom chung.")
                    _full_editor_df = st.data_editor(
                        pd.DataFrame(_full_seed_rows),
                        use_container_width=True,
                        hide_index=True,
                        height=min(520, 50 * (len(_full_seed_rows) + 1) + 40),
                        key=f"return_note_full_editor_{int(_allow_final)}_{_ascii_code(_codes_key)[:50]}",
                        disabled=["Ngày tạo", "Mã đơn", "Mã trả", "VĐ đi", "VĐ trả về", "Hồ sơ", "Ghi chú hiện tại", "_return_id", "_requires_shipper"],
                        column_config={
                            "Ghi": st.column_config.CheckboxColumn("Ghi", width="small"),
                            "Ngày tạo": st.column_config.TextColumn("Ngày tạo", width="small"),
                            "Mã đơn": st.column_config.TextColumn("Mã đơn", width="small"),
                            "Mã trả": st.column_config.TextColumn("Mã trả", width="small"),
                            "VĐ đi": st.column_config.TextColumn("VĐ đi", width="small"),
                            "VĐ trả về": st.column_config.TextColumn("VĐ trả về", width="small"),
                            "Hồ sơ": st.column_config.LinkColumn("Mở", width="small", display_text="Mở"),
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
                        st.caption(f"Đã sẵn sàng ghi {_ready_count} phiếu. App vẫn kiểm tra prefix chuẩn và tên shipper trước khi cho ghi.")
        if (not _full_note_mode) and _preview_ready:
            st.markdown("**Tự tạo ghi chú đúng mẫu**")
            st.caption("Dùng phần này khi chị muốn tự soạn bằng mẫu có sẵn. Không dùng CẦN KN để ghi SAPO hàng loạt vì đó là trạng thái chưa chốt.")
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
            "custom_note": "⚪ KHÔNG CẦN KN | Đã nhận hàng hoàn ở Sapo cũ",
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
                    value="⚪ KHÔNG CẦN KN | Đã nhận hàng hoàn ở Sapo cũ",
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
            st.caption("Chỉ sửa các cột cần thiết. Ghi chú đầy đủ được ẩn bên dưới trong mục xem trước.")
            _editor_df = st.data_editor(
                pd.DataFrame(_seed_rows),
                use_container_width=True,
                hide_index=True,
                height=min(420, 38 * (len(_seed_rows) + 1) + 40),
                key=f"return_note_individual_editor_{_ascii_code(_codes_key)[:50]}",
                disabled=["Ngày tạo", "Mã đơn", "Mã trả", "VĐ đi", "VĐ trả về", "_return_id", "Ghi chú hiện tại", "Link hồ sơ trả", "_requires_shipper"],
                column_config={
                    "Ghi": st.column_config.CheckboxColumn("Ghi"),
                    "Mẫu ghi chú": st.column_config.SelectboxColumn("Mẫu ghi chú", options=_RETURN_NOTE_TEMPLATE_LABELS),
                    "Sàn": st.column_config.SelectboxColumn("Sàn", options=["TikTok", "Shopee", "Sàn"]),
                    "SL thiếu": st.column_config.NumberColumn("SL thiếu", min_value=1, max_value=99, step=1),
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
                    st.caption("Chưa chọn dòng nào để ghi.")
        if not _note_valid:
            st.error("Ghi chú chưa đúng chuẩn. Dòng đầu phải là THẮNG / THUA / HẾT HẠN / KHÔNG CẦN KN.")
        if not _shipper_valid:
            st.error("Nếu có mã vận đơn hoàn về thì bắt buộc điền tên shipper hoàn. Nếu chưa có tên shipper, đơn vẫn phải để nhóm CẦN KN/theo dõi, chưa chốt kết quả.")
        if _individual_mode and not _individual_valid:
            st.error("Bảng ghi chú riêng từng mã còn dòng thiếu thông tin hoặc sai prefix chuẩn.")
        if _full_note_mode and not _full_note_valid:
            st.error("Bảng agent còn dòng thiếu thông tin hoặc sai prefix chuẩn.")
        st.caption("Khi ghi thật, app sẽ tự chèn ghi chú cũ SAPO của từng phiếu vào dòng kế cuối, ngay trước dòng Cập nhật.")
        st.caption("Tool này chỉ ghi vào ghi chú hồ sơ trả hàng, là nơi bảng KN đang đọc kết quả.")
        _confirm_write = st.checkbox("Tôi xác nhận ghi chú các phiếu tìm thấy vào SAPO", value=False,
                                     key="return_note_confirm_write")
        if st.button("✍️ Ghi chú vào SAPO",
                     disabled=(not _codes or not _preview_ready or not _confirm_write or not _can_write_sapo
                               or (_full_note_mode and (not _full_note_plan or not _full_note_valid))
                               or ((not _full_note_mode) and (not _individual_mode) and (not _note_valid or not _shipper_valid))
                               or ((not _full_note_mode) and _individual_mode and (not _individual_plan or not _individual_valid))),
                     key="return_note_write_btn"):
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
                    if _full_note_mode:
                        _plan = _full_note_plan.get(str(rid))
                        if not _plan:
                            results.append({
                                "Mã đơn": order_name or ", ".join(info["codes"]),
                                "Mã trả": return_name,
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
                                "Mã trả": return_name,
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
                            "Mã trả": return_name,
                            "Link hồ sơ trả": f"https://vitranboutiquehcm.mysapo.net/admin/order_returns/{rid}",
                            "Kết quả": "Đã khớp, không cần cập nhật",
                        })
                        continue
                    if _row_requires_return_shipper(r) and not str(_shipper_for_row or "").strip():
                        results.append({
                            "Mã đơn": order_name or ", ".join(info["codes"]),
                            "Mã trả": return_name,
                            "Link hồ sơ trả": f"https://vitranboutiquehcm.mysapo.net/admin/order_returns/{rid}",
                            "Kết quả": "Bỏ qua: phiếu trả hàng hoàn tiền có VĐ trả về nhưng chưa nhập tên shipper hoàn",
                        })
                        continue
                    new_note, status = _compose_return_note(r.get("note"), _note_to_write, _replace_result)
                    if not new_note:
                        results.append({
                            "Mã đơn": order_name or ", ".join(info["codes"]),
                            "Mã trả": return_name,
                            "Link hồ sơ trả": f"https://vitranboutiquehcm.mysapo.net/admin/order_returns/{rid}",
                            "Kết quả": status,
                        })
                        continue
                    try:
                        update_order_return_note(session, rid, new_note)
                        results.append({
                            "Mã đơn": order_name or ", ".join(info["codes"]),
                            "Mã trả": return_name,
                            "Link hồ sơ trả": f"https://vitranboutiquehcm.mysapo.net/admin/order_returns/{rid}",
                            "Kết quả": "Đã ghi và xác nhận",
                        })
                    except Exception as e:
                        results.append({
                            "Mã đơn": order_name or ", ".join(info["codes"]),
                            "Mã trả": return_name,
                            "Link hồ sơ trả": f"https://vitranboutiquehcm.mysapo.net/admin/order_returns/{rid}",
                            "Kết quả": f"Lỗi ghi hồ sơ trả: {e}",
                        })
                missing = [c for c in _codes if not matches.get(c)]
                for code in missing:
                    results.append({"Mã đơn": code, "Mã trả": "", "Link hồ sơ trả": "", "Kết quả": "Không tìm thấy"})
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
                "Kết quả": x.get("Kết quả", ""),
                "Hồ sơ": x.get("Link hồ sơ trả", "") or x.get("Hồ sơ", ""),
            } for x in _res])
            st.dataframe(_write_df,
                         use_container_width=True, hide_index=True,
                         column_config={
                             "": st.column_config.TextColumn("", width="small"),
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
            pre = _ascii_code(str(d.get("note") or "").split("|")[0])
            return bool(d.get("khong_can_kn_note")) or "KHONGCANKN" in pre or "KHONGCANKHIEUNAI" in pre

        _khong_can_kn_list = [d for d in _rip["detail"] if _note_is_khong_can_kn(d)]
        _ckn_list = [d for d in _rip["detail"] if d.get("need_kn")]
        _no_return_list = [d for d in _rip["detail"] if d.get("ship_code") == "no_return"]
        _khong_can_kn_money = sum(int(d.get("khong_can_kn_money")
                                      if d.get("khong_can_kn_money") is not None
                                      else d.get("money") or 0)
                                  for d in _khong_can_kn_list)
        _oc = dict(_oc)
        _oc["khong_kn"] = {"n": len(_khong_can_kn_list), "money": _khong_can_kn_money}
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

            def _return_outcome(d):
                if _stock_group(d) == "Đã nhập kho":
                    return "Đã nhập kho"
                compact = _note_compact(d)
                if "THANG" in compact:
                    return "Thắng"
                if "THUA" in compact:
                    return "Thua"
                if "HETHAN" in compact:
                    return "Hết hạn"
                if "KHONGCANKN" in compact or "KHONGCANKHIEUNAI" in compact:
                    return "Không cần KN"
                if "DANGKN" in compact or "DANGKHANGNGHI" in compact or "DANGXULY" in compact:
                    return "Đang KN"
                if d.get("need_kn"):
                    return "Cần KN"
                return "Chưa chốt"

            _all_returns_detail = _rip.get("all_detail") or _rip.get("detail") or []
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
                st.caption("🚚 Tổng theo ĐVVC")
                _dvr = _ls.get("by_dvvc") or []
                st.dataframe(pd.DataFrame([{"ĐVVC": r["dvvc"], "Đơn": r["n"],
                    "Thua/Hết": f"{r['thua']}/{r['het']}", "Tiền mất": _fm(r["money"])}
                    for r in _dvr]), hide_index=True, width="stretch")
                st.caption("🧍 Từng shipper & các đơn làm mất (gộp nhóm theo shipper; trong nhóm: mới → cũ)")
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
                        _rc = o.get("return_code") or ""
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
                st.caption("📋 Bấm nút **📋** để copy mã trả / mã VĐ · STT đếm theo TỪNG shipper · màu = ĐVVC · vạch = đổi shipper. "
                           "⚠️ Shopee/SPX không ghi tên shipper → cột Shipper hiện ĐVVC; mã VĐ lấy từ 'VĐ về' trong ghi chú "
                           "nếu field trống; vài đơn Shopee sàn ẩn → '—'.")
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
            st.caption("🟡 **Dòng tô vàng = đơn CẦN KN** (hơn 5 ngày & CHƯA có ghi chú kết quả).  "
                    "VĐ đi = mã vận đơn giao đi · VĐ trả về = mã vận đơn hoàn về "
                    "(giao thất bại: 2 mã trùng nhau; chỉ hoàn tiền: không có kiện hàng hoàn về)."
                    + ("  ·  ⚠️ đã chạm giới hạn quét — có thể còn đơn cũ hơn" if _rip.get("capped") else ""))

            def _jss(s):       # escape chuỗi cho onclick JS
                return str(s or "").replace("\\", "\\\\").replace("'", "\\'")

            def _cp(val):      # nút copy 📋 (bấm 1 phát copy mã)
                return (f"<span class='cp' onclick=\"cp('{_jss(val)}',this)\" title='Copy mã'>📋</span>"
                        if val else "")

            def _code_cell(val, link=None):    # mã + nút copy (kèm link nếu có)
                v = _esc(str(val or ""))
                disp = f"<a href='{_esc(link)}' target='_blank'>{v}</a>" if link else v
                return f"{disp} {_cp(val)}" if val else ""

            def _search_norm(s):
                return "".join(ch for ch in _ascii_code(s) if ch.isalnum())

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
                if str(d.get("stock_code") or "").lower() in ("stocked", "restocked"):
                    return "Đã nhận/đã nhập kho"
                if d.get("need_kn"):
                    return "Cần KN"
                if _note_is_khong_can_kn(d):
                    return "Không cần KN"
                if d.get("ship_code") == "no_return":
                    return "Không có hàng hoàn về / chỉ hoàn tiền"
                if d.get("loai_tra_code") == "return_and_refund":
                    return "Trả hàng hoàn tiền"
                if d.get("loai_tra_code") == "delivery_failed":
                    return "Giao hàng thất bại"
                return "Khác"

            def _sub_table(items, h, show_type=False, show_reason=False, merge_delivery_vd=False, show_location=False):
                if not items:
                    st.caption("— Không có —")
                    return
                def _safe(v, default=""):
                    return _esc(str(v if v not in (None, "") else default))
                def _doisoat(d):   # 1 LINK đối soát TikTok/Shopee, tự chọn tab: note CÓ kết quả KN
                    oc = d.get("order_code") or ""              # (🟢✅🔴❌⛔⚪⚫) → "Đã thanh toán"; còn lại → "Chưa thanh toán"
                    _lk = (d.get("order_link") or "").lower()
                    if oc and "tiktok" in _lk:                  # channel_type/connection_ids account-specific
                        app, conn, ch = "tiktok-channel", "11589%2C12966%2C19313", "6"
                    elif oc and "shopee" in _lk:
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
                cols = ["STT"]
                if show_location:
                    cols += ["Vị trí"]
                cols += ["Ngày tạo", "Mã đơn", "Mã trả hàng"]
                cols += ["Vận đơn"] if merge_delivery_vd else ["VĐ đi", "VĐ trả về"]
                cols += ["Shipper hoàn", "Gian hàng"]
                if show_type:
                    cols += ["Loại trả"]
                cols += ["SKU", "SL", "Tổng tiền", "Nhập kho"]
                if show_reason:
                    cols += ["Lý do vào KN"]
                cols += ["Đối soát", "Ghi chú"]
                _sticky_n = cols.index("Mã trả hàng") + 1   # cố định các cột đầu → hết "Mã trả hàng"
                thead = "".join(f"<th>{c}</th>" for c in cols)
                body = ""
                for i, d in enumerate(items, 1):
                    bg = "background:#fff3cd" if d.get("need_kn") else ""
                    note = d.get("note") or ""
                    tds = [f"<td class='r'>{i}</td>"]
                    if show_location:
                        tds.append(f"<td>{_safe(d.get('_location') or _row_location(d))}</td>")
                    tds += [
                        f"<td>{_safe(d.get('created'))}</td>",
                        f"<td>{_code_cell(d['order_code'], d.get('order_link'))}</td>",
                        f"<td>{_code_cell(d.get('return_code'))}</td>",
                    ]   # KHÔNG link, chỉ copy
                    if merge_delivery_vd:
                        tds.append(f"<td>{_code_cell(d.get('vd_di') or d.get('vd_tra'))}</td>")
                    else:
                        tds.append(f"<td>{_code_cell(d['vd_di'])}</td>")
                        tds.append(f"<td>{_code_cell(d['vd_tra'])}</td>")
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
                    if show_reason:
                        tds.append(f"<td>{_safe(d.get('reason'))}</td>")
                    tds.append(f"<td>{_doisoat(d)}</td>")
                    tds.append(f"<td class='note' title='{_safe(note)}'>{_safe(note)}</td>")
                    body += f"<tr style='{bg}'>" + "".join(tds) + "</tr>"
                html = f"""<style>
 body{{margin:0;font-family:Tahoma,Arial,sans-serif;color:#1f2937}}
 table{{border-collapse:collapse;font-size:12.5px;width:max-content;min-width:100%}}
 th,td{{border:1px solid #e2e6ec;padding:4px 8px;text-align:left;white-space:nowrap}}
 th{{background:#eef1f6;position:sticky;top:0;z-index:4;font-weight:700}}
 td.r{{text-align:right}}
 td.note{{max-width:220px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;cursor:help}}
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
                    _sub_table(hoan, 260, merge_delivery_vd=(code == "delivery_failed"))
                if giao:
                    st.markdown(f"**📥 Đã giao người bán — {len(giao)} đơn**")
                    _sub_table(giao, 260, merge_delivery_vd=(code == "delivery_failed"))
                if khong_hoan:
                    st.markdown(f"**🚫 Không có hàng hoàn về — {len(khong_hoan)} đơn**")
                    _sub_table(khong_hoan, 260)

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
                    for _d in (_rip.get("all_detail") or _rip["detail"]):
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
                            ["Tất cả", "Thắng", "Thua", "Hết hạn", "Không cần KN", "Cần KN", "Đang KN", "Chưa chốt", "Đã nhập kho"],
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
                                "Mã trả": _d.get("return_code") or "",
                                "Loại trả": _d.get("loai_tra") or "",
                                "VĐ đi": _d.get("vd_di") or "",
                                "VĐ trả về": _d.get("vd_tra") or "",
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
                            st.dataframe(pd.DataFrame(_drill_rows), use_container_width=True, hide_index=True)
                        else:
                            st.caption(f"Không có đơn phù hợp: {_filter_desc}.")

            # ── VIDEO DOHANA (metadata tích luỹ ở Gist → LƯU CẢ NĂM; khui hàng có tag=cần KN, đóng hàng có tag=không) ──
            try:
                _dvids = load_dohana_videos()
            except Exception:
                _dvids = []
            _dtag_kn = [r for r in _dvids if r.get("tag_id") and r.get("type") == "inbound"]     # khui hàng có tag → CẦN KN
            _dtag_nokn = [r for r in _dvids if r.get("tag_id") and r.get("type") == "package"]   # đóng hàng có tag → KHÔNG cần KN

            def _dohana_tag_tbl(items):
                if not items:
                    st.caption("— (Dohana) chưa ghi nhận đơn gắn tag —")
                    return
                st.dataframe(pd.DataFrame([{
                    "Mã đơn": r.get("code"),
                    "Tag": dohana._tag_name(r.get("tag_id")),
                    "Ngày quay": r.get("date") or "",
                    "Giờ": r.get("time") or "",
                    "Thời lượng(s)": r.get("dur"),
                    "Ghi nhận": r.get("first_seen") or "",
                } for r in sorted(items, key=lambda x: (x.get("date") or "", x.get("time") or ""), reverse=True)]),
                    width="stretch", hide_index=True)

            # ── DANH SÁCH ĐƠN CẦN KN (bấm ô "Cần KN" ở trên sẽ nhảy tới đây) ──
            st.subheader("🚨 Đơn cần KN — lấy làm khiếu nại", anchor="don-can-kn")
            st.caption("Gồm các đơn CHƯA có ghi chú kết quả chuẩn (THẮNG/THUA/KHÔNG CẦN KN/HẾT HẠN): "
                       "đã giao người bán chưa nhập kho, đang hoàn hơn 5 ngày, hoặc chỉ hoàn tiền/không có hàng hoàn về. "
                       "Đây chính là các dòng tô vàng — NV lấy làm khiếu nại.")
            _sub_table(_ckn_list, 360, show_reason=True)
            st.markdown(f"**🏷️ + Đơn Dohana gắn tag KHUI HÀNG (tráo · đã dùng · trả thiếu · hư hỏng) — {len(_dtag_kn)} đơn**")
            _dohana_tag_tbl(_dtag_kn)
            st.subheader("⛔ Đơn không cần KN — đã có kết luận", anchor="don-khong-can-kn")
            st.caption("Các đơn trong bảng detail đã có ghi chú KHÔNG CẦN KN: đã nhận hàng, đã nhận/được đền tiền, hoặc shop đóng thiếu thật. Nhóm này không trộn vào danh sách CẦN KN.")
            _sub_table(_khong_can_kn_list, 300)
            st.markdown(f"**🏷️ + Đơn Dohana gắn tag ĐÓNG HÀNG (đóng thiếu SP) — {len(_dtag_nokn)} đơn**")
            _dohana_tag_tbl(_dtag_nokn)
            st.divider()
            st.markdown("### 📋 Chi tiết còn hàng hoàn về theo loại")
            _type_block("💸 Trả hàng hoàn tiền", "return_and_refund")
            _type_block("📕 Giao hàng thất bại", "delivery_failed")
            _type_block("🚫 Chỉ hoàn tiền / không có hàng hoàn về", "refund")
            _other = [d for d in _rip["detail"]
                      if d["loai_tra_code"] not in ("return_and_refund", "delivery_failed", "refund")
                      and d["ship_code"] != "no_return"]
            if _other:
                st.markdown(f"### Khác — {len(_other)} đơn")
                _sub_table(_other, 200)

        with _tabs[2]:
            # ── 🎥 KHO VIDEO DOHANA (lưu CẢ NĂM, vượt hạn 30 ngày của Dohana) — tra cứu metadata ──
            st.divider()
            st.subheader("🎥 Kho video Dohana (lưu cả năm)")
            st.caption(f"Đã lưu **{len(_dvids)}** video (đóng hàng + khui hàng): trạng thái · ngày quay · giờ · "
                       "thời lượng · tag. Dohana chỉ giữ 30 ngày — kho này gom dần (13/16/19h) nên đọc được đến cuối năm.")
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
                        "Tag": dohana._tag_name(r.get("tag_id")) if r.get("tag_id") else "",
                    } for r in _hits]), width="stretch", hide_index=True)
                else:
                    st.caption("Không thấy trong kho (có thể chưa tới mốc lấy 13/16/19h, hoặc video ngoài phạm vi đã gom).")
    st.stop()


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
