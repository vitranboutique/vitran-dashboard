"""snapshot_returns.py — QUÉT ĐƠN TRẢ / ĐƠN CẦN KN chạy NỀN rồi đẩy Gist.

Vì sao cần: mục "đơn trả / đơn cần KN" phải quét hàng trăm trang Sapo (throttle ~3 req/s
để né Cloudflare) → mỗi lần cache hết hạn là chờ ~2 phút. Script này chạy ĐỊNH KỲ trên
GitHub Actions (không chiếm phiên người dùng), kết quả đẩy vào Gist. App chỉ ĐỌC Gist
=> hiện TỨC THÌ, gần real-time, không ai phải chờ.

Env cần (đã có sẵn trong GitHub Secrets của repo):
  SAPO_API_KEY + SAPO_API_SECRET   (hoặc SAPO_ACCESS_TOKEN / SAPO_COOKIE)
  GITHUB_TOKEN                     (= secrets.GIST_TOKEN, quyền gist)
"""
import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone

import requests
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
    """Giãn nhịp ~3 req/s: Cloudflare của Sapo sẽ CHẶN IP nếu gọi quá dày."""
    last = [0.0]

    def fj(path, **p):
        gap = time.monotonic() - last[0]
        if gap < 0.34:
            time.sleep(0.34 - gap)
        r = s.get(f"{BASE}{path}", params=p, timeout=40)
        last[0] = time.monotonic()
        if r.status_code in (403, 503) and "cloudflare" in (r.text or "")[:600].lower():
            sys.exit("Cloudflare của Sapo đang chặn IP runner — thử lại lần sau.")
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
                       data=json.dumps({"files": {fname: {"content": json.dumps(data, ensure_ascii=False, default=str)}}}),
                       timeout=60)
    print("Đẩy Gist:", r.status_code, fname)
    if r.status_code != 200:
        sys.exit("Ghi Gist lỗi.")


def main():
    fj = make_fetch_json(build_session())

    # Hai bộ quét CHẬM (chính là thứ khiến app chờ 2 phút) — nay chạy nền:
    in_progress = L.get_returns_in_progress(fj)   # dict: đơn trả đang xử lý + CỜ CẦN KN
    followup = L.get_returns_followup(fj)          # list: đơn trả năm nay cần theo dõi

    now_vn = datetime.now(timezone.utc) + timedelta(hours=7)
    payload = {
        "at": now_vn.strftime("%H:%M %d/%m/%Y"),
        "at_epoch": int(time.time()),
        "in_progress": in_progress,
        "followup": followup,
    }
    push_to_gist(os.environ["GITHUB_TOKEN"], "vitran_returns.json", payload)

    try:
        _need_kn = len((in_progress or {}).get("need_kn") or (in_progress or {}).get("items") or [])
    except Exception:
        _need_kn = "?"
    print(f"Đã snapshot đơn trả lúc {payload['at']} · followup={len(followup)} · in_progress_keys={list((in_progress or {}).keys())}")


if __name__ == "__main__":
    main()
