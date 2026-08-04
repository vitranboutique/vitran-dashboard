"""
cham_cong_ui.py — Giao diện Streamlit cho chấm công (gọi từ app.py theo trang + quyền).
Logic/tính lương/lưu Gist nằm ở cham_cong.py. Chống gian lận: QR động (ở shop) + selfie.
"""
import base64
import io
from datetime import datetime, timezone, timedelta, time as dtime

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
        return ""    # không có PIL → bỏ selfie (tránh ảnh gốc quá to gây lỗi lưu Gist)


def _qr_png_b64(text):
    import qrcode
    img = qrcode.make(text)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode()


# ══════════════════ NHÂN VIÊN — CHẤM CÔNG ══════════════════
def _success_alert(kind, hhmm):
    """Báo chấm công OK: banner TO + chuông + rung (chạy 1 lần sau khi chấm)."""
    import streamlit.components.v1 as components
    label = "VÀO CA" if kind == "in" else "TAN CA"
    color = "#16a34a" if kind == "in" else "#dc2626"
    components.html(f"""
      <div style="background:{color};color:#fff;border-radius:16px;padding:20px;text-align:center;
                  font-family:sans-serif;animation:pop .4s ease-out">
        <div style="font-size:3rem;line-height:1">✅</div>
        <div style="font-size:1.5rem;font-weight:800;margin-top:6px">ĐÃ CHẤM {label}</div>
        <div style="font-size:2.4rem;font-weight:800;letter-spacing:2px">{hhmm}</div>
        <div style="opacity:.9;margin-top:4px;font-size:.95rem">Đã lưu ảnh + giờ ✔ — có thể cất điện thoại.</div>
      </div>
      <style>@keyframes pop{{0%{{transform:scale(.7);opacity:0}}100%{{transform:scale(1);opacity:1}}}}</style>
      <script>
        try {{
          var A=new (window.AudioContext||window.webkitAudioContext)();
          var o=A.createOscillator(), g=A.createGain(); o.connect(g); g.connect(A.destination);
          o.type="sine"; g.gain.value=0.25;
          o.frequency.setValueAtTime(784,A.currentTime);
          o.frequency.setValueAtTime(1047,A.currentTime+0.12);
          o.frequency.setValueAtTime(1319,A.currentTime+0.24);
          o.start(); o.stop(A.currentTime+0.42);
        }} catch(e) {{}}
        try {{ navigator.vibrate([180,80,180]); }} catch(e) {{}}
      </script>
    """, height=210)


