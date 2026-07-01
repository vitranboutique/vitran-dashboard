"""
sapo_client.py — Lớp gọi API Sapo cho dashboard "Báo cáo sáng".

Hỗ trợ 2 cách xác thực (đọc từ st.secrets HOẶC biến môi trường):
  - SAPO_COOKIE                      : chuỗi cookie phiên admin (giống script hiện tại)
  - SAPO_API_KEY + SAPO_API_SECRET   : Sapo Open API (Basic Auth) — tùy chọn

Nếu KHÔNG có credential nào -> raise SapoAuthError (app sẽ rơi về chế độ DEMO).
"""
from __future__ import annotations

from html import unescape
from html.parser import HTMLParser
import os
import re
import time
from urllib.parse import urljoin
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
    """True nếu đã có token, cookie HOẶC cặp api key/secret."""
    return bool(
        _get_secret("SAPO_ACCESS_TOKEN")
        or _get_secret("SAPO_TOKEN")
        or _get_secret("SAPO_COOKIE")
        or (_get_secret("SAPO_API_KEY") and _get_secret("SAPO_API_SECRET"))
    )


def build_session() -> requests.Session:
    """Tạo session đã gắn xác thực. Raise SapoAuthError nếu thiếu credential."""
    s = requests.Session()
    s.headers.update({"User-Agent": "Mozilla/5.0", "Accept": "application/json"})

    cookie = _get_secret("SAPO_COOKIE")
    token = _get_secret("SAPO_ACCESS_TOKEN") or _get_secret("SAPO_TOKEN")
    key = _get_secret("SAPO_API_KEY")
    secret = _get_secret("SAPO_API_SECRET")

    if token:
        s.headers["X-Sapo-Access-Token"] = token
    elif cookie:
        s.headers["Cookie"] = cookie
    elif key and secret:
        s.auth = (key, secret)  # Basic Auth cho Sapo Open API
    else:
        raise SapoAuthError(
            "Thiếu credential: cần SAPO_ACCESS_TOKEN, SAPO_COOKIE hoặc SAPO_API_KEY + SAPO_API_SECRET."
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


def _json_or_empty(resp: requests.Response) -> dict:
    try:
        return resp.json() if resp.content else {}
    except Exception:
        return {}


def _note_payloads(return_id, note: str) -> list[dict]:
    return [
        {"order_return": {"id": return_id, "note": note}},
        {"order_return": {"note": note}},
        {"note": note},
    ]


def _attempt_desc(resp: requests.Response) -> str:
    req = resp.request
    return f"{req.method} {req.url} -> {resp.status_code}"


def get_order_return(session: requests.Session, return_id) -> dict:
    """Lấy chi tiết hồ sơ trả hàng theo id."""
    resp = session.get(f"{BASE}/admin/order_returns/{return_id}.json", timeout=30)
    resp.raise_for_status()
    data = _json_or_empty(resp)
    return data.get("order_return") or data.get("return") or data


def get_order(session: requests.Session, order_id) -> dict:
    """Lấy chi tiết đơn hàng theo id."""
    resp = session.get(f"{BASE}/admin/orders/{order_id}.json", timeout=30)
    resp.raise_for_status()
    data = _json_or_empty(resp)
    return data.get("order") or data


def get_customer(session: requests.Session, customer_id) -> dict:
    """Lấy chi tiết khách hàng theo id."""
    resp = session.get(f"{BASE}/admin/customers/{customer_id}.json", timeout=30)
    resp.raise_for_status()
    data = _json_or_empty(resp)
    return data.get("customer") or data


def _saved_order_note(session: requests.Session, order_id, expected_note: str, attempts: list[str]) -> bool:
    expected = str(expected_note or "").strip()
    if not expected:
        return False
    time.sleep(0.15)
    try:
        row = get_order(session, order_id)
        saved = str(row.get("note") or "").strip()
        attempts.append(f"GET order verify -> {bool(saved)}")
        return saved == expected or expected in saved
    except Exception as e:
        attempts.append(f"GET order verify -> {type(e).__name__}: {e}")
        return False


def update_order_note(session: requests.Session, order_id, note: str) -> dict:
    """Cập nhật ghi chú đơn hàng SAPO và đọc lại để xác nhận đã lưu."""
    attempts = []
    page_url = f"{BASE}/admin/orders/{order_id}"
    token = _page_csrf_token(session, page_url, attempts)
    paths = [
        f"{BASE}/admin/orders/{order_id}.json",
        page_url,
    ]
    payloads = [
        {"order": {"id": order_id, "note": note}},
        {"order": {"note": note}},
        {"note": note},
    ]
    for path in paths:
        for method in ("put", "patch", "post"):
            for payload in payloads:
                resp = getattr(session, method)(
                    path,
                    json=payload,
                    headers=_json_headers(page_url, token),
                    timeout=30,
                    allow_redirects=False,
                )
                attempts.append(_attempt_desc(resp))
                if resp.status_code < 400 and _saved_order_note(session, order_id, note, attempts):
                    return _json_or_empty(resp)
        for data in (
            {"_method": "put", "order[note]": note},
            {"_method": "patch", "order[note]": note},
            {"order[note]": note},
            {"note": note},
        ):
            resp = session.post(
                path,
                data=data,
                headers=_json_headers(page_url, token),
                timeout=30,
                allow_redirects=False,
            )
            attempts.append(_attempt_desc(resp))
            if resp.status_code < 400 and _saved_order_note(session, order_id, note, attempts):
                return _json_or_empty(resp)
    tail = "; ".join(attempts[-16:])
    raise RuntimeError(f"SAPO có phản hồi nhưng đọc lại chưa thấy ghi chú được lưu cho đơn {order_id}. Đã thử: {tail}")


def _saved_order_customer_info(session: requests.Session, order_id, info: dict, expected_note: str, attempts: list[str], customer_id=None) -> bool:
    try:
        row = get_order(session, order_id)
        addr = row.get("shipping_address") or {}
        saved_note = str(row.get("note") or "")
        saved_phone = re.sub(r"\D+", "", str(addr.get("phone") or addr.get("phone_number") or ""))
        expected_phone = re.sub(r"\D+", "", str(info.get("phone") or ""))
        attempts.append(f"GET order customer verify -> phone:{bool(saved_phone)} note:{bool(saved_note)}")
        phone_ok = expected_phone and (saved_phone.endswith(expected_phone[-9:]) or expected_phone.endswith(saved_phone[-9:]))
        note_ok = (not expected_note) or expected_note.strip() in saved_note or saved_note.strip() == expected_note.strip()
        customer_ok = True
        linked_customer_id = (row.get("customer") or {}).get("id") if isinstance(row.get("customer"), dict) else row.get("customer_id")
        linked_ok = (not customer_id) or (str(linked_customer_id or "") == str(customer_id))
        check_customer_id = linked_customer_id or customer_id
        if check_customer_id:
            try:
                customer_ok = _customer_phone_saved(get_customer(session, check_customer_id), info.get("phone"))
                attempts.append(f"GET linked customer verify -> linked:{linked_ok} phone:{customer_ok}")
            except Exception as e:
                customer_ok = False
                attempts.append(f"GET linked customer verify -> {type(e).__name__}: {e}")
        return bool(phone_ok and note_ok and linked_ok and customer_ok)
    except Exception as e:
        attempts.append(f"GET order customer verify -> {type(e).__name__}: {e}")
        return False


def _customer_payload(customer_id, info: dict, note: str) -> dict:
    name = str(info.get("name") or "").strip()
    parts = name.split()
    first_name = parts[0] if parts else name
    last_name = " ".join(parts[1:]) if len(parts) > 1 else ""
    address = {
        "name": name,
        "phone": info.get("phone") or "",
        "address1": info.get("address1") or "",
        "ward": info.get("ward") or "",
        "district": info.get("district") or "",
        "province": info.get("province") or "",
        "city": info.get("province") or "",
        "country": "Vietnam",
        "default": True,
    }
    customer = {
        "first_name": first_name,
        "last_name": last_name,
        "name": name,
        "phone": info.get("phone") or "",
        "note": note,
        "addresses": [address],
        "default_address": address,
    }
    if customer_id:
        customer["id"] = customer_id
    return {"customer": customer}


def _customer_phone_saved(customer: dict, expected_phone: str) -> bool:
    expected = re.sub(r"\D+", "", str(expected_phone or ""))
    phones = [customer.get("phone"), customer.get("mobile"), customer.get("phone_number")]
    for addr in (customer.get("addresses") or []):
        if isinstance(addr, dict):
            phones.extend([addr.get("phone"), addr.get("mobile"), addr.get("phone_number")])
    default_addr = customer.get("default_address") or {}
    if isinstance(default_addr, dict):
        phones.extend([default_addr.get("phone"), default_addr.get("mobile"), default_addr.get("phone_number")])
    for phone in phones:
        saved = re.sub(r"\D+", "", str(phone or ""))
        if expected and saved and (saved.endswith(expected[-9:]) or expected.endswith(saved[-9:])):
            return True
    return False


def _upsert_customer_info(session: requests.Session, order: dict, info: dict, note: str, attempts: list[str]):
    customer = order.get("customer") if isinstance(order.get("customer"), dict) else {}
    customer_id = customer.get("id") or order.get("customer_id")
    token = _page_csrf_token(session, f"{BASE}/admin/customers/{customer_id}" if customer_id else f"{BASE}/admin/customers", attempts)
    if customer_id:
        url = f"{BASE}/admin/customers/{customer_id}.json"
        for method in ("put", "patch"):
            resp = getattr(session, method)(
                url,
                json=_customer_payload(customer_id, info, note),
                headers=_json_headers(f"{BASE}/admin/customers/{customer_id}", token),
                timeout=30,
                allow_redirects=False,
            )
            attempts.append(_attempt_desc(resp))
            if resp.status_code < 400:
                try:
                    saved = get_customer(session, customer_id)
                    attempts.append("GET customer verify -> ok")
                    if _customer_phone_saved(saved, info.get("phone")):
                        return customer_id
                except Exception as e:
                    attempts.append(f"GET customer verify -> {type(e).__name__}: {e}")
    create_url = f"{BASE}/admin/customers.json"
    resp = session.post(
        create_url,
        json=_customer_payload(None, info, note),
        headers=_json_headers(f"{BASE}/admin/customers", token),
        timeout=30,
        allow_redirects=False,
    )
    attempts.append(_attempt_desc(resp))
    if resp.status_code < 400:
        data = _json_or_empty(resp)
        created = data.get("customer") or data
        new_id = created.get("id")
        if new_id:
            return new_id
    return customer_id


def update_order_customer_info(session: requests.Session, order_id, info: dict, note: str) -> dict:
    """Cập nhật thông tin giao hàng của đơn và ghi note đánh dấu đã lấy TTKH."""
    attempts = []
    page_url = f"{BASE}/admin/orders/{order_id}"
    token = _page_csrf_token(session, page_url, attempts)
    current_order = get_order(session, order_id)
    customer_note = f"TTKH từ sàn: {info.get('phone') or ''}".strip()
    customer_id = _upsert_customer_info(session, current_order, info, customer_note, attempts)
    shipping = {
        "name": info.get("name") or "",
        "phone": info.get("phone") or "",
        "address1": info.get("address1") or "",
        "ward": info.get("ward") or "",
        "district": info.get("district") or "",
        "province": info.get("province") or "",
        "city": info.get("province") or "",
        "country": "Vietnam",
    }
    order_payload = {
        "id": order_id,
        "note": note,
        "shipping_address": shipping,
        "shipping_address_attributes": shipping,
    }
    if customer_id:
        order_payload["customer_id"] = customer_id
        order_payload["customer"] = {"id": customer_id}
    paths = [f"{BASE}/admin/orders/{order_id}.json", page_url]
    payloads = [
        {"order": order_payload},
        {"order": {"note": note, "shipping_address": shipping}},
        {"order": {"note": note, "shipping_address_attributes": shipping}},
    ]
    if customer_id:
        payloads.append({"order": {"note": note, "customer_id": customer_id, "customer": {"id": customer_id}, "shipping_address": shipping}})
    for path in paths:
        for method in ("put", "patch", "post"):
            for payload in payloads:
                resp = getattr(session, method)(
                    path,
                    json=payload,
                    headers=_json_headers(page_url, token),
                    timeout=30,
                    allow_redirects=False,
                )
                attempts.append(_attempt_desc(resp))
                if resp.status_code < 400 and _saved_order_customer_info(session, order_id, info, note, attempts, customer_id):
                    return _json_or_empty(resp)
        form_data = {"_method": "put", "order[note]": note}
        if customer_id:
            form_data["order[customer_id]"] = customer_id
        for k, v in shipping.items():
            form_data[f"order[shipping_address][{k}]"] = v
            form_data[f"order[shipping_address_attributes][{k}]"] = v
        resp = session.post(
            path,
            data=form_data,
            headers=_json_headers(page_url, token),
            timeout=30,
            allow_redirects=False,
        )
        attempts.append(_attempt_desc(resp))
        if resp.status_code < 400 and _saved_order_customer_info(session, order_id, info, note, attempts, customer_id):
            return _json_or_empty(resp)
    tail = "; ".join(attempts[-16:])
    raise RuntimeError(f"SAPO có phản hồi nhưng đọc lại chưa thấy TTKH được lưu cho đơn {order_id}. Đã thử: {tail}")


def _saved_return_note(session: requests.Session, return_id, expected_note: str, attempts: list[str]) -> bool:
    expected = str(expected_note or "").strip()
    if not expected:
        return False
    time.sleep(0.15)
    try:
        resp = session.get(f"{BASE}/admin/order_returns/{return_id}.json", timeout=30)
        attempts.append(_attempt_desc(resp))
        if resp.status_code < 400:
            data = _json_or_empty(resp)
            row = data.get("order_return") or data.get("return") or data
            saved = str(row.get("note") or "").strip()
            if saved == expected or expected in saved:
                return True
    except Exception as e:
        attempts.append(f"GET verify json -> {type(e).__name__}: {e}")
    try:
        resp = session.get(f"{BASE}/admin/order_returns/{return_id}", headers={"Accept": "text/html,application/xhtml+xml"}, timeout=30)
        attempts.append(_attempt_desc(resp))
        if resp.status_code < 400 and expected in unescape(resp.text or ""):
            return True
    except Exception as e:
        attempts.append(f"GET verify html -> {type(e).__name__}: {e}")
    return False


class _SapoFormParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.forms = []
        self._form = None
        self._textarea = None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "form":
            self._form = {"attrs": attrs, "fields": {}, "textareas": []}
            return
        if not self._form:
            return
        if tag == "input":
            name = attrs.get("name")
            if name:
                self._form["fields"][name] = attrs.get("value", "")
        elif tag == "textarea":
            name = attrs.get("name")
            if name:
                self._form["textareas"].append(name)
                self._form["fields"].setdefault(name, "")
                self._textarea = name

    def handle_data(self, data):
        if self._form and self._textarea:
            self._form["fields"][self._textarea] = self._form["fields"].get(self._textarea, "") + data

    def handle_endtag(self, tag):
        if tag == "textarea":
            self._textarea = None
        elif tag == "form" and self._form:
            self.forms.append(self._form)
            self._form = None


def _csrf_token(html: str) -> str | None:
    m = re.search(r'<meta[^>]+name=["\']csrf-token["\'][^>]+content=["\']([^"\']+)["\']', html, re.I)
    if m:
        return m.group(1)
    m = re.search(r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+name=["\']csrf-token["\']', html, re.I)
    return m.group(1) if m else None


def _json_headers(referer: str | None = None, token: str | None = None) -> dict:
    headers = {
        "Accept": "application/json, text/plain, */*",
        "X-Bizweb-Accept-Language": "vi",
        "X-Sapo-Client": "frontend",
    }
    if referer:
        headers["Referer"] = referer
    if token:
        headers["X-Csrf-Token"] = token
    return headers


def _page_csrf_token(session: requests.Session, page_url: str, attempts: list[str]) -> str | None:
    try:
        page = session.get(page_url, headers={"Accept": "text/html,application/xhtml+xml"}, timeout=30)
        attempts.append(_attempt_desc(page))
        if page.status_code < 400:
            return _csrf_token(page.text or "")
    except Exception as e:
        attempts.append(f"GET csrf html -> {type(e).__name__}: {e}")
    return None


def _post_form(session: requests.Session, url: str, data: dict, token: str | None, attempts: list[str]) -> requests.Response | None:
    headers = {
        "Accept": "application/json, text/javascript, */*; q=0.01",
        "X-Bizweb-Accept-Language": "vi",
        "X-Sapo-Client": "frontend",
        "X-Requested-With": "XMLHttpRequest",
        "Referer": url,
    }
    if token:
        headers["X-Csrf-Token"] = token
    resp = session.post(url, data=data, headers=headers, timeout=30, allow_redirects=False)
    attempts.append(_attempt_desc(resp))
    if resp.status_code < 400:
        return resp
    return None


def _update_order_return_note_via_html(session: requests.Session, return_id, note: str, attempts: list[str]) -> dict | None:
    page_url = f"{BASE}/admin/order_returns/{return_id}"
    page = session.get(page_url, headers={"Accept": "text/html,application/xhtml+xml"}, timeout=30)
    attempts.append(_attempt_desc(page))
    if page.status_code >= 400:
        return None

    html = page.text or ""
    token = _csrf_token(html)
    parser = _SapoFormParser()
    parser.feed(html)
    note_names = ("note", "ghi_chu", "remark", "description")

    for form in parser.forms:
        fields = dict(form.get("fields") or {})
        textareas = form.get("textareas") or []
        note_field = next((n for n in textareas if any(k in n.lower() for k in note_names)), None)
        if not note_field:
            continue
        fields[note_field] = note
        action = form.get("attrs", {}).get("action") or page_url
        url = urljoin(BASE, action)
        resp = _post_form(session, url, fields, token, attempts)
        if resp is not None and _saved_return_note(session, return_id, note, attempts):
            return _json_or_empty(resp)

    fallback_rows = [
        {"_method": "put", "order_return[note]": note},
        {"_method": "patch", "order_return[note]": note},
        {"order_return[note]": note},
        {"note": note},
    ]
    fallback_urls = [
        page_url,
        f"{page_url}/update_note",
        f"{page_url}/update_note.json",
        f"{page_url}/notes",
        f"{page_url}/notes.json",
    ]
    for url in fallback_urls:
        for data in fallback_rows:
            resp = _post_form(session, url, data, token, attempts)
            if resp is not None and _saved_return_note(session, return_id, note, attempts):
                return _json_or_empty(resp)
    return None


def update_order_return_note(session: requests.Session, return_id, note: str) -> dict:
    """Cập nhật note phiếu trả hàng trên Sapo."""
    attempts = []
    page_url = f"{BASE}/admin/order_returns/{return_id}"
    token = _page_csrf_token(session, page_url, attempts)
    resp = session.put(
        f"{page_url}/edit_note.json",
        json={"order_return": {"note": note}},
        headers=_json_headers(page_url, token),
        timeout=30,
        allow_redirects=False,
    )
    attempts.append(_attempt_desc(resp))
    if resp.status_code < 400 and _saved_return_note(session, return_id, note, attempts):
        return _json_or_empty(resp)
    paths = [
        f"{BASE}/admin/order_returns/{return_id}.json",
        page_url,
    ]
    for path in paths:
        for method in ("put", "patch", "post"):
            for payload in _note_payloads(return_id, note):
                resp = getattr(session, method)(
                    path,
                    json=payload,
                    headers=_json_headers(page_url, token),
                    timeout=30,
                    allow_redirects=False,
                )
                attempts.append(_attempt_desc(resp))
                if resp.status_code < 400 and _saved_return_note(session, return_id, note, attempts):
                    return _json_or_empty(resp)
        for data in (
            {"_method": "put", "order_return[note]": note},
            {"_method": "patch", "order_return[note]": note},
        ):
            resp = session.post(
                path,
                data=data,
                headers=_json_headers(page_url, token),
                timeout=30,
                allow_redirects=False,
            )
            attempts.append(_attempt_desc(resp))
            if resp.status_code < 400 and _saved_return_note(session, return_id, note, attempts):
                return _json_or_empty(resp)

    result = _update_order_return_note_via_html(session, return_id, note, attempts)
    if result is not None:
        return result

    tail = "; ".join(attempts[-16:])
    raise RuntimeError(f"SAPO có phản hồi nhưng đọc lại chưa thấy ghi chú được lưu cho phiếu {return_id}. Đã thử: {tail}")
