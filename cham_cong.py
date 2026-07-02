"""
cham_cong.py — Chấm công + TÍNH LƯƠNG tự động cho NV VITRAN (giai đoạn 1: logic tính lương).

Quy tắc lương (user chốt 01/07):
- 2 NV, 30.000đ/GIỜ, 8h/ngày (đã trừ nghỉ trưa 1h). Làm T2–T7, NGHỈ Chủ nhật.
  · Kho : ca 09:30 → 18:30   · CSKH: ca 10:00 → 19:00
- Chấm 2 lần/ngày: Vào (sáng) + Ra (chiều); nghỉ trưa 1h TỰ TRỪ.
- Đi trễ: miễn 5' đầu; trễ quá 5' → tính theo giờ thực (ít giờ = ít lương). KHÔNG tăng ca (>8h vẫn 8h).
- Thiếu ≥4h/ngày → MẤT suất ăn ngày đó. Nghỉ hẳn 1 ngày → 0 lương + 0 ăn (dù có phép hay không).
- Cả tháng nghỉ >8h → MẤT chuyên cần 500k; nghỉ ≤8h → +500k.
- Tiền ăn 30k/ngày công. Lương tháng = Σ(giờ×30k + ăn) + chuyên cần (nếu đạt).
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

EMPLOYEES = {
    "kho":  {"name": "NV Kho",  "start": "09:30", "end": "18:30"},
    "cskh": {"name": "NV CSKH", "start": "10:00", "end": "19:00"},
}


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
    eff_ci = ss if ci <= ss + GRACE_MIN else ci      # trễ ≤5' coi như đúng giờ
    eff_ci = max(eff_ci, ss)                          # tới sớm tính từ giờ ca
    eff_co = min(co, se)                              # về trễ KHÔNG tính tăng ca
    worked = max(0, min((eff_co - eff_ci) - LUNCH_MIN, FULL_DAY_MIN))
    missed = FULL_DAY_MIN - worked
    late = (ci - ss) if ci > ss + GRACE_MIN else 0   # phút trễ THỰC (trễ ≤5' được miễn = 0)
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
        r = calc_day(e["start"], e["end"], ci, co)
        tot_sal += r["salary"]; tot_meal += r["meal"]; tot_miss += r["missed"]
        if r["worked"] > 0:
            days_w += 1
        else:
            days_off += 1
        rows.append({"ngay": d.isoformat(), **r})
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
    """Mã QR hiện tại (8 ký tự) — đổi mỗi 60s."""
    w = int((now if now is not None else _time.time()) // QR_WINDOW)
    return _hmac.new(_qr_secret().encode(), str(w).encode(), _hashlib.sha256).hexdigest()[:8]


def verify_token(tok, now=None):
    """True nếu mã khớp cửa sổ hiện tại HOẶC ngay trước (bù thời gian quét ~ tối đa 2')."""
    if not tok:
        return False
    n = now if now is not None else _time.time()
    base = int(n // QR_WINDOW)
    for w in (base, base - 1):
        good = _hmac.new(_qr_secret().encode(), str(w).encode(), _hashlib.sha256).hexdigest()[:8]
        if _hmac.compare_digest(str(tok), good):
            return True
    return False


# ─── Lưu / đọc chấm công (Gist — mỗi tháng 1 file vitran_cong_YYYY-MM.json) ───
def _vn_now():
    return _dt.now(_tz.utc) + timedelta(hours=7)


def _cong_file(y, mth):
    return f"vitran_cong_{y:04d}-{mth:02d}.json"


def save_check(emp, kind, selfie_b64=""):
    """Ghi 1 lần chấm (kind='in'|'out') với GIỜ HIỆN TẠI + selfie vào Gist. Trả (ok, msg, hhmm)."""
    import picklog
    now = _vn_now()
    fname = _cong_file(now.year, now.month)
    d = picklog._read_gist_file(fname) or {"records": {}}
    recs = d.setdefault("records", {})
    day = recs.setdefault(emp, {}).setdefault(now.strftime("%Y-%m-%d"), {})
    hhmm = now.strftime("%H:%M")
    day[kind] = hhmm
    if selfie_b64:
        day[kind + "_selfie"] = selfie_b64
    ok = picklog._write_gist_file(fname, d)
    lbl = "VÀO ca" if kind == "in" else "TAN ca"
    return ok, (f"✅ Đã chấm {lbl} lúc {hhmm}" if ok else "❌ Lỗi lưu, thử lại"), hhmm


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


def month_selfies(emp, y, mth):
    """{ngày_iso: {in,out,in_selfie,out_selfie}} — cho quản lý duyệt."""
    import picklog
    d = picklog._read_gist_file(_cong_file(y, mth)) or {}
    return (d.get("records") or {}).get(emp, {})


def salary_report(emp_key, y, mth, upto=None):
    """Báo cáo lương tháng 1 NV (đọc Gist → tính)."""
    return calc_month(emp_key, month_records(emp_key, y, mth), y, mth, upto)
