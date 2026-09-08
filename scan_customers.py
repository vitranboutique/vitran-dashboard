"""scan_customers.py — Quét khách hàng chưa chuẩn (phân nhóm) → đẩy vào Gist cho app.

Chạy ngoài app (vd GitHub Actions mỗi đêm) để app luôn có số liệu mới, khỏi bấm quét.

Env cần:
  SAPO_API_KEY + SAPO_API_SECRET   (hoặc SAPO_ACCESS_TOKEN / SAPO_COOKIE)
  GITHUB_TOKEN                     (quyền gist — đẩy kết quả vào gist chứa vitran_picklog.json)
"""
import json, os, sys, requests
import sapo_logic as L

# Dùng CHUNG lớp gọi Sapo của snapshot_returns: giãn nhịp 1 request / 2 giây và tự thử lại
# khi gặp 429/5xx. Trước đây file này gọi thẳng, không giãn nhịp (≈3 request/giây) — đúng
# kiểu Sapo đã cảnh báo và chặn IP ngày 08/09/2026.
from snapshot_returns import build_session, make_fetch_json  # noqa: F401

BASE = "https://vitranboutiquehcm.mysapo.net"


def push_to_gist(token, fname, data):
    api = "https://api.github.com"
    hdr = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
           "X-GitHub-Api-Version": "2022-11-28"}
    gid = None
    for page in range(1, 6):
        r = requests.get(f"{api}/gists", headers=hdr, params={"per_page": 100, "page": page}, timeout=20)
        if r.status_code != 200 or not r.json():
            break
        for g in r.json():
            if "vitran_picklog.json" in (g.get("files") or {}):
                gid = g.get("id"); break
        if gid:
            break
    if not gid:
        sys.exit("Không tìm thấy gist picklog.")
    r = requests.patch(f"{api}/gists/{gid}", headers=hdr,
                       data=json.dumps({"files": {fname: {"content": json.dumps(data, ensure_ascii=False)}}}), timeout=40)
    print("Đẩy Gist:", r.status_code)


def main():
    real_fj = make_fetch_json(build_session())
    fj = real_fj
    try:                       # phần ĐƠN HÀNG đọc từ KHO ĐỆM, khỏi phân trang lại lịch sử
        import sapo_cache
        _ok, _info = sapo_cache.cache_ready()
        print(("Kho dem SAN SANG: " if _ok else "Kho dem CHUA DU: ") + _info)
        if _ok:
            fj = sapo_cache.make_cached_fetch_json(real_fj)
    except Exception as _ce:
        print(f"Kho dem loi ({type(_ce).__name__}) - dung API truc tiep.")
    print("Quét khách hàng…")
    # throttle=0: nhịp đã do lớp fetch lo (2s/request), khỏi cộng thêm.
    # order_days=110: nằm gọn trong phạm vi kho đệm (120 ngày) → vòng quét đơn không tốn
    # lượt gọi Sapo nào. Đơn cũ hơn mốc này không còn được soi "thiếu ghi chú SĐT".
    res = L.audit_customers(fj, per_cat_keep=10000, throttle=0.0, order_days=110,
                            progress_cb=lambda pg, tot, f: print(f"  trang {pg} · {tot} khách · {f} lỗi") if pg % 20 == 0 else None)
    print("Tổng:", res["total"], "| lỗi:", sum(res["counts"].values()), "|", res["counts"])
    gh = os.environ.get("GITHUB_TOKEN")
    if gh:
        push_to_gist(gh, "vitran_cust_audit.json", res)
    else:
        print("Không có GITHUB_TOKEN — bỏ qua đẩy Gist.")


if __name__ == "__main__":
    main()
