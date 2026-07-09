"""
scan_invalid_orders.py — Chạy ĐỘC LẬP (ngoài Streamlit) để lấy danh sách đơn CHƯA
HỢP LỆ, dùng lại đúng logic của app (sapo_logic). Dùng khi quét trong app không xong.

Kết quả:
  1) Xuất Excel  invalid_orders.xlsx  (2 sheet: chua_co_khach, dia_chi_chua_chuan)
  2) (tuỳ chọn) Đẩy vào Gist vitran_ttkh_audit.json để APP hiển thị luôn.

Chạy:
  # Windows PowerShell
  $env:SAPO_ACCESS_TOKEN="..."      # HOẶC  $env:SAPO_COOKIE="..."
  $env:AUDIT_DAYS="365"             # tuỳ chọn (mặc định 365)
  $env:GITHUB_TOKEN="ghp_..."       # tuỳ chọn — để đẩy kết quả vào Gist cho app
  python scan_invalid_orders.py
"""
import json
import os
import sys
import time

import requests

import sapo_logic as L

BASE = "https://vitranboutiquehcm.mysapo.net"


def build_session():
    s = requests.Session()
    s.headers.update({"User-Agent": "Mozilla/5.0", "Accept": "application/json"})
    token = os.environ.get("SAPO_ACCESS_TOKEN") or os.environ.get("SAPO_TOKEN")
    cookie = os.environ.get("SAPO_COOKIE")
    if token:
        s.headers["X-Sapo-Access-Token"] = token
    elif cookie:
        s.headers["Cookie"] = cookie
    else:
        sys.exit("❌ Thiếu credential: đặt SAPO_ACCESS_TOKEN hoặc SAPO_COOKIE.")
    return s


def make_fetch_json(session):
    def fetch_json(path, **params):
        r = session.get(f"{BASE}{path}", params=params, timeout=40)
        r.raise_for_status()
        return r.json()
    return fetch_json


def push_to_gist(github_token, data):
    """Ghi kết quả vào file vitran_ttkh_audit.json trong gist chứa vitran_picklog.json."""
    api = "https://api.github.com"
    hdr = {"Authorization": f"Bearer {github_token}",
           "Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
    gid = None
    for page in range(1, 6):
        r = requests.get(f"{api}/gists", headers=hdr, params={"per_page": 100, "page": page}, timeout=20)
        if r.status_code != 200:
            break
        rows = r.json()
        if not rows:
            break
        for g in rows:
            if "vitran_picklog.json" in (g.get("files") or {}):
                gid = g.get("id")
                break
        if gid or len(rows) < 100:
            break
    if not gid:
        print("⚠️ Không tìm thấy gist picklog để đẩy kết quả (bỏ qua Gist).")
        return
    body = {"files": {"vitran_ttkh_audit.json": {"content": json.dumps(data, ensure_ascii=False)}}}
    r = requests.patch(f"{api}/gists/{gid}", headers=hdr, data=json.dumps(body), timeout=30)
    print("✅ Đã đẩy vào Gist." if r.status_code == 200 else f"⚠️ Đẩy Gist lỗi ({r.status_code}).")


def main():
    days = int(os.environ.get("AUDIT_DAYS") or 365)
    sess = build_session()
    fj = make_fetch_json(sess)

    print(f"→ Tải danh sách khách hàng (có thể vài phút)…")
    cores, good, cap = L.get_customer_phone_set(fj, max_pages=300)
    print(f"   Lấy được {len(cores)} SĐT khách ({len(good)} địa chỉ chuẩn). hit_cap={cap}")

    print(f"→ Đối chiếu đơn {days} ngày…")

    def prog(win_i, win_n, n_seen, n_found):
        print(f"   tháng {win_i}/{win_n} · đã xét {n_seen} đơn · tìm {n_found} đơn cần xử lý")

    missing = L.audit_orders_missing_customer(fj, good, days=days, channel_filter="all",
                                              all_phone_set=cores, progress_cb=prog)
    n_text = sum(1 for m in missing if "text" in str(m.get("ly_do", "")).lower() or "chưa chuẩn" in str(m.get("ly_do", "")).lower())
    n_nocust = len(missing) - n_text
    print(f"✅ XONG: {len(missing)} đơn chưa hợp lệ — {n_nocust} chưa có khách, {n_text} địa chỉ chưa chuẩn.")

    # Xuất Excel
    try:
        import openpyxl
        from openpyxl import Workbook
        wb = Workbook()
        ws1 = wb.active
        ws1.title = "chua_co_khach"
        ws2 = wb.create_sheet("dia_chi_chua_chuan")
        head = ["Mã đơn", "Tên", "SĐT", "Địa chỉ", "Định dạng", "Ngày tạo"]
        for ws in (ws1, ws2):
            ws.append(head)

        def addr(info):
            return ", ".join(str(x).strip() for x in (
                info.get("address1"), info.get("ward"), info.get("district"), info.get("province")) if str(x or "").strip())

        for m in missing:
            info = m.get("info") or {}
            row = [m.get("code"), info.get("name", ""), m.get("phone"), addr(info),
                   "Mới" if info.get("address_format") == "new" else "Cũ", m.get("created_on")]
            (ws2 if ("text" in str(m.get("ly_do", "")).lower() or "chưa chuẩn" in str(m.get("ly_do", "")).lower()) else ws1).append(row)
        wb.save("invalid_orders.xlsx")
        print("📄 Đã lưu invalid_orders.xlsx")
    except Exception as e:
        print(f"⚠️ Không xuất được Excel: {e}")

    # Đẩy vào Gist (nếu có token) để app hiển thị
    gh = os.environ.get("GITHUB_TOKEN")
    if gh:
        result = {"missing": missing, "cap": cap, "n_suspect": len(missing), "days": days,
                  "ts": time.strftime("%H:%M %d/%m")}
        push_to_gist(gh, result)


if __name__ == "__main__":
    main()
