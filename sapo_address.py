from __future__ import annotations

import json
import re
import unicodedata
from functools import lru_cache
from pathlib import Path


def norm_key(value) -> str:
    s = unicodedata.normalize("NFD", str(value or ""))
    s = "".join(ch for ch in s if unicodedata.category(ch) != "Mn")
    s = re.sub(
        r"^(TP|THANH PHO|TINH|QUAN|HUYEN|THI XA|PHUONG|XA|THI TRAN)\s+",
        "",
        s.strip(),
        flags=re.I,
    )
    return re.sub(r"[^A-Z0-9]+", "", s.upper())


@lru_cache(maxsize=1)
def _codes() -> dict:
    path = Path(__file__).with_name("data") / "sapo_address_codes.json"
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {"old": {"provinces": [], "districts": [], "wards": []}, "new": {"provinces": [], "wards": []}}


def _find_one(rows, **keys):
    for row in rows:
        ok = True
        for key, value in keys.items():
            if value and row.get(key) != value:
                ok = False
                break
        if ok:
            return row
    return None


def resolve_address(info: dict) -> dict:
    """Return a copy of parsed address info with canonical Sapo names and codes."""
    out = dict(info or {})
    data = _codes()
    fmt = out.get("address_format") or ("old" if out.get("district") else "new")
    ward_key = norm_key(out.get("ward"))
    district_key = norm_key(out.get("district"))
    province_key = norm_key(out.get("province"))

    if fmt == "old":
        ward = _find_one(
            data.get("old", {}).get("wards", []),
            key=ward_key,
            district_key=district_key,
            province_key=province_key,
        ) or _find_one(data.get("old", {}).get("wards", []), key=ward_key, district_key=district_key)
        if ward:
            out.update({
                "address_format": "old",
                "ward": ward.get("name") or out.get("ward"),
                "ward_code": ward.get("code") or "",
                "district": ward.get("district") or out.get("district"),
                "district_code": ward.get("district_code") or "",
                "province": ward.get("province") or out.get("province"),
                "province_code": ward.get("province_code") or "",
            })
            return out

    # If TikTok gives a new-format address, or the old catalog cannot match it,
    # fall back to the new ward/province catalog.
    ward = _find_one(
        data.get("new", {}).get("wards", []),
        key=ward_key,
        province_key=province_key,
    ) or _find_one(data.get("new", {}).get("wards", []), key=ward_key)
    if ward:
        out.update({
            "address_format": "new",
            "ward": ward.get("name") or out.get("ward"),
            "ward_code": ward.get("code") or "",
            "district": "",
            "district_code": "",
            "province": ward.get("province") or out.get("province"),
            "province_code": ward.get("province_code") or "",
        })
        return out

    provinces = data.get(fmt, {}).get("provinces", [])
    province = _find_one(provinces, key=province_key)
    if province:
        out["province"] = province.get("name") or out.get("province")
        out["province_code"] = province.get("code") or ""
    return out
