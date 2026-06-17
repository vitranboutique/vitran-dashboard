"""
app.py — Dashboard "Báo cáo sáng" VITRAN BOUTIQUE HCM (Sapo → Streamlit + Plotly).

Chạy:  streamlit run app.py
DEMO:  tự bật khi chưa cấu hình credential (xem README để chuyển sang LIVE).
"""
import os
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
from sapo_client import SapoAuthError, build_session, credential_present, make_fetch_json
from picking_render import history_slips_html, picking_html

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
    </style>
    """,
    unsafe_allow_html=True,
)


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
**Bật lưu lịch sử in phiếu (Google Sheet) — chỉ làm 1 lần (~5 phút):**

1. Tạo 1 **Google Sheet** mới (vd: *VITRAN – Lịch sử in phiếu*).
2. Trong Sheet mở **Tiện ích mở rộng → Apps Script**.
3. Xoá hết code mẫu, dán đoạn dưới rồi bấm **Lưu** 💾:

```javascript
function doPost(e){
  var ss=SpreadsheetApp.getActiveSpreadsheet();
  var sh=ss.getSheetByName('Log')||ss.insertSheet('Log');
  var d=JSON.parse(e.postData.contents).data||{};
  sh.appendRow([new Date(),d.ngay||'',d.gio||'',d.so_don||0,d.so_sp||0,d.so_sku||0,d.ht_don||0,d.th_don||0]);
  return ContentService.createTextOutput(JSON.stringify({ok:true})).setMimeType(ContentService.MimeType.JSON);
}
function doGet(e){
  var sh=SpreadsheetApp.getActiveSpreadsheet().getSheetByName('Log');var rows=[],dt=e.parameter.date;
  if(sh){var v=sh.getDataRange().getValues();
    for(var i=0;i<v.length;i++){
      var ds=(v[i][0] instanceof Date)?Utilities.formatDate(v[i][0],'Asia/Ho_Chi_Minh','yyyy-MM-dd'):String(v[i][1]);
      if(ds===dt){rows.push({gio:v[i][2],so_don:v[i][3],so_sp:v[i][4],so_sku:v[i][5],ht_don:v[i][6],th_don:v[i][7]});}}}
  return ContentService.createTextOutput(JSON.stringify({rows:rows})).setMimeType(ContentService.MimeType.JSON);
}
```

4. **Triển khai → Bản triển khai mới**: Loại = **Ứng dụng web**, Thực thi với tư cách = **Tôi**, Người truy cập = **Bất kỳ ai** → **Triển khai** và cấp quyền.
5. Copy **URL ứng dụng web** (`https://script.google.com/macros/s/…/exec`).
6. **Gửi URL đó cho mình** để dán vào cấu hình (hoặc tự thêm vào Streamlit *Settings → Secrets*):
   `[picklog]` rồi dòng `url = "…"`.
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
_page = st.sidebar.radio("Trang", [PAGE_OVERVIEW, PAGE_REPORT, PAGE_PICK], index=0)
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


@st.cache_data(ttl=900, show_spinner="Đang quét đơn trả cả năm…")
def load_returns_followup():
    return L.get_returns_followup(make_fetch_json(build_session()))


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
    _a[0].metric("📦 Đơn đặt hôm nay", f"{ov['don_today']:,}", f"Tổng SP: {ov['sp_today']:,}", delta_color="off")
    _a[1].metric("📦 Đơn đặt hôm qua", f"{ov['don_yest']:,}", f"Tổng SP: {ov['sp_yest']:,}", delta_color="off")
    _a[2].metric("🗓️ Tổng đơn 7 ngày", f"{ov['don_week']:,}", f"Tổng SP: {ov['sp_week']:,}", delta_color="off")
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

    # ═══════════ ĐƠN CẦN GIAO SHIPPER (hôm nay) ═══════════
    dl = ov["delivery"]
    st.markdown('<div class="sec sec-orange">Đơn cần giao shipper hôm nay'
                '<span class="ic" title="Phễu xử lý giao hàng TRONG NGÀY HÔM NAY: xử lý (tạo vận đơn) → đóng gói → xuất cho ĐVVC, kèm số đơn đang chờ shipper tới lấy. Mốc xác nhận = NGÀY XỬ LÝ trên Sapo. Giờ VN.">&#9432;</span></div>',
                unsafe_allow_html=True)
    # Hàng 1 — hoạt động trong ngày
    _d = st.columns(3)
    _d[0].metric("📋 Đã xác nhận", f"{dl['da_xac_nhan']:,}",
                 help="Số đơn được XỬ LÝ (tạo vận đơn) trong hôm nay — đúng cột 'Ngày xử lý' trên Sapo.")
    _d[1].metric("✅ Đã đóng hàng", f"{dl['da_dong']:,}",
                 help="Số đơn ĐÓNG GÓI XONG trong hôm nay — gồm cả đơn sót (xử lý hôm trước, nay mới đóng).")
    _d[2].metric("🚚 Shipper đã nhận", f"{dl['shipper_nhan']:,}",
                 help="Số đơn ĐÃ XUẤT/giao cho ĐVVC (shipper) trong hôm nay (theo issued_on).")
    # Hàng 2 — đang chờ shipper tới lấy (snapshot hiện tại)
    st.markdown("**🟠 Đang chờ shipper tới lấy** "
                "<span class='ic' title='Đơn đã có vận đơn nhưng shipper CHƯA LẤY (shipment_status=pending). Con số này thay đổi LIÊN TỤC trong ngày khi shipper lấy hàng dần.'>&#9432;</span>",
                unsafe_allow_html=True)
    _e = st.columns(4)
    _e[0].metric("⏳ Đang chờ giao", f"{dl['cho_giao']:,}",
                 help="Tổng đơn đang chờ shipper tới lấy ngay lúc này.")
    _e[1].metric("🆕 Mới hôm nay", f"{dl['cho_moi']:,}",
                 help="Trong nhóm chờ giao: đơn có NGÀY XỬ LÝ = hôm nay.")
    _e[2].metric("📌 Sót", f"{dl['cho_sot']:,}",
                 help="Trong nhóm chờ giao: đơn NGÀY XỬ LÝ HÔM TRƯỚC, đã in, hôm nay mới nhặt/đóng — shipper chưa lấy.")
    _e[3].metric("🔴 Hỏa tốc chờ", f"{dl['hoa_toc_cho']:,}",
                 help="Trong nhóm chờ giao: đơn HỎA TỐC cần ưu tiên đẩy trước.")
    st.caption(f"Trong nhóm chờ giao: đã đóng **{dl['cho_packed']}** · chưa đóng **{dl['cho_chua_dong']}**.")
    if dl.get("sot_list"):
        _by = {}
        for _r in dl["sot_list"]:
            _by[_r["ĐVVC"]] = _by.get(_r["ĐVVC"], 0) + 1
        _bytxt = " · ".join(f"{k}: {v}" for k, v in sorted(_by.items(), key=lambda x: -x[1]))
        with st.expander(f"📌 Xem {dl['cho_sot']} đơn SÓT theo ĐVVC — {_bytxt}"):
            render_compact_table(pd.DataFrame(dl["sot_list"]))
            st.caption("Mã vận đơn + ĐVVC để đối chiếu Sapo. Số 'sót' đổi theo thời điểm xem "
                       "(mỗi lượt đóng hàng / shipper lấy đều thay đổi).")
    st.markdown("**Phân bổ đơn chờ giao theo đơn vị vận chuyển**")
    if ov["dvvc"]:
        render_compact_table(pd.DataFrame(ov["dvvc"]).rename(columns={
            "dvvc": "ĐVVC", "total": "Tổng", "thuong": "Thường", "hoatoc": "Hỏa tốc",
            "packed": "Đã đóng", "chua_dong": "Chưa đóng"}))

    # ═══════════ CẢNH BÁO + ĐƠN HỦY ═══════════
    _w1, _w2 = st.columns(2)
    with _w1:
        st.markdown('<div class="sec sec-red">⚠️ Cảnh báo quan trọng</div>', unsafe_allow_html=True)
        al = ov["alerts"]
        st.error(
            f"🕒 Xác nhận sau 18h hôm nay: **{al['conf_after18']}**\n\n"
            f"📌 Đặt trước 18h, xác nhận sau 18h: **{al['late_confirm']}**\n\n"
            f"📦 Đang chờ shipper tới lấy: **{dl['cho_giao']}**\n\n"
            f"🔴 Hỏa tốc chưa giao: **{al['express_pending']}**"
        )
    with _w2:
        st.markdown('<div class="sec sec-red">Đơn hủy sau đẩy VC</div>', unsafe_allow_html=True)
        cn = ov["cancel"]
        _cc = st.columns(3)
        _cc[0].metric("Hôm nay", cn["today"])
        _cc[1].metric("Hôm qua", cn["yest"])
        _cc[2].metric("7 ngày", cn["total7d"])
        st.metric("💸 Giá trị hàng rủi ro (ước tính)", f"{int(cn['risk_value']):,} đ")
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

    # ── LỊCH SỬ IN PHIẾU hôm nay (qua dashboard) — từ Google Sheet ──
    st.markdown("#### 📋 Lịch sử in phiếu nhặt hôm nay (qua dashboard)")
    if not picklog.configured():
        st.info("Chưa bật lưu lịch sử in. Mở hướng dẫn bên dưới để bật (1 lần).")
        with st.expander("⚙️ Cách bật lưu lịch sử in phiếu (~5 phút)"):
            st.markdown(_PICKLOG_SETUP)
    else:
        _logrows = picklog.read_today()
        if _logrows:
            _ldf = pd.DataFrame([{"Lượt": i + 1, "Giờ": r.get("gio", ""),
                                  "Số đơn": r.get("so_don", 0), "Số SP": r.get("so_sp", 0),
                                  "Số SKU": r.get("so_sku", 0), "Hỏa tốc": r.get("ht_don", 0),
                                  "Thường": r.get("th_don", 0)} for i, r in enumerate(_logrows)])
            st.markdown(f"**{len(_logrows)} lượt in** · {int(_ldf['Số đơn'].sum())} đơn · "
                        f"{int(_ldf['Số SP'].sum())} SP")
            render_compact_table(_ldf)
        else:
            st.caption("Chưa lưu lượt in nào hôm nay. Bấm **🖨️ In K80** ở phiếu bên dưới, "
                       "rồi bấm **💾 Lưu đợt vừa in**.")

    # ── Đối chiếu: TẤT CẢ đơn đóng gói trên Sapo (tham khảo) ──
    hist = pdata.get("history", {})
    if hist.get("batches"):
        with st.expander(f"📦 Đối chiếu: tất cả đơn ĐÓNG GÓI trên Sapo hôm nay "
                         f"({hist['so_dot']} lượt · {hist['tong_don']} đơn · {hist['tong_sp']} SP)"):
            render_compact_table(pd.DataFrame(
                [{"Lượt": b["dot"], "Giờ": b["gio"], "Số đơn": b["don"], "Số SP": b["sp"],
                  "Số SKU": b["sku_count"], "Hỏa tốc": b["hoatoc"], "Đã xuất kho": b["xuat"]}
                 for b in hist["batches"]]))
            st.caption("Gồm cả lượt bấm đóng gói HÀNG LOẠT thẳng trên Sapo (vd ca sáng) — thường "
                       "nhiều hơn số phiếu in ở dashboard. Dùng để đối chiếu, không phải số phiếu bạn in.")
            components.html(history_slips_html(hist["batches"], now_str), height=460, scrolling=True)

    # ── Đối chiếu SP soạn hàng vs xuất kho hôm nay (theo SKU) ──
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

    components.html(picking_html(pdata, now_str), height=820, scrolling=True)

    # ── Lưu đợt vừa in vào lịch sử (Google Sheet) ──
    if pdata["total"] > 0:
        st.caption("➡️ Sau khi bấm **🖨️ In K80** ở trên, bấm nút này để ghi vào *Lịch sử in phiếu*:")
        if st.button("💾 Lưu đợt vừa in", type="primary", disabled=not picklog.configured()):
            _now_vn = datetime.now(timezone.utc) + timedelta(hours=7)
            _allsku = {s for s, _ in exp["skus"]} | {s for s, _ in nor["skus"]}
            ok, msg = picklog.log_batch({
                "ngay": _now_vn.strftime("%Y-%m-%d"), "gio": _now_vn.strftime("%H:%M"),
                "so_don": exp["total_orders"] + nor["total_orders"],
                "so_sp": exp["total_qty"] + nor["total_qty"], "so_sku": len(_allsku),
                "ht_don": exp["total_orders"], "th_don": nor["total_orders"],
            })
            (st.success(msg + " Bấm '🔄 Tải lại' để thấy trong lịch sử.") if ok else st.error(msg))
        if not picklog.configured():
            st.caption("⚠️ Nút lưu cần bật Google Sheet (xem hướng dẫn ở mục *Lịch sử in phiếu* phía trên).")

    with st.expander("📄 Hoặc: tạo phiếu từ file Excel (upload thủ công)"):
        _html_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "picking_slip.html")
        with open(_html_path, encoding="utf-8") as _f:
            components.html(_f.read(), height=1300, scrolling=True)
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
