"""
daily_report.py — Render BÁO CÁO VẬN HÀNH CUỐI NGÀY (khổ A4) từ get_daily_report() + Dohana.
Trả 1 chuỗi HTML (nhúng bằng components.html) gồm nút In A4 + báo cáo bố cục chuyên nghiệp.
"""
import json
from collections import OrderedDict
from html import escape as _e


def _tag_label(tag, tag_id=""):
    tag = str(tag or "").strip()
    tid = str(tag_id or "").strip()
    if not tag:
        return ""
    if tag in ("⚠️ Có tag", "Có tag"):
        return f"⚠️ Tag chưa map tên{f' (id {tid[:8]})' if tid else ''}"
    return tag


_CSS = """
  --navy:#16233f; --accent:#E24B4A; --line:#cfd6e0; --grid:#8c98ab; --soft:#eef1f6; --ink:#1f2733;
  body{font-family:Tahoma,Verdana,'Segoe UI',system-ui,Roboto,Arial,sans-serif;margin:0;background:#e9edf2;color:var(--ink);}
  .toolbar{position:sticky;top:0;background:#e9edf2;padding:8px;text-align:center;z-index:5;}
  .printbtn{background:var(--accent);color:#fff;border:0;border-radius:9px;padding:10px 20px;font-size:14px;font-weight:800;cursor:pointer;box-shadow:0 2px 8px rgba(226,75,74,.4);}
  .page{width:210mm;height:297mm;margin:0 auto 14px;background:#fff;box-sizing:border-box;box-shadow:0 2px 14px rgba(0,0,0,.12);overflow:hidden;}
  .pfit{padding:9mm 11mm 8mm;font-size:var(--fs,13px);box-sizing:border-box;}
  .page.fixed .pfit{font-size:12px;}
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
  th,td{border:1px solid #5b6878;padding:.23em .54em;text-align:center;}
  table{border:2px solid #3f4a5a;}
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
  .foot{margin-top:.36em;text-align:center;font-size:.73em;color:#9aa3af;border-top:1px solid var(--line);padding-top:.2em;}
  .page2{page-break-before:always;page:return-portrait;width:210mm;height:297mm;}
  .page2 .pfit{padding:7mm 7mm 5mm;}
  .page2 .hd{padding-bottom:.2em;border-bottom-width:2px;}
  .page2 .hd .brand{font-size:1.22em;}
  .page2 .title{margin:.24em 0 .04em;font-size:1.08em;}
  .page2 .title-sub{margin-bottom:.2em;}
  .page2 .kpis.kf5{grid-template-columns:repeat(3,1fr);gap:.28em;margin:.24em 0 .3em;}
  .page2 .kf5 .kpi{padding:.18em .34em;}
  .page2 .kf5 .kpi .l{font-size:.9em;line-height:1.22;}
  .page2 .kf5 .kpi .v{font-size:1.62em;}
  .page2 .warn{padding:.28em .55em;margin:.28em 0 .34em;}
  .page2 .warn .wh{font-size:1em;}
  .page2 .warn .wb{font-size:.88em;line-height:1.32;}
  .page2 .warn .wc{font-size:.94em;}
  .page2 .sec{margin:.32em 0 .16em;padding:.18em .5em;}
  .return-table{font-size:1.08em;line-height:1.22;}
  .return-table th,.return-table td{padding:.22em .36em;}
  .return-table th:first-child,.return-table td:first-child{white-space:nowrap;padding-left:.15em;padding-right:.15em;}
  .mono-code{white-space:nowrap;word-break:normal;overflow-wrap:normal;font-size:.9em;letter-spacing:0;font-variant-numeric:tabular-nums;}
  .kpis.k3{grid-template-columns:repeat(3,1fr);}
  .kpis.kf4{grid-template-columns:repeat(4,1fr);gap:.38em;margin:.3em 0 .4em;}
  .kpis.kf3{grid-template-columns:repeat(3,1fr);gap:.38em;margin:.3em 0 .4em;}
  .kpis.kf2{grid-template-columns:repeat(2,1fr);gap:.6em;margin:.5em 0 0;}
  .kpi.strong{border:2px solid var(--navy);background:#eaf0fb;}
  .kpi.huytone{background:#fdf3f2;border-color:#e6b3ab;}
  .kpi.xottone{background:#fff8ec;border-color:#e3c485;}
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
  .fdetail{display:grid;grid-template-columns:1fr 1fr;gap:.6em;margin:.2em 0 .7em;}
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
  @page return-portrait{size:A4 portrait;margin:0;}
  @media print{
    body{background:#fff;} .toolbar{display:none;}
    .page{box-shadow:none;margin:0;}
    table,tr,td,th{page-break-inside:avoid;}
    *{-webkit-print-color-adjust:exact;print-color-adjust:exact;}
  }
"""


def _carrier_rows(rows, tot, video_total=0, cancel_split=None):
    cancel_split = cancel_split or {}
    body = ""
    for r in rows:
        hot = "Hỏa tốc" in str(r["carrier"])
        cname = str(r["carrier"])
        cs = cancel_split.get(cname, {})
        cls = ' style="background:#fff3ed"' if hot else ''
        _cl = r["con_lai"]
        _clc = (f'<td class="num" style="color:#dc2626;font-weight:800">{_cl}</td>'
                if _cl else '<td class="num"></td>')
        # Đã giao khách — quan trọng với hỏa tốc: shipper nhận > giao khách = đơn đang giao / BỊ TRẢ VỀ
        _gk = r.get("giao_khach", 0)
        _gk_warn = hot and r["shipper_nhan"] > _gk
        _gkc = (f'<td class="num" style="color:#c2410c;font-weight:800">{_gk}</td>'
                if _gk_warn else f'<td class="num">{_gk or ""}</td>')
        _dgcu = r.get("dg_cu", 0)
        _soan = r.get("soan")
        if _soan is None:
            _soan = int(_dgcu or 0) + int(r.get("dong_goi") or 0)
        _htr = cs.get("truoc")
        _hsa = cs.get("sau")
        if _htr is None and _hsa is None:
            _hsa = r.get("huy_sau")
            _htr = r.get("huy_truoc")
        _cxp, _cxu = r.get("cx_packed", 0), r.get("cx_unpacked", 0)
        _cxpc = (f'<td class="num" style="color:#c2410c;font-weight:800">{_cxp}</td>'
                 if _cxp else '<td class="num"></td>')
        _cxuc = (f'<td class="num" style="color:#b45309;font-weight:800">{_cxu}</td>'
                 if _cxu else '<td class="num"></td>')
        body += (f'<tr{cls}><td class="l">{"⚡ " if hot else ""}{_e(str(r["carrier"]))}</td>'
                 f'<td class="num">{_soan or ""}</td>'
                 f'<td class="num">{_dgcu or ""}</td>'
                 f'<td class="num">{r["dong_goi"]}</td>'
                 f'<td class="num">{int(_htr or 0) or ""}</td>'
                 f'<td class="num">{int(_hsa or 0) or ""}</td>'
                 f'<td class="num">{r.get("video", "") or ""}</td>'
                 f'<td class="num">{r.get("xuat_kho", 0)}</td>'
                 f'<td class="num">{r["shipper_nhan"]}</td>' + _gkc + _clc + _cxpc + _cxuc + '</tr>')
    body = body or '<tr><td class="l" colspan="13">—</td></tr>'
    _tcl = tot["con_lai"]
    _tsoan = tot.get("soan")
    if _tsoan is None:
        _tsoan = int(tot.get("dg_cu", 0) or 0) + int(tot.get("dong_goi", 0) or 0)
    _htr_tot = sum(int(v.get("truoc") or 0) for v in cancel_split.values())
    _hsa_tot = sum(int(v.get("sau") or 0) for v in cancel_split.values())
    if not (_htr_tot or _hsa_tot):
        _hsa_tot = int(tot.get("huy_sau") or 0)
        _htr_tot = int(tot.get("huy_truoc") or 0)
    if not (_htr_tot or _hsa_tot):
        _hsa_tot = int(tot.get("huy") or 0)
        _htr_tot = 0
    body += (f'<tr class="total"><td class="l">TỔNG CỘNG</td>'
             f'<td class="num">{_tsoan or ""}</td>'
             f'<td class="num">{tot.get("dg_cu", 0) or ""}</td>'
             f'<td class="num">{tot["dong_goi"]}</td>'
             f'<td class="num">{_htr_tot or ""}</td>'
             f'<td class="num accent">{_hsa_tot or ""}</td>'
             f'<td class="num">{int(video_total or 0) or ""}</td>'
             f'<td class="num">{tot.get("xuat_kho", 0)}</td>'
             f'<td class="num">{tot["shipper_nhan"]}</td>'
             f'<td class="num">{tot.get("giao_khach", 0) or ""}</td>'
             f'<td class="num{" accent" if _tcl else ""}">{_tcl or ""}</td>'
             f'<td class="num">{tot.get("cx_packed", 0) or ""}</td>'
             f'<td class="num">{tot.get("cx_unpacked", 0) or ""}</td></tr>')
    return body


