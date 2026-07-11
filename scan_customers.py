"""scan_customers.py — Quét khách hàng chưa chuẩn (phân nhóm) → đẩy vào Gist cho app.

Chạy ngoài app (vd GitHub Actions mỗi đêm) để app luôn có số liệu mới, khỏi bấm quét.

Env cần:
  SAPO_API_KEY + SAPO_API_SECRET   (hoặc SAPO_ACCESS_TOKEN / SAPO_COOKIE)
  GITHUB_TOKEN                     (quyền gist — đẩy kết quả vào gist chứa vitran_picklog.json)
"""
import json, os, sys, requests
import sapo_logic as L

BASE = "https://vitranboutiquehcm.mysapo.net"


def build_session():
    s = requests.Session()
    s.headers.update({"User-Agent": "Mozilla/5.0", "Accept": "application/json"})
    tok = os.environ.get("SAPO_ACCESS_TOKEN") or os.environ.get("SAPO_TOKEN")
    ck = os.environ.get("SAPO_COOKIE")
    key = os.environ.get("SAPO_API_KEY"); sec = os.environ.get("SAPO_API_SECRET")
    if tok:
        s.headers["X-Sapo-Access-Token"] = tok
    elif ck:
        s.headers["Cookie"] = ck
    elif key and sec:
        s.auth = (key, sec)
    else:
        sys.exit("Thiếu credential Sapo.")
    return s


def make_fetch_json(s):
    def fj(path, **p):
        r = s.get(f"{BASE}{path}", params=p, timeout=40); r.raise_for_status(); return r.json()
    return fj


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
    fj = make_fetch_json(build_session())
    print("Quét khách hàng…")
    res = L.audit_customers(fj, per_cat_keep=10000,
                            progress_cb=lambda pg, tot, f: print(f"  trang {pg} · {tot} khách · {f} lỗi") if pg % 20 == 0 else None)
    print("Tổng:", res["total"], "| lỗi:", sum(res["counts"].values()), "|", res["counts"])
    gh = os.environ.get("GITHUB_TOKEN")
    if gh:
        push_to_gist(gh, "vitran_cust_audit.json", res)
    else:
        print("Không có GITHUB_TOKEN — bỏ qua đẩy Gist.")


if __name__ == "__main__":
    main()
