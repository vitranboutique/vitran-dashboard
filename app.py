"""
app.py — Dashboard "Báo cáo sáng" VITRAN BOUTIQUE HCM (Sapo → Streamlit + Plotly).

Chạy:  streamlit run app.py
DEMO:  tự bật khi chưa cấu hình credential (xem README để chuyển sang LIVE).
"""
import os
import unicodedata
from datetime import datetime, timedelta, timezone
from html import escape as _esc

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
from sapo_client import SapoAuthError, build_session, credential_present, make_fetch_json
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
      @media (max-width: 640px) { .alert-pop { width: 190px; right: 8px; bottom: 72px; } }
      @media print { .alert-pop { display: none !important; } }
    </style>
    """,
    unsafe_allow_html=True,
)


def _week_table_html(wk):
    """Bảng tổng hợp 7 ngày qua (đóng gói/hủy/soạn/shipper/giao khách), tô dòng hôm nay."""
    cols = [("ngay", "Ngày"), ("thu", "Thứ"), ("dong_goi", "Đóng gói"), ("huy", "Hủy"),
            ("soan", "Soạn"), ("shipper_nhan", "Shipper nhận"), ("giao_khach", "Giao khách")]
    _bd = "border:1px solid #aab2c2;"
    head = "".join(
        f'<th style="text-align:{"left" if k in ("ngay", "thu") else "right"};'
        f'padding:6px 10px;{_bd}background:#dfe4ec;color:#16233f">{lbl}</th>'
        for k, lbl in cols)
    body = ""
    for r in wk:
        hot = r.get("is_today")
        bg = "background:#fff7ed;" if hot else ""
        cells = ""
        for k, _ in cols:
            al = "left" if k in ("ngay", "thu") else "right"
            tag = (' <span style="color:#E24B4A;font-size:11px">• đang chạy</span>'
                   if hot and k == "ngay" else "")
            wt = "font-weight:700;" if hot else ""
            cells += (f'<td style="text-align:{al};padding:5px 10px;{wt}{_bd}">'
                      f'{r.get(k, "")}{tag}</td>')
        body += f'<tr style="{bg}">{cells}</tr>'
    keys = ("dong_goi", "huy", "soan", "shipper_nhan", "giao_khach")
    tot = {k: sum(r.get(k, 0) for r in wk) for k in keys}
    totc = (f'<td colspan="2" style="text-align:left;padding:6px 10px;{_bd}">TỔNG 7 ngày</td>'
            + "".join(f'<td style="text-align:right;padding:6px 10px;{_bd}">{tot[k]}</td>'
                      for k in keys))
    return (f'<table style="width:100%;border-collapse:collapse;font-size:13px">'
            f'<thead><tr>{head}</tr></thead><tbody>{body}'
            f'<tr style="font-weight:800;background:#eef1f6;color:#16233f">{totc}</tr>'
            f'</tbody></table>')


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
        # BẢNG ĐỐI CHIẾU: mỗi dòng = 1 sự kiện hoàn. Đơn ĐÃ nhập kho (có Sapo) + clip DƯ (chưa nhập kho).
        recon = []
        for d in nk.get("detail", []):
            recon.append({
                "clip_code": d.get("clip_code"), "clip_time": d.get("clip_time"),
                "clip_dur": d.get("clip_dur"), "clip_tag": d.get("clip_tag"),
                "clip_alt": d.get("clip_altcode"), "has_clip": bool(d.get("clip")),
                "order_code": d.get("order_code"), "recv_time": d.get("recv_time"),
                "vd_gui": d.get("tracking"),   # mã VĐ GIAO ĐI (tra Sapo/sàn được)
                # Cột "Đã nhận hàng trả (Sapo)" → CHỈ lấy NV nhận hàng từ Sapo,
                # KHÔNG fallback sang NV quay clip (Dohana) để tránh hiển thị sai người.
                "nhan_vien": d.get("nhan_vien") or "",
                "sku": d.get("sku"), "loai_tra": d.get("loai_tra"),
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
    else:
        nk["clip_available"] = False
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


CUR_NAME, CUR_USER, CUR_ROLE = require_login()


# ───────────────────────── Chọn trang ─────────────────────────
PAGE_OVERVIEW = "📊 Tổng quan điều hành"
PAGE_REPORT = "📋 Báo cáo sáng"
PAGE_PICK = "🧾 Phiếu nhặt hàng"
PAGE_DAILY = "📄 Báo cáo cuối ngày"
_page = st.sidebar.radio("Trang", [PAGE_OVERVIEW, PAGE_REPORT, PAGE_PICK, PAGE_DAILY], index=0)
st.sidebar.divider()


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


@st.cache_data(ttl=300, show_spinner=False)
def load_dohana():
    return dohana.today_package_videos()


@st.cache_data(ttl=300, show_spinner=False)
def load_dohana_inbound():
    return dohana.inbound_videos()


@st.cache_data(ttl=600, show_spinner=False)
def load_dohana_date(date_iso):
    from datetime import date as _date
    return dohana.today_package_videos(target_date=_date.fromisoformat(date_iso))


@st.cache_data(ttl=600, show_spinner=False)
def load_dohana_inbound_date(date_iso):
    from datetime import date as _date
    return dohana.inbound_videos(target_date=_date.fromisoformat(date_iso))


@st.cache_data(ttl=180, show_spinner="Đang tổng hợp báo cáo cuối ngày…")
def load_daily_report(date_iso=None):
    from datetime import date as _date
    td = _date.fromisoformat(date_iso) if date_iso else None
    return L.get_daily_report(make_fetch_json(build_session()), target_date=td)


@st.cache_data(ttl=600, show_spinner="Đang tổng hợp 7 ngày qua…")
def load_week_summary():
    return L.get_week_summary(make_fetch_json(build_session()), days=7)


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


# ════════════════ TRANG BÁO CÁO CUỐI NGÀY (A4) ════════════════
if _page == PAGE_DAILY:
    st.title("📄 Báo cáo vận hành cuối ngày")
    st.caption("Tổng hợp tự động từ Sapo + Dohana — bấm **In báo cáo A4** trong khung để in/lưu PDF.")
    if not credential_present():
        st.warning("⚠️ Cần kết nối Sapo (API LIVE).")
        st.stop()

    # ===== Tổng hợp 7 NGÀY QUA (số cố định sau ngày — query lại là ra số cuối) =====
    # Ẩn mặc định — bấm mới mở (đỡ rối, chỉ xem khi cần).
    with st.expander("📅 Tổng hợp 7 ngày qua", expanded=False):
        try:
            _wk = load_week_summary()
            st.markdown(_week_table_html(_wk), unsafe_allow_html=True)
        except Exception as e:
            st.warning(f"Chưa lấy được tổng hợp tuần: `{e}`")

    # ===== Chọn ngày xem báo cáo A4 chi tiết =====
    _vn_today = (datetime.now(timezone.utc) + timedelta(hours=7)).date()
    _LIVE = f"📅 Hôm nay ({_vn_today.strftime('%d/%m')})"
    _past = {(_vn_today - timedelta(days=i)).strftime("%d/%m/%Y"):
             (_vn_today - timedelta(days=i)).isoformat() for i in range(1, 7)}
    _pick = st.selectbox("Xem báo cáo chi tiết (A4) ngày", [_LIVE] + [f"🗂️ {k}" for k in _past])
    _sign_on = "1"   # phần ký tên LUÔN đặt ở Trang 1 (mặt trước)

    # ---- Xem báo cáo NGÀY CŨ (query lại Sapo + Dohana theo ngày, số đã cố định) ----
    if _pick != _LIVE:
        _iso = _past[_pick[3:]]
        try:
            _rep = load_daily_report(_iso)
        except Exception as e:
            st.error(f"❌ Lỗi tổng hợp báo cáo ngày {_pick[3:]}: `{e}`")
            st.stop()
        _dvr = load_dohana_date(_iso) if dohana.configured() else None
        _inb = load_dohana_inbound_date(_iso) if dohana.configured() else None
        _enrich_daily(_rep, _dvr, _inb)
        if picklog.configured() and isinstance(_rep.get("funnel"), dict):
            _pl = picklog.read_date(_iso)
            _rep["funnel"]["soan"] = sum(r.get("so_don", 0) or 0 for r in _pl) or None
            _rep["funnel"]["soan_sp"] = sum(r.get("so_sp", 0) or 0 for r in _pl) or None
        st.info(f"🗂️ Báo cáo ngày **{_pick[3:]}** — query lại từ Sapo + Dohana (số đã cố định). "
                "Video chỉ còn cho ~vài ngày gần nhất; ngày quá cũ mục video có thể trống.")
        _nrep = f"{_pick[3:]} (xem lại)"
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
    components.html(daily_report.report_html(_rep, _dvr, _nrep, sign_on=_sign_on),
                    height=_h, scrolling=True)
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
