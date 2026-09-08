"""local_snapshot.py — chạy QUÉT NỀN ngay tại máy shop, thay cho GitHub Actions.

Vì sao cần: app trên Streamlit Cloud không gọi Sapo trực tiếp (hay bị Cloudflare chặn IP),
nó chỉ đọc snapshot trên Gist. Snapshot đó do GitHub Actions quét — lịch đặt 15 phút/lần
nhưng GitHub hay giãn thành 2–5 TIẾNG/lần, nên ghi chú vừa viết hay đợt vừa in không lên app.

Máy trong shop dùng IP nhà, Sapo không chặn → chạy file này 15 phút/lần là app luôn có số mới.

Cần trong `.streamlit/secrets.toml` (file này KHÔNG lên GitHub):
    SAPO_API_KEY    = "..."
    SAPO_API_SECRET = "..."
    [picklog]
    github_token = "ghp_..."      # để ghi snapshot lên Gist

Chạy:  python local_snapshot.py            (quét đơn trả + báo cáo cuối ngày)
       python local_snapshot.py --shared   (quét thêm bộ dữ liệu dùng chung)
"""
from __future__ import annotations

import os
import re
import sys
from datetime import datetime

_ROOT = os.path.dirname(os.path.abspath(__file__))
_SECRETS = os.path.join(_ROOT, ".streamlit", "secrets.toml")
_LOG = os.path.join(_ROOT, "snapshot_local.log")


def _log(line: str) -> None:
    print(line)
    try:
        with open(_LOG, "a", encoding="utf-8") as f:
            f.write(f"{datetime.now():%Y-%m-%d %H:%M:%S}  {line}\n")
    except Exception:
        pass


def _load_secrets_into_env() -> bool:
    """Đọc secrets.toml (dạng đơn giản) → đổ vào biến môi trường cho snapshot_*.py dùng.
    Không dùng thư viện toml vì Python 3.10 chưa có sẵn tomllib."""
    if not os.path.exists(_SECRETS):
        _log(f"LOI: khong thay {_SECRETS}")
        return False
    section = ""
    got = {}
    for raw in open(_SECRETS, encoding="utf-8"):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        m = re.match(r"^\[([^\]]+)\]$", line)
        if m:
            section = m.group(1).strip()
            continue
        m = re.match(r'^([A-Za-z0-9_]+)\s*=\s*"(.*)"\s*$', line)
        if not m:
            continue
        key, val = m.group(1), m.group(2)
        if not section and key.startswith("SAPO_"):
            got[key] = val
        elif section == "picklog" and key == "github_token":
            got["GITHUB_TOKEN"] = val
    for k, v in got.items():
        os.environ.setdefault(k, v)
    _missing = [k for k in ("SAPO_API_KEY", "SAPO_API_SECRET", "GITHUB_TOKEN")
                if not os.environ.get(k) or "DAN_" in os.environ.get(k, "")]
    if _missing:
        _log("LOI: thieu/chua dien " + ", ".join(_missing) + f" trong {_SECRETS}")
        return False
    return True


def main() -> int:
    if not _load_secrets_into_env():
        return 2
    sys.path.insert(0, _ROOT)
    _t0 = datetime.now()
    try:
        import snapshot_returns
        snapshot_returns.main()
    except Exception as e:
        _log(f"LOI quet don tra: {e}")
        return 3
    if "--shared" in sys.argv:
        try:
            import snapshot_shared
            snapshot_shared.main()
        except Exception as e:
            _log(f"LOI quet du lieu chung: {e}")
    _log(f"OK quet nen xong sau {int((datetime.now() - _t0).total_seconds())}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
