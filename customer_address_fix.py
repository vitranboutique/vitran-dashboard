from __future__ import annotations

import json
import re
import unicodedata
from collections import defaultdict
from functools import lru_cache
from pathlib import Path


FIXABLE_CATEGORIES = ("sdt_sai", "thieu_ma_tinh", "thieu_ca_2", "thieu_sdt", "thieu_ma_phuong")
FIX_VERSION = "2026-07-11-customer-fix-buttons-v3"

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


def _distinct_ward_items(items: list[tuple[int, dict]]) -> list[tuple[int, dict]]:
    seen = set()
    out = []
    for score, ward in items:
        code = str(ward.get("code") or "")
        fmt = str(ward.get("_format") or "")
        key = (fmt, code)
        if key in seen:
            continue
        seen.add(key)
        out.append((score, ward))
    return out


def best_unique_ward(items: list[tuple[int, dict]]) -> tuple[int, dict] | None:
    return best_unique(_distinct_ward_items(items))


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


def _key_present_with_boundary(key: str, address_key: str) -> bool:
    if not key:
        return False
    if key[-1:].isdigit():
        return re.search(re.escape(key) + r"(?!\d)", address_key) is not None
    return key in address_key


def loose_name_present(row: dict, address_key: str, address_words: str, min_len: int = 4) -> bool:
    if phrase_present(row.get("name", ""), address_words):
        return True
    for key in row_key_variants(row):
        if len(key) >= min_len and _key_present_with_boundary(key, address_key):
            return True
    return False


def component_name_present(row: dict, parts: list[str], kind: str) -> bool:
    row_keys = row_key_variants(row)
    for part in parts:
        keys = component_keys(part, kind)
        if row_keys & keys:
            return True
    return False


def province_hint(row: dict, address_key: str, address_words: str) -> bool:
    if province_present(row, address_key, address_words):
        return True
    aliases = {
        "HOCHIMINH": ("TPHCM", "HCM", "SAIGON"),
        "HANOI": ("HN",),
        "HUE": ("TTHUE", "THUATHIENHUE"),
    }
    for key in row_key_variants(row):
        for alias in aliases.get(key, ()):
            if len(alias) <= 2:
                if f" {alias} " in f" {address_words} ":
                    return True
            elif alias in address_key:
                return True
    return False


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


def relaxed_tail_match(address: str) -> dict | None:
    data = address_codes()
    idx = indexes()
    parts = meaningful_parts(address)
    if len(parts) < 3:
        return None

    # Try several tail windows because Sapo/TikTok text often has duplicated
    # ward/province pieces or a trailing "Viet Nam" fragment that was not clean.
    old_matches = []
    for start in range(max(0, len(parts) - 6), max(0, len(parts) - 2)):
        tail = parts[start:]
        if len(tail) < 3:
            continue
        ward_part, district_part, province_part = tail[-3], tail[-2], tail[-1]
        province_keys = component_keys(province_part, "province")
        district_keys = component_keys(district_part, "district")
        ward_keys = component_keys(ward_part, "ward")
        for province in data.get("old", {}).get("provinces", []):
            if not (row_key_variants(province) & province_keys):
                continue
            for district in idx["old_districts_by_province"].get(province.get("key"), []):
                if not (row_key_variants(district) & district_keys):
                    continue
                for ward in idx["old_wards_by_province_district"].get((province.get("key"), district.get("key")), []):
                    if row_key_variants(ward) & ward_keys:
                        old_matches.append((920 + len(ward_keys), ward))
    old_best = best_unique_ward(old_matches)
    if old_best:
        return _ward_result(old_best[1], "old", old_best[0], "relaxed_tail_old")

    new_matches = []
    for start in range(max(0, len(parts) - 5), max(0, len(parts) - 1)):
        tail = parts[start:]
        if len(tail) < 2:
            continue
        ward_part, province_part = tail[-2], tail[-1]
        if starts_with_admin_prefix(province_part, ("HUYEN", "QUAN", "DISTRICT", "H", "Q", "THI XA", "TX")):
            continue
        province_keys = component_keys(province_part, "province")
        ward_keys = component_keys(ward_part, "ward")
        for province in data.get("new", {}).get("provinces", []):
            if not (row_key_variants(province) & province_keys):
                continue
            for ward in idx["new_wards_by_province"].get(province.get("key"), []):
                if row_key_variants(ward) & ward_keys:
                    new_matches.append((910 + len(ward_keys), ward))
    new_best = best_unique_ward(new_matches)
    if new_best:
        return _ward_result(new_best[1], "new", new_best[0], "relaxed_tail_new")
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