def _carrier_lech_notes(rows):
    """Tự sinh LÝ DO chênh lệch khi các cột cộng/trừ không khớp — để NV biết đường kiểm tra."""
    notes = []
    for r in rows:
        c = str(r["carrier"])
        hot = "Hỏa tốc" in c
        dg = r.get("dg_cu", 0) + r.get("dong_goi", 0)   # tổng đã đóng gói (cũ + hôm nay)
        x = r.get("xuat_kho", 0)
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


def _grouped_tick_rows(detail, mark_packed=False, force_pk=False, tick=True):
    """Liệt kê đơn GOM THEO ĐVVC, mỗi đơn 1 ô tick + mã đơn + mã VĐ + SKU×SL.
    force_pk=True → mọi đơn đều gắn 'cần lấy lại' (nhóm đã soạn). tick=False → bỏ ô tick."""
    if not detail:
        return '<div class="dline" style="color:#9aa3af">— Không có đơn —</div>'
    groups = OrderedDict()
    for d in detail:
        groups.setdefault(str(d.get("carrier") or "?"), []).append(d)
    _box = ('<span class="cbox2"></span> ' if tick
            else '<span style="display:inline-block;width:.85em;margin-right:2px"></span>')
    html = ""
    for cr, items in groups.items():
        html += f'<div class="dvgrp">▸ {_e(cr)} ({len(items)})</div>'
        for d in items:
            nm = _e(str(d.get("name") or "?"))
            tk = str(d.get("tracking") or "")
            tk_html = f' · <span class="vd">{_e(tk)}</span>' if tk and tk != d.get("name") else ""
            pk = (' <span class="pk">📦 cần lấy lại</span>'
                  if (force_pk or (mark_packed and d.get("packed"))) else "")
            html += (f'<div class="dline">{_box}'
                     f'<b>{nm}</b>{tk_html} · {_e(str(d.get("sku", "")))}{pk}</div>')
    return html


def _huy_split_html(huy_all, soan_known):
    """Tách đơn hủy 2 nhóm: ĐÃ SOẠN (mã ∈ phiếu nhặt → cầm hàng ra kho → CẦN LẤY LẠI) vs
    CHƯA SOẠN (mã không có trong phiếu nhặt → hủy sớm, KHỎI lấy lại).
    soan_known=False (ngày chưa lưu mã phiếu nhặt) → chưa tách được, dùng danh sách cũ + ghi chú."""
    if not huy_all:
        return '<div class="dline" style="color:#9aa3af">— Không có đơn —</div>'
    if not soan_known:
        return (_grouped_tick_rows(huy_all, mark_packed=True)
                + '<div class="dline" style="color:#9aa3af;font-size:.9em">'
                  '(Ngày này phiếu nhặt chưa lưu mã đơn nên chưa tách được nhóm "cần lấy lại thật")</div>')
    _soan = [d for d in huy_all if d.get("soan")]
    _som = [d for d in huy_all if not d.get("soan")]
    h = ""
    if _soan:
        h += ('<div style="color:#b91c1c;font-weight:800;margin:1px 0 2px">'
              f'📦 CẦN LẤY LẠI — đã soạn, đã cầm hàng ra kho ({len(_soan)}) · tick khi đã nhận lại</div>'
              + _grouped_tick_rows(_soan, force_pk=True))
    if _som:
        h += ('<div style="color:#6b7280;font-weight:800;margin:5px 0 2px">'
              f'⚪ HỦY SỚM — chưa soạn, KHỎI lấy lại ({len(_som)})</div>'
              + _grouped_tick_rows(_som, tick=False))
    return h


def _conxot_rows(packed, unpacked, collapse=False):
    """Còn xót tách 2 nhóm theo TRẠNG THÁI ĐÓNG HÀNG: ĐÃ đóng (cần xác nhận lấy lại hàng — có
    ô tick) vs CHƯA đóng (chưa gói → không cần lấy lại, không tick).
    collapse=True (trước 18h, shipper chưa tới) → mỗi ĐVVC chỉ hiện 5 đơn, còn lại ghi '…'."""
    def _lines(items, need_tick):
        if not items:
            return '<div class="dline" style="color:#9aa3af">— không có —</div>'
        groups = OrderedDict()
        for d in items:
            groups.setdefault(str(d.get("carrier") or "?"), []).append(d)
        h = ""
        for cr, gitems in groups.items():
            shown = gitems[:5] if collapse else gitems
            for d in shown:
                tk = str(d.get("tracking") or "")
                tk_html = f' · <span class="vd">{_e(tk)}</span>' if tk and tk != d.get("name") else ""
                box = ('<span class="cbox2"></span> ' if need_tick
                       else '<span style="display:inline-block;width:.85em;margin-right:2px"></span>')
                mk = ' <span class="pk">📦 lấy lại</span>' if need_tick else ''
                h += (f'<div class="dline">{box}<b>{_e(str(d.get("name", "?")))}</b>'
                      f'{tk_html} · {_e(str(d.get("carrier", "")))} · {_e(str(d.get("sku", "")))}{mk}</div>')
            if collapse and len(gitems) > 5:
                h += (f'<div class="dline" style="color:#b45309;font-style:italic">'
                      f'… còn <b>{len(gitems) - 5} đơn {_e(cr)}</b> (rút gọn cho dễ đọc)</div>')
        return h
    return (f'<div class="dvgrp" style="color:#b91c1c">▸ ĐÃ đóng hàng ({len(packed)}) '
            '— ☐ tick khi đã LẤY LẠI hàng</div>'
            + _lines(packed, True)
            + f'<div class="dvgrp" style="color:#475569;margin-top:3px">'
              f'▸ CHƯA đóng hàng ({len(unpacked)}) — không cần lấy lại</div>'
            + _lines(unpacked, False))


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
            cell = (f'<span style="color:#15803d;font-weight:800">✓ Có'
                    f'{" ×" + str(cnt) if cnt > 1 else ""}</span>')
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
        # Tag khui hàng = hàng có vấn đề. Nếu đã nằm trong bảng nhập kho thì phải cảnh báo.
        tag = _tag_label(d.get("clip_tag"), d.get("clip_tag_id"))
        if tag:
            tag_cell = (f'<span style="color:#b91c1c;font-weight:900;background:#fee2e2;'
                        f'padding:1px 5px;border-radius:4px">🏷️ {_e(str(tag))}</span>'
                        '<div style="font-size:.78em;color:#b91c1c;font-weight:800;margin-top:2px">'
                        '⚠️ Đã nhập kho đơn có tag</div>')
        else:
            tag_cell = '<span style="color:#cbd5e1">—</span>'
        # 2 MÃ TRA CỨU: (1) Mã đơn = tra Sapo + SÀN; (2) Mã clip = tra APP ĐÓNG HÀNG (Dohana)
        _oc = str(d.get("order_code") or d.get("tracking") or "?")
        _cc = str(d.get("clip_code") or "")
        _ma = (f'<div><b>{_e(_oc)}</b> '
               f'<span style="font-size:.72em;color:#9ca3af">Sapo · sàn</span></div>')
        if _cc:
            _altc = " · mã khác" if d.get("clip_altcode") else ""
            _ma += (f'<div style="font-size:.86em;color:#6d28d9">🎥 {_e(_cc)} '
                    f'<span style="font-size:.85em;color:#9ca3af">app đóng hàng{_altc}</span></div>')
        else:
            _ma += '<div style="font-size:.82em;color:#cbd5e1">🎥 — chưa có clip Dohana</div>'
        body += (f'<tr><td>{i}</td>'
                 f'<td class="l">{_ma}</td>'
                 f'<td>{_e(str(d.get("carrier", "")))}</td>'
                 f'<td class="l">{_e(str(d.get("sku", "")))}</td>'
                 f'<td class="l" style="{lt_style}">{_e(str(lt))}</td>'
                 f'<td class="l">{tag_cell}</td>'
                 f'<td{tdcls}>{cell}</td></tr>')
    return body or '<tr><td colspan="7">Hôm nay không có đơn hoàn nhập kho.</td></tr>'


