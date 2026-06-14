"""
sapo_client.py — Lớp gọi API Sapo cho dashboard "Báo cáo sáng".

Hỗ trợ 2 cách xác thực (đọc từ st.secrets HOẶC biến môi trường):
  - SAPO_COOKIE                      : chuỗi cookie phiên admin (giống script hiện tại)
  - SAPO_API_KEY + SAPO_API_SECRET   : Sapo Open API (Basic Auth) — tùy chọn

Nếu KHÔNG có credential nào -> raise SapoAuthError (app sẽ rơi về chế độ DEMO).
"""
from __future__ import annotations

import os
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
