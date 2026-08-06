"""
cham_cong.py — Chấm công + TÍNH LƯƠNG tự động cho NV VITRAN (giai đoạn 1: logic tính lương).

Quy tắc lương (user chốt 01/07):
- 2 NV, 30.000đ/GIỜ, 8h/ngày (đã trừ nghỉ trưa 1h). Làm T2–T7, NGHỈ Chủ nhật.
  · Kho : ca 08:30 → 17:30 (từ 13/7; trước đó 09:30→18:30)   · CSKH: ca 10:00 → 19:00
- Chấm 2 lần/ngày: Vào (sáng) + Ra (chiều); nghỉ trưa 1h TỰ TRỪ.
- Về ĐÚNG giờ tan (về sớm bị trừ). Mỗi ngày hụt TỔNG (đi trễ + về sớm) ≤5' → bỏ qua; quá 5' → trừ giờ thực. KHÔNG tăng ca (>8h vẫn 8h).
- Thiếu ≥4h/ngày → MẤT suất ăn ngày đó. Nghỉ hẳn 1 ngày → 0 lương + 0 ăn (dù có phép hay không).
- Cả tháng nghỉ >8h → MẤT chuyên cần 500k; nghỉ ≤8h → +500k.
- Thiếu chấm (quên chấm 1 lần Vào HOẶC Ra) mà KHÔNG có bằng chứng → TRỪ 50k/ngày.
- Tăng ca phải XIN PHÉP + chủ duyệt → ×1.5 (45k/giờ); tự làm quá giờ KHÔNG tự cộng.
- Tiền ăn 30k/ngày công. Lương tháng = Σ(giờ×30k + ăn) + chuyên cần + tăng ca − phạt thiếu chấm.
"""
from datetime import date, timedelta

RATE = 30_000          # đồng/giờ
LUNCH_MIN = 60         # nghỉ trưa tự trừ
GRACE_MIN = 5          # cho phép đi trễ 5'
FULL_DAY_MIN = 480     # 8h chuẩn/ngày
MEAL = 30_000          # tiền ăn / ngày công
NO_MEAL_IF_MISS = 240  # thiếu ≥4h → mất suất ăn
CHUYEN_CAN = 500_000
CHUYEN_CAN_MAX_MISS = 480   # cả tháng nghỉ ≤8h thì được chuyên cần
PHAT_THIEU_CHAM = 50_000    # thiếu chấm 1 lần (Vào/Ra) không bằng chứng → trừ 50k/ngày

EMPLOYEES = {
    # start/end = ca HIỆN TẠI. "history" = lịch sử đổi ca (mốc 'from' mới nhất ≤ ngày → dùng ca đó)
    # để KHÔNG tính sai ngày cũ. NV Kho đổi giờ chính thức 08:30→17:30 từ 2026-07-13 (trước: 09:30→18:30).
    "kho":  {"name": "NV Kho",  "start": "08:30", "end": "17:30",
             "history": [{"from": "2026-07-13", "start": "08:30", "end": "17:30"},
                         {"from": "2000-01-01", "start": "09:30", "end": "18:30"}]},
    "cskh": {"name": "NV CSKH", "start": "10:00", "end": "19:00"},
}


def _shift_for(emp_key, d):
    """(start, end) của NV cho NGÀY d theo lịch sử đổi ca (mốc 'from' mới nhất ≤ d)."""
    e = EMPLOYEES.get(emp_key) or {}
    _hist = e.get("history")
    if _hist and d is not None:
        _iso = d.isoformat() if hasattr(d, "isoformat") else str(d)
        for h in sorted(_hist, key=lambda x: str(x.get("from", "")), reverse=True):
            if _iso >= str(h.get("from", "")):
                return h.get("start", e.get("start")), h.get("end", e.get("end"))
    return e.get("start"), e.get("end")


def _m(hhmm):
    """'09:30' -> số phút từ 0h."""
    h, m = str(hhmm).split(":")
    return int(h) * 60 + int(m)


