"""snapshot_stock.py — CHỐT TỒN KHO CUỐI NGÀY → đẩy vào Gist cho app.

Vì sao cần: app chỉ chốt tồn khi có người MỞ TRANG, nên "tồn cuối ngày" thực chất là
tồn lúc người ta mở trang (vd 9h sáng). Hàng nhập/xuất buổi tối sau đó KHÔNG được tính
→ hôm sau "Tồn đầu ngày" sai. Chạy script này lúc GẦN NỬA ĐÊM (GitHub Actions) thì mốc
chốt mới đúng là số CUỐI NGÀY, gồm cả hàng nhập buổi tối.

Env cần:
  SAPO_API_KEY + SAPO_API_SECRET   (hoặc SAPO_ACCESS_TOKEN / SAPO_COOKIE)
  GITHUB_TOKEN                     (quyền gist — ghi vào gist chứa vitran_picklog.json)
"""
import json, os, sys, time
from datetime import datetime, timedelta, timezone

import requests

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
    """Giãn nhịp ~3 req/s: Cloudflare của Sapo sẽ CHẶN IP nếu gọi quá dày."""
    last = [0.0]

    def fj(path, **p):
        gap = time.monotonic() - last[0]
        if gap < 0.34:
            time.sleep(0.34 - gap)
        r = s.get(f"{BASE}{path}", params=p, timeout=40)
        last[0] = time.monotonic()
        if r.status_code in (403, 503) and "cloudflare" in (r.text or "")[:600].lower():
            sys.exit("Cloudflare của Sapo đang chặn IP runner — thử lại sau.")
        r.raise_for_status()
        return r.json()
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
                       data=json.dumps({"files": {fname: {"content": json.dumps(data, ensure_ascii=False)}}}),
                       timeout=40)
    print("Đẩy Gist:", r.status_code, fname)
    if r.status_code != 200:
        sys.exit("Ghi Gist lỗi.")


def main():
    fj = make_fetch_json(build_session())

    # 1) variant_id → SKU
    v2sku = {}
    for p in range(1, 81):
        prods = (fj("/admin/products.json", limit=250, page=p) or {}).get("products", [])
        if not prods:
            break
        for prod in prods:
            for v in (prod.get("variants") or []):
                sku = str(v.get("sku") or "").strip().upper()
                if sku and v.get("id") is not None:
                    v2sku[v["id"]] = sku
        if len(prods) < 250:
            break
    print("SKU map:", len(v2sku))

    # 2) inventory_levels → on_hand THẬT (gộp mọi kho)
    on_hand = {}
    for p in range(1, 61):
        levels = (fj("/admin/inventory_levels.json", limit=250, page=p) or {}).get("inventory_levels", [])
        if not levels:
            break
        for it in levels:
            k = v2sku.get(it.get("variant_id"))
            if not k:
                continue
            try:
                on_hand[k] = on_hand.get(k, 0) + int(round(float(it.get("on_hand") or 0)))
            except Exception:
                pass
        if len(levels) < 250:
            break
    print("SKU có tồn:", len(on_hand))
    if not on_hand:
        sys.exit("Không lấy được tồn kho — KHÔNG ghi đè mốc chốt.")

    now_vn = datetime.now(timezone.utc) + timedelta(hours=7)
    day_iso = now_vn.strftime("%Y-%m-%d")
    push_to_gist(os.environ["GITHUB_TOKEN"], f"vitran_stock_{day_iso}.json",
                 {"at": now_vn.strftime("%H:%M %d/%m/%Y") + " (chốt tự động cuối ngày)",
                  "on_hand": on_hand})
    print("Đã chốt tồn ngày", day_iso, "-", len(on_hand), "SKU")


if __name__ == "__main__":
    main()
