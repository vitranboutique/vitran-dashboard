from __future__ import annotations

import json
import re
import unicodedata
from collections import defaultdict
from functools import lru_cache
from pathlib import Path


FIXABLE_CATEGORIES = ("thieu_ma_tinh", "thieu_ca_2")

ADMIN_PREFIXES = (
    "THANH PHO",
    "TINH",
    "QUAN",
    "HUYEN",
    "THI XA",
    "THI TRAN",
    "PHUONG",
    "XA",
    "TP",
    "TX",
    "TT",
    "P",
    "X",
    "H",
    "Q",
    "WARD",
    "DISTRICT",
    "CITY",
    "PROVINCE",
    "COMMUNE",
    "TOWN",
    "TOWNSHIP",
)


def strip_marks(value: str) -> str:
    value = str(value or "").replace("Đ", "D").replace("đ", "d")
    value = unicodedata.normalize("NFD", value)
    return "".join(ch for ch in value if unicodedata.category(ch) != "Mn")


def words(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", " ", strip_marks(value)).upper().strip()


def compact(value: str) -> str:
    return re.sub(r"[^A-Z0-9]+", "", words(value))


def bare_words(name: str) -> str:
    out = words(name)
    changed = True
    while changed:
        changed = False
        for prefix in ADMIN_PREFIXES:
            if out == prefix:
                return ""
            if out.startswith(prefix + " "):
                out = out[len(prefix) + 1 :].strip()
                changed = True
                break
    return out


def bare_key(name: str) -> str:
    return compact(bare_words(name))


def key_variants(value: str) -> set[str]:
    out = {bare_key(value), compact(value)}
    variants = set()
    for item in out:
        if item:
            variants.add(item)
            if "D" in item:
                variants.add(item.replace("D", ""))
    return variants


def row_key_variants(row: dict) -> set[str]:
    return key_variants(row.get("name") or "") | key_variants(row.get("key") or "")


def phrase_present(name: str, address_words: str) -> bool:
    phrase = bare_words(name)
    key = compact(phrase)
    if not key or len(key) <= 2:
        return False
    return f" {phrase} " in f" {address_words} "


def prefixed_compact_present(prefixes: tuple[str, ...], name: str, address_key: str) -> bool:
    keys = key_variants(name)
    for key in keys:
        if not key:
            continue
        for prefix in prefixes:
            pattern = prefix + key
            if key[-1:].isdigit():
                if re.search(re.escape(pattern) + r"(?!\d)", address_key):
                    return True
            elif pattern in address_key:
                return True
    return False


def province_present(row: dict, address_key: str, address_words: str) -> bool:
    aliases = {
        "HOCHIMINH": ("TPHCM", "HCM", "SAIGON"),
        "HANOI": ("HN",),
    }
    keys = row_key_variants(row)
    if any(alias in address_key for key in keys for alias in aliases.get(key, ())):
        return True
    if any((prefix + key) in address_key for key in keys for prefix in ("TINH", "TP", "THANHPHO", "CITY", "PROVINCE")):
        return True
    return phrase_present(row.get("name", ""), address_words)


def district_prefixed(row: dict, address_key: str) -> bool:
    return prefixed_compact_present(
        ("HUYEN", "QUAN", "THIXA", "THANHPHO", "DISTRICT", "H", "Q", "TX", "TP"),
        row.get("name", ""),
        address_key,
    )


def ward_prefixed(row: dict, address_key: str) -> bool:
    return prefixed_compact_present(
        ("PHUONG", "XA", "THITRAN", "WARD", "COMMUNE", "P", "X", "TT"),
        row.get("name", ""),
        address_key,
    )


def meaningful_parts(address: str) -> list[str]:
    ignore = {"VIET NAM", "VIETNAM", "VN", "DOI", "DOI TRA"}
    parts = []
    for raw in re.split(r"[,，]", address or ""):
        part = raw.strip(" \t\r\n-()[]")
        if not part:
            continue
        if words(part) in ignore:
            continue
        parts.append(part)
    return parts


def component_keys(part: str, kind: str) -> set[str]:
    out = set(key_variants(part))
    normalized = words(part)
    if kind == "ward":
        prefixes = ("PHUONG", "WARD", "P", "XA", "X", "THI TRAN", "TT", "COMMUNE")
    elif kind == "district":
        prefixes = ("HUYEN", "QUAN", "DISTRICT", "H", "Q", "THANH PHO", "THI XA", "TP", "TX")
    else:
        prefixes = ("TINH", "TP", "THANH PHO", "CITY", "PROVINCE")
    prefix_expr = "|".join(re.escape(prefix) for prefix in sorted(prefixes, key=len, reverse=True))
    for match in re.finditer(rf"(?:^|\s)(?:{prefix_expr})\s+([A-Z0-9]+(?:\s+[A-Z0-9]+){{0,5}})", normalized):
        tokens = match.group(1).split()
        for end in range(1, len(tokens) + 1):
            out.update(key_variants(" ".join(tokens[:end])))
    return {x for x in out if x}


def starts_with_admin_prefix(part: str, prefixes: tuple[str, ...]) -> bool:
    normalized = words(part)
    return any(normalized == prefix or normalized.startswith(prefix + " ") for prefix in prefixes)


@lru_cache(maxsize=1)
def address_codes() -> dict:
    path = Path(__file__).with_name("data") / "sapo_address_codes.json"
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {"old": {"provinces": [], "districts": [], "wards": []}, "new": {"provinces": [], "wards": []}}


@lru_cache(maxsize=1)
def indexes() -> dict:
    data = address_codes()
    old_districts_by_province = defaultdict(list)
    old_wards_by_province_district = defaultdict(list)
    new_wards_by_province = defaultdict(list)

    for district in data.get("old", {}).get("districts", []):
        old_districts_by_province[district.get("province_key")].append(district)
    for ward in data.get("old", {}).get("wards", []):
        old_wards_by_province_district[(ward.get("province_key"), ward.get("district_key"))].append(ward)
    for ward in data.get("new", {}).get("wards", []):
        new_wards_by_province[ward.get("province_key")].append(ward)

    return {
        "old_districts_by_province": old_districts_by_province,
        "old_wards_by_province_district": old_wards_by_province_district,
        "new_wards_by_province": new_wards_by_province,
    }


def best_unique(items: list[tuple[int, dict]]) -> tuple[int, dict] | None:
    if not items:
        return None
    items = sorted(items, key=lambda item: item[0], reverse=True)
    if len(items) > 1 and items[0][0] == items[1][0]:
        return None
    return items[0]


def _ward_result(ward: dict, fmt: str, confidence: int, source: str) -> dict:
    return {
        "ok": True,
        "format": fmt,
        "address_format": fmt,
        "province": ward.get("province") or "",
        "province_code": str(ward.get("province_code") or ""),
        "district": "" if fmt == "new" else ward.get("district") or "",
        "district_code": "" if fmt == "new" else str(ward.get("district_code") or ""),
        "ward": ward.get("name") or "",
        "ward_code": str(ward.get("code") or ""),
        "confidence": confidence,
        "match_source": source,
    }


def exact_component_match(address: str) -> dict | None:
    data = address_codes()
    idx = indexes()
    parts = meaningful_parts(address)
    if len(parts) >= 3:
        ward_part, district_part, province_part = parts[-3], parts[-2], parts[-1]
        province_keys = component_keys(province_part, "province")
        district_keys = component_keys(district_part, "district")
        ward_keys = component_keys(ward_part, "ward")
        old_matches = []
        for province in data.get("old", {}).get("provinces", []):
            if not (row_key_variants(province) & province_keys):
                continue
            for district in idx["old_districts_by_province"].get(province.get("key"), []):
                if not (row_key_variants(district) & district_keys):
                    continue
                for ward in idx["old_wards_by_province_district"].get((province.get("key"), district.get("key")), []):
                    if row_key_variants(ward) & ward_keys:
                        old_matches.append(ward)
        if len(old_matches) == 1:
            return _ward_result(old_matches[0], "old", 999, "comma_tail_old")

    if len(parts) >= 2:
        if len(parts) >= 3 and starts_with_admin_prefix(
            parts[-2],
            ("HUYEN", "QUAN", "DISTRICT", "H", "Q", "THANH PHO", "THI XA", "TP", "TX"),
        ):
            return None
        ward_part, province_part = parts[-2], parts[-1]
        province_keys = component_keys(province_part, "province")
        ward_keys = component_keys(ward_part, "ward")
        new_matches = []
        for province in data.get("new", {}).get("provinces", []):
            if not (row_key_variants(province) & province_keys):
                continue
            for ward in idx["new_wards_by_province"].get(province.get("key"), []):
                if row_key_variants(ward) & ward_keys:
                    new_matches.append(ward)
        if len(new_matches) == 1:
            return _ward_result(new_matches[0], "new", 998, "comma_tail_new")
    return None


def strict_text_match(address: str) -> dict | None:
    data = address_codes()
    idx = indexes()
    address_key = compact(address)
    address_words = words(address)

    old_matches = []
    for province in data.get("old", {}).get("provinces", []):
        if not province_present(province, address_key, address_words):
            continue
        for district in idx["old_districts_by_province"].get(province.get("key"), []):
            if not district_prefixed(district, address_key):
                continue
            for ward in idx["old_wards_by_province_district"].get((province.get("key"), district.get("key")), []):
                if not ward_prefixed(ward, address_key):
                    continue
                score = len(bare_key(province.get("name"))) + len(bare_key(district.get("name"))) + len(bare_key(ward.get("name")))
                old_matches.append((score, ward))
    old_best = best_unique(old_matches)
    if old_best:
        return _ward_result(old_best[1], "old", old_best[0], "text_old_strict")

    if re.search(r"\b(QUAN|HUYEN|DISTRICT|THI\s+XA|TX)\b", address_words):
        return None

    new_matches = []
    for province in data.get("new", {}).get("provinces", []):
        if not province_present(province, address_key, address_words):
            continue
        for ward in idx["new_wards_by_province"].get(province.get("key"), []):
            if not ward_prefixed(ward, address_key):
                continue
            score = len(bare_key(province.get("name"))) + len(bare_key(ward.get("name")))
            new_matches.append((score, ward))
    new_best = best_unique(new_matches)
    if new_best:
        return _ward_result(new_best[1], "new", new_best[0], "text_new_strict")
    return None


def explicit_conflict(address: str, match: dict) -> str:
    data = address_codes()
    idx = indexes()
    address_key = compact(address)
    conflicts = []
    matched_ward_code = str(match.get("ward_code") or "")
    if match.get("format") == "old":
        for province_key in key_variants(match.get("province")):
            for district_key in key_variants(match.get("district")):
                for ward in idx["old_wards_by_province_district"].get((province_key, district_key), []):
                    if str(ward.get("code") or "") == matched_ward_code:
                        continue
                    if ward_prefixed(ward, address_key):
                        conflicts.append(f"{ward.get('name')} / {ward.get('district')} / {ward.get('province')}")
    else:
        province_keys = key_variants(match.get("province"))
        matched_key = bare_key(match.get("ward"))
        for province_key in province_keys:
            for ward in idx["new_wards_by_province"].get(province_key, []):
                if str(ward.get("code") or "") == matched_ward_code:
                    continue
                if ward_prefixed(ward, address_key):
                    conflicts.append(f"{ward.get('name')} / {ward.get('province')}")
        for ward in data.get("old", {}).get("wards", []):
            if ward.get("province_key") not in province_keys:
                continue
            if bare_key(ward.get("name")) == matched_key:
                continue
            if ward_prefixed(ward, address_key):
                conflicts.append(f"{ward.get('name')} / {ward.get('district')} / {ward.get('province')}")
    if conflicts:
        return "; ".join(conflicts[:3])
    return ""


def resolve_text_address(address: str) -> dict:
    text = str(address or "").strip()
    if not text:
        return {"ok": False, "reason": "no_address"}
    match = exact_component_match(text) or strict_text_match(text)
    if not match:
        return {"ok": False, "reason": "address_unresolved"}
    conflict = explicit_conflict(text, match)
    if conflict:
        return {**match, "ok": False, "reason": "address_conflict", "conflict": conflict}
    return match


def normalize_phone(value: str) -> str:
    raw = str(value or "").strip()
    if not raw or "*" in raw:
        return ""
    if re.match(r"^0\d{9}$", raw) or re.match(r"^\+84\d{9}$", raw):
        return raw
    digits = re.sub(r"\D+", "", raw)
    if digits.startswith("00"):
        digits = digits[2:]
    if digits.startswith("84") and len(digits) == 11:
        return "+84" + digits[2:]
    digits = "0" + digits.lstrip("0")
    return digits if re.match(r"^0\d{9}$", digits) else ""


def primary_address(customer: dict) -> dict:
    addr = customer.get("default_address") if isinstance(customer, dict) else {}
    if isinstance(addr, dict) and (addr.get("address1") or addr.get("id")):
        return addr
    for item in (customer.get("addresses") or [] if isinstance(customer, dict) else []):
        if isinstance(item, dict) and (item.get("address1") or item.get("id")):
            return item
    return {}


def full_address_text(addr: dict) -> str:
    seen = set()
    parts = []
    for key in ("address1", "ward_name", "ward", "district_name", "district", "province_name", "province", "city"):
        value = str((addr or {}).get(key) or "").strip()
        if value and value not in seen:
            seen.add(value)
            parts.append(value)
    return ", ".join(parts)


def customer_fix_info(customer: dict, category: str) -> dict:
    if category not in FIXABLE_CATEGORIES:
        return {"ok": False, "reason": "unsupported_category"}
    if not isinstance(customer, dict) or not customer.get("id"):
        return {"ok": False, "reason": "bad_customer"}

    addr = primary_address(customer)
    text = full_address_text(addr)
    resolved = resolve_text_address(text)
    if not resolved.get("ok"):
        return resolved

    addr_phone = normalize_phone(addr.get("phone") or addr.get("phone_number") or addr.get("mobile"))
    contact_phone = normalize_phone(customer.get("phone") or customer.get("phone_number") or customer.get("mobile"))
    phone = addr_phone or contact_phone
    if category == "thieu_ca_2" and not phone:
        return {"ok": False, "reason": "no_valid_phone"}
    if not phone:
        return {"ok": False, "reason": "no_valid_phone"}

    name = str(customer.get("name") or f"{customer.get('first_name') or ''} {customer.get('last_name') or ''}".strip()).strip()
    address1 = str(addr.get("address1") or text).strip()
    if len(address1) > 255:
        address1 = address1[:255]

    info = {
        "name": name,
        "phone": phone,
        "address1": address1,
        "address_format": resolved.get("format"),
        "province": resolved.get("province"),
        "province_code": str(resolved.get("province_code") or ""),
        "district": resolved.get("district") or "",
        "district_code": str(resolved.get("district_code") or ""),
        "ward": resolved.get("ward"),
        "ward_code": str(resolved.get("ward_code") or ""),
    }
    return {"ok": True, "info": info, "resolved": resolved, "source_address": text}
