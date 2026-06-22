"""
daily_report.py — Render BÁO CÁO VẬN HÀNH CUỐI NGÀY (khổ A4) từ get_daily_report() + Dohana.
Trả 1 chuỗi HTML (nhúng bằng components.html) gồm nút In A4 + báo cáo bố cục chuyên nghiệp.
"""
import json
from collections import OrderedDict
from html import escape as _e

_CSS = """
  --navy:#16233f; --accent:#E24B4A; --line:#cfd6e0; --grid:#8c98ab; --soft:#eef1f6; --ink:#1f2733;
  body{font-family:Tahoma,Verdana,'Segoe UI',system-ui,Roboto,Arial,sans-serif;margin:0;background:#e9edf2;color:var(--ink);}
  .toolbar{position:sticky;top:0;background:#e9edf2;padding:8px;text-align:center;z-index:5;}
  .printbtn{background:var(--accent);color:#fff;border:0;border-radius:9px;padding:10px 20px;font-size:14px;font-weight:800;cursor:pointer;box-shadow:0 2px 8px rgba(226,75,74,.4);}
  .page{width:210mm;height:297mm;margin:0 auto 14px;background:#fff;box-sizing:border-box;box-shadow:0 2px 14px rgba(0,0,0,.12);overflow:hidden;}
  .pfit{padding:9mm 11mm 8mm;font-size:var(--fs,13px);box-sizing:border-box;}
  .hd{display:flex;align-items:center;justify-content:space-between;border-bottom:3px solid var(--navy);padding-bottom:.45em;}
  .hd .brand{font-size:1.38em;font-weight:900;color:var(--navy);letter-spacing:.5px;}
  .hd .sub{font-size:.81em;color:#6b7280;margin-top:1px;}
  .hd .meta{text-align:right;font-size:.81em;color:#374151;}
  .hd .meta b{font-size:1.24em;color:var(--accent);}
  .title{text-align:center;font-size:1.15em;font-weight:900;color:var(--navy);margin:.6em 0 .15em;text-transform:uppercase;letter-spacing:.5px;}
  .title-sub{text-align:center;font-size:.77em;color:#6b7280;margin-bottom:.55em;}
  .kpis{display:grid;grid-template-columns:repeat(4,1fr);gap:.46em;margin:.46em 0 .7em;}
  .kpi{border:1px solid var(--grid);border-radius:7px;padding:.38em .7em;background:var(--soft);}
  .kpi .l{font-size:.77em;color:#6b7280;font-weight:600;}
  .kpi .v{font-size:1.46em;font-weight:900;color:var(--navy);line-height:1.15;}
  .kpi.hot .v{color:var(--accent);}
  .sec{font-size:.88em;font-weight:800;color:#fff;background:var(--navy);padding:.23em .6em;border-radius:4px;margin:.7em 0 .3em;}
  table{width:100%;border-collapse:collapse;font-size:.85em;}
  th,td{border:1px solid var(--grid);padding:.23em .54em;text-align:center;}
  th{background:#dfe4ec;font-weight:800;color:#2c3a52;}
  td.l,th.l{text-align:left;}
  td.num{text-align:right;font-variant-numeric:tabular-nums;}
  tr.total td{background:#fff2dd;font-weight:900;color:var(--navy);}
  tr.total td.accent{color:var(--accent);}
  .two{display:grid;grid-template-columns:1fr 1fr;gap:11px;}
  .note{border:1px solid var(--grid);border-radius:5px;min-height:2.3em;padding:.38em .6em;font-size:.81em;color:#374151;}
  .note .lines{margin-top:.3em;}
  .note .lines div{border-bottom:1px dashed #c0c8d4;height:1.15em;}
  .sign{display:grid;grid-template-columns:repeat(3,1fr);gap:14px;margin-top:.9em;text-align:center;font-size:.85em;}
  .sign .role{font-weight:800;color:var(--navy);}
  .sign .hint{color:#9aa3af;font-size:.86em;}
  .sign .space{height:3.2em;}
  .foot{margin-top:.55em;text-align:center;font-size:.73em;color:#9aa3af;border-top:1px solid var(--line);padding-top:.3em;}
  .page2{page-break-before:always;}
  .kpis.k3{grid-template-columns:repeat(3,1fr);}
  .kpis.kf5{grid-template-columns:repeat(5,1fr);gap:.38em;margin:.46em 0 .4em;}
  .kf5 .kpi{padding:.3em .46em;text-align:center;}
  .kf5 .kpi .l{font-size:.69em;line-height:1.2;}
  .kf5 .kpi .v{font-size:1.31em;}
  .kpi.bad{border-color:#dc2626;background:#fdeeee;}
  .kpi .lech{font-size:.65em;color:#dc2626;font-weight:800;margin-top:1px;}
  .kpi .tick{font-size:.62em;color:#6b7280;margin-top:.23em;border-top:1px dashed #c0c8d4;padding-top:.15em;}
  .kpi .cbox{display:inline-block;width:.8em;height:.8em;border:1.2px solid #6b7280;vertical-align:-1px;margin-right:2px;border-radius:2px;}
  .warn{border:1px solid #e0a155;border-left:5px solid #d97706;background:#fff8ec;border-radius:6px;padding:.46em .77em;margin:.6em 0 .7em;}
  .warn .wh{font-size:.88em;font-weight:900;color:#b45309;}
  .warn .wb{font-size:.77em;color:#7c4a13;margin-top:2px;line-height:1.4;}
  .warn .wc{font-size:.85em;font-weight:900;color:#b45309;margin-top:.23em;letter-spacing:.3px;}
  .fdetail{display:grid;grid-template-columns:1fr 1fr;gap:.6em;margin:.55em 0 .7em;}
  .fdcol{border:1px solid #d6dbe6;border-radius:6px;padding:.38em .6em .46em;}
  .fdcol-huy{background:#fdf3f2;border-color:#eec2bc;}
  .fdcol-xot{background:#fff8ec;border-color:#e9cf9b;}
  .fdhead{font-size:.77em;font-weight:900;margin-bottom:2px;line-height:1.3;}
  .dvgrp{font-size:.73em;font-weight:800;color:#475569;margin:.23em 0 0;}
  .dline{font-size:.77em;color:#1f2937;padding:1px 0 1px 3px;line-height:1.5;}
  .dline .vd{color:#6b7280;font-size:.9em;}
  .dline .pk{color:#b91c1c;font-size:.85em;font-weight:800;}
  .cbox2{display:inline-block;width:.8em;height:.8em;border:1.3px solid #475569;border-radius:2px;vertical-align:-1px;margin-right:2px;}
  .itip{position:relative;display:inline-block;font-size:.7em;font-weight:800;color:#2563eb;cursor:help;margin:.3em 0 0;}
  .ipop{display:none;position:absolute;left:0;top:1.5em;z-index:30;width:80mm;background:#fff;border:1px solid #b9c2d0;border-radius:6px;padding:7px 9px;box-shadow:0 5px 16px rgba(0,0,0,.22);font-size:1.12em;font-weight:400;color:#374151;line-height:1.5;}
  .itip:hover .ipop{display:block;}
  .sign.s2{grid-template-columns:repeat(2,1fr);max-width:70%;margin-left:auto;margin-right:auto;}
  @page{size:A4 portrait;margin:0;}
  @media print{
    body{background:#fff;} .toolbar{display:none;}
    .page{box-shadow:none;margin:0;}
    table,tr,td,th{page-break-inside:avoid;}
    *{-webkit-print-color-adjust:exact;print-color-adjust:exact;}
  }
"""


