"""Build shared read-only SAPO data outside Streamlit and persist it to Gist."""
from __future__ import annotations

import os
import sys
import time
from datetime import datetime, timedelta, timezone

import sapo_logic as L
import sapo_tools as PT
from snapshot_returns import build_session, make_fetch_json, push_to_gist


def main() -> None:
    now_vn = datetime.now(timezone.utc) + timedelta(hours=7)
    fetch_json = make_fetch_json(build_session())

    overview = L.get_overview(fetch_json)
    sales = {
        period: L.get_sales_analysis(fetch_json, period=period, _v="shared-snapshot-v1")
        for period in ("1tuan", "1thang", "thangnay", "namnay")
    }
    ttkh = L.get_tt_customer_candidates(fetch_json, days=30, channel_filter="all", pending_ids=None)
    catalog = PT.get_catalog_variants(fetch_json, max_pages=80)
    stock = L.get_stock_by_sku(fetch_json)

    payload = {
        "at": now_vn.strftime("%H:%M %d/%m/%Y"),
        "at_epoch": int(time.time()),
        "overview": overview,
        "sales": sales,
        "ttkh": ttkh,
        "catalog": catalog,
        "stock": stock,
    }
    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        raise RuntimeError("Thieu GIST_TOKEN cho workflow snapshot.")
    push_to_gist(token, "vitran_shared.json", payload)
    print(
        f"Shared snapshot {payload['at']} | catalog={len(catalog)} "
        f"ttkh={ttkh.get('total', 0)} stock={len(stock)}"
    )


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"Shared snapshot that bai: {exc}", file=sys.stderr)
        raise
