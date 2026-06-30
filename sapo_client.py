"""
sapo_client.py — Lớp gọi API Sapo cho dashboard "Báo cáo sáng".

Hỗ trợ 2 cách xác thực (đọc từ st.secrets HOẶC biến môi trường):
  - SAPO_COOKIE                      : chuỗi cookie phiên admin (giống script hiện tại)
  - SAPO_API_KEY + SAPO_API_SECRET   : Sapo Open API (Basic Auth) — tùy chọn

Nếu KHÔNG có credential nào -> raise SapoAuthError (app sẽ rơi về chế độ DEMO).
"""
from __future__ import annotations

import os
import re
import requests

BASE = "https://vitranboutiquehcm.mysapo.net"


class SapoAuthError(RuntimeError):
    """Chưa cấu hình thông tin đăng nhập Sapo."""


def _get_secret(name: str) -> str | None:
    """Ưu tiên st.secrets (khi chạy trong Streamlit), fallback về biến môi trường."""
    try:
        import streamlit as st
        try:
            if name in st.secrets:
                return str(st.secrets[name])
        except Exception:
            # Không có file secrets.toml -> bỏ qua, dùng env
            pass
    except ModuleNotFoundError:
        pass
    return os.environ.get(name)


def credential_present() -> bool:
    """True nếu đã có đủ cookie HOẶC cặp api key/secret."""
    return bool(
        _get_secret("SAPO_COOKIE")
        or (_get_secret("SAPO_API_KEY") and _get_secret("SAPO_API_SECRET"))
    )


def build_session() -> requests.Session:
    """Tạo session đã gắn xác thực. Raise SapoAuthError nếu thiếu credential."""
    s = requests.Session()
    s.headers.update({"User-Agent": "Mozilla/5.0", "Accept": "application/json"})

    cookie = _get_secret("SAPO_COOKIE")
    key = _get_secret("SAPO_API_KEY")
    secret = _get_secret("SAPO_API_SECRET")

    if cookie:
        s.headers["Cookie"] = cookie
    elif key and secret:
        s.auth = (key, secret)  # Basic Auth cho Sapo Open API
    else:
        raise SapoAuthError(
            "Thiếu credential: cần SAPO_COOKIE hoặc SAPO_API_KEY + SAPO_API_SECRET."
        )
    return s


def make_fetch_json(session: requests.Session):
    """Trả về hàm fetch_json(path, **params) -> dict (đã raise_for_status)."""
    def fetch_json(path: str, **params):
        r = session.get(f"{BASE}{path}", params=params, timeout=30)
        r.raise_for_status()
        return r.json()
    return fetch_json


def _code_key(value) -> str:
    return re.sub(r"\s+", "", str(value or "")).upper()


def parse_codes(text: str) -> list[str]:
    """Tách danh sách mã đơn/mã trả hàng/mã vận đơn từ textarea."""
    seen, out = set(), []
    for raw in re.split(r"[\s,;]+", str(text or "")):
        code = _code_key(raw)
        if code and code not in seen:
            seen.add(code)
            out.append(code)
    return out


def _order_return_lookup_keys(row: dict) -> set[str]:
    order = row.get("order") or {}
    shipping = row.get("shipping_info") or {}
    keys = {
        row.get("id"),
        row.get("name"),
        row.get("code"),
        row.get("return_code"),
        order.get("id"),
        order.get("name"),
        order.get("code"),
        order.get("source_identifier"),
        shipping.get("tracking_number"),
    }
    keys.update(shipping.get("fulfillment_tracking_numbers") or [])
    return {_code_key(k) for k in keys if _code_key(k)}


def find_order_returns_by_codes(session: requests.Session, codes: list[str], max_pages: int = 80) -> dict[str, list[dict]]:
    """Dò phiếu trả hàng theo mã đơn/mã trả hàng/mã vận đơn. Trả về code -> list rows."""
    wanted = {_code_key(c) for c in codes if _code_key(c)}
    found = {c: [] for c in wanted}
    if not wanted:
        return found
    for page in range(1, int(max_pages) + 1):
        r = session.get(f"{BASE}/admin/order_returns.json", params={"limit": 250, "page": page}, timeout=30)
        r.raise_for_status()
        rows = r.json().get("order_returns", []) or []
        if not rows:
            break
        for row in rows:
            keys = _order_return_lookup_keys(row)
            matched = keys & wanted
            for code in matched:
                found[code].append(row)
    return found


def update_order_return_note(session: requests.Session, return_id, note: str) -> dict:
    """Cập nhật note phiếu trả hàng trên Sapo."""
    path = f"{BASE}/admin/order_returns/{return_id}.json"
    payloads = (
        {"order_return": {"id": return_id, "note": note}},
        {"order_return": {"note": note}},
        {"note": note},
    )
    last = None
    for payload in payloads:
        r = session.put(path, json=payload, timeout=30)
        if r.status_code < 400:
            return r.json() if r.content else {}
        last = r
        if r.status_code not in (400, 422):
            break
    if last is not None:
        last.raise_for_status()
    return {}
