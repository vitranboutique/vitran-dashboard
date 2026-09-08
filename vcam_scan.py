"""vcam_scan.py — quét kho video của app VCAM trên máy shop (LAN) → index JSON.

Từ 03/09/2026 video KHÔNG còn lấy từ Dohana mà do app VCAM tự quay và lưu vào ổ chia sẻ:

    \\\\192.168.1.3\\VideoDongHang\\<Khui_hàng_hoàn|Đóng_hàng>\\<YYYY-MM-DD>\\<MÃ>_<HHMMSS>.mp4

Streamlit Cloud KHÔNG vào được LAN nên phải có máy trong shop chạy file này:
  · `python vcam_scan.py`            → ghi index ra vcam_index.json (đem upload trong app)
  · `python vcam_scan.py --push`     → đẩy thẳng vào kho video trên Gist (cần token picklog)

Bản ghi đúng schema kho video sẵn có (picklog.merge_dohana_videos) nên MỌI báo cáo/đối chiếu
đang chạy dùng lại được ngay, không phải sửa logic:
    {code, type, status, date, time, dur, link, slug, staff}
  · type "inbound" = khui hàng hoàn   · type "package" = đóng hàng
  · dur = giờ sửa file cuối − giờ bắt đầu quay (trong tên file) → xấp xỉ thời lượng clip.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime

VCAM_ROOT = os.environ.get("VCAM_ROOT", r"\\192.168.1.3\VideoDongHang")
VCAM_FROM = os.environ.get("VCAM_FROM", "2026-09-03")   # trước ngày này vẫn là video Dohana
FOLDER_TYPE = {"Khui_hàng_hoàn": "inbound", "Đóng_hàng": "package"}
# 2 kiểu tên gặp thực tế:
#   854158325178_132010.mp4                       → chỉ 1 mã
#   854157157497_163518__4042018142694114699.mp4  → mã VĐ + (2 gạch dưới) + mã đơn/mã phiếu trả
_NAME_RE = re.compile(r"^(?P<code>[A-Za-z0-9][A-Za-z0-9.-]{4,})_(?P<hms>\d{6})"
                      r"(?:__(?P<code2>[A-Za-z0-9._-]{4,}))?$")
_DAY_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_VIDEO_EXT = (".mp4", ".mov", ".mkv", ".avi", ".m4v")


def _norm_code(value: str) -> str:
    """Bỏ ký tự thừa, viết HOA — khớp với cách app chuẩn hoá mã."""
    return re.sub(r"[^A-Za-z0-9]", "", str(value or "")).upper()


def scan(root: str = VCAM_ROOT, since: str = VCAM_FROM) -> list[dict]:
    """Quét toàn bộ ngày >= since, trả về list bản ghi video (đã khử trùng theo (code, type))."""
    out: dict[tuple, dict] = {}
    for folder, vtype in FOLDER_TYPE.items():
        base = os.path.join(root, folder)
        if not os.path.isdir(base):
            continue
        for day in sorted(os.listdir(base)):
            if not _DAY_RE.match(day) or (since and day < since):
                continue
            day_dir = os.path.join(base, day)
            if not os.path.isdir(day_dir):
                continue
            for name in sorted(os.listdir(day_dir)):
                stem, ext = os.path.splitext(name)
                if ext.lower() not in _VIDEO_EXT:
                    continue
                m = _NAME_RE.match(stem)
                if not m:
                    continue
                code = _norm_code(m.group("code"))
                hms = m.group("hms")
                start_txt = f"{hms[0:2]}:{hms[2:4]}:{hms[4:6]}"
                path = os.path.join(day_dir, name)
                try:
                    mtime = os.path.getmtime(path)
                    size = os.path.getsize(path)
                except OSError:
                    continue
                dur = 0
                try:    # thời lượng ≈ lúc ghi xong (mtime) − lúc bắt đầu quay (tên file)
                    start = datetime.strptime(f"{day} {start_txt}", "%Y-%m-%d %H:%M:%S")
                    dur = int(round(datetime.fromtimestamp(mtime).timestamp() - start.timestamp()))
                except Exception:
                    dur = 0
                if not (0 < dur <= 3600):       # giờ máy lệch / file copy lại → bỏ, khỏi báo số bậy
                    dur = 0
                # mã thứ 2 (mã đơn / mã phiếu trả) cất vào slug để đối chiếu thêm, KHÔNG tạo
                # bản ghi riêng — tạo riêng sẽ làm số "video đóng gói" đếm gấp đôi.
                code2 = _norm_code(m.group("code2")) if m.group("code2") else ""
                rec = {"code": code, "type": vtype, "status": "done", "date": day,
                       "time": start_txt, "dur": dur, "link": "", "slug": code2,
                       "staff": "VCAM", "src": "vcam", "size": size, "file": name}
                key = (code, vtype)
                old = out.get(key)
                if old is None or (old.get("date"), old.get("time")) < (day, start_txt):
                    out[key] = rec        # cùng mã quay nhiều lần → giữ clip MỚI NHẤT
    return sorted(out.values(), key=lambda r: (r["date"], r["time"]))


def summary(rows: list[dict]) -> dict:
    days: dict[str, dict] = {}
    for r in rows:
        d = days.setdefault(r["date"], {"inbound": 0, "package": 0, "no_dur": 0})
        d[r["type"]] = d.get(r["type"], 0) + 1
        if not r.get("dur"):
            d["no_dur"] += 1
    return days


def main() -> int:
    ap = argparse.ArgumentParser(description="Quét kho video VCAM → index JSON / đẩy Gist")
    ap.add_argument("--root", default=VCAM_ROOT)
    ap.add_argument("--since", default=VCAM_FROM, help="chỉ lấy ngày >= (YYYY-MM-DD)")
    ap.add_argument("--out", default="vcam_index.json")
    ap.add_argument("--push", action="store_true", help="đẩy thẳng vào kho video Gist (cần token picklog)")
    args = ap.parse_args()

    if not os.path.isdir(args.root):
        print(f"❌ Không vào được kho video: {args.root}\n"
              "   → kiểm tra máy shop đã bật và ổ chia sẻ còn mở chưa.")
        return 2

    rows = scan(args.root, args.since)
    days = summary(rows)
    print(f"✅ Quét xong {len(rows)} video từ {args.since} tại {args.root}")
    for day in sorted(days):
        d = days[day]
        print(f"   {day}: khui hàng hoàn {d.get('inbound', 0):>3} · đóng hàng {d.get('package', 0):>3}"
              + (f"  (⚠️ {d['no_dur']} clip không tính được thời lượng)" if d.get("no_dur") else ""))

    payload = {"src": "vcam", "root": args.root, "since": args.since,
               "scanned_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
               "count": len(rows), "videos": rows}
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=1)
    print(f"📄 Đã ghi {args.out} — vào app → trang Đơn trả → 🎥 Kho video → nạp file này.")

    if args.push:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import picklog
        if not picklog.configured():
            print("❌ Máy này chưa có token picklog/Gist nên KHÔNG đẩy được. "
                  "Dùng file vcam_index.json để nạp trong app, hoặc khai token rồi chạy lại.")
            return 3
        picklog.merge_dohana_videos(rows)
        print(f"☁️ Đã đẩy {len(rows)} video vào kho trên Gist — app đọc được ngay.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
