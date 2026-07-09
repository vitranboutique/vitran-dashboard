from __future__ import annotations

import json
import re
import unicodedata
from functools import lru_cache
from pathlib import Path


def norm_key(value) -> str:
    s = unicodedata.normalize("NFD", str(value or ""))
    s = "".join(ch for ch in s if unicodedata.category(ch) != "Mn")
    s = s.strip()
    # Bỏ tiền tố tiếng Việt (Phường/Quận/TP...) ở ĐẦU
    s = re.sub(
        r"^(TP|THANH PHO|TINH|QUAN|HUYEN|THI XA|PHUONG|XA|THI TRAN)\s+",
        "",
        s,
        flags=re.I,
    )
    # Bỏ đuôi tiếng ANH (Ward/District/City/Province...) do TikTok trả — nếu không sẽ
    # khớp trượt (vd 'Chanh Hung Ward' != 'Chánh Hưng') → sai phường/quận.
    s = re.sub(
        r"\s+(WARD|DISTRICT|CITY|PROVINCE|COMMUNE|TOWN|TOWNSHIP)$",
        "",
        s,
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


@lru_cache(maxsize=1)
def _new_province_keys() -> frozenset:
    return frozenset(p.get("key") for p in _codes().get("new", {}).get("provinces", []))


@lru_cache(maxsize=1)
def _merged_province_map() -> dict:
    """Bản đồ tỉnh CŨ (đã sáp nhập 2025) → TÊN tỉnh MỚI, suy từ độ trùng tên phường.
    Vd 'Bình Dương'→'Hồ Chí Minh'. Dùng để dịch tỉnh cũ trước khi tra phường mới,
    tránh chọn nhầm phường trùng tên ở tỉnh khác."""
    from collections import Counter, defaultdict
    data = _codes()
    new_keys = _new_province_keys()
    new_ward_prov = defaultdict(set)
    for w in data.get("new", {}).get("wards", []):
        new_ward_prov[w.get("key")].add(w.get("province"))
    old_prov_wards = defaultdict(list)
    for w in data.get("old", {}).get("wards", []):
        old_prov_wards[w.get("province_key")].append(w.get("key"))
    out = {}
    for p in data.get("old", {}).get("provinces", []):
        pk = p.get("key")
        if not pk or pk in new_keys:
            continue
        votes = Counter()
        for wk in old_prov_wards.get(pk, []):
            for prov in new_ward_prov.get(wk, ()):
                votes[prov] += 1
        if votes:
            out[pk] = votes.most_common(1)[0][0]
    return out


def resolve_address(info: dict) -> dict:
    """Return a copy of parsed address info with canonical Sapo names and codes."""
    out = dict(info or {})
    data = _codes()
    fmt = out.get("address_format") or ("old" if out.get("district") else "new")
    ward_key = norm_key(out.get("ward"))
    district_key = norm_key(out.get("district"))
    province_key = norm_key(out.get("province"))

    # Old SAPO address: has district. Ward can be numbered ("Phường 22")
    # or named. New SAPO address has no district and keeps ward as a name.
    if out.get("district"):
        fmt = "old"

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

    # New SAPO address keeps ward/province as names; codes are only retained for
    # diagnostics and fallback, not used as the primary submitted value.
    # Tỉnh CŨ đã sáp nhập (vd 'Bình Dương') → dịch sang tỉnh mới ('Hồ Chí Minh')
    # để tra đúng phường, không chọn nhầm phường trùng tên ở tỉnh khác.
    lookup_prov_key = province_key
    if province_key and province_key not in _new_province_keys():
        _mapped = _merged_province_map().get(province_key)
        if _mapped:
            lookup_prov_key = norm_key(_mapped)
    ward = _find_one(
        data.get("new", {}).get("wards", []),
        key=ward_key,
        province_key=lookup_prov_key,
    ) or _find_one(data.get("new", {}).get("wards", []), key=ward_key, province_key=lookup_prov_key) \
        or _find_one(data.get("new", {}).get("wards", []), key=ward_key)
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