def _return_carrier_label(row):
    raw = str((row or {}).get("carrier") or "").strip()
    key = raw.lower()
    if not raw or raw in ("?", "—"):
        return "Chưa xác định"
    if "j&t" in key or key == "jt":
        return "J&T Express"
    if "spx" in key:
        return "SPX Express"
    if "viettel" in key or key == "vtp":
        return "Viettel Post"
    if "giao hàng nhanh" in key or key == "ghn":
        return "Giao Hàng Nhanh"
    return raw


def _short_store_label(value):
    """Tên gian hàng ngắn để bảng A4 không lặp tên kênh hai lần."""
    raw = str(value or "").strip()
    key = raw.lower()
    if not raw:
        return "Chưa xác định"
    if "smoss" in key:
        brand = "SMOSS"
    elif "mun" in key and "ai" in key:
        brand = "MUN AI"
    elif "vitran" in key:
        brand = "VITRAN"
    else:
        brand = raw.split(" - ")[0].strip()
    if "tiktok" in key:
        return f"{brand} · TikTok"
    if "shopee" in key:
        return f"{brand} · Shopee"
    return brand


def _return_sort_key(row):
    carrier = _return_carrier_label(row)
    type_order = {"delivery_failed": 0, "return_and_refund": 1, "refund": 2}
    return (
        carrier != "Chưa xác định",
        carrier.lower(),
        type_order.get(str(row.get("loai_tra_code") or ""), 9),
        str(row.get("order_code") or row.get("clip_code") or ""),
    )


