"""
cham_cong_ui.py — Giao diện Streamlit cho chấm công (gọi từ app.py theo trang + quyền).
Logic/tính lương/lưu Gist nằm ở cham_cong.py. Chống gian lận: QR động (ở shop) + selfie.
"""
import base64
import io
from datetime import datetime, timezone, timedelta

import streamlit as st
import pandas as pd

import cham_cong as CC

APP_URL = "https://vitranboutique.streamlit.app"   # QR trỏ về đây kèm ?tk=<mã>


def _vn_now():
    return datetime.now(timezone.utc) + timedelta(hours=7)


def _vnd(x):
    return f"{int(round(x or 0)):,}đ".replace(",", ".")


def _thumb_b64(uploaded, px=240, q=55):
    """Resize selfie -> JPEG nhỏ -> base64 (lưu Gist gọn ~10-20KB)."""
    try:
        from PIL import Image
        im = Image.open(uploaded).convert("RGB")
        im.thumbnail((px, px))
        buf = io.BytesIO()
        im.save(buf, format="JPEG", quality=q)
        return base64.b64encode(buf.getvalue()).decode()
    except Exception:
        try:
            return base64.b64encode(uploaded.getvalue()).decode()
        except Exception:
            return ""


def _qr_png_b64(text):
    import qrcode
    img = qrcode.make(text)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode()


# ══════════════════ NHÂN VIÊN — CHẤM CÔNG ══════════════════
def _checkin_body(emp):
    if not emp or emp not in CC.EMPLOYEES:
        st.error("Không xác định được nhân viên.")
        return
    st.header(f"🕘 Chấm công — {CC.EMPLOYEES[emp]['name']}")

    today = _vn_now().strftime("%Y-%m-%d")
    rec = CC.day_record(emp, today)
    c1, c2 = st.columns(2)
    c1.metric("Vào ca hôm nay", rec.get("in") or "—")
    c2.metric("Tan ca hôm nay", rec.get("out") or "—")
    st.divider()

    tk = st.query_params.get("tk")            # quét QR (nếu có) → tự điền mã
    if not CC.verify_token(tk):               # chưa/không quét → NHẬP TAY mã ở màn hình shop
        code = st.text_input("🔑 Nhập MÃ đang hiện trên màn hình shop (đổi mỗi phút)",
                             max_chars=12, key=f"cc_code_{emp}")
        tk = code.strip() if code else None
    if not CC.verify_token(tk):
        st.info("Nhập đúng mã ở màn hình shop để xác nhận **đang có mặt tại shop**, rồi chụp selfie.")
        return

    st.success("✅ Xác nhận **đang ở shop**. Chụp selfie để chấm:")
    selfie = st.camera_input("Selfie xác nhận chính chủ", key=f"cc_selfie_{emp}")
    if selfie is None:
        st.info("Chụp selfie xong mới bấm nút chấm được.")
        return

    b1, b2 = st.columns(2)
    if b1.button("🟢 VÀO CA", use_container_width=True, disabled=bool(rec.get("in"))):
        ok, msg, _ = CC.save_check(emp, "in", _thumb_b64(selfie))
        (st.success if ok else st.error)(msg)
        if ok:
            st.rerun()
    if b2.button("🔴 TAN CA", use_container_width=True, disabled=bool(rec.get("out"))):
        ok, msg, _ = CC.save_check(emp, "out", _thumb_b64(selfie))
        (st.success if ok else st.error)(msg)
        if ok:
            st.rerun()


def render_checkin(username):
    _checkin_body(CC.emp_of(username))


def render_checkin_dev(emp):     # chế độ THIẾT BỊ: mở link riêng → vào thẳng, khỏi đăng nhập
    _checkin_body(emp)


# ══════════════════ LƯƠNG ══════════════════
def _month_picker(key):
    now = _vn_now()
    c1, c2 = st.columns(2)
    y = c1.selectbox("Năm", [now.year, now.year - 1], index=0, key=f"{key}_y")
    mth = c2.selectbox("Tháng", list(range(1, 13)), index=now.month - 1, key=f"{key}_m")
    upto = now.date() if (y == now.year and mth == now.month) else None
    return y, mth, upto


def _salary_block(emp, y, mth, upto):
    rep = CC.salary_report(emp, y, mth, upto)
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Ngày công", rep["days_worked"])
    m2.metric("Giờ công", rep["gio_cong"])
    m3.metric("Nghỉ (giờ)", round(rep["nghi_phut"] / 60, 1))
    m4.metric("Chuyên cần", _vnd(rep["chuyen_can"]))
    st.markdown(f"#### 🧾 TỔNG LƯƠNG {mth}/{y}: **{_vnd(rep['tong'])}**")
    st.caption(f"Lương giờ {_vnd(rep['luong_gio'])} + ăn {_vnd(rep['tien_an'])} "
               f"+ chuyên cần {_vnd(rep['chuyen_can'])}")
    df = pd.DataFrame([{
        "Ngày": r["ngay"], "Trạng thái": r["status"],
        "Giờ công": round(r["worked"] / 60, 2), "Trễ (phút)": r["late"],
        "Lương ngày": _vnd(r["salary"]), "Tiền ăn": _vnd(r["meal"]),
    } for r in rep["rows"]])
    st.dataframe(df, width="stretch", hide_index=True)