def unique_component_text_match(address: str) -> dict | None:
    data = address_codes()
    idx = indexes()
    address_key = compact(address)
    address_words = words(address)
    parts = meaningful_parts(address)
    hinted_old_provinces = {
        province.get("key")
        for province in data.get("old", {}).get("provinces", [])
        if province_hint(province, address_key, address_words)
    }

    old_matches = []
    for province in data.get("old", {}).get("provinces", []):
        if hinted_old_provinces and province.get("key") not in hinted_old_provinces:
            continue
        has_province = province.get("key") in hinted_old_provinces
        for district in idx["old_districts_by_province"].get(province.get("key"), []):
            d_pref = district_prefixed(district, address_key)
            d_component = component_name_present(district, parts, "district")
            d_loose = d_pref or d_component or (has_province and loose_name_present(district, address_key, address_words, min_len=4))
            if not d_loose:
                continue
            for ward in idx["old_wards_by_province_district"].get((province.get("key"), district.get("key")), []):
                w_pref = ward_prefixed(ward, address_key)
                w_loose = w_pref or (has_province and loose_name_present(ward, address_key, address_words, min_len=4))
                if not w_loose:
                    continue
                # This relaxed branch is allowed to infer a missing province,
                # but it still needs an explicit ward marker. Otherwise shop,
                # street, and industrial-zone names can look like wards.
                if not w_pref:
                    continue
                if not has_province and not (d_loose and (d_pref or d_component)):
                    continue
                score = 0
                score += 80 if has_province else 0
                score += 45 if d_pref else 25
                score += 45 if w_pref else 25
                score += len(bare_key(province.get("name"))) + len(bare_key(district.get("name"))) + len(bare_key(ward.get("name")))
                old_matches.append((score, {**ward, "_format": "old"}))
    old_best = best_unique_ward(old_matches)
    if old_best and old_best[0] >= 70:
        return _ward_result(old_best[1], "old", old_best[0], "text_old_unique")

    new_matches = []
    hinted_new_provinces = {
        province.get("key")
        for province in data.get("new", {}).get("provinces", [])
        if province_hint(province, address_key, address_words)
    }
    for province in data.get("new", {}).get("provinces", []):
        if province.get("key") not in hinted_new_provinces:
            continue
        for ward in idx["new_wards_by_province"].get(province.get("key"), []):
            w_pref = ward_prefixed(ward, address_key)
            if not w_pref:
                continue
            score = 125 + len(bare_key(province.get("name"))) + len(bare_key(ward.get("name")))
            new_matches.append((score, {**ward, "_format": "new"}))
    new_best = best_unique_ward(new_matches)
    if new_best and new_best[0] >= 100:
        return _ward_result(new_best[1], "new", new_best[0], "text_new_unique")
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
    match = exact_component_match(text) or relaxed_tail_match(text) or strict_text_match(text) or unique_component_text_match(text)
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


def normalize_phone_strict(value: str) -> str:
    """Return a Sapo-safe VN phone only when the source is clearly repairable."""
    raw = str(value or "").strip()
    if not raw or "*" in raw:
        return ""
    digits = re.sub(r"\D+", "", raw)
    if raw.startswith("+84") and len(digits) == 11 and digits.startswith("84"):
        return "+84" + digits[2:]
    if digits.startswith("0084") and len(digits) == 13:
        return "+84" + digits[4:]
    if digits.startswith("840") and len(digits) == 12:
        rest = digits[3:]
        return "+84" + rest if len(rest) == 9 else ""
    if digits.startswith("84") and len(digits) == 11:
        return "+84" + digits[2:]
    if digits.startswith("00") and len(digits) == 11:
        fixed = "0" + digits[2:]
        return fixed if re.match(r"^0\d{9}$", fixed) else ""
    if digits.startswith("0") and len(digits) == 10:
        return digits
    return ""


def phone_core(value: str) -> str:
    fixed = normalize_phone_strict(value)
    return fixed[-9:] if fixed else ""