def _checkin_body(emp):
    if not emp or emp not in CC.EMPLOYEES:
        st.error("Không xác định được nhân viên.")
        return
    # Gương lại camera selfie cho tự nhiên (như camera trước của điện thoại)
    st.markdown("<style>[data-testid='stCameraInput'] video{transform:scaleX(-1)!important}</style>",
                unsafe_allow_html=True)
    st.header(f"🕘 Chấm công — {CC.EMPLOYEES[emp]['name']}")

    # Vừa chấm xong (lần trước) → báo TO + chuông + rung, đúng 1 lần
    flag = st.session_state.pop(f"cc_done_{emp}", None)
    if flag:
        _success_alert(*flag)

    now = _vn_now()
    today = now.strftime("%Y-%m-%d")
    recs = CC.month_selfies(emp, now.year, now.month)      # đọc cả tháng 1 lần
    rec = recs.get(today, {}) or {}
    c1, c2 = st.columns(2)
    c1.metric("Vào ca hôm nay", rec.get("in") or "—")
    c2.metric("Tan ca hôm nay", rec.get("out") or "—")
    with st.expander("📅 Lịch sử chấm công tháng này"):
        if not recs:
            st.caption("Chưa có lần chấm nào trong tháng.")
        else:
            hist = pd.DataFrame([{"Ngày": dd, "Vào": (recs[dd].get("in") or "—"),
                                  "Ra": (recs[dd].get("out") or "—")}
                                 for dd in sorted(recs, reverse=True)])
            st.dataframe(hist, width="stretch", hide_index=True)

    done_in, done_out = bool(rec.get("in")), bool(rec.get("out"))
    if done_in and done_out:
        st.success("✅ Hôm nay bạn đã chấm ĐỦ **Vào ca + Tan ca** rồi. Không cần chấm nữa.")
        return
    st.divider()

    tk = st.query_params.get("tk")            # (cũ) quét QR → tự điền; giờ chủ yếu là NHẬP TAY
    if not CC.verify_token(tk):
        code = st.text_input("🔑 Nhập MÃ đang hiện trên màn hình shop (đổi mỗi phút)",
                             max_chars=12, key=f"cc_code_{emp}")
        tk = code.strip() if code else None
    if not CC.verify_token(tk):
        st.info("Nhập đúng mã ở màn hình shop để xác nhận **đang có mặt tại shop**, rồi chụp selfie.")
        return

    # Nói RÕ đang chấm cái gì — chỉ hiện 1 hành động kế tiếp
    next_kind = "in" if not done_in else "out"
    if next_kind == "in":
        st.markdown("<div style='background:#dcfce7;border:2px solid #16a34a;border-radius:12px;padding:10px;"
                    "text-align:center;font-size:1.3rem;font-weight:800;color:#166534;margin-bottom:8px'>"
                    "🟢 BẠN ĐANG CHẤM: VÀO CA</div>", unsafe_allow_html=True)
        btn_label = "🟢 XÁC NHẬN VÀO CA"
    else:
        st.markdown("<div style='background:#fee2e2;border:2px solid #dc2626;border-radius:12px;padding:10px;"
                    "text-align:center;font-size:1.3rem;font-weight:800;color:#991b1b;margin-bottom:8px'>"
                    "🔴 BẠN ĐANG CHẤM: TAN CA</div>", unsafe_allow_html=True)
        btn_label = "🔴 XÁC NHẬN TAN CA"

    st.caption("Đã ở shop ✔ — chụp selfie rồi bấm nút bên dưới:")
    shot = st.session_state.get(f"cc_shot_{emp}", 0)
    selfie = st.camera_input("📸 Chụp selfie chính chủ", key=f"cc_selfie_{emp}_{shot}")
    if selfie is None:
        st.info("⬆️ Bấm nút máy ảnh để chụp selfie trước đã.")
        return

    if st.button(btn_label, use_container_width=True, type="primary"):
        ok, msg, hhmm = CC.save_check(emp, next_kind, _thumb_b64(selfie))
        if ok:
            st.session_state[f"cc_done_{emp}"] = (next_kind, hhmm)   # để báo TO sau khi rerun
            st.session_state[f"cc_shot_{emp}"] = shot + 1            # đổi key camera → XÓA ảnh cũ
            st.session_state.pop(f"cc_code_{emp}", None)             # xóa mã → về trạng thái sạch
            st.rerun()
        else:
            st.error(msg)


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
    m3.metric("Nghỉ (giờ)", round(rep["nghi_phut"] / 60, 1),
              help="Chỉ tính ngày làm T2–T7 (nghỉ hẳn + thiếu giờ). ĐÃ loại Chủ nhật.")
    m4.metric("Chuyên cần", _vnd(rep["chuyen_can"]))
    st.markdown(f"#### 🧾 TỔNG LƯƠNG {mth}/{y}: **{_vnd(rep['tong'])}**")
    st.caption(f"Lương giờ {_vnd(rep['luong_gio'])} + ăn {_vnd(rep['tien_an'])} "
               f"+ chuyên cần {_vnd(rep['chuyen_can'])}")
    # Bảng chi tiết TÔ MÀU: 🛌 Chủ nhật xám (nghỉ lịch, không tính) · ❌ NGHỈ đỏ (ngày làm không đi)
    # · ⚠️ thiếu giờ hổ phách + SỐ PHÚT thiếu · ✅ đủ xanh. Dễ phân biệt, khỏi đọc bảng trắng.
    import datetime as _dt
    _THU = ["T2", "T3", "T4", "T5", "T6", "T7", "CN"]
    _by = {r["ngay"]: r for r in rep["rows"]}
    _d = _dt.date(y, mth, 1)
    _end = _dt.date(y + (mth == 12), (mth % 12) + 1, 1) - _dt.timedelta(days=1)
    if upto and upto < _end:
        _end = upto
    _trs = ""
    while _d <= _end:
        _thu = _THU[_d.weekday()]
        _lbl = f"{_d.day:02d}/{mth:02d} {_thu}"
        if _d.weekday() == 6:                       # CHỦ NHẬT — nghỉ lịch, xám RẤT NHẠT (KHÔNG tính)
            _trs += (f'<tr style="background:#fafbfc;color:#94a3b8">'
                     f'<td><b>{_lbl}</b></td>'
                     f'<td colspan="5" style="text-align:center">🛌 Chủ nhật — nghỉ, không tính lương</td>'
                     f'<td style="text-align:right">—</td></tr>')
            _d += _dt.timedelta(days=1)
            continue
        _r = _by.get(_d.isoformat())
        if not _r:
            _d += _dt.timedelta(days=1)
            continue
        _w = _r.get("worked") or 0
        _miss = int(_r.get("missed") or 0)
        _gio = round(_w / 60, 2)
        _ci = _r.get("vao")
        _co = _r.get("ra")
        _vao = _ci or "—"
        _ra = _co or "—"
        if bool(_ci) != bool(_co):                  # CÓ vào HOẶC ra, THIẾU 1 lần → cần bằng chứng
            _bg, _fg, _tt, _th = "#f5f3ff", "#6d28d9", "⚠️ THIẾU CHẤM — cần bằng chứng", "?"
        elif _w <= 0:                               # KHÔNG chấm gì (vào & ra đều trống) → NGHỈ thật
            _bg, _fg, _tt, _th = "#fef2f2", "#dc2626", "❌ NGHỈ", "cả ngày"
        elif _miss > CC.GRACE_MIN:                  # THIẾU GIỜ → hổ phách NHẠT + số phút
            _bg, _fg, _tt, _th = "#fffbeb", "#b45309", "⚠️ thiếu giờ", f"-{_miss}′"
        else:                                       # đủ giờ → TRẮNG (khỏi tô), chỉ icon xanh
            _bg, _fg, _tt, _th = "#ffffff", "#334155", "✅", "—"
        _trs += (f'<tr style="background:{_bg};color:{_fg}">'
                 f'<td><b>{_lbl}</b></td><td>{_vao}</td><td>{_ra}</td>'
                 f'<td>{_gio}h</td><td style="font-weight:800">{_th}</td>'
                 f'<td>{_tt}</td><td style="text-align:right">{_vnd(_r["salary"])}</td></tr>')
        _d += _dt.timedelta(days=1)
    st.markdown(
        '<style>.cctbl{border-collapse:collapse;width:100%;font-size:.9em}'
        '.cctbl td,.cctbl th{padding:4px 8px;border-bottom:1px solid #e5eaf1;text-align:left}</style>'
        '<div style="overflow-x:auto"><table class="cctbl"><thead>'
        '<tr style="background:#1e293b;color:#fff"><th>Ngày</th><th>Vào</th><th>Ra</th>'
        '<th>Giờ</th><th>Thiếu</th><th>Trạng thái</th><th style="text-align:right">Lương ngày</th>'
        f'</tr></thead><tbody>{_trs}</tbody></table></div>', unsafe_allow_html=True)


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
    try:   # tự làm mới mỗi 50s → mã luôn mới + giữ kết nối, KHÔNG bị văng/ngủ khi để yên
        from streamlit_autorefresh import st_autorefresh
        st_autorefresh(interval=50000, key="shop_qr_keepalive")
    except Exception:
        pass
    st.header("📟 Mã chấm công (màn hình SHOP)")
    st.caption("Để điện thoại này ở shop. NV **nhập MÃ** dưới đây vào máy mình để chấm. "
               "Mã đổi mỗi phút, đừng để lộ ra ngoài shop.")
    st.session_state.setdefault("cc_show_qr", False)
    if not st.session_state["cc_show_qr"]:
        if st.button("🔓 Hiện MÃ chấm công", use_container_width=True, type="primary"):
            st.session_state["cc_show_qr"] = True
            st.rerun()
        return
    tok = CC.qr_token()
    st.markdown(f"<div style='text-align:center;font-size:3rem;font-weight:800;letter-spacing:6px;"
                f"background:#fef3c7;border-radius:14px;padding:18px;margin:8px 0'>{tok}</div>",
                unsafe_allow_html=True)
    st.caption("👆 NV **nhập mã này** vào máy mình để chấm — **KHÔNG quét** (quét sẽ bắt đăng nhập). Đổi mỗi phút.")
    c1, c2 = st.columns(2)
    if c1.button("🔄 Làm mới", use_container_width=True):
        st.rerun()
    if c2.button("🙈 Ẩn mã", use_container_width=True):
        st.session_state["cc_show_qr"] = False
        st.rerun()


