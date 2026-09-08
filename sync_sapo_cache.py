"""sync_sapo_cache.py — đồng bộ TĂNG DẦN đơn hàng / đơn hoàn vào kho đệm trên Gist.

Chạy trên GitHub Actions (hoặc máy shop). Mỗi lượt chỉ hỏi Sapo phần MỚI/ĐỔI kể từ lần
đồng bộ trước bằng endpoint Sapo khuyến nghị:
    /admin/orders/search.json?modified_on_min=…&modified_on_max=…
    /admin/order_returns/search.json?modified_on_min=…&modified_on_max=…

  python sync_sapo_cache.py                 # đồng bộ cả 2
  python sync_sapo_cache.py --kind returns  # chỉ đơn hoàn (dùng khi nạp lần đầu, đo dung lượng)
  python sync_sapo_cache.py --backfill 400  # ép nạp lại N ngày (kho trống mới cần)
"""
from __future__ import annotations

import argparse
import os
import sys

import sapo_cache
from snapshot_returns import build_session, make_fetch_json


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--kind", choices=("orders", "returns", "all"), default="all")
    ap.add_argument("--backfill", type=int, default=None,
                    help="số ngày nạp lần đầu khi kho còn trống")
    ap.add_argument("--max-pages", type=int, default=120)
    args = ap.parse_args()

    if not os.environ.get("GITHUB_TOKEN"):
        print("Thieu GITHUB_TOKEN (kho Gist).")
        return 2
    fetch_json = make_fetch_json(build_session())

    kinds = ("returns", "orders") if args.kind == "all" else (args.kind,)
    for kind in kinds:                     # đơn hoàn trước: nhẹ hơn, thấy dung lượng sớm
        print(f"→ đồng bộ {kind}…")
        try:
            r = sapo_cache.sync(kind, fetch_json, backfill_days=args.backfill,
                                max_pages=args.max_pages)
        except Exception as e:
            print(f"  LOI [{kind}]: {type(e).__name__}: {str(e)[:200]}")
            return 3
        if not r.get("saved"):
            print(f"  LOI: khong ghi duoc kho {kind} len Gist")
            return 4
    ok, info = sapo_cache.cache_ready()
    print(("KHO SAN SANG: " if ok else "KHO CHUA DU: ") + info)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
