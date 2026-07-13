import json
import os
import subprocess
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse


HOST = "127.0.0.1"
PORT = int(os.environ.get("VITRAN_SHOPEE_LAUNCHER_PORT", "17654"))

SHOP_PROFILES = {
    "179402721": "Default",     # VITRAN BOUTIQUE
    "58785946": "Profile 7",    # SMOSS
    "736667756": "Profile 10",  # MUN-AI / mun.partnership
}

SHOP_NAMES = {
    "179402721": "VITRAN",
    "58785946": "SMOSS",
    "736667756": "MUN-AI",
}


def _chrome_path():
    candidates = [
        os.environ.get("CHROME_EXE"),
        str(Path(os.environ.get("LOCALAPPDATA", "")) / "Google/Chrome/Application/chrome.exe"),
        str(Path(os.environ.get("PROGRAMFILES", "")) / "Google/Chrome/Application/chrome.exe"),
        str(Path(os.environ.get("PROGRAMFILES(X86)", "")) / "Google/Chrome/Application/chrome.exe"),
    ]
    for path in candidates:
        if path and Path(path).exists():
            return path
    return "chrome.exe"


def _safe_shopee_url(raw):
    raw = (raw or "").strip()
    parsed = urlparse(raw)
    if parsed.scheme != "https" or parsed.netloc != "banhang.shopee.vn":
        raise ValueError("Only https://banhang.shopee.vn links are allowed")
    if not parsed.path.startswith("/portal/sale/"):
        raise ValueError("Only Shopee sale pages are allowed")
    return raw


def open_shopee(shop_id, target_url):
    profile = SHOP_PROFILES.get(str(shop_id or "").strip())
    if not profile:
        raise ValueError(f"Unknown Shopee shop id: {shop_id}")
    target_url = _safe_shopee_url(target_url)
    cmd = [
        _chrome_path(),
        f"--profile-directory={profile}",
        "--new-window",
        target_url,
    ]
    subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, close_fds=True)
    return profile


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        return

    def _send(self, code, payload, content_type="text/html; charset=utf-8"):
        data = payload.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path in ("/", "/health"):
            self._send(200, json.dumps({"ok": True, "service": "vitran-shopee-launcher"}), "application/json")
            return
        if parsed.path != "/open":
            self._send(404, "Not found")
            return
        qs = parse_qs(parsed.query)
        shop_id = (qs.get("shop_id") or [""])[0]
        target_url = (qs.get("target") or qs.get("url") or [""])[0]
        try:
            profile = open_shopee(shop_id, target_url)
            shop_name = SHOP_NAMES.get(shop_id, shop_id)
            self._send(
                200,
                "<!doctype html><meta charset='utf-8'>"
                "<title>VITRAN Shopee Launcher</title>"
                "<body style='font-family:Tahoma,Arial,sans-serif;padding:18px'>"
                f"<b>Da mo Shopee {shop_name}</b><br>"
                f"Chrome profile: {profile}"
                "<script>setTimeout(function(){window.close()},900)</script>"
                "</body>",
            )
        except Exception as exc:
            self._send(
                400,
                "<!doctype html><meta charset='utf-8'>"
                "<title>VITRAN Shopee Launcher</title>"
                "<body style='font-family:Tahoma,Arial,sans-serif;padding:18px;color:#991b1b'>"
                f"<b>Khong mo duoc Shopee:</b> {str(exc)}"
                "</body>",
            )


def main():
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"VITRAN Shopee launcher listening on http://{HOST}:{PORT}")
    server.serve_forever()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(0)