def _recon_rows(rows, start=0, clip_on=True):
    """Đối chiếu mỗi sự kiện hoàn, nhóm ĐVVC trước rồi đến loại trả hàng."""
    body = ""
    _prev_carrier = None
    _prev_lt = None
    _cols = 5
    for i, r in enumerate(rows, start + 1):
        _carrier = _return_carrier_label(r)
        if _carrier != _prev_carrier:
            body += (f'<tr><td colspan="{_cols}" style="background:#dbeafe;color:#1e3a8a;'
                     f'font-weight:900;padding:6px 8px;text-transform:uppercase">'
                     f'🚚 ĐVVC: {_e(_carrier)}</td></tr>')
            _prev_carrier = _carrier
            _prev_lt = None
        _ltn = r.get("loai_tra") or "—"
        if _ltn != _prev_lt:
            _df = r.get("loai_tra_code") == "delivery_failed"
            body += (f'<tr><td colspan="{_cols}" style="background:{"#fdece3" if _df else "#eef6ea"};'
                     f'color:{"#c2410c" if _df else "#166534"};font-weight:800;padding:5px 8px">'
                     f'↳ 📦 Loại trả: {_e(str(_ltn))}</td></tr>')
            _prev_lt = _ltn
        # ── Cột 1: CLIP KHUI HÀNG (Dohana) ──
        if r.get("has_clip"):
            _alt = ' <span style="color:#b45309;font-weight:700">(mã khác)</span>' if r.get("clip_alt") else ""
            _cs = []
            if r.get("clip_dur"):
                _cs.append(f'{r["clip_dur"]}s')
            if r.get("clip_time"):
                _cs.append(str(r["clip_time"]))
            clip_cell = (f'<b style="color:#6d28d9">🎥 <span class="mono-code">'
                         f'{_e(str(r.get("clip_code") or "?"))}</span></b>{_alt}'
                         + (f'<div style="font-size:.82em;color:#6b7280">⏱ {_e(" · ".join(_cs))}</div>'
                            if _cs else ''))
            clip_td = ""
        elif clip_on:
            clip_cell = '<span style="color:#dc2626;font-weight:800">✗ CHƯA quay clip khui hàng — kiểm tra Dohana</span>'
            clip_td = ' style="background:#fef2f2"'
        else:   # Dohana 429/lỗi: KHÔNG kết luận "chưa quay" — chỉ là tạm không lấy được clip
            clip_cell = '<span style="color:#9ca3af">— Dohana tạm không lấy được clip</span>'
            clip_td = ''
        _row_tag = _tag_label(r.get("clip_tag"), r.get("clip_tag_id"))
        if _row_tag:
            clip_cell += (f'<div style="margin-top:2px"><span style="color:#6d28d9;font-weight:800;'
                          f'background:#f3e8ff;padding:1px 5px;border-radius:4px">'
                          f'🏷️ {_e(str(_row_tag))}</span></div>')
        # ── Cột 2: ĐÃ NHẬN HÀNG TRẢ (Sapo) ──
        if r.get("has_sapo"):
            _ss = []
            if r.get("recv_time"):
                _ss.append(f'📥 {_e(str(r["recv_time"]))}')
            if r.get("nhan_vien"):
                _ss.append(f'👤 {_e(str(r["nhan_vien"]))}')
            _tag = _tag_label(r.get("clip_tag"), r.get("clip_tag_id"))
            # DÒNG SL NHẬP KHO: khách trả THIẾU (nhập < kỳ vọng) → đỏ đậm cảnh báo; đủ → xanh
            _spn, _spe = r.get("sp_nhap"), r.get("sp")
            if _spn is not None and _spe is not None and _spn < _spe:
                _nhap = (f'<div style="font-size:.85em;color:#dc2626;font-weight:800">'
                         f'📦 Nhập kho {_spn}/{_spe} SP — ⚠️ TRẢ THIẾU</div>')
            else:
                _nhap = ''
            _tag_warn = (
                f'<div style="font-size:.85em;color:#b91c1c;font-weight:900;margin-top:2px">'
                f'⚠️ ĐÃ nhập kho dù clip có tag “{_e(str(_tag))}” — kiểm tra/gỡ nhập kho nếu hàng hư hỏng, thiếu, sai hoặc tráo.</div>'
                if _tag else '')
            sapo_cell = (f'<b class="mono-code">{_e(str(r.get("order_code") or "?"))}</b>'
                         + (f'<div style="font-size:.82em;color:#6b7280">{" · ".join(_ss)}</div>'
                            if _ss else '')
                         + f'<div style="font-size:.88em;color:#475569">🏪 {_e(_short_store_label(r.get("gian_hang")))}</div>'
                         + _nhap + _tag_warn)
            sapo_td = ' style="background:#fef2f2"' if _tag else ""
        else:
            _oc = r.get("order_code") or ""
            _tag = _tag_label(r.get("clip_tag"), r.get("clip_tag_id"))
            _ocb = f'<b class="mono-code">{_e(str(_oc))}</b><br>' if _oc else ''
            if _tag:
                _rsn = (f'✓ KHÔNG nhập kho Sapo — đúng quy trình vì clip có tag “{_e(str(_tag))}”. '
                        'Giữ xử lý tranh chấp/khiếu nại sàn, giữ clip làm bằng chứng.')
                sapo_cell = (f'{_ocb}<div style="font-size:.82em;color:#475569">'
                             f'🏪 {_e(_short_store_label(r.get("gian_hang")))}</div>'
                             f'<span style="color:#15803d;font-weight:900">{_rsn}</span>')
                sapo_td = ' style="background:#f0fdf4"'
            else:
                _rsn = '✗ CHƯA bấm nhập kho trên Sapo — kiểm tra: quên nhập kho / quay nhầm mục / quay trùng'
                sapo_cell = (f'{_ocb}<div style="font-size:.82em;color:#475569">'
                             f'🏪 {_e(_short_store_label(r.get("gian_hang")))}</div>'
                             f'<span style="color:#dc2626;font-weight:800">{_rsn}</span>')
                sapo_td = ' style="background:#fef2f2"'
        # ── SKU · Loại trả ──
        sku = _e(str(r.get("sku") or "—"))
        _vdg = str(r.get("vd_gui") or "")
        vdg_cell = (f'<span class="mono-code">{_e(_vdg)}</span>' if _vdg and _vdg != r.get("order_code")
                    else '<span style="color:#cbd5e1">—</span>')
        # Mã ĐƠN trả (tra trên sàn, vd 585...-R1) — KHÁC mã vận đơn trả (đã có ở cột VĐ)
        _rct = str(r.get("return_code") or "")
        vdt_cell = (f'<span class="mono-code">{_e(_rct)}</span>'
                    if _rct else '<span style="color:#cbd5e1">—</span>')
        _vdr = str(r.get("track_return") or "")
        vdr_cell = (f'<span class="mono-code">{_e(_vdr)}</span>'
                    if _vdr else '<span style="color:#cbd5e1">—</span>')
        if _vdg and _vdr and _vdg == _vdr:
            transport_cell = (f'<div><span style="color:#64748b;font-weight:700">VĐ đi/hoàn:</span> '
                              f'{vdr_cell}</div>')
        else:
            transport_cell = (
                f'<div><span style="color:#64748b;font-weight:700">Đi:</span> {vdg_cell}</div>'
                f'<div><span style="color:#64748b;font-weight:700">Hoàn:</span> {vdr_cell}</div>'
            )
        transport_cell += f'<div><span style="color:#64748b;font-weight:700">Mã trả:</span> {vdt_cell}</div>'
        body += (f'<tr><td>{i}</td>'
                 f'<td class="l"{clip_td}>{clip_cell}</td>'
                 f'<td class="l"{sapo_td}>{sapo_cell}</td>'
                 f'<td class="l">{transport_cell}</td>'
                 f'<td class="l">{sku}</td></tr>')
    return body or f'<tr><td colspan="{_cols}">Hôm nay không có đơn hoàn / clip khui hàng.</td></tr>'