def phone_format_bad(value: str) -> bool:
    value = str(value or "").strip()
    if not value or "*" in value:
        return False
    return not (re.match(r"^0\d{9}$", value) or re.match(r"^\+84\d{9}$", value))


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


def customer_name(customer: dict) -> str:
    return str(
        customer.get("name")
        or f"{customer.get('first_name') or ''} {customer.get('last_name') or ''}".strip()
        or ""
    ).strip()


def address_code_value(addr: dict, *keys: str) -> str:
    for key in keys:
        value = str((addr or {}).get(key) or "").strip()
        if value:
            return value
    return ""


def structured_info_from_existing(customer: dict, phone: str) -> dict | None:
    addr = primary_address(customer)
    province_code = address_code_value(addr, "province_code", "province_id", "city_id", "municipality_id")
    ward_code = address_code_value(addr, "ward_code", "ward_id", "commune_code", "commune_id", "location_id", "new_ward_id")
    if not province_code and not ward_code:
        return None
    district_code = address_code_value(addr, "district_code", "district_id")
    return {
        "name": customer_name(customer),
        "phone": phone,
        "address1": str(addr.get("address1") or full_address_text(addr)).strip()[:255],
        "address_format": "old" if district_code else "new",
        "province": str(addr.get("province_name") or addr.get("province") or addr.get("city") or "").strip(),
        "province_code": province_code,
        "district": str(addr.get("district_name") or addr.get("district") or "").strip(),
        "district_code": district_code,
        "ward": str(addr.get("ward_name") or addr.get("ward") or "").strip(),
        "ward_code": ward_code,
    }


def resolved_info_from_text(customer: dict, phone: str) -> dict:
    addr = primary_address(customer)
    text = full_address_text(addr)
    resolved = resolve_text_address(text)
    if not resolved.get("ok"):
        return {**resolved, "source_address": text}

    address1 = str(addr.get("address1") or text).strip()
    if len(address1) > 255:
        address1 = address1[:255]
    info = {
        "name": customer_name(customer),
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


def customer_fix_info(customer: dict, category: str) -> dict:
    if category not in FIXABLE_CATEGORIES:
        return {"ok": False, "reason": "unsupported_category"}
    if not isinstance(customer, dict) or not customer.get("id"):
        return {"ok": False, "reason": "bad_customer"}

    addr = primary_address(customer)
    text = full_address_text(addr)
    addr_raw = addr.get("phone") or addr.get("phone_number") or addr.get("mobile")
    contact_raw = customer.get("phone") or customer.get("phone_number") or customer.get("mobile")
    addr_phone = normalize_phone(addr_raw)
    contact_phone = normalize_phone(contact_raw)
    phone = addr_phone or contact_phone

    if category == "sdt_sai":
        candidates = []
        for raw in (contact_raw, addr_raw):
            fixed = normalize_phone_strict(raw)
            if fixed:
                candidates.append(fixed)
        cores = {phone_core(p) for p in candidates if phone_core(p)}
        if not cores:
            return {"ok": False, "reason": "no_valid_phone", "source_address": text}
        if len(cores) > 1:
            return {"ok": False, "reason": "phone_conflict", "source_address": text}
        phone = candidates[0]
        existing = structured_info_from_existing(customer, phone)
        if existing:
            existing["require_contact_phone"] = phone_format_bad(contact_raw)
            return {"ok": True, "info": existing, "source_address": text}
        resolved = resolved_info_from_text(customer, phone)
        if resolved.get("ok"):
            resolved["info"]["require_contact_phone"] = phone_format_bad(contact_raw)
            return resolved
        if text:
            return resolved
        return {
            "ok": True,
            "info": {
                "name": customer_name(customer),
                "phone": phone,
                "phone_only": True,
                "require_contact_phone": True,
            },
            "source_address": text,
        }

    if category == "thieu_sdt":
        phone = normalize_phone_strict(contact_raw) or normalize_phone(contact_raw)
        if not phone:
            return {"ok": False, "reason": "no_valid_phone", "source_address": text}
        existing = structured_info_from_existing(customer, phone)
        if existing and existing.get("province_code") and existing.get("ward_code"):
            return {"ok": True, "info": existing, "source_address": text}
        return resolved_info_from_text(customer, phone)

    if not phone:
        return {"ok": False, "reason": "no_valid_phone", "source_address": text}
    return resolved_info_from_text(customer, phone)