def _carrier_rows(rows, tot):
    body = ""
    for r in rows:
        hot = "Hỏa tốc" in str(r["carrier"])
        cls = ' style="background:#fff3ed"' if hot else ''
        _cl = r["con_lai"]
        _clc = (f'<td class="num" style="color:#dc2626;font-weight:800">{_cl}</td>'
                if _cl else '<td class="num"></td>')
        # Đã giao khách — quan trọng với hỏa tốc: shipper nhận > giao khách = đơn đang giao / BỊ TRẢ VỀ
        _gk = r.get("giao_khach", 0)
        _gk_warn = hot and r["shipper_nhan"] > _gk
        _gkc = (f'<td class="num" style="color:#c2410c;font-weight:800">{_gk}</td>'
                if _gk_warn else f'<td class="num">{_gk or ""}</td>')
        body += (f'<tr{cls}><td class="l">{"⚡ " if hot else ""}{_e(str(r["carrier"]))}</td>'
                 f'<td class="num">{r["dong_goi"]}</td><td class="num">{r["huy"] or ""}</td>'
                 f'<td class="num">{r.get("xuat_kho", 0)}</td>'
                 f'<td class="num">{r["shipper_nhan"]}</td>' + _gkc + _clc + '</tr>')
    body = body or '<tr><td class="l" colspan="7">—</td></tr>'
    _tcl = tot["con_lai"]
    body += (f'<tr class="total"><td class="l">TỔNG CỘNG</td>'
             f'<td class="num">{tot["dong_goi"]}</td><td class="num accent">{tot["huy"] or ""}</td>'
             f'<td class="num">{tot.get("xuat_kho", 0)}</td>'
             f'<td class="num">{tot["shipper_nhan"]}</td>'
             f'<td class="num">{tot.get("giao_khach", 0) or ""}</td>'
             f'<td class="num{" accent" if _tcl else ""}">{_tcl or ""}</td></tr>')
    return body