def report_html(rep, dv, now_str, sign_on="1", collapse_xot=True):
    t = rep["totals"]
    video_total = (dv or {}).get("total", "—")
    # ---- VIDEO ĐÓNG GÓI: trình bày theo góc ĐƠN (đơn đóng gói có / thiếu video) ----
    vr = rep.get("video_recon") or {}
    if vr.get("available"):
        _have = int(vr.get("open_with_video") or 0)
        _miss_codes = vr.get("missing_codes") or []
        _is_pick_video = vr.get("source") == "picklog_dedup"
        _video_subject = "Đơn trong phiếu nhặt đã khử trùng" if _is_pick_video else "Đơn đóng gói hôm nay"
        _video_base = rep.get("tong_don_soan") if _is_pick_video else t["dong_goi"]
        _mv_raw = max(0, int(_video_base or 0) - _have)
        try:
            _mv = int(vr.get("missing_video")) if vr.get("missing_video") is not None else _mv_raw
        except Exception:
            _mv = _mv_raw
        _raw_total = int(vr.get("total") or 0)
        _unique_total = int(vr.get("unique_total") or _raw_total or 0)
        _match_note = ""
        if _raw_total and _raw_total != _have:
            _match_note = f" Dohana có {_raw_total} clip thô"
            if _unique_total and _unique_total != _raw_total:
                _match_note += f" / {_unique_total} mã unique"
            _match_note += f"; khớp được {_have} đơn."
        _miss_row = (f'<tr><td class="l" style="padding-left:20px;color:#b45309">⤷ ⚠️ Thiếu video</td>'
                     f'<td class="num" style="color:#b45309;font-weight:900">{_mv}</td></tr>'
                     if _mv else
                     '<tr><td class="l" style="padding-left:20px;color:#15803d">⤷ ✅ Đủ video (100%)</td>'
                     '<td class="num" style="color:#15803d;font-weight:800">✓</td></tr>')
        iii_rows = (
            f'<tr><td class="l">📦 {_video_subject}</td>'
            f'<td class="num" style="font-weight:900">{_video_base}</td></tr>'
            f'<tr><td class="l" style="padding-left:20px">⤷ ✅ Đã có video đóng gói</td>'
            f'<td class="num">{_have}</td></tr>'
            + _miss_row)
        _ff = vr.get("font_fixed") or []
        vid_note = _info_tip(
            'Đơn đóng gói đã gồm cả <b>đơn hỏa tốc giao xong trong ngày</b> (dòng “Hỏa tốc” bảng ĐVVC). '
            + (f'<b>{_mv} đơn chưa tìm thấy video khớp</b> — xem cảnh báo.'
               if _mv else 'Tất cả đơn đóng gói đều có video.')
            + _e(_match_note))
        _w = []
        if _mv:
            _ml = ", ".join(_e(str(c)) for c in _miss_codes[:8]) + (f" …(+{_mv - 8})" if _mv > 8 else "")
            _w.append(f'<b>{_mv} đơn trong phiếu nhặt/đóng gói nhưng CHƯA TÌM THẤY video khớp</b> '
                      f'(có thể: chưa quay · quay nhầm mục “khui hàng” · mã lỗi phông nặng) '
                      f'— kiểm tra Dohana. Mã: {_ml}')
        if vr.get("dup"):
            _dl = ", ".join(f'{_e(str(k))}×{v}' for k, v in vr["dup"].items())
            _w.append(f'<b>{len(vr["dup"])} đơn quay TRÙNG (≥2 lần)</b>: {_dl}.')
        vid_warn = ('<div class="warn" style="margin-top:12px">'
                    '<div class="wh">⚠️ Cảnh báo video đóng gói — cần xử lý</div>'
                    + "".join(f'<div class="wb">• {w}</div>' for w in _w) + '</div>') if _w else ''
        # Clip mã bị LỖI PHÔNG / dính mã nhưng ĐÃ tự khớp (NV quay đủ, không phải thiếu)
        if _ff:
            _fl = ", ".join(f'{_e(str(v))}↔{_e(str(o))}' for v, o in _ff[:6]) + (
                f' …(+{len(_ff) - 6})' if len(_ff) > 6 else '')
            vid_warn += (
                '<div class="warn" style="margin-top:8px;border-color:#2563eb;background:#eff6ff">'
                '<div class="wh" style="color:#1d4ed8">ℹ️ Clip mã bị lỗi phông / dính mã — ĐÃ tự khớp</div>'
                f'<div class="wb">• {len(_ff)} clip NV quay ĐỦ nhưng mã bị méo (vd {_fl}) — '
                'đã tự nhận diện, KHÔNG tính thiếu. Nên sửa app đóng hàng để mã chuẩn.</div></div>')
    else:
        iii_rows = (f'<tr><td class="l">🎥 Tổng video đóng hàng hôm nay</td><td class="num">{video_total}</td></tr>'
                    f'<tr><td class="l">📦 Đơn đã đóng gói</td><td class="num">{t["dong_goi"]}</td></tr>')
        vid_note = vid_warn = ''
    _exp_done = next((r for r in rep.get("by_carrier", []) if "Hỏa tốc" in str(r.get("carrier"))), None)
    _tcl = (rep.get("totals") or {}).get("con_lai", 0)
    sec1_note = _info_tip(
        '<b>Cần gửi · Cũ</b> = đơn xác nhận từ hôm trước, hôm nay mới xuất/xử lý; <b>· Hôm nay</b> = đơn xác nhận hôm nay. '
        '<b>Video</b> = số đơn đã khớp được clip đóng hàng Dohana. '
        '<b>Hủy trước soạn</b> = khách hủy sớm, chưa cầm hàng; <b>Hủy sau soạn</b> = đã soạn/gói, cần lấy lại. '
        '<b>Đã xuất kho</b> = số ĐƠN đã bàn giao khỏi kho (= mục “Xuất kho đơn hàng” trong '
        '<b>Báo cáo sổ kho</b>, tính theo đơn). '
        '<b>Shipper thực nhận</b> = ĐVVC đã XÁC NHẬN lấy; '
        '<b>Đã giao khách</b> = đã giao tới tay khách (đơn hỏa tốc giao trong ngày). '
        '<b>Chưa x.nhận</b> = Đã xuất kho − Shipper thực nhận (nghi mất đơn). '
        '<b>Còn xót lại</b> = đơn đã xác nhận nhưng CHƯA giao shipper: <b>Đã gói</b> (gói rồi, '
        'chờ giao — cần lấy lại nếu hủy) / <b>Chưa gói</b> (chưa đóng gói).')
    # Auto-sinh lý do chênh lệch các cột để NV kiểm tra (yêu cầu user)
    _lech = _carrier_lech_notes(rep.get("by_carrier", []))
    if _lech:
        lech_html = ('<div class="warn"><div class="wh">⚠️ CHÊNH LỆCH GIỮA CÁC CỘT — NHÂN VIÊN KIỂM TRA</div>'
                     + ''.join(f'<div class="wb">• {n}</div>' for n in _lech) + '</div>')
    else:
        lech_html = ('<div style="font-size:.77em;color:#15803d;margin:.46em 0 0;font-weight:700">'
                     '✅ Các cột khớp nhau (xuất kho = shipper nhận = giao khách) — không có chênh lệch.</div>')
    _cancel_split = {}
    for _h in rep.get("huy_all_detail") or []:
        _c = str(_h.get("carrier") or "?")
        _entry = _cancel_split.setdefault(_c, {"truoc": 0, "sau": 0})
        if _h.get("soan") or _h.get("packed"):
            _entry["sau"] += 1
        else:
            _entry["truoc"] += 1
    _video_for_table = int((rep.get("video_recon") or {}).get("open_with_video") or 0)
    # Đợt soạn GỒM cả đơn đã hủy đã gói (đã soạn rồi mới hủy)
    _soan = rep.get("tong_don_soan", 0)
    _hdg = rep.get("huy_da_goi", 0)
    if rep.get("soan_source") == "picklog_dedup":
        _dup = int(rep.get("soan_dup_orders") or 0)
        _dup_txt = f" Đã tự bỏ {_dup} đơn/mã bị lưu trùng." if _dup else ""
        sec2_note = (f'<div style="font-size:.77em;color:#6b7280;margin:.4em 0 0">'
                     f'ℹ️ Tổng soạn ({_soan}) lấy từ lịch sử phiếu nhặt đã lưu, '
                     f'đã khử trùng theo mã đơn/vận đơn.{_dup_txt}</div>')
    elif _hdg and _soan == int(t.get("dong_goi") or 0) + int(_hdg or 0):
        sec2_note = (f'<div style="font-size:.77em;color:#6b7280;margin:.4em 0 0">'
                     f'ℹ️ Tổng soạn ({_soan}) = {t["dong_goi"]} đơn đóng gói + '
                     f'<b>{_hdg} đơn đã hủy sau khi soạn</b> (vẫn tính vì kho đã lấy hàng).</div>')
    elif _hdg:
        sec2_note = (f'<div style="font-size:.77em;color:#6b7280;margin:.4em 0 0">'
                     f'ℹ️ Tổng soạn ({_soan}) lấy theo các đợt đóng gói Sapo; '
                     f'có <b>{_hdg} đơn đã hủy sau khi soạn</b> vẫn cần tính vì kho đã lấy hàng.</div>')
    else:
        sec2_note = ''
    _miss_pick = rep.get("confirmed_not_in_picklog") or []
    if _miss_pick:
        _miss_rows = []
        for _m in _miss_pick[:30]:
            _name = _m.get("name") or ""
            _tracking = _m.get("tracking") or ""
            _code = _name or _tracking or next((str(c) for c in (_m.get("codes") or []) if c), "?")
            _extra = []
            if _tracking and _tracking != _code:
                _extra.append(f"VD {_e(_tracking)}")
            if _m.get("carrier"):
                _extra.append(_e(_m.get("carrier")))
            if _m.get("sku"):
                _extra.append(_e(_m.get("sku")))
            _miss_rows.append(f'<div class="wb">• <b>{_e(_code)}</b>'
                              f'{(" · " + " · ".join(_extra)) if _extra else ""}</div>')
        _more = len(_miss_pick) - len(_miss_rows)
        _more_txt = f'<div class="wb">… còn {_more} đơn nữa</div>' if _more > 0 else ''
        sec2_note += (
            '<div class="warn" style="margin-top:.5em">'
            f'<div class="wh">⚠️ Sapo xác nhận nhưng chưa thấy trong phiếu nhặt ({len(_miss_pick)} đơn)</div>'
            + ''.join(_miss_rows) + _more_txt + '</div>')
    # (Đơn hủy đã chuyển lên block chi tiết ngay dưới phễu — gom theo ĐVVC + ô tick)
    nk = rep.get("nhap_kho") or {}
    nk_src = " · ".join(f"{_e(_SRC.get(k, str(k)))} {v}"
                        for k, v in (nk.get("by_source") or {}).items())

    # ---- Phần ĐƠN HOÀN (render ở TRANG 2) ----
    nk_detail = nk.get("detail") or []
    clip_co = nk.get("clip_co", 0)
    clip_total = nk.get("clip_total", 0)
    unmatched = nk.get("clip_unmatched") or []
    unmatched_detail = nk.get("clip_unmatched_detail") or [{"code": c} for c in unmatched]
    unmatched_tagged = [u for u in unmatched_detail if _tag_label(u.get("tag"), u.get("tag_id"))]
    unmatched_plain = [u for u in unmatched_detail if not _tag_label(u.get("tag"), u.get("tag_id"))]
    clip_on = nk.get("clip_available", False)
    n_ret = len(nk_detail)
    _shop_orders = OrderedDict()
    for _d in nk_detail:
        _shop = str(_d.get("gian_hang") or "Chưa xác định")
        _order = str(_d.get("order_code") or _d.get("return_code") or id(_d))
        _shop_orders.setdefault(_shop, set()).add(_order)
    _shop_counts = sorted(
        ((_shop, len(_orders)) for _shop, _orders in _shop_orders.items()),
        key=lambda item: (-item[1], item[0].lower()),
    )
    _shop_summary = " · ".join(
        f"{_e(_short_store_label(_shop))} {_count}" for _shop, _count in _shop_counts
    ) or "Chưa có đơn"
    _sp_exp = sum(int(d.get("sp", 0) or 0) for d in nk_detail)         # Σ SP kỳ vọng phải trả về
    _sp_nhap = sum(int(d.get("sp_nhap", 0) or 0) for d in nk_detail)   # Σ SP thực nhập kho
    _sp_thieu = max(0, _sp_exp - _sp_nhap)                             # SP khách trả THIẾU
    # Bảng đối chiếu (clip ↔ nhận hàng trả) + tóm tắt cột trống
    recon = nk.get("recon_rows") or []
    _cm = sum(1 for r in recon if not r.get("has_clip"))
    _sm = sum(1 for r in recon if (not r.get("has_sapo")) and (not _tag_label(r.get("clip_tag"), r.get("clip_tag_id"))))
    _tag_hold = sum(1 for r in recon if (not r.get("has_sapo")) and _tag_label(r.get("clip_tag"), r.get("clip_tag_id")))
    _tag_imported = sum(1 for r in recon if r.get("has_sapo") and _tag_label(r.get("clip_tag"), r.get("clip_tag_id")))
    _tag_hold_txt = f' · {_tag_hold} tag giữ xử lý' if _tag_hold else ''
    _tag_imported_txt = f' · {_tag_imported} đã nhập kho có tag' if _tag_imported else ''
    recon_badge = (f' <span style="font-size:.8em;color:{"#dc2626" if (_cm or _sm or _tag_imported) else "#15803d"}">'
                   f'({len(recon)} dòng · {_cm} thiếu clip · {_sm} chưa nhập kho cần kiểm tra'
                   f'{_tag_hold_txt}{_tag_imported_txt})</span>')
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
        if unmatched_detail:
            def _clip_lines(items, color="#b45309"):
                _lines = ""
                for u in items:
                    _tag = _tag_label(u.get("tag"), u.get("tag_id"))
                    _tg = (f' · <span style="background:#fde68a;color:#7c2d12;font-weight:900;'
                           f'padding:0 4px;border-radius:3px">🏷️ {_e(str(_tag))}</span>'
                           if _tag else "")
                    _mt = []
                    if u.get("dur"):
                        _mt.append(f'{u["dur"]}s')
                    if u.get("recorded"):
                        _mt.append(str(u["recorded"]))
                    _mts = (' <span style="color:#9a7a3a">· ' + _e(" · ".join(_mt)) + '</span>') if _mt else ""
                    _lines += (f'<div class="wc" style="margin-top:2px;color:{color}">'
                               f'{_e(str(u.get("code", "")))}{_tg}{_mts}</div>')
                return _lines

            _lines = ""
            if unmatched_tagged:
                _lines += (
                    '<div class="warn" style="background:#f0fdf4;border:1px solid #16a34a;border-left:5px solid #16a34a">'
                    f'<div class="wh" style="color:#15803d">✅ {len(unmatched_tagged)} clip có TAG đang giữ xử lý — không nhập kho Sapo là đúng quy trình</div>'
                    '<div class="wb" style="color:#166534"><b>Tag hư hỏng · trả thiếu · sai hàng · khách tráo</b> = hàng có vấn đề; '
                    'nhân viên giữ lại xử lý tranh chấp/khiếu nại sàn và giữ clip làm bằng chứng, không bấm nhập kho.</div>'
                    + _clip_lines(unmatched_tagged, "#15803d")
                    + '</div>')
            if unmatched_plain:
                _lines += (
                    '<div class="warn">'
                    f'<div class="wh">⚠️ {len(unmatched_plain)} clip khui hàng KHÔNG tag có trên Dohana nhưng CHƯA có đơn hoàn nhập kho</div>'
                    '<div class="wb">Cần kiểm tra: <b>(1)</b> hàng hoàn chưa bấm nhập kho (vào Sapo nhập kho để lên bảng), '
                    '<b>(2)</b> quay nhầm mục (đóng hàng ↔ khui hàng), <b>(3)</b> quay trùng.</div>'
                    + _clip_lines(unmatched_plain)
                    + '</div>')
            warn_box = _lines
        else:
            warn_box = ''

    clip_kpi_v = clip_total if clip_on else "—"
    if clip_on:
        _clip_parts = [f"khớp {clip_co}"]
        if unmatched_tagged:
            _clip_parts.append(f"tag giữ {len(unmatched_tagged)}")
        if _tag_imported:
            _clip_parts.append(f"nhập tag {_tag_imported}")
        _clip_parts.append(f"lệch {len(unmatched_plain)}")
        clip_kpi_sub = " · ".join(_clip_parts)
    else:
        clip_kpi_sub = "chưa kết nối Dohana"
    _sp_sub = (f"Đã nhập kho {_sp_nhap}"
               + (f' · <span style="color:#dc2626;font-weight:800">Thiếu {_sp_thieu}</span>' if _sp_thieu else ""))
    r_kpis_html = (
        f'<div class="kpi"><div class="l">📥 Hoàn nhập kho hôm nay</div>'
        f'<div class="v">{nk.get("so_phieu", 0)}</div>'
        f'<div class="l" style="margin-top:3px;font-weight:700">{nk.get("so_sp", 0)} SP'
        f'{(" · " + nk_src) if nk_src else ""}</div></div>'
        f'<div class="kpi"><div class="l">📦 Tổng SL SP hoàn</div>'
        f'<div class="v">{_sp_exp}</div>'
        f'<div class="l" style="margin-top:3px;font-weight:700">{_sp_sub}</div></div>'
        f'<div class="kpi"><div class="l">↩️ Đang hoàn về (chờ nhận)</div>'
        f'<div class="v">{nk.get("cho_xu_ly", 0)}</div>'
        f'<div class="l" style="margin-top:3px">đang trên đường về kho</div></div>'
        f'<div class="kpi{" hot" if (clip_on and (unmatched_plain or _tag_imported)) else ""}">'
        f'<div class="l">📹 Clip khui hàng hôm nay</div>'
        f'<div class="v">{clip_kpi_v}</div>'
        f'<div class="l" style="margin-top:3px;font-weight:700">{clip_kpi_sub}</div></div>'
        f'<div class="kpi"><div class="l">🏪 Đơn hoàn theo gian hàng</div>'
        f'<div class="v">{sum(_count for _, _count in _shop_counts)}</div>'
        f'<div class="l" style="margin-top:3px;font-weight:700">{_shop_summary}</div></div>'
    )
    # ── KẾT LUẬN sai lệch (Phần 2) + lý do có thể ──
    _concl = []
    if _cm > 0:
        _concl.append(f"<b>{_cm}</b> đơn hoàn THIẾU clip khui hàng")
    if clip_on and unmatched_plain:
        _concl.append(f"<b>{len(unmatched_plain)}</b> clip khui hàng KHÔNG tag chưa có nhập kho Sapo")
    if _sp_thieu > 0:
        _concl.append(f"<b>{_sp_thieu}</b> SP khách trả THIẾU")
    if _tag_imported > 0:
        _concl.append(f"<b>{_tag_imported}</b> đơn ĐÃ nhập kho nhưng clip có tag hư hỏng/thiếu/sai hàng/khách tráo")
    _hold_note = (f'<div class="wb" style="margin-top:3px;color:#166534">✅ <b>{_tag_hold}</b> clip có tag hư hỏng/thiếu/sai hàng/khách tráo: '
                  'không nhập kho Sapo là đúng quy trình, giữ xử lý tranh chấp/khiếu nại sàn.</div>'
                  if _tag_hold else '')
    if _concl:
        concl_box = (
            '<div class="warn" style="background:#fffbeb;border:1px solid #f59e0b;margin:.3em 0 .5em">'
            '<div class="wh" style="color:#b45309">📌 KẾT LUẬN — SAI LỆCH cần kiểm tra:</div>'
            '<div class="wb">• ' + '<br>• '.join(_concl) + '</div>'
            '<div class="wb" style="margin-top:3px;color:#78350f">💡 Lý do có thể: '
            '<b>sai mã lúc quay</b> · <b>quay nhầm mục</b> (khui hàng ↔ đóng hàng) · '
            '<b>quay trùng</b> · <b>khách trả thiếu SP</b> · <b>chưa bấm nhập kho trên Sapo</b>.</div>'
            + _hold_note +
            '</div>')
    else:
        concl_box = ('<div class="warn" style="background:#f0fdf4;border:1px solid #16a34a;margin:.3em 0 .5em">'
                     '<div class="wh" style="color:#15803d">✅ KẾT LUẬN: Không có sai lệch cần kiểm tra.</div>'
                     + _hold_note +
                     '</div>')
    # ── PHỄU: xác nhận → soạn(in phiếu) → video(đóng gói) → ĐVVC nhận | hủy · còn xót ──
    # 4 ô dòng 1 + 2 ô dòng 2. Mỗi ô có ô ☐ để NV KHO TICK xác nhận trước khi ký cuối.
    # Soạn hàng = đã in phiếu nhặt (dashboard/picklog); Có video = đơn đóng gói đã quay video.
    # (Đã bỏ ô "Đã quét biên bản": Sapo KHÔNG mở API biên bản nên không có số THẬT để báo.)
    fn = rep.get("funnel") or {}
    _base = fn.get("base") or fn.get("dong_goi") or 0   # đóng gói GỒM hủy (89) = chuẩn so lệch
    _huy = fn.get("huy") or 0
    _dvvc, _video = fn.get("dvvc_nhan"), fn.get("video")
    _soan = fn.get("soan")
    _soan_sp = fn.get("soan_sp")
    if _soan is None:
        _soan = rep.get("tong_don_soan")
    if _soan_sp is None:
        _soan_sp = rep.get("tong_sp_soan")

    def _fbox(icon, label, val, lech=0, hot=False, tick=False, strong=False, tone="", lech_txt="lệch", sub=""):
        disp = "—" if val is None else val
        classes, mark = ["kpi"], ""
        if strong:
            classes.append("strong")
        if hot and val:
            classes.append("hot")
        if tone:
            classes.append(tone)
        if lech and lech > 0:
            classes, mark = ["kpi", "bad"], f'<div class="lech">▼ {lech_txt} {lech}</div>'
        sb = (f'<div style="font-size:.72em;color:#5b6878;font-weight:800;margin-top:1px">{sub}</div>'
              if sub else '')
        tk = '<div class="tick"><span class="cbox"></span> đã nhận</div>' if tick else ''
        return (f'<div class="{" ".join(classes)}"><div class="l">{icon} {label}</div>'
                f'<div class="v">{disp}</div>{sb}{mark}{tk}</div>')

    # Thiếu video = đóng gói (gồm hủy) chưa quay.
    _lv = max(0, _base - _video) if (isinstance(_video, int) and _base) else 0
    # Hàng ĐẦU: đơn sót hôm trước + xác nhận hôm nay = TỔNG đơn cần gửi hôm nay (baseline phễu)
    _row_in = "".join([
        _fbox("📥", "Đơn xót hôm trước", fn.get("xot_truoc")),
        _fbox("➕✅", "Xác nhận hôm nay", fn.get("xac_nhan_today")),
        _fbox("🟰📦", "TỔNG đơn cần gửi hôm nay", fn.get("xac_nhan"), strong=True),
    ])
    _row1 = "".join([
        _fbox("🖨️", "Đã soạn hàng", _soan, sub=(f"{_soan_sp:,} SP" if _soan_sp else "")),
        _fbox("🎥", "Đã có video", _video, lech=_lv),
        _fbox("🚚", "ĐVVC đã nhận", _dvvc),
    ])
    # 2 ô này 50/50, NẰM NGAY TRÊN bảng chi tiết tương ứng (Hủy ↔ bảng Hủy, Xót ↔ bảng Xót)
    _row2 = "".join([
        _fbox("❌", "Hủy hôm nay", fn.get("huy"), hot=True, tick=True, tone="huytone"),
        _fbox("⏳", "Còn xót lại", fn.get("con_xot"), tick=True, tone="xottone"),
    ])
    kpi_html = (f'<div class="kpis k3">{_row_in}</div>'
                f'<div class="kpis kf3">{_row1}</div>'
                f'<div class="kpis kf2">{_row2}</div>')

    # Chi tiết đơn HỦY + CÒN XÓT ngay dưới 2 ô phễu — gom theo ĐVVC, mỗi đơn 1 ô tick xác nhận
    _huy_all = rep.get("huy_all_detail") or []
    _cx_pk = rep.get("con_xot_packed") or []
    _cx_upk = rep.get("con_xot_unpacked") or []
    _conxot = _cx_pk + _cx_upk
    detail_block = ''
    if _huy_all or _conxot:
        detail_block = (
            '<div class="fdetail">'
            '<div class="fdcol fdcol-huy">'
            f'<div class="fdhead" style="color:#b91c1c">❌ ĐƠN HỦY HÔM NAY ({len(_huy_all)})</div>'
            f'{_huy_split_html(_huy_all, rep.get("huy_soan_known"))}</div>'
            '<div class="fdcol fdcol-xot">'
            f'<div class="fdhead" style="color:#b45309">⏳ CÒN XÓT LẠI ({len(_conxot)}) '
            '— đã xác nhận, CHƯA giao shipper</div>'
            f'{_conxot_rows(_cx_pk, _cx_upk, collapse=collapse_xot)}</div>'
            '</div>')

    # Phần KÝ TÊN — đặt ở Trang 1, Trang 2, hoặc cả 2 (tùy chọn sign_on). Mặc định Trang 2.
    _sign_block = (
        '<div class="sign">'
        '<div><div class="role">NV soạn hàng</div><div class="space"></div><div class="hint">(Ký, ghi rõ họ tên)</div></div>'
        '<div><div class="role">NV kho</div><div class="space"></div><div class="hint">(Ký, ghi rõ họ tên)</div></div>'
        '<div><div class="role">Quản lý</div><div class="space"></div><div class="hint">(Ký, ghi rõ họ tên)</div></div>'
        '</div>')
    sign1 = _sign_block if sign_on in ("1", "both") else ""
    sign2 = _sign_block if sign_on in ("2", "both") else ""
    _p1note = " · (ký xác nhận ở mặt sau)" if sign_on == "2" else ""

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
    <thead>
      <tr><th rowspan="2" class="l">Đơn vị vận chuyển</th>
        <th rowspan="2">Soạn</th>
        <th colspan="2">Cần gửi</th><th colspan="2">Hủy</th><th rowspan="2">Video</th>
        <th rowspan="2">Đã xuất kho</th><th rowspan="2">Shipper thực nhận</th>
        <th rowspan="2">Đã giao khách</th><th rowspan="2">Chưa x.nhận</th>
        <th colspan="2">Còn xót lại (chưa giao)</th></tr>
      <tr><th>Cũ</th><th>Hôm nay</th><th>Trước soạn</th><th>Sau soạn</th><th>Đã gói</th><th>Chưa gói</th></tr>
    </thead>
    <tbody>{_carrier_rows(rep["by_carrier"], t, _video_for_table, _cancel_split)}</tbody>
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

  {sign1}
  <div class="foot">VITRAN BOUTIQUE · Trang 1/2 — Vận hành đơn giao đi{_p1note} · {_e(rep["date"])}</div>
