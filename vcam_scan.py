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


def mp4_duration(path: str) -> int:
    """Thời lượng THẬT đọc từ header MP4 (atom mvhd) — chính xác hơn nhiều so với lấy
    giờ sửa file trừ giờ trong tên (ghi file xong trễ vài chục giây là sai bét)."""
    try:
        with open(path, "rb") as f:
            end = os.path.getsize(path)
            pos = 0
            while pos < end - 8:                    # duyệt atom cấp 1 tìm moov
                f.seek(pos)
                head = f.read(8)
                if len(head) < 8:
                    return 0
                size = int.from_bytes(head[:4], "big")
                typ = head[4:8]
                if size == 1:                       # size 64-bit
                    size = int.from_bytes(f.read(8), "big")
                if size < 8:
                    return 0
                if typ == b"moov":
                    moov_end = pos + size
                    q = f.tell()
                    while q < moov_end - 8:          # trong moov tìm mvhd
                        f.seek(q)
                        h2 = f.read(8)
                        if len(h2) < 8:
                            return 0
                        s2 = int.from_bytes(h2[:4], "big")
                        t2 = h2[4:8]
                        if s2 == 1:
                            s2 = int.from_bytes(f.read(8), "big")
                        if s2 < 8:
                            return 0
                        if t2 == b"mvhd":
                            ver = f.read(1)[0]
                            f.read(3)                # flags
                            if ver == 1:
                                f.read(16)           # created + modified (64-bit)
                                scale = int.from_bytes(f.read(4), "big")
                                dur = int.from_bytes(f.read(8), "big")
                            else:
                                f.read(8)            # created + modified (32-bit)
                                scale = int.from_bytes(f.read(4), "big")
                                dur = int.from_bytes(f.read(4), "big")
                            return int(round(dur / scale)) if scale else 0
                        q += s2
                    return 0
                pos += size
    except Exception:
        return 0
    return 0


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
                dur = mp4_duration(path)        # ưu tiên thời lượng THẬT trong header MP4
                if not dur:
                    try:    # không đọc được header → ước lượng: giờ ghi xong − giờ trong tên
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

    def _log(line):        # chạy nền bằng pythonw thì không có màn hình → ghi log cạnh script
        try:
            with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "vcam_sync.log"),
                      "a", encoding="utf-8") as lf:
                lf.write(f"{datetime.now():%Y-%m-%d %H:%M:%S}  {line}\n")
        except Exception:
            pass

    if args.push:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import picklog
        if not picklog.configured():
            print("❌ Máy này chưa có token picklog/Gist nên KHÔNG đẩy được. "
                  "Dùng file vcam_index.json để nạp trong app, hoặc khai token rồi chạy lại.")
            _log("LOI: chua co token picklog/Gist -> khong day duoc")
            return 3
        if not picklog._resolve_gid():
            # configured() chỉ kiểm tra CÓ chuỗi token, token sai/hết hạn vẫn qua được →
            # phải hỏi thẳng GitHub, không thì log "OK" mà thực tế chẳng đẩy được gì.
            print("❌ Token Gist sai hoặc hết hạn (GitHub từ chối). Chưa đẩy được gì.")
            _log("LOI: token Gist sai/het han -> KHONG day duoc")
            return 4
        try:
            picklog.merge_dohana_videos(rows)
            _after = picklog.read_dohana_videos() or []
        except Exception as e:
            print(f"❌ Đẩy Gist lỗi: {e}")
            _log(f"LOI day Gist: {e}")
            return 4
        # merge_dohana_videos chỉ ĐIỀN field còn trống → thời lượng/giờ cũ sai vẫn nằm đó.
        # Bản ghi VCAM là của mình nên cập nhật đè cho đúng (Dohana giữ nguyên, không đụng).
        _want = {(x["code"], x["type"]): x for x in rows}
        _fixed = 0
        for _r in _after:
            _x = _want.get((_r.get("code"), _r.get("type")))
            if not _x or str(_r.get("staff") or "").upper() != "VCAM":
                continue
            for _k in ("dur", "time", "date", "slug"):
                if _x.get(_k) not in (None, "") and _r.get(_k) != _x.get(_k):
                    _r[_k] = _x[_k]
                    _fixed += 1
        if _fixed:
            picklog._write_dohana_store(_after)
            print(f"🔧 Sửa lại {_fixed} field của bản ghi VCAM đã lưu (thời lượng/giờ).")
            _log(f"sua {_fixed} field VCAM da luu")
        _saved = sum(1 for r in _after if (r.get("code"), r.get("type")) in
                     {(x["code"], x["type"]) for x in rows})
        if not _saved:
            print("❌ Đẩy xong nhưng kho KHÔNG có bản ghi nào — kiểm tra quyền gist của token.")
            _log("LOI: day xong nhung kho khong nhan ban ghi")
            return 5
        print(f"☁️ Đã đẩy {len(rows)} video vào kho trên Gist ({_saved} bản ghi có trong kho).")
        _log(f"OK day {len(rows)} video (kho co {_saved}) | "
             + " · ".join(f"{d}: khui {v.get('inbound', 0)}/dong {v.get('package', 0)}"
                          for d, v in sorted(days.items())))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