def _carrier_lech_notes(rows):
    """Tự sinh LÝ DO chênh lệch khi các cột cộng/trừ không khớp — để NV biết đường kiểm tra."""
    notes = []
    for r in rows:
        c = str(r["carrier"])
        hot = "Hỏa tốc" in c
        dg, x = r.get("dong_goi", 0), r.get("xuat_kho", 0)
        s, g, hu = r.get("shipper_nhan", 0), r.get("giao_khach", 0), r.get("huy", 0)
        if x > s:   # xuất kho mà shipper chưa xác nhận = NGHI MẤT ĐƠN
            notes.append(f'⚠️ <b>{_e(c)}</b>: đã xuất kho <b>{x}</b> đơn nhưng ĐVVC mới xác nhận lấy '
                         f'<b>{s}</b> → <b style="color:#dc2626">thiếu {x - s} đơn</b> (shipper chưa quét '
                         'biên bản hoặc chưa lấy). Đối chiếu biên bản bàn giao ngay — tránh MẤT ĐƠN.')
        if hot and s > g:   # hỏa tốc: shipper nhận nhưng chưa tới khách = đang giao / bị trả về
            notes.append(f'⚠️ <b>{_e(c)}</b>: shipper đã nhận <b>{s}</b> nhưng mới giao tới khách '
                         f'<b>{g}</b> → <b style="color:#c2410c">{s - g} đơn chưa tới khách</b> '
                         '(đang giao hoặc GIAO THẤT BẠI bị trả về). Kiểm tra tình trạng giao từng đơn.')
        # đóng gói (trừ hủy đã gói) nhiều hơn xuất kho = còn đơn đã gói chưa xuất kho
        if dg - hu > x:
            notes.append(f'⚠️ <b>{_e(c)}</b>: đóng gói <b>{dg}</b> (gồm {hu} hủy) nhưng mới xuất kho '
                         f'<b>{x}</b> → còn <b>{dg - hu - x} đơn đã gói CHƯA xuất kho</b>. '
                         'Kiểm tra xem có sót đơn chưa bàn giao ĐVVC không.')
    return notes


def _huy_rows(detail):
    body = ""
    for i, d in enumerate(detail, 1):
        ten = f' — {_e(str(d["ten"]))}' if d.get("ten") else ""
        body += (f'<tr><td>{i}</td><td class="l">{_e(str(d.get("tracking", "")))}</td>'
                 f'<td>{_e(str(d.get("carrier", "")))}</td>'
                 f'<td class="l">{_e(str(d.get("sku", "")))}{ten}</td>'
                 f'<td class="num" style="font-weight:800">{d.get("sp", 0)}</td></tr>')
    return body or '<tr><td colspan="5">Không có đơn hủy đã đóng gói.</td></tr>'


def _grouped_tick_rows(detail, mark_packed=False):
    """Liệt kê đơn GOM THEO ĐVVC, mỗi đơn 1 ô tick + mã đơn + mã VĐ + SKU×SL."""
    if not detail:
        return '<div class="dline" style="color:#9aa3af">— Không có đơn —</div>'
    groups = OrderedDict()
    for d in detail:
        groups.setdefault(str(d.get("carrier") or "?"), []).append(d)
    html = ""
    for cr, items in groups.items():
        html += f'<div class="dvgrp">▸ {_e(cr)} ({len(items)})</div>'
        for d in items:
            nm = _e(str(d.get("name") or "?"))
            tk = str(d.get("tracking") or "")
            tk_html = f' · <span class="vd">{_e(tk)}</span>' if tk and tk != d.get("name") else ""
            pk = ' <span class="pk">📦 cần lấy lại</span>' if (mark_packed and d.get("packed")) else ""
            html += (f'<div class="dline"><span class="cbox2"></span> '
                     f'<b>{nm}</b>{tk_html} · {_e(str(d.get("sku", "")))}{pk}</div>')
    return html


def _conxot_rows(today_list, old_list):
    """Còn xót tách 2 nhóm: xót HÔM NAY vs xót CŨ (tồn từ ngày trước, kèm ngày tạo)."""
    def _lines(items, show_date):
        if not items:
            return '<div class="dline" style="color:#9aa3af">— không có —</div>'
        h = ""
        for d in items:
            tk = str(d.get("tracking") or "")
            tk_html = f' · <span class="vd">{_e(tk)}</span>' if tk and tk != d.get("name") else ""
            dt = (f' · <span class="pk">tồn từ {_e(str(d.get("created", "")))}</span>'
                  if show_date else "")
            h += (f'<div class="dline"><span class="cbox2"></span> <b>{_e(str(d.get("name", "?")))}</b>'
                  f'{tk_html} · {_e(str(d.get("carrier", "")))} · {_e(str(d.get("sku", "")))}{dt}</div>')
        return h
    return (f'<div class="dvgrp" style="color:#b45309">▸ Xót HÔM NAY ({len(today_list)})</div>'
            + _lines(today_list, False)
            + f'<div class="dvgrp" style="color:#dc2626;margin-top:3px">'
              f'▸ Xót CŨ — tồn từ ngày trước ({len(old_list)})</div>'
            + _lines(old_list, True))


def _info_tip(content):
    """Ghi chú ẩn cho gọn trang: chỉ hiện 'ℹ️ Giải thích', RÊ CHUỘT mới bung nội dung."""
    return f'<span class="itip">ℹ️ Giải thích<span class="ipop">{content}</span></span>'


