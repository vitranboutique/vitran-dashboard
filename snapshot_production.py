"""Build the production forecast outside Streamlit and persist it to Gist."""
from __future__ import annotations

import os
import sys
import time
from datetime import datetime, timedelta, timezone

import sapo_tools as PT
from snapshot_returns import build_session, make_fetch_json, push_to_gist


def _attach_inbound(report: dict, inbound: dict) -> None:
    """Attach period inbound quantities and derive opening stock for each SKU/group."""
    ncc = (inbound or {}).get("ncc", {}) or {}
    returns = (inbound or {}).get("returns", {}) or {}
    seen = set()

    def fill_row(row):
        if not isinstance(row, dict) or id(row) in seen:
            return
        seen.add(id(row))
        in_ncc = int(round(ncc.get(row.get("sku"), 0) or 0))
        in_return = int(round(returns.get(row.get("sku"), 0) or 0))
        row["inNCC"] = in_ncc
        row["inReturn"] = in_return
        row["totalIn"] = in_ncc + in_return
        row["openingStock"] = (
            int(round(row.get("endingStock") or 0))
            - row["totalIn"]
            + int(round(row.get("totalOut") or 0))
        )

    for key in ("aggregated", "needRows", "outSkuList", "zeroSalesList", "slowStockList"):
        for row in report.get(key, []) or []:
            fill_row(row)

    def fill_group(group):
        in_ncc = in_return = 0
        for row in group.get("skus", []) or []:
            fill_row(row)
            in_ncc += int(round(ncc.get(row.get("sku"), 0) or 0))
            in_return += int(round(returns.get(row.get("sku"), 0) or 0))
        group["inNCC"] = in_ncc
        group["inReturn"] = in_return
        group["totalIn"] = in_ncc + in_return
        group["openingStock"] = (
            int(round(group.get("totalStock") or 0))
            - group["totalIn"]
            + int(round(group.get("totalOut") or 0))
        )

    for group in report.get("groupRows", []) or []:
        fill_group(group)
    for key in ("mustProduceGroups", "suggestGroups", "manualCutGroups"):
        for group in (report.get("critical", {}) or {}).get(key, []) or []:
            fill_group(group)


def main() -> None:
    now_vn = datetime.now(timezone.utc) + timedelta(hours=7)
    end_date = now_vn.date()
    data_months = 3
    forecast_months = 1
    safety_factor = 1.5
    round_mode = "ceil"

    fetch_json = make_fetch_json(build_session())
    report = PT.get_production_forecast(
        fetch_json,
        data_months=data_months,
        forecast_months=forecast_months,
        safety_factor=safety_factor,
        round_mode=round_mode,
        end_date=end_date,
        max_product_pages=80,
        max_order_pages=250,
    )
    start_date = end_date - timedelta(days=data_months * 30)
    try:
        inbound = PT.get_inbound_by_sku(
            fetch_json,
            start_date=start_date,
            end_date=end_date,
            max_pages=40,
        )
    except Exception:
        inbound = {"ncc": {}, "returns": {}}
    _attach_inbound(report, inbound)

    payload = {
        "at": now_vn.strftime("%H:%M %d/%m/%Y"),
        "at_epoch": int(time.time()),
        "end_date": end_date.isoformat(),
        "params": {
            "data_months": data_months,
            "forecast_months": forecast_months,
            "safety_factor": safety_factor,
            "round_mode": round_mode,
        },
        "report": report,
    }
    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        raise RuntimeError("Thieu GIST_TOKEN cho workflow snapshot.")
    push_to_gist(token, "vitran_production.json", payload)
    source = report.get("source") or {}
    critical = report.get("critical") or {}
    print(
        f"Production snapshot {payload['at']} | sku={source.get('sku_count', 0)} "
        f"orders={source.get('order_count', 0)} | "
        f"must={len(critical.get('mustProduceGroups') or [])} "
        f"suggest={len(critical.get('suggestGroups') or [])} "
        f"manual={len(critical.get('manualCutGroups') or [])}"
    )


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"Production snapshot that bai: {exc}", file=sys.stderr)
        raise