def render_my_salary(username):
    emp = CC.emp_of(username)
    if not emp:
        st.error("Tài khoản này không phải nhân viên.")
        return
    st.header(f"💰 Lương của {CC.EMPLOYEES[emp]['name']}")
    y, mth, upto = _month_picker("mysal")
    _salary_block(emp, y, mth, upto)


# ══════════════════ SHOP — HIỆN QR ══════════════════
def render_shop_qr():
    st.header("📲 QR chấm công (màn hình SHOP)")
    st.caption("Để điện thoại này ở shop. NV cần chấm → NV **nhập MÃ** (hoặc quét QR) trên máy mình. "
               "Mã đổi mỗi phút, đừng để lộ ra ngoài shop.")
    st.session_state.setdefault("cc_show_qr", False)
    if not st.session_state["cc_show_qr"]:
        if st.button("🔓 Hiện QR chấm công", use_container_width=True, type="primary"):
            st.session_state["cc_show_qr"] = True
            st.rerun()
        return
    tok = CC.qr_token()
    url = f"{APP_URL}/?tk={tok}"
    try:
        png = _qr_png_b64(url)
        st.markdown(f'<div style="text-align:center;background:#fff;padding:16px;border-radius:12px">'
                    f'<img src="data:image/png;base64,{png}" style="width:260px;height:260px"/></div>',
                    unsafe_allow_html=True)
    except Exception as e:
        st.error(f"Chưa tạo được QR ({e}) — cần thư viện 'qrcode' trong requirements.")
    st.markdown(f"<div style='text-align:center;font-size:2.1rem;font-weight:800;letter-spacing:3px;"
                f"background:#fef3c7;border-radius:10px;padding:8px;margin-top:8px'>{tok}</div>",
                unsafe_allow_html=True)
    st.caption("👆 NV **nhập mã này** vào máy để chấm (hoặc quét QR). Còn hạn ~1–2 phút; trễ thì **Làm mới**.")
    c1, c2 = st.columns(2)
    if c1.button("🔄 Làm mới QR", use_container_width=True):
        st.rerun()
    if c2.button("🙈 Ẩn QR", use_container_width=True):
        st.session_state["cc_show_qr"] = False
        st.rerun()


# ══════════════════ QUẢN LÝ ══════════════════
def render_admin():
    st.header("🛠️ Quản lý chấm công")
    y, mth, upto = _month_picker("adm")
    tab1, tab2, tab3 = st.tabs(["💰 Bảng lương 2 NV", "📸 Duyệt selfie", "🔗 Link máy NV"])
    with tab1:
        for emp in CC.EMPLOYEES:
            st.subheader(CC.EMPLOYEES[emp]["name"])
            _salary_block(emp, y, mth, upto)
            st.divider()
    with tab2:
        for emp in CC.EMPLOYEES:
            st.subheader(CC.EMPLOYEES[emp]["name"])
            days = CC.month_selfies(emp, y, mth)
            if not days:
                st.caption("Chưa có dữ liệu.")
                continue
            for day in sorted(days.keys(), reverse=True):
                v = days[day]
                cols = st.columns([1.2, 1, 1])
                cols[0].markdown(f"**{day}**\n\nVào {v.get('in') or '—'} · Ra {v.get('out') or '—'}")
                for i, k in enumerate(("in_selfie", "out_selfie")):
                    if v.get(k):
                        cols[i + 1].markdown(
                            f'<img src="data:image/jpeg;base64,{v[k]}" style="width:110px;border-radius:8px"/>'
                            f'<div style="font-size:.7rem;color:#888">{"Vào" if k=="in_selfie" else "Ra"}</div>',
                            unsafe_allow_html=True)
                    else:
                        cols[i + 1].caption("—")
                st.divider()
    with tab3:
        st.caption("Mở link tương ứng trên ĐÚNG máy từng NV → menu trình duyệt **'Thêm vào màn hình chính'** → "
                   "từ đó bấm icon vào THẲNG chấm công, khỏi đăng nhập.")
        for emp in CC.EMPLOYEES:
            st.markdown(f"**{CC.EMPLOYEES[emp]['name']}** — mở trên máy của {CC.EMPLOYEES[emp]['name']}:")
            st.code(f"{APP_URL}/?nv={emp}&k={CC.device_key(emp)}", language=None)
        st.caption("⚠️ Giữ kín link (như mật khẩu). Lỡ lộ, kẻ khác vẫn phải qua **selfie + mã ở shop** nên khó chấm bậy.")