def _batch_rows(batches, tong_don, tong_sp):
    body = "".join(
        f'<tr><td class="l">Đợt {b["dot"]}{" (hỏa tốc)" if b.get("hoatoc") else ""}</td>'
        f'<td>{_e(str(b["gio"]))}</td><td class="num">{b["don"]}</td><td class="num">{b["sp"]}</td></tr>'
        for b in batches) or '<tr><td class="l" colspan="4">Chưa có đợt nào</td></tr>'
    body += (f'<tr class="total"><td class="l">TỔNG</td><td></td>'
             f'<td class="num">{tong_don}</td><td class="num">{tong_sp}</td></tr>')
    return body


_SRC = {"tiktokshop": "TikTok", "shopee": "Shopee", "lazada": "Lazada",
        "website": "Website", "pos": "Tại quầy"}


def _returns_clip_rows(detail):
    body = ""
    for i, d in enumerate(detail, 1):
        cnt = d.get("clip_count", 0) or 0
        if d.get("clip"):
            _alt = ' <span style="color:#b45309;font-weight:700">(mã khác)</span>' if d.get("clip_altcode") else ""
            cell = (f'<span style="color:#15803d;font-weight:800">✓ Có'
                    f'{" ×" + str(cnt) if cnt > 1 else ""}</span>{_alt}')
            sub = []
            if d.get("clip_dur"):
                sub.append(f'{d["clip_dur"]}s')
            if d.get("clip_time"):
                sub.append(str(d["clip_time"]))
            if sub:
                cell += (f'<div style="font-size:.82em;color:#6b7280;font-weight:600">'
                         f'⏱ {_e(" · ".join(sub))}</div>')
            tdcls = ""
        else:
            cell = '<span style="color:#dc2626;font-weight:800">✗ Thiếu clip</span>'
            tdcls = ' style="background:#fef2f2"'
        # Loại trả hàng — giao hàng thất bại tô cam để nhân viên lưu ý (hàng chưa tới khách)
        lt = d.get("loai_tra", "—")
        lt_style = ("color:#c2410c;font-weight:800"
                    if d.get("loai_tra_code") == "delivery_failed" else "color:#374151")
        # Tag app đóng hàng (tráo hàng / mất hàng…) — tô tím nổi bật để cảnh báo
        tag = d.get("clip_tag") or ""
        if tag:
            tag_cell = (f'<span style="color:#6d28d9;font-weight:800;background:#f3e8ff;'
                        f'padding:1px 5px;border-radius:4px">🏷️ {_e(str(tag))}</span>')
        else:
            tag_cell = '<span style="color:#cbd5e1">—</span>'
        # Liệt kê ĐỦ mã liên quan để tra Sapo: Mã đơn (đậm, tra được) + VĐ giao đi (tra được)
        # + VĐ hoàn về (mã in trên kiện hàng trả — KHÔNG tra được ở Sapo, chỉ để đối chiếu kiện).
        _oc = str(d.get("order_code") or d.get("tracking") or "?")
        _go = str(d.get("tracking") or "")            # VĐ giao đi
        _hv = str(d.get("track_return") or "")        # VĐ hoàn về (trên kiện)
        _lines = ""
        if _go and _go != _oc:
            _lines += (f'<div style="font-size:.82em;color:#15803d">→ giao đi: {_e(_go)} '
                       '<span style="color:#9ca3af">(tra được)</span></div>')
        if _hv and _hv != _go and _hv != _oc:
            _lines += (f'<div style="font-size:.82em;color:#9ca3af">← hoàn về: {_e(_hv)} '
                       '<span style="color:#cbd5e1">(mã trên kiện)</span></div>')
        body += (f'<tr><td>{i}</td>'
                 f'<td class="l"><b>{_e(_oc)}</b>{_lines}</td>'
                 f'<td>{_e(str(d.get("carrier", "")))}</td>'
                 f'<td class="l">{_e(str(d.get("sku", "")))}</td>'
                 f'<td class="l" style="{lt_style}">{_e(str(lt))}</td>'
                 f'<td class="l">{tag_cell}</td>'
                 f'<td{tdcls}>{cell}</td></tr>')
    return body or '<tr><td colspan="7">Hôm nay không có đơn hoàn nhập kho.</td></tr>'


