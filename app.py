"""
app.py — Dashboard "Báo cáo sáng" VITRAN BOUTIQUE HCM (Sapo → Streamlit + Plotly).

Chạy:  streamlit run app.py
DEMO:  tự bật khi chưa cấu hình credential (xem README để chuyển sang LIVE).
"""
from datetime import datetime, timedelta, timezone

import pandas as pd
import plotly.graph_objects as go
import requests
import streamlit as st
import streamlit.components.v1 as components
import streamlit_authenticator as stauth

import sapo_logic as L
from sapo_client import SapoAuthError, build_session, credential_present, make_fetch_json

# ───────────────────────── Cấu hình trang ─────────────────────────
st.set_page_config(
    page_title="Báo cáo sáng — VITRAN BOUTIQUE HCM",
    page_icon="📦",
    layout="wide",
)

# ───────────────────────── Bảng màu (đồng bộ báo cáo PNG) ─────────────────────────
COLOR_SOURCE = {"tiktokshop": "#534AB7", "shopee": "#D85A30"}
SOURCE_LABEL = {"tiktokshop": "TikTok Shop", "shopee": "Shopee"}
COLOR_CARRIER = {
    "J&T Express": "#378ADD", "NB tự VC": "#888780", "Nhanh": "#BA7517",
    "SPX Express": "#1D9E75", "Hỏa Tốc": "#E24B4A", "SPX Instant": "#639922",
    "Giao Hàng Nhanh": "#639922", "GHN": "#639922",
}
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
    </style>
    """,
    unsafe_allow_html=True,
)


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
        st.success(f"👤 **{name}**\n\n`{username}` · vai trò: {roles[0]}")
        authenticator.logout("🚪 Đăng xuất", "sidebar")
        st.divider()
    return (name, username, roles[0])


CUR_NAME, CUR_USER, CUR_ROLE = require_login()


# ───────────────────────── Tiện ích ─────────────────────────
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
left.title("📦 Báo cáo sáng — VITRAN BOUTIQUE HCM")
if snap_time:
    right.metric("Dữ liệu chụp lúc", snap_time[11:16], snap_time[:10])
else:
    vn_now = datetime.now(timezone.utc) + timedelta(hours=7)
    right.metric("Cập nhật (giờ VN)", vn_now.strftime("%H:%M"), vn_now.strftime("%d/%m/%Y"))

# ═══════════════════════ PHẦN 1 — CHỜ XÁC NHẬN ═══════════════════════
st.markdown(
    f'<div class="sec sec-orange">Chờ xác nhận '
    f'<span class="sub">— {p["total"]} đơn · {p["total_items"]} SP · {p["sku_count"]} SKU</span></div>',
    unsafe_allow_html=True,
)

k = st.columns(5)
k[0].metric("Tổng đơn", p["total"])
k[1].metric("Sản phẩm", p["total_items"])
k[2].metric("SKU", p["sku_count"])
k[3].metric("🟠 Đặt hôm nay", p["today"])
k[4].metric("Đặt hôm qua", p["yesterday"])

k2 = st.columns(5)
k2[0].metric("Giao nhanh", p["fast"])
k2[1].metric("Hỏa tốc", p["express"])

g1, g2 = st.columns(2)
with g1:
    st.markdown("**Sàn TMĐT**")
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
    st.markdown("**Đơn vị vận chuyển**")
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

st.markdown("**Chi tiết SKU chờ xác nhận**")
sku_df = pd.DataFrame(p["skus"]).rename(
    columns={"sku": "SKU", "name": "Sản phẩm", "qty": "SL", "orders": "Đơn"}
)
st.dataframe(
    sku_df, width="stretch", hide_index=True,
    column_config={
        "SL": st.column_config.ProgressColumn(
            "SL", format="%d",
            min_value=0, max_value=int(sku_df["SL"].max()) if not sku_df.empty else 1,
        ),
    },
)

# ═══════════════════════ PHẦN 2 — ĐÃ ĐẨY VC → HỦY (7 NGÀY) ═══════════════════════
st.markdown(
    f'<div class="sec sec-red">Đã đẩy VC → hủy (7 ngày) '
    f'<span class="sub">— loại trừ {c["excluded_appeal"]} đơn kháng nghị thành công</span></div>',
    unsafe_allow_html=True,
)

m = st.columns(3)
m[0].metric("Tổng đơn hủy", c["total"])
m[1].metric("⚠ Đã đóng gói (lấy lại)", len(c["packed"]))
m[2].metric("Chưa đóng gói", len(c["not_packed"]))

st.markdown("**⚠ Đã đóng gói — cần lấy lại hàng**")
packed_df = cancel_table(c["packed"])
if packed_df.empty:
    st.success("Không có đơn đã đóng gói nào bị hủy. 👍")
else:
    st.dataframe(packed_df, width="stretch", hide_index=True)

st.markdown("**Chưa đóng gói**")
np_df = cancel_table(c["not_packed"])
if np_df.empty:
    st.info("Không có đơn chưa đóng gói.")
else:
    st.dataframe(np_df, width="stretch", hide_index=True)

# ═══════════════════════ PHẦN 3 — ĐƠN TRẢ HÀNG (7 NGÀY) ═══════════════════════
st.markdown(
    f'<div class="sec sec-blue">Đơn trả hàng (7 ngày) '
    f'<span class="sub">— đã loại {r["canceled"]} phiếu canceled (khách đóng yêu cầu)</span></div>',
    unsafe_allow_html=True,
)

rm = st.columns(4)
rm[0].metric("Tổng phiếu (7 ngày)", r["recent7d_total"])
rm[1].metric("🟢 Đang xử lý (open)", r["open"])
rm[2].metric("Đã trả xong (closed)", r["closed"])
rm[3].metric("Cần xử lý (active)", r["active"])

st.plotly_chart(
    donut(
        ["Đang xử lý (open)", "Đã trả xong (closed)"],
        [r["open"], r["closed"]],
        [ACCENT_BLUE, "#1D9E75"],
        str(r["active"]),
    ),
    width="stretch",
)

st.caption("Cache 5 phút · tự làm mới mỗi 5 phút (bật/tắt ở sidebar) · múi giờ VN (UTC+7).")

# Tự làm mới: reload trang sau 5 phút (đăng nhập nhớ cookie nên không bị đăng xuất)
if auto_refresh:
    components.html(
        "<script>setTimeout(function(){parent.window.location.reload();}, 300000);</script>",
        height=0,
    )