</div></div>"""

    # ===== TRANG 2: bảng 5 cột; tag (nếu có) nằm ngay trong cột clip =====
    _thead = ('<thead><tr><th>#</th>'
              '<th class="l">🎥 Clip khui hàng (Dohana)<br><span style="font-weight:600;font-size:.85em">mã · thời lượng · giờ quay</span></th>'
              '<th class="l">📥 Đơn hàng · gian hàng<br><span style="font-weight:600;font-size:.85em">giờ nhận · NV nhập kho</span></th>'
              '<th class="l">🚚 Mã vận chuyển<br><span style="font-weight:600;font-size:.85em">VĐ đi · VĐ hoàn · mã trả</span></th>'
              '<th class="l">Sản phẩm (SKU × SL)</th>'
              + '</tr></thead>')
    _legend = ('<div style="font-size:.72em;color:#6b7280;margin:.25em 0 0">🔎 <b>Mã clip</b> = tra trên '
               '<b>app đóng hàng (Dohana)</b>. <b>Mã đơn</b> = tra trên <b>Sapo</b> và <b>sàn TMĐT</b>. '
               'Ô <span style="color:#dc2626;font-weight:700">đỏ</span> = thiếu/chưa làm, đã ghi rõ lý do trong ô. '
               '<b style="color:#b45309">“mã khác”</b> = clip có nhưng lưu dưới <b>mã vận đơn KHÁC</b> với đơn '
               '(SPX đổi mã nhiều lần) — máy ghép theo ĐVVC + ngày, nên KIỂM TRA lại cho chắc.</div>')
    _ghichu = ('<div class="sec">B. Ghi chú đơn hoàn / khiếu nại</div>'
               '<div class="note"><span style="color:#9aa3af;font-size:.95em">(Ghi tay: tình trạng hàng hoàn, '
               'đơn cần khiếu nại sàn, thiếu/sai SP…)</span><div class="lines"><div></div></div></div>')
    # Nhóm ĐVVC trước; trong từng ĐVVC mới chia loại trả hàng.
    recon = sorted(recon, key=_return_sort_key)
    # Số đơn/tờ (auto-fit tự co chữ nên không lo tràn/mất dòng; giữ vừa phải cho chữ dễ đọc).
    _FIRST, _REST = 11, 15
    _chunks, _starts, _i = [], [], 0
    while _i < len(recon):
        _sz = _FIRST if _i == 0 else _REST
        _starts.append(_i)
        _chunks.append(recon[_i:_i + _sz])
        _i += _sz
    if not _chunks:
        _chunks, _starts = [[]], [0]
    _ns = len(_chunks)
    page2 = ""
    for _si, _chunk in enumerate(_chunks):
        _first, _last = _si == 0, _si == _ns - 1
        _sub = f" (tờ {_si + 1}/{_ns})" if _ns > 1 else ""
        _pno = f"Trang 2.{_si + 1}/{_ns}" if _ns > 1 else "Trang 2/2"
        _kpi = f'<div class="kpis kf5">{r_kpis_html}</div>{concl_box}{warn_box}' if _first else ''
        _badge = recon_badge if _first else ''
        _tail = (_legend + _ghichu + sign2) if _last else ''
        page2 += f"""<div class="page page2"><div class="pfit">
  <div class="hd">
    <div><div class="brand">VITRAN BOUTIQUE</div>
      <div class="sub">Báo cáo đơn hàng hoàn trả</div></div>
    <div class="meta">Ngày báo cáo<br><b>{_e(rep["date"])}</b><br>
      <span style="font-size:.95em">{_pno}</span></div>
  </div>
  <div class="title">Báo cáo đơn hàng hoàn trả</div>
  <div class="title-sub">Phần 2 — Hàng hoàn nhận về · nhập kho · video khui hàng{_sub}</div>
  {_kpi}
  <div class="sec">A. Đối chiếu Clip khui hàng ↔ Đã nhận hàng trả{_badge}</div>
  <table class="return-table" style="table-layout:fixed;overflow-wrap:anywhere"><colgroup><col style="width:4%"><col style="width:23%"><col style="width:28%"><col style="width:30%"><col style="width:15%"></colgroup>{_thead}<tbody>{_recon_rows(_chunk, start=_starts[_si], clip_on=clip_on)}</tbody></table>
  {_tail}
  <div class="foot">VITRAN BOUTIQUE · {_pno} — Đơn hàng hoàn trả · {_e(rep["date"])}</div>
</div></div>"""

    body = page1 + page2

    # Auto-fit: tìm cỡ chữ LỚN NHẤT mà mỗi trang vẫn lọt 1 tờ A4 (nhiều đơn → chữ nhỏ lại,
    # ít đơn → chữ to ra). Dùng nhị phân trên --fs của .pfit so với chiều cao .page (297mm).
    fitjs = (
        "function fitPages(doc){doc=doc||document;"
        "var ps=doc.querySelectorAll('.page');"
        "for(var i=0;i<ps.length;i++){var pg=ps[i];"
        # trang .fixed (font cố định, phân trang 30 đơn) → KHÔNG auto-fit
        "if((' '+pg.className+' ').indexOf(' fixed ')>=0)continue;"
        "var ft=pg.querySelector('.pfit');if(!ft)continue;"
        "var t=pg.clientHeight,lo=8,hi=((' '+pg.className+' ').indexOf(' page2 ')>=0?13.5:24),b=lo;"
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