def report_html(rep, dv, now_str):
    t = rep["totals"]
    video_total = (dv or {}).get("total", "—")
    # ---- VIDEO ĐÓNG GÓI: trình bày theo góc ĐƠN (đơn đóng gói có / thiếu video) ----
    vr = rep.get("video_recon") or {}
    if vr.get("available"):
        _have = vr.get("open_with_video", 0)
        _mv = vr.get("missing_video", 0)
        _miss_codes = vr.get("missing_codes") or []
        _miss_row = (f'<tr><td class="l" style="padding-left:20px;color:#b45309">⤷ ⚠️ Thiếu video</td>'
                     f'<td class="num" style="color:#b45309;font-weight:900">{_mv}</td></tr>'
                     if _mv else
                     '<tr><td class="l" style="padding-left:20px;color:#15803d">⤷ ✅ Đủ video (100%)</td>'
                     '<td class="num" style="color:#15803d;font-weight:800">✓</td></tr>')
        iii_rows = (
            f'<tr><td class="l">📦 Đơn đóng gói hôm nay</td>'
            f'<td class="num" style="font-weight:900">{t["dong_goi"]}</td></tr>'
            f'<tr><td class="l" style="padding-left:20px">⤷ ✅ Đã có video đóng gói</td>'
            f'<td class="num">{_have}</td></tr>'
            + _miss_row)
        vid_note = _info_tip(
            'Đơn đóng gói đã gồm cả <b>đơn hỏa tốc giao xong trong ngày</b> (dòng “Hỏa tốc” bảng ĐVVC). '
            + (f'<b>{_mv} đơn thiếu video</b> do clip bị <b>quay nhầm sang mục “khui hàng”</b> — xem cảnh báo.'
               if _mv else 'Tất cả đơn đóng gói đều có video.'))
        _w = []
        if _mv:
            _ml = ", ".join(_e(str(c)) for c in _miss_codes[:8]) + (f" …(+{_mv - 8})" if _mv > 8 else "")
            _w.append(f'<b>{_mv} đơn đã đóng gói nhưng THIẾU video đóng gói</b> '
                      f'(clip bị quay nhầm sang mục “khui hàng”) — cần quay/chuyển lại đúng. Mã: {_ml}')
        if vr.get("dup"):
            _dl = ", ".join(f'{_e(str(k))}×{v}' for k, v in vr["dup"].items())
            _w.append(f'<b>{len(vr["dup"])} đơn quay TRÙNG (≥2 lần)</b>: {_dl}.')
        vid_warn = ('<div class="warn" style="margin-top:12px">'
                    '<div class="wh">⚠️ Cảnh báo video đóng gói — cần xử lý</div>'
                    + "".join(f'<div class="wb">• {w}</div>' for w in _w) + '</div>') if _w else ''
    else:
        iii_rows = (f'<tr><td class="l">🎥 Tổng video đóng hàng hôm nay</td><td class="num">{video_total}</td></tr>'
                    f'<tr><td class="l">📦 Đơn đã đóng gói</td><td class="num">{t["dong_goi"]}</td></tr>')
        vid_note = vid_warn = ''
    _exp_done = next((r for r in rep.get("by_carrier", []) if "Hỏa tốc" in str(r.get("carrier"))), None)
    _tcl = (rep.get("totals") or {}).get("con_lai", 0)
    sec1_note = _info_tip(
        (f'Đóng gói đã gồm <b>{_exp_done["dong_goi"]} đơn hỏa tốc</b> (dòng đầu). ' if _exp_done else '')
        + '<b>Đã xuất kho</b> = số ĐƠN đã bàn giao khỏi kho (= mục “Xuất kho đơn hàng” trong '
          '<b>Báo cáo sổ kho</b>, tính theo đơn — báo cáo sổ kho đếm theo SỐ LƯỢNG sản phẩm). '
          '<b>Shipper thực nhận</b> = ĐVVC đã XÁC NHẬN lấy; '
          '<b>Đã giao khách</b> = đã giao tới tay khách (đơn hỏa tốc nên giao trong ngày). '
          '<b>Chưa x.nhận</b> = Đã xuất kho − Shipper thực nhận.')
    # Auto-sinh lý do chênh lệch các cột để NV kiểm tra (yêu cầu user)
    _lech = _carrier_lech_notes(rep.get("by_carrier", []))
    if _lech:
        lech_html = ('<div class="warn"><div class="wh">⚠️ CHÊNH LỆCH GIỮA CÁC CỘT — NHÂN VIÊN KIỂM TRA</div>'
                     + ''.join(f'<div class="wb">• {n}</div>' for n in _lech) + '</div>')
    else:
        lech_html = ('<div style="font-size:.77em;color:#15803d;margin:.46em 0 0;font-weight:700">'
                     '✅ Các cột khớp nhau (xuất kho = shipper nhận = giao khách) — không có chênh lệch.</div>')
    # Đợt soạn GỒM cả đơn đã hủy đã gói (đã soạn rồi mới hủy)
    _soan = rep.get("tong_don_soan", 0)
    _hdg = rep.get("huy_da_goi", 0)
    sec2_note = (f'<div style="font-size:.77em;color:#6b7280;margin:.4em 0 0">'
                 f'ℹ️ Tổng soạn ({_soan}) = {t["dong_goi"]} đơn đóng gói + '
                 f'<b>{_hdg} đơn đã hủy sau khi soạn</b> (vẫn tính vì kho đã lấy hàng).</div>'
                 if _hdg else '')
    # (Đơn hủy đã chuyển lên block chi tiết ngay dưới phễu — gom theo ĐVVC + ô tick)
    nk = rep.get("nhap_kho") or {}
    nk_src = " · ".join(f"{_e(_SRC.get(k, str(k)))} {v}"
                        for k, v in (nk.get("by_source") or {}).items())

    # ---- Phần ĐƠN HOÀN (render ở TRANG 2) ----
    nk_detail = nk.get("detail") or []
    clip_co = nk.get("clip_co", 0)
    clip_total = nk.get("clip_total", 0)
    unmatched = nk.get("clip_unmatched") or []
    clip_on = nk.get("clip_available", False)
    n_ret = len(nk_detail)
    if not clip_on:
        clip_summary = ''
        clip_note = ('<div style="font-size:.85em;color:#dc2626;margin-top:.46em">'
                     '⚠️ Chưa kết nối Dohana — không kiểm tra được clip khui hàng.</div>')
        warn_box = ''
    else:
        ok = clip_co == n_ret
        col = "#15803d" if ok else "#dc2626"
        clip_summary = (f' <span style="font-size:.96em;color:{col}">({clip_co}/{n_ret} có clip)</span>'
                        if n_ret else '')
        clip_note = ('' if ok or not n_ret else
                     f'<div style="font-size:.85em;color:#dc2626;margin-top:.46em;font-weight:700">'
                     f'⚠️ Có {n_ret - clip_co} đơn hoàn THIẾU clip khui hàng — cần kiểm tra/khiếu nại ngay.</div>')
        if unmatched:
            warn_box = (
                '<div class="warn">'
                f'<div class="wh">⚠️ CẢNH BÁO: {len(unmatched)} clip khui hàng KHÔNG khớp đơn hoàn nào — cần sửa</div>'
                '<div class="wb">Các đơn này thực tế đang <b>giao đi cho khách</b> (không có phiếu hoàn) '
                'nhưng clip lại lưu ở mục “khui hàng” và <b>thiếu video đóng hàng</b> → nghi '
                '<b>quay nhầm chế độ</b> (đóng hàng ↔ khui hàng). Hoặc hàng hoàn <b>chưa bấm nhập kho</b>.</div>'
                '<div class="wb">→ <b>Nhân viên kiểm tra & quay lại clip đúng mục “đóng hàng”</b> cho các mã '
                'dưới đây (để đủ bằng chứng khi khiếu nại):</div>'
                f'<div class="wc">{_e(", ".join(map(str, unmatched)))}</div>'
                '</div>')
        else:
            warn_box = ''

    clip_kpi_v = clip_total if clip_on else "—"
    clip_kpi_sub = (f"khớp {clip_co} · lệch {len(unmatched)}" if clip_on else "chưa kết nối Dohana")
    r_kpis_html = (
        f'<div class="kpi"><div class="l">📥 Hoàn nhập kho hôm nay</div>'
        f'<div class="v">{nk.get("so_phieu", 0)}</div>'
        f'<div class="l" style="margin-top:3px;font-weight:700">{nk.get("so_sp", 0)} SP'
        f'{(" · " + nk_src) if nk_src else ""}</div></div>'
        f'<div class="kpi"><div class="l">↩️ Đang hoàn về (chờ nhận)</div>'
        f'<div class="v">{nk.get("cho_xu_ly", 0)}</div>'
        f'<div class="l" style="margin-top:3px">đang trên đường về kho</div></div>'
        f'<div class="kpi{" hot" if (clip_on and unmatched) else ""}">'
        f'<div class="l">📹 Clip khui hàng hôm nay</div>'
        f'<div class="v">{clip_kpi_v}</div>'
        f'<div class="l" style="margin-top:3px;font-weight:700">{clip_kpi_sub}</div></div>'
    )
    # ── PHỄU: xác nhận → soạn(in phiếu) → video(đóng gói) → quét biên bản → ĐVVC nhận | hủy · còn xót ──
    # 5 ô dòng 1 + 2 ô dòng 2. Mỗi ô có ô ☐ để NV KHO TICK xác nhận trước khi ký cuối.
    # Soạn hàng = đã in phiếu nhặt (dashboard/picklog); Có video = đơn đóng gói đã quay video.
    fn = rep.get("funnel") or {}
    _base = fn.get("base") or fn.get("dong_goi") or 0   # đóng gói GỒM hủy (89) = chuẩn so lệch
    _huy = fn.get("huy") or 0
    _quet, _dvvc, _video, _soan = (fn.get("quet_bien_ban"), fn.get("dvvc_nhan"),
                                   fn.get("video"), fn.get("soan"))

    def _fbox(icon, label, val, lech=0, hot=False, tick=False):
        disp = "—" if val is None else val
        cls, mark = "kpi", ""
        if hot and val:
            cls = "kpi hot"
        if lech and lech > 0:
            cls = "kpi bad"
            mark = f'<div class="lech">▼ lệch {lech}</div>'
        tk = '<div class="tick"><span class="cbox"></span> đã nhận</div>' if tick else ''
        return (f'<div class="{cls}"><div class="l">{icon} {label}</div>'
                f'<div class="v">{disp}</div>{mark}{tk}</div>')

    # Thiếu video = đóng gói (gồm hủy) chưa quay. Quét biên bản nên = đóng gói − hủy (hủy không xuất).
    _lv = max(0, _base - _video) if (isinstance(_video, int) and _base) else 0
    _lq = max(0, (_base - _huy) - _quet) if (isinstance(_quet, int) and _base) else 0
    # ĐVVC đã nhận < đã quét biên bản (xuất kho) = đơn xuất kho mà shipper CHƯA xác nhận → NGHI MẤT ĐƠN
    _ld = (_quet - _dvvc) if (isinstance(_quet, int) and isinstance(_dvvc, int) and _quet > _dvvc) else 0
    _row1 = "".join([
        _fbox("✅", "Đã xác nhận", fn.get("xac_nhan")),
        _fbox("🖨️", "Đã soạn hàng", _soan),
        _fbox("🎥", "Đã có video", _video, lech=_lv),
        _fbox("📋", "Đã quét biên bản", _quet, lech=_lq),
        _fbox("🚚", "ĐVVC đã nhận", _dvvc, lech=_ld),
    ])
    _row2 = "".join([
        _fbox("❌", "Hủy hôm nay", fn.get("huy"), hot=True, tick=True),
        _fbox("⏳", "Còn xót lại", fn.get("con_xot"), tick=True),
    ])
    kpi_html = (f'<div class="kpis kf5">{_row1}</div>'
                f'<div class="kpis kf5">{_row2}</div>')

    # Chi tiết đơn HỦY + CÒN XÓT ngay dưới 2 ô phễu — gom theo ĐVVC, mỗi đơn 1 ô tick xác nhận
    _huy_all = rep.get("huy_all_detail") or []
    _cx_today = rep.get("con_xot_today") or []
    _cx_old = rep.get("con_xot_old") or []
    _conxot = _cx_today + _cx_old
    detail_block = ''
    if _huy_all or _conxot:
        detail_block = (
            '<div class="fdetail">'
            '<div class="fdcol fdcol-huy">'
            f'<div class="fdhead" style="color:#b91c1c">❌ ĐƠN HỦY HÔM NAY ({len(_huy_all)}) '
            '— tick khi đã nhận lại hàng</div>'
            f'{_grouped_tick_rows(_huy_all, mark_packed=True)}</div>'
            '<div class="fdcol fdcol-xot">'
            f'<div class="fdhead" style="color:#b45309">⏳ CÒN XÓT LẠI ({len(_conxot)}) '
            '— đã xuất kho, shipper CHƯA xác nhận</div>'
            f'{_conxot_rows(_cx_today, _cx_old)}</div>'
            '</div>')

    page1 = f"""<div class="page"><div class="pfit">
  <div class="hd">
    <div><div class="brand">VITRAN BOUTIQUE</div>
      <div class="sub">Hệ thống vận hành đơn hàng</div></div>
    <div class="meta">Ngày báo cáo<br><b>{_e(rep["date"])}</b><br>
      <span style="font-size:.95em">In lúc: {_e(now_str)}</span></div>
  </div>

  <div class="title">Báo cáo vận hành cuối ngày</div>
  <div class="title-sub">Phần 1 — Đơn giao đi · đóng gói · soạn hàng · video (dữ liệu Sapo, giờ VN)</div>

  {kpi_html}
  {detail_block}

  {vid_warn}
  {vid_note}

  <div class="sec">I. Số lượng đơn theo đơn vị vận chuyển</div>
  <table>
    <thead><tr><th class="l">Đơn vị vận chuyển</th><th>Đóng gói</th><th>Hủy</th>
      <th>Đã xuất kho</th><th>Shipper thực nhận</th><th>Đã giao khách</th><th>Chưa x.nhận</th></tr></thead>
    <tbody>{_carrier_rows(rep["by_carrier"], t)}</tbody>
  </table>
  {sec1_note}
  {lech_html}

  <div class="sec">II. Số lượng hàng theo đợt soạn</div>
  <table>
    <thead><tr><th class="l">Đợt lấy hàng</th><th>Giờ</th><th>Số đơn</th><th>Số SP</th></tr></thead>
    <tbody>{_batch_rows(rep["batches"], rep["tong_don_soan"], rep["tong_sp_soan"])}</tbody>
  </table>
  {sec2_note}

  <div class="sec">III. Ghi chú / Sự cố trong ngày</div>
  <div class="note"><span style="color:#9aa3af;font-size:.95em">(Ghi tay: đơn GHN còn lại, hỏa tốc tìm tài xế, đơn lỗi…)</span>
    <div class="lines"><div></div></div></div>

  <div class="foot">VITRAN BOUTIQUE · Trang 1/2 — Vận hành đơn giao đi · (ký xác nhận ở mặt sau) · {_e(rep["date"])}</div>
</div></div>"""

    page2 = f"""<div class="page page2"><div class="pfit">
  <div class="hd">
    <div><div class="brand">VITRAN BOUTIQUE</div>
      <div class="sub">Báo cáo đơn hàng hoàn trả</div></div>
    <div class="meta">Ngày báo cáo<br><b>{_e(rep["date"])}</b><br>
      <span style="font-size:.95em">Trang 2 / 2</span></div>
  </div>

  <div class="title">Báo cáo đơn hàng hoàn trả</div>
  <div class="title-sub">Phần 2 — Hàng hoàn nhận về · nhập kho · video khui hàng (Sapo + Dohana)</div>

  <div class="kpis k3">{r_kpis_html}</div>

  {warn_box}

  <div class="sec">A. Chi tiết đơn hàng hoàn nhận hôm nay{clip_summary}</div>
  <table>
    <thead><tr><th>#</th><th class="l">Mã đơn · Vận đơn (giao / hoàn)</th><th>ĐVVC</th>
      <th class="l">Sản phẩm (SKU × SL)</th><th class="l">Loại trả hàng</th>
      <th class="l">🏷️ Tag app đóng hàng</th>
      <th>🎥 Clip khui hàng (thời lượng · giờ quay)</th></tr></thead>
    <tbody>{_returns_clip_rows(nk_detail)}</tbody>
  </table>
  <div style="font-size:.72em;color:#6b7280;margin:.25em 0 0">🔎 Tra Sapo bằng <b>Mã đơn</b> (in đậm) hoặc <b>VĐ giao đi</b>. <b>VĐ hoàn về</b> = mã in trên kiện hàng khách gửi trả (đối chiếu kiện, KHÔNG tra ra ở Sapo).</div>
  {clip_note}

  <div class="sec">B. Ghi chú đơn hoàn / khiếu nại</div>
  <div class="note"><span style="color:#9aa3af;font-size:.95em">(Ghi tay: tình trạng hàng hoàn, đơn cần khiếu nại sàn, thiếu/sai SP…)</span>
    <div class="lines"><div></div></div></div>

  <div class="sign">
    <div><div class="role">NV soạn hàng</div><div class="space"></div><div class="hint">(Ký, ghi rõ họ tên)</div></div>
    <div><div class="role">NV kho</div><div class="space"></div><div class="hint">(Ký, ghi rõ họ tên)</div></div>
    <div><div class="role">Quản lý</div><div class="space"></div><div class="hint">(Ký, ghi rõ họ tên)</div></div>
  </div>

  <div class="foot">VITRAN BOUTIQUE · Trang 2/2 — Đơn hàng hoàn trả · {_e(rep["date"])}</div>
</div></div>"""

    body = page1 + page2

    # Auto-fit: tìm cỡ chữ LỚN NHẤT mà mỗi trang vẫn lọt 1 tờ A4 (nhiều đơn → chữ nhỏ lại,
    # ít đơn → chữ to ra). Dùng nhị phân trên --fs của .pfit so với chiều cao .page (297mm).
    fitjs = (
        "function fitPages(doc){doc=doc||document;"
        "var ps=doc.querySelectorAll('.page');"
        "for(var i=0;i<ps.length;i++){var pg=ps[i],ft=pg.querySelector('.pfit');if(!ft)continue;"
        "var t=pg.clientHeight,lo=8,hi=20,b=lo;"
        "for(var k=0;k<18;k++){var m=(lo+hi)/2;ft.style.fontSize=m+'px';"
        "if(ft.scrollHeight<=t){b=m;lo=m;}else{hi=m;}}"
        "ft.style.fontSize=b.toFixed(2)+'px';}}"
    )
    js = (
        fitjs +
        "function printA4(){"
        "var html=document.getElementById('rp').innerHTML;"
        "var f=document.createElement('iframe');"
        "f.style.cssText='position:fixed;right:0;bottom:0;width:0;height:0;border:0';"
        "document.body.appendChild(f);var d=f.contentWindow.document;d.open();"
        "d.write('<!doctype html><html><head><meta charset=\\\"utf-8\\\"><style>'+"
        + json.dumps(_CSS) + "+'</style><scr'+'ipt>'+" + json.dumps(fitjs)
        + "+'</scr'+'ipt></head><body>'+html+'</body></html>');"
        "d.close();f.onload=function(){try{f.contentWindow.fitPages();}catch(e){}"
        "f.contentWindow.focus();f.contentWindow.print();"
        "setTimeout(function(){document.body.removeChild(f);},700);};}"
        "window.addEventListener('load',function(){fitPages();});"
        "setTimeout(function(){fitPages();},300);"
    )
    return (
        "<style>" + _CSS + "</style>"
        "<div class='toolbar'><button class='printbtn' onclick='printA4()'>🖨️ In báo cáo A4 / Lưu PDF</button></div>"
        "<div id='rp'>" + body + "</div>"
        "<script>" + js + "</script>"
    )