def calc_day(start, end, ci, co):
    """1 ngày. start/end/ci/co = 'HH:MM' (ci/co None = nghỉ). Trả dict công + lương ngày."""
    ss, se = _m(start), _m(end)
    if ci is None or co is None:
        return {"status": "Nghỉ", "worked": 0, "missed": FULL_DAY_MIN,
                "late": 0, "salary": 0, "meal": 0}
    ci, co = _m(ci), _m(co)
    eff_ci = max(ci, ss)                             # tới sớm tính từ giờ ca; đi trễ tính thực
    eff_co = min(co, se)                             # về ĐÚNG giờ (về sớm bị trừ); về trễ KHÔNG tính tăng ca
    worked = max(0, min((eff_co - eff_ci) - LUNCH_MIN, FULL_DAY_MIN))
    missed = FULL_DAY_MIN - worked
    if 0 < missed <= GRACE_MIN:                      # cả ngày hụt TỔNG (đi trễ + về sớm) ≤5' → bỏ qua
        worked, missed = FULL_DAY_MIN, 0
    late = max(0, ci - ss)                           # phút đi trễ thực (để hiển thị)
    salary = round(worked / 60 * RATE)
    meal = MEAL if missed < NO_MEAL_IF_MISS else 0
    status = "Đủ công" if missed == 0 else ("Thiếu giờ" if worked > 0 else "Nghỉ")
    return {"status": status, "worked": worked, "missed": missed,
            "late": late, "salary": salary, "meal": meal}


def working_days(y, mth, upto=None):
    """Các ngày T2–T7 trong tháng (bỏ Chủ nhật), tới ngày 'upto' (mặc định hết tháng)."""
    d = date(y, mth, 1)
    end = date(y + (mth == 12), (mth % 12) + 1, 1) - timedelta(days=1)
    if upto and upto < end:
        end = upto
    out = []
    while d <= end:
        if d.weekday() != 6:          # 6 = Chủ nhật → nghỉ, không tính
            out.append(d)
        d += timedelta(days=1)
    return out


def calc_month(emp_key, records, y, mth, upto=None):
    """Tính lương tháng cho 1 NV. records = {ngày_iso: (ci, co)}. Ngày làm không có bản ghi = Nghỉ."""
    e = EMPLOYEES[emp_key]
    rows, tot_sal, tot_meal, tot_miss, days_w, days_off = [], 0, 0, 0, 0, 0
    for d in working_days(y, mth, upto):
        ci, co = records.get(d.isoformat(), (None, None))
        _st, _en = _shift_for(emp_key, d)   # ca theo NGÀY (đổi giờ 13/7) → không tính sai ngày cũ
        r = calc_day(_st, _en, ci, co)
        tot_sal += r["salary"]; tot_meal += r["meal"]; tot_miss += r["missed"]
        if r["worked"] > 0:
            days_w += 1
        else:
            days_off += 1
        rows.append({"ngay": d.isoformat(), "vao": ci, "ra": co, **r})
    cc = CHUYEN_CAN if tot_miss <= CHUYEN_CAN_MAX_MISS else 0
    return {
        "nv": e["name"], "rows": rows,
        "days_worked": days_w, "days_off": days_off,
        "gio_cong": round(sum(r["worked"] for r in rows) / 60, 1),
        "luong_gio": tot_sal, "tien_an": tot_meal,
        "nghi_phut": tot_miss, "chuyen_can": cc,
        "tong": tot_sal + tot_meal + cc,
    }


# ═══════════════════════════════════════════════════════════════════════════
# GIAI ĐOẠN 2 — Phân quyền · Mã QR động · Lưu chấm công (Gist)
# ═══════════════════════════════════════════════════════════════════════════
import hmac as _hmac
import hashlib as _hashlib
import time as _time
from datetime import datetime as _dt, timezone as _tz

# Tài khoản đăng nhập → nhân viên + quyền (user cung cấp 01/07)
ACCOUNTS = {
    "mun.inventory@gmail.com": {"emp": "kho",  "role": "nv"},
    "official024@gmail.com":   {"emp": "cskh", "role": "nv"},
    "vitran2291@gmail.com":    {"emp": None,   "role": "admin"},
    "0703902291":              {"emp": None,   "role": "shop"},   # máy shop: chỉ thấy trang QR/mã
    "073902291":               {"emp": None,   "role": "shop"},   # (phòng hờ số cũ)
}


def role_of(username):
    return (ACCOUNTS.get(str(username or "").strip().lower()) or {}).get("role", "guest")


def emp_of(username):
    return (ACCOUNTS.get(str(username or "").strip().lower()) or {}).get("emp")


