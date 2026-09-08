"""Build shared read-only SAPO data outside Streamlit and persist it to Gist."""
from __future__ import annotations

import os
import sys
import time
from datetime import datetime, timedelta, timezone

import sapo_logic as L
import sapo_tools as PT
from snapshot_returns import build_session, make_fetch_json, push_to_gist


def _read_prev_shared() -> dict:
    """Đọc snapshot dùng chung của lượt trước (để tái dùng phần số cả năm)."""
    try:
        import sapo_cache
        return sapo_cache._read_file("vitran_shared.json") or {}
    except Exception:
        return {}


def _age_hours(at_epoch) -> float:
    try:
        return max(0.0, (time.time() - float(at_epoch)) / 3600.0)
    except Exception:
        return 999.0


def main() -> None:
    now_vn = datetime.now(timezone.utc) + timedelta(hours=7)
    _real = make_fetch_json(build_session())

    # ĐẾM lượt gọi Sapo THẬT + đo thời gian từng phần: để biết chỗ nào còn nặng mà cắt tiếp.
    _calls = {"n": 0}

    def real_fetch(path, **params):
        _calls["n"] += 1
        return _real(path, **params)

    _t_last = [time.time(), 0]
    _diag = []                 # ghi luon vao payload: log cua Actions doc phai co quyen

    def _step(name):
        _dt = time.time() - _t_last[0]
        _dn = _calls["n"] - _t_last[1]
        _diag.append({"buoc": name, "giay": round(_dt, 1), "goi_sapo": _dn})
        print(f"  [{name}] {_dt:.0f}s · {_dn} luot goi Sapo", flush=True)
        _t_last[0], _t_last[1] = time.time(), _calls["n"]

    fetch_json = real_fetch
    try:                      # đọc từ KHO ĐỆM, chỉ ra API khi hỏi ngoài phạm vi kho
        import sapo_cache
        _ok, _info = sapo_cache.cache_ready()
        print(("Kho dem SAN SANG: " if _ok else "Kho dem CHUA DU: ") + _info)
        if _ok:
            fetch_json = sapo_cache.make_cached_fetch_json(real_fetch)
    except Exception as _ce:
        print(f"Kho dem loi ({type(_ce).__name__}) - dung API truc tiep.")
    _step("mo kho dem")

    overview = L.get_overview(fetch_json)
    _step("tong quan")

    # "năm nay" phải quét cả năm (~40.000 đơn) — Sapo cảnh báo chính kiểu quét này. Số cả năm
    # thay đổi rất chậm nên chỉ tính LẠI 1 lần/ngày, các lượt khác dùng lại số của lượt trước.
    _prev = _read_prev_shared()
    _prev_sales = (_prev.get("sales") or {}) if isinstance(_prev, dict) else {}
    _prev_age_h = _age_hours(_prev.get("at_epoch") if isinstance(_prev, dict) else None)
    sales = {}
    for period in ("1tuan", "1thang", "thangnay", "namnay"):
        if period == "namnay" and _prev_sales.get("namnay") and _prev_age_h < 20:
            sales[period] = _prev_sales["namnay"]
            print(f"  sales[namnay]: dung lai so cu ({_prev_age_h:.1f}h truoc) - khoi quet ca nam")
            _diag.append({"buoc": "doanh thu namnay (dung lai so cu)",
                          "giay": 0, "goi_sapo": 0, "tuoi_gio": round(_prev_age_h, 1)})
            continue
        sales[period] = L.get_sales_analysis(fetch_json, period=period, _v="shared-snapshot-v1")
        _step(f"doanh thu {period}")
    ttkh = L.get_tt_customer_candidates(fetch_json, days=30, channel_filter="all", pending_ids=None)
    _step("khach can chuan hoa")
    catalog = PT.get_catalog_variants(fetch_json, max_pages=80)
    _step("danh muc")
    stock = L.get_stock_by_sku(fetch_json)
    _step("ton kho")

    payload = {
        "at": now_vn.strftime("%H:%M %d/%m/%Y"),
        "at_epoch": int(time.time()),
        "overview": overview,
        "sales": sales,
        "ttkh": ttkh,
        "catalog": catalog,
        "stock": stock,
        "_diag": {"buoc": _diag, "tong_goi_sapo": _calls["n"]},
    }
    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        raise RuntimeError("Thieu GIST_TOKEN cho workflow snapshot.")
    push_to_gist(token, "vitran_shared.json", payload)
    print(
        f"Shared snapshot {payload['at']} | catalog={len(catalog)} "
        f"ttkh={ttkh.get('total', 0)} stock={len(stock)} "
        f"| TONG {_calls['n']} luot goi Sapo"
    )


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"Shared snapshot that bai: {exc}", file=sys.stderr)
        raise