# ══════════════════ QUẢN LÝ ══════════════════
def render_admin():
    st.header("🛠️ Quản lý chấm công")
    y, mth, upto = _month_picker("adm")
    tab1, tab_edit, tab2, tab3 = st.tabs(
        ["💰 Bảng lương 2 NV", "✏️ Sửa giờ công", "📸 Duyệt selfie", "🔗 Link máy NV"])
    with tab1:
        for emp in CC.EMPLOYEES:
            st.subheader(CC.EMPLOYEES[emp]["name"])
            _salary_block(emp, y, mth, upto)
            st.divider()
    with tab_edit:
        flash = st.session_state.pop("edit_flash", None)
        if flash:
            st.success(flash)
        st.caption("Khi NV **quên chấm**: chọn NV + ngày, chỉnh **giờ Vào/Ra** (bấm vào ô, có sẵn dấu **:**). "
                   "Tick **Nghỉ** để xóa cả 2 giờ. Lưu xong bảng lương tự tính lại.")
        e = st.selectbox("Nhân viên", list(CC.EMPLOYEES),
                         format_func=lambda k: CC.EMPLOYEES[k]["name"], key="edit_emp")
        d = st.date_input("Ngày", value=_vn_now().date(), key="edit_day")
        day_iso = d.isoformat()
        cur = CC.day_record(e, day_iso)
        st.info(f"Ngày **{day_iso}** hiện tại — Vào **{cur.get('in') or '—'}** · Ra **{cur.get('out') or '—'}**")

        def _to_time(hhmm, dft):
            try:
                h, m = str(hhmm).split(":")
                return dtime(int(h), int(m))
            except Exception:
                return dft
        dft_in = _to_time(CC.EMPLOYEES[e]["start"], dtime(9, 30))
        dft_out = _to_time(CC.EMPLOYEES[e]["end"], dtime(18, 30))
        cc1, cc2 = st.columns(2)
        tin = cc1.time_input("Giờ VÀO", value=_to_time(cur.get("in"), dft_in),
                             step=timedelta(minutes=1), key=f"edit_in_{e}_{day_iso}")
        tout = cc2.time_input("Giờ RA", value=_to_time(cur.get("out"), dft_out),
                              step=timedelta(minutes=1), key=f"edit_out_{e}_{day_iso}")
        off = st.checkbox("🚫 Đánh NGHỈ ngày này (xóa cả 2 giờ)", key=f"edit_off_{e}_{day_iso}")
        if st.button("💾 Lưu giờ công", type="primary", key="edit_save"):
            if off:
                ok, msg = CC.set_check(e, day_iso, "", "")
            else:
                ok, msg = CC.set_check(e, day_iso, tin.strftime("%H:%M"), tout.strftime("%H:%M"))
            if ok:
                st.session_state["edit_flash"] = msg     # báo "đã lưu" hiện SAU khi rerun
                st.rerun()
            else:
                st.error(msg)
    with tab2:
        for emp in CC.EMPLOYEES:
            st.subheader(CC.EMPLOYEES[emp]["name"])
            days = CC.month_selfies(emp, y, mth)
            if not days:
                st.caption("Chưa có dữ liệu.")
                continue
            for day in sorted(days.keys(), reverse=True):
                v = days[day]
                cA, cB, cC = st.columns([1.3, 1, 1])
                cA.markdown(f"**{day}**")
                cA.caption(f"Vào {v.get('in') or '—'} · Ra {v.get('out') or '—'}")
                for col, k, lbl, tt, clr in (
                        (cB, "in_selfie", "🟢 VÀO", v.get("in"), "#16a34a"),
                        (cC, "out_selfie", "🔴 RA", v.get("out"), "#dc2626")):
                    col.markdown(f"<div style='text-align:center;font-weight:800;color:{clr}'>"
                                 f"{lbl} {tt or '—'}</div>", unsafe_allow_html=True)
                    if v.get(k):
                        try:
                            col.image(base64.b64decode(v[k]), width=140)
                        except Exception:
                            col.caption("(ảnh lỗi)")
                    else:
                        col.caption("(không có ảnh)")
                st.divider()
    with tab3:
        st.caption("Mở link tương ứng trên ĐÚNG máy từng NV → menu trình duyệt **'Thêm vào màn hình chính'** → "
                   "từ đó bấm icon vào THẲNG chấm công, khỏi đăng nhập.")
        for emp in CC.EMPLOYEES:
            st.markdown(f"**{CC.EMPLOYEES[emp]['name']}** — mở trên máy của {CC.EMPLOYEES[emp]['name']}:")
            st.code(f"{APP_URL}/?nv={emp}&k={CC.device_key(emp)}", language=None)
        st.markdown("**📲 Máy SHOP (hiện mã)** — mở trên điện thoại để ở shop (khỏi đăng nhập):")
        st.code(f"{APP_URL}/?nv=shop&k={CC.device_key('shop')}", language=None)
        st.caption("⚠️ Giữ kín link (như mật khẩu). Lỡ lộ, kẻ khác vẫn phải qua **selfie + mã ở shop** nên khó chấm bậy.")