# ─── Mã QR động (HMAC theo cửa sổ thời gian) ───
QR_WINDOW = 60   # mỗi mã sống 60 giây


def _qr_secret():
    """Bí mật ký mã QR. Ưu tiên secrets[cham_cong].qr_secret; không có thì DẪN XUẤT từ token
    picklog (đã có trong secrets) → khỏi thêm secret. Cuối cùng mới dùng hằng dự phòng."""
    try:
        import streamlit as st
        s = st.secrets["cham_cong"]["qr_secret"]
        if s:
            return str(s)
    except Exception:
        pass
    try:
        import picklog
        t = picklog._token()
        if t:
            return _hashlib.sha256((t + "|cc-qr").encode()).hexdigest()
    except Exception:
        pass
    return "vitran-cham-cong-qr-fallback"


def qr_token(now=None):
    """Mã hiện tại — 6 CHỮ SỐ (dễ gõ), đổi mỗi 60s."""
    w = int((now if now is not None else _time.time()) // QR_WINDOW)
    h = _hmac.new(_qr_secret().encode(), str(w).encode(), _hashlib.sha256).hexdigest()
    return f"{int(h[:8], 16) % 1000000:06d}"


def verify_token(tok, now=None):
    """True nếu mã (6 số) khớp cửa sổ hiện tại HOẶC ngay trước (~2 phút)."""
    if not tok:
        return False
    tok = str(tok).strip()
    n = now if now is not None else _time.time()
    base = int(n // QR_WINDOW)
    for w in (base, base - 1):
        h = _hmac.new(_qr_secret().encode(), str(w).encode(), _hashlib.sha256).hexdigest()
        if _hmac.compare_digest(tok, f"{int(h[:8], 16) % 1000000:06d}"):
            return True
    return False


def device_key(emp):
    """Mã thiết bị CỐ ĐỊNH cho mỗi NV — nhúng vào link riêng để máy tự nhận diện (khỏi đăng nhập)."""
    return _hmac.new(_qr_secret().encode(), ("device:" + str(emp)).encode(), _hashlib.sha256).hexdigest()[:12]


def verify_device(nv, k):
    """True nếu nv hợp lệ (NV hoặc 'shop') và k khớp mã thiết bị của nv."""
    return bool(nv) and (nv in EMPLOYEES or nv == "shop") and bool(k) and _hmac.compare_digest(str(k), device_key(nv))


# ─── Lưu / đọc chấm công (Gist — mỗi tháng 1 file vitran_cong_YYYY-MM.json) ───
def _vn_now():
    return _dt.now(_tz.utc) + timedelta(hours=7)


def _cong_file(y, mth):
    return f"vitran_cong_{y:04d}-{mth:02d}.json"


def save_check(emp, kind, selfie_b64=""):
    """Ghi 1 lần chấm (kind='in'|'out') với GIỜ HIỆN TẠI + selfie vào Gist. Trả (ok, msg, hhmm)."""
    import picklog, requests, json
    now = _vn_now()
    hhmm = now.strftime("%H:%M")
    fname = _cong_file(now.year, now.month)
    try:
        d = picklog._read_gist_file(fname) or {"records": {}}
        day = d.setdefault("records", {}).setdefault(emp, {}).setdefault(now.strftime("%Y-%m-%d"), {})
        day[kind] = hhmm
        if selfie_b64:
            day[kind + "_selfie"] = selfie_b64
        gid = picklog._resolve_gid()
        if not gid:
            return False, "❌ Chưa cấu hình kho lưu (thiếu token picklog).", hhmm
        body = {"files": {fname: {"content": json.dumps(d, ensure_ascii=False)}}}
        r = requests.patch(f"{picklog._API}/gists/{gid}", headers=picklog._hdr(),
                           data=json.dumps(body), timeout=30)
        if r.status_code == 200:
            lbl = "VÀO ca" if kind == "in" else "TAN ca"
            return True, f"✅ Đã chấm {lbl} lúc {hhmm}", hhmm
        return False, f"❌ Lỗi lưu (mã {r.status_code}). Thử lại.", hhmm
    except Exception as e:
        return False, f"❌ Lỗi lưu: {str(e)[:60]}. Thử lại.", hhmm


def _norm_hhmm(s):
    """Chuẩn hóa giờ người gõ → 'HH:MM'. Nhận 9:30 · 9h30 · 9.30 · 9 30 · 930 · 0930 · 9 · 9h.
    Trả '' nếu để trống (xóa), None nếu không hiểu."""
    import re
    s = str(s or "").strip().lower()
    if not s:
        return ""
    m = re.match(r'^(\d{1,2})\s*[:hg.,\s]\s*(\d{1,2})$', s)   # có phân tách: 9:30 9h30 9.30 "9 30"
    if m:
        h, mm = int(m.group(1)), int(m.group(2))
    elif re.match(r'^\d{1,2}[hg]?$', s):                      # chỉ giờ: 9 · 9h
        h, mm = int(re.sub(r'\D', '', s)), 0
    else:
        dg = re.sub(r'\D', '', s)
        if len(dg) == 3:                                      # 930  → 9:30
            h, mm = int(dg[0]), int(dg[1:])
        elif len(dg) == 4:                                    # 0930 → 09:30
            h, mm = int(dg[:2]), int(dg[2:])
        else:
            return None
    return f"{h:02d}:{mm:02d}" if (0 <= h <= 23 and 0 <= mm <= 59) else None


def set_check(emp, day_iso, in_hhmm=None, out_hhmm=None, note="", by="chủ shop", evidence=None):
    """Admin đặt/sửa giờ Vào–Ra cho 1 ngày (khi NV quên chấm). Trả (ok, msg).
    Mỗi field: **None = GIỮ NGUYÊN** (không đụng) · **"" = XÓA** · **"HH:MM"(-ish) = ĐẶT**.
    Giờ do CHỦ SHOP đặt/sửa (KHÁC giờ NV tự chấm) được ĐÁNH DẤU `in_edit`/`out_edit`
    (ai bổ sung + lúc nào + ghi chú + giá trị cũ) → hiện ngay tại giờ đó để ĐỐI CHIẾU.
    `evidence` (True/False/None): đánh dấu ngày thiếu chấm ĐÃ CÓ bằng chứng → miễn phạt 50k."""
    import picklog, requests, json

    def _norm_or_keep(v):
        return "KEEP" if v is None else _norm_hhmm(v)   # None=giữ; ""=xóa; None-trả-về=gõ sai
    in_v, out_v = _norm_or_keep(in_hhmm), _norm_or_keep(out_hhmm)
    if in_v is None:
        return False, "❌ Giờ VÀO chưa hiểu — gõ kiểu: 9:30 · 9h30 · 0930."
    if out_v is None:
        return False, "❌ Giờ RA chưa hiểu — gõ kiểu: 18:30 · 18h30 · 1830."
    # KHÔNG cho ĐẶT giờ vào ngày CHƯA TỚI (tương lai); vẫn cho XÓA ("" cả 2) để dọn bản ghi nhầm
    _setting = (in_v not in ("KEEP", "")) or (out_v not in ("KEEP", ""))
    if _setting:
        try:
            if date.fromisoformat(day_iso) > _vn_now().date():
                return False, "❌ Không đặt giờ cho ngày CHƯA TỚI (ngày tương lai)."
        except Exception:
            pass
    y, mth = int(day_iso[:4]), int(day_iso[5:7])
    fname = _cong_file(y, mth)
    try:
        d = picklog._read_gist_file(fname) or {"records": {}}
        recs = d.setdefault("records", {}).setdefault(emp, {})
        day = recs.setdefault(day_iso, {})
        old_in, old_out = day.get("in"), day.get("out")
        eff_in = old_in if in_v == "KEEP" else (in_v or None)     # giờ VÀO sau khi áp
        eff_out = old_out if out_v == "KEEP" else (out_v or None)  # giờ RA sau khi áp
        if eff_in and eff_out and _m(eff_out) <= _m(eff_in):
            return False, "❌ Giờ RA phải sau giờ VÀO."
        _stamp = _vn_now().strftime("%H:%M %d/%m/%Y")
        _note = str(note or "").strip()[:200]

        def _apply(kind, val, old):
            k = kind                       # 'in' | 'out'
            if val == "KEEP":
                return
            if val:                        # ĐẶT giờ
                day[k] = val
                if val != old:             # chủ shop bổ sung/sửa → ĐÁNH DẤU tại giờ đó
                    _e = {"by": by, "at": _stamp}
                    if _note:
                        _e["note"] = _note
                    if old:
                        _e["old"] = old
                    day[k + "_edit"] = _e
            else:                          # XÓA giờ
                day.pop(k, None); day.pop(k + "_selfie", None); day.pop(k + "_edit", None)

        _apply("in", in_v, old_in)
        _apply("out", out_v, old_out)
        if evidence is not None:           # cờ "đã có bằng chứng" (miễn phạt thiếu chấm)
            if evidence:
                day["evidence"] = True
            else:
                day.pop("evidence", None)
        if not day:                        # ngày trống hẳn → bỏ bản ghi
            recs.pop(day_iso, None)
        gid = picklog._resolve_gid()
        if not gid:
            return False, "❌ Thiếu token picklog (chưa cấu hình kho lưu)."
        body = {"files": {fname: {"content": json.dumps(d, ensure_ascii=False)}}}
        r = requests.patch(f"{picklog._API}/gists/{gid}", headers=picklog._hdr(),
                           data=json.dumps(body), timeout=30)
        if r.status_code == 200:
            _m2 = " · đã ghi chú bổ sung tay" if _note else ""
            return True, f"✅ Đã lưu {day_iso}: Vào {day.get('in', '—')} · Ra {day.get('out', '—')}{_m2}"
        return False, f"❌ Lỗi lưu (mã {r.status_code}). Thử lại."
    except Exception as e:
        return False, f"❌ Lỗi: {str(e)[:60]}"


def day_record(emp, day_iso=None):
    """Bản ghi 1 ngày của NV: {'in','out','in_selfie','out_selfie'} (rỗng nếu chưa chấm)."""
    import picklog
    now = _vn_now()
    day_iso = day_iso or now.strftime("%Y-%m-%d")
    y, mth = int(day_iso[:4]), int(day_iso[5:7])
    d = picklog._read_gist_file(_cong_file(y, mth)) or {}
    return ((d.get("records") or {}).get(emp, {}) or {}).get(day_iso, {}) or {}


def month_records(emp, y, mth):
    """{ngày_iso: (in, out)} của NV trong tháng — nạp cho calc_month."""
    import picklog
    d = picklog._read_gist_file(_cong_file(y, mth)) or {}
    recs = (d.get("records") or {}).get(emp, {})
    return {day: (v.get("in"), v.get("out")) for day, v in recs.items()}


def month_meta(emp, y, mth):
    """{ngày_iso: {'in_edit','out_edit','evidence'}} — dấu giờ CHỦ SHOP bổ sung tay (đối chiếu)
    + cờ 'evidence' (ngày thiếu chấm đã có bằng chứng → miễn phạt). KHÔNG có in_edit/out_edit =
    giờ đó NV tự chấm (hệ thống ghi tự động)."""
    import picklog
    d = picklog._read_gist_file(_cong_file(y, mth)) or {}
    recs = (d.get("records") or {}).get(emp, {})
    out = {}
    for day, v in recs.items():
        e = {}
        if v.get("in_edit"):
            e["in_edit"] = v["in_edit"]
        if v.get("out_edit"):
            e["out_edit"] = v["out_edit"]
        if v.get("evidence"):
            e["evidence"] = True
        if e:
            out[day] = e
    return out


def month_selfies(emp, y, mth):
    """{ngày_iso: {in,out,in_selfie,out_selfie}} — cho quản lý duyệt."""
    import picklog
    d = picklog._read_gist_file(_cong_file(y, mth)) or {}
    return (d.get("records") or {}).get(emp, {})


def salary_report(emp_key, y, mth, upto=None):
    """Báo cáo lương tháng 1 NV (đọc Gist → tính) + TĂNG CA đã duyệt (×1.5)."""
    rep = calc_month(emp_key, month_records(emp_key, y, mth), y, mth, upto)
    _ot_h = approved_ot_hours(emp_key, y, mth)
    _ot_pay = int(round(_ot_h * RATE * 1.5))
    rep["ot_hours"] = _ot_h
    rep["ot_pay"] = _ot_pay
    _meta = month_meta(emp_key, y, mth)           # dấu bổ sung tay + cờ đã-có-bằng-chứng
    _tc_days = 0
    for r in rep["rows"]:
        _m2 = _meta.get(r["ngay"], {})
        r["in_edit"] = _m2.get("in_edit")
        r["out_edit"] = _m2.get("out_edit")
        r["evidence"] = bool(_m2.get("evidence"))
        # THIẾU CHẤM = có đúng 1 trong 2 giờ (quên chấm 1 lần) & CHƯA có bằng chứng → phạt 50k
        r["thieu_cham"] = (bool(r.get("vao")) != bool(r.get("ra"))) and not r["evidence"]
        if r["thieu_cham"]:
            _tc_days += 1
    rep["thieu_cham_days"] = _tc_days
    rep["phat_thieu_cham"] = PHAT_THIEU_CHAM * _tc_days
    rep["tong"] = rep["tong"] + _ot_pay - rep["phat_thieu_cham"]
    return rep


def missing_punch_days(emp_key, y, mth, upto=None):
    """Danh sách ngày (iso) NV chấm 1 lần (VÀO hoặc RA) mà THIẾU lần kia → cần bổ sung/bằng chứng.
    Bỏ Chủ nhật (working_days). Dùng để nhắc lên 'Việc cần làm' của chính NV."""
    recs = month_records(emp_key, y, mth)
    out = []
    for d in working_days(y, mth, upto):
        ci, co = recs.get(d.isoformat(), (None, None))
        if bool(ci) != bool(co):
            out.append(d.isoformat())
    return out


# ═══════════════ XIN PHÉP TĂNG CA → chủ shop DUYỆT → tính ×1.5 ═══════════════
_OT_FILE = "vitran_tangca.json"   # {emp: [{id,date,hours,note,status,at,approved_at}]}


def _ot_read():
    import picklog
    d = picklog._read_gist_file(_OT_FILE)
    return d if isinstance(d, dict) else {}


def _ot_write(d):
    import picklog
    return picklog._write_gist_file(_OT_FILE, d)


def add_ot_request(emp, day_iso, hours, note=""):
    """NV gửi 1 đơn xin tăng ca (ngày + số giờ). Trạng thái 'pending' chờ duyệt."""
    if emp not in EMPLOYEES or not day_iso:
        return False
    try:
        hours = round(float(hours), 2)
    except Exception:
        return False
    if hours <= 0 or hours > 12:
        return False
    d = _ot_read()
    lst = d.setdefault(emp, [])
    lst.append({"id": f"{day_iso}-{len(lst) + 1}", "date": str(day_iso), "hours": hours,
                "note": str(note or "")[:200], "status": "pending", "at": _vn_now().strftime("%H:%M %d/%m/%Y")})
    return _ot_write(d)


def list_ot(emp, y=None, mth=None):
    """Đơn tăng ca của 1 NV (lọc theo tháng nếu có), mới nhất trước."""
    lst = list(_ot_read().get(emp, []))
    if y and mth:
        _pfx = f"{y:04d}-{mth:02d}"
        lst = [r for r in lst if str(r.get("date", "")).startswith(_pfx)]
    return sorted(lst, key=lambda r: str(r.get("date", "")), reverse=True)


def list_pending_ot():
    """Tất cả đơn tăng ca CHỜ DUYỆT (mọi NV) — cho chủ shop."""
    out = []
    for emp, lst in _ot_read().items():
        for r in (lst or []):
            if r.get("status") == "pending":
                out.append({**r, "emp": emp})
    return sorted(out, key=lambda r: str(r.get("date", "")))


def set_ot_status(emp, req_id, status):
    """Chủ shop duyệt/từ chối 1 đơn (status = approved | rejected)."""
    if status not in ("approved", "rejected", "pending"):
        return False
    d = _ot_read()
    for r in d.get(emp, []):
        if r.get("id") == req_id:
            r["status"] = status
            r["approved_at"] = _vn_now().strftime("%H:%M %d/%m/%Y")
            return _ot_write(d)
    return False


def approved_ot_hours(emp, y, mth):
    """Tổng giờ tăng ca ĐÃ DUYỆT của NV trong tháng (để tính lương ×1.5)."""
    _pfx = f"{y:04d}-{mth:02d}"
    return round(sum(float(r.get("hours") or 0) for r in _ot_read().get(emp, [])
                     if r.get("status") == "approved" and str(r.get("date", "")).startswith(_pfx)), 2)
