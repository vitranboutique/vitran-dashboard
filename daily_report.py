"""
daily_report.py — Render BÁO CÁO VẬN HÀNH CUỐI NGÀY (khổ A4) từ get_daily_report() + Dohana.
Trả 1 chuỗi HTML (nhúng bằng components.html) gồm nút In A4 + báo cáo bố cục chuyên nghiệp.
"""
import json
from html import escape as _e

_CSS = """
  --navy:#16233f; --accent:#E24B4A; --line:#d8dde6; --soft:#f4f6f8; --ink:#1f2733;
  body{font-family:'Segoe UI',system-ui,-apple-system,Roboto,Arial,sans-serif;margin:0;background:#e9edf2;color:var(--ink);}
  .toolbar{position:sticky;top:0;background:#e9edf2;padding:10px;text-align:center;z-index:5;}
  .printbtn{background:var(--accent);color:#fff;border:0;border-radius:10px;padding:11px 22px;font-size:15px;font-weight:800;cursor:pointer;box-shadow:0 2px 8px rgba(226,75,74,.4);}
  .page{width:210mm;min-height:296mm;margin:0 auto 16px;background:#fff;padding:14mm 14mm 12mm;box-sizing:border-box;box-shadow:0 2px 14px rgba(0,0,0,.12);}
  .hd{display:flex;align-items:center;justify-content:space-between;border-bottom:3px solid var(--navy);padding-bottom:10px;}
  .hd .brand{font-size:22px;font-weight:900;color:var(--navy);letter-spacing:.5px;}
  .hd .sub{font-size:12px;color:#6b7280;margin-top:2px;}
  .hd .meta{text-align:right;font-size:12px;color:#374151;}
  .hd .meta b{font-size:15px;color:var(--accent);}
  .title{text-align:center;font-size:18px;font-weight:900;color:var(--navy);margin:14px 0 4px;text-transform:uppercase;letter-spacing:.5px;}
  .title-sub{text-align:center;font-size:11px;color:#6b7280;margin-bottom:12px;}
  .kpis{display:grid;grid-template-columns:repeat(4,1fr);gap:8px;margin:10px 0 16px;}
  .kpi{border:1px solid var(--line);border-radius:10px;padding:10px 12px;background:var(--soft);}
  .kpi .l{font-size:11px;color:#6b7280;font-weight:600;}
  .kpi .v{font-size:24px;font-weight:900;color:var(--navy);line-height:1.1;}
  .kpi.hot .v{color:var(--accent);}
  .sec{font-size:13px;font-weight:800;color:#fff;background:var(--navy);padding:5px 10px;border-radius:6px;margin:16px 0 8px;}
  table{width:100%;border-collapse:collapse;font-size:12px;}
  th,td{border:1px solid var(--line);padding:5px 8px;text-align:center;}
  th{background:var(--soft);font-weight:800;color:#374151;}
  td.l,th.l{text-align:left;}
  td.num{text-align:right;font-variant-numeric:tabular-nums;}
  tr.total td{background:#fff7ed;font-weight:900;color:var(--navy);}
  tr.total td.accent{color:var(--accent);}
  .two{display:grid;grid-template-columns:1fr 1fr;gap:14px;}
  .note{border:1px solid var(--line);border-radius:8px;min-height:64px;padding:8px 10px;font-size:12px;color:#374151;}
  .note .lines{margin-top:6px;}
  .note .lines div{border-bottom:1px dashed #cbd2dc;height:20px;}
  .sign{display:grid;grid-template-columns:repeat(3,1fr);gap:16px;margin-top:22px;text-align:center;font-size:12px;}
  .sign .role{font-weight:800;color:var(--navy);}
  .sign .hint{color:#9aa3af;font-size:10px;}
  .sign .space{height:54px;}
  .foot{margin-top:14px;text-align:center;font-size:10px;color:#9aa3af;border-top:1px solid var(--line);padding-top:6px;}
  .page2{page-break-before:always;}
  .kpis.k3{grid-template-columns:repeat(3,1fr);}
  .warn{border:1px solid #f0b86e;border-left:5px solid #d97706;background:#fff8ec;border-radius:8px;padding:10px 12px;margin:12px 0 14px;}
  .warn .wh{font-size:13px;font-weight:900;color:#b45309;}
  .warn .wb{font-size:11px;color:#7c4a13;margin-top:3px;line-height:1.5;}
  .warn .wc{font-size:12px;font-weight:900;color:#b45309;margin-top:5px;letter-spacing:.3px;}
  .sign.s2{grid-template-columns:repeat(2,1fr);max-width:70%;margin-left:auto;margin-right:auto;}
  @page{size:A4 portrait;margin:0;}
  @media print{
    body{background:#fff;} .toolbar{display:none;}
    .page{box-shadow:none;margin:0;width:auto;min-height:auto;}
    *{-webkit-print-color-adjust:exact;print-color-adjust:exact;}
  }
"""


def _carrier_rows(rows, tot):
    body = "".join(
        f'<tr><td class="l">{_e(str(r["carrier"]))}</td>'
        f'<td class="num">{r["dong_goi"]}</td><td class="num">{r["huy"] or ""}</td>'
        f'<td class="num">{r["shipper_nhan"]}</td><td class="num">{r["con_lai"] or ""}</td></tr>'
        for r in rows) or '<tr><td class="l" colspan="5">—</td></tr>'
    body += (f'<tr class="total"><td class="l">TỔNG CỘNG</td>'
             f'<td class="num">{tot["dong_goi"]}</td><td class="num accent">{tot["huy"] or ""}</td>'
             f'<td class="num">{tot["shipper_nhan"]}</td><td class="num">{tot["con_lai"]}</td></tr>')
    return body


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
            tdcls = ""
        else:
            cell = '<span style="color:#dc2626;font-weight:800">✗ Thiếu clip</span>'
            tdcls = ' style="background:#fef2f2"'
        body += (f'<tr><td>{i}</td>'
                 f'<td class="l">{_e(str(d.get("tracking", "")))}</td>'
                 f'<td>{_e(str(d.get("carrier", "")))}</td>'
                 f'<td class="l">{_e(str(d.get("sku", "")))}</td>'
                 f'<td class="l">{_e(str(d.get("ly_do", "")))}</td>'
                 f'<td{tdcls}>{cell}</td></tr>')
    return body or '<tr><td colspan="6">Hôm nay không có đơn hoàn nhập kho.</td></tr>'


def report_html(rep, dv, now_str):
    t = rep["totals"]
    video_total = (dv or {}).get("total", "—")
    # ---- Đối chiếu VIDEO ĐÓNG GÓI (giải thích vì sao video ≠ đơn) ----
    vr = rep.get("video_recon") or {}
    if vr.get("available"):
        iii_rows = (
            f'<tr><td class="l">🎥 Tổng video đóng gói</td><td class="num">{vr["total"]}</td></tr>'
            f'<tr><td class="l">✅ Khớp đơn đang xử lý</td><td class="num">{vr["match_open"]}</td></tr>'
            f'<tr><td class="l">⚡ Hỏa tốc đã giao xong</td><td class="num">{vr["done_express"] or ""}</td></tr>'
            f'<tr><td class="l">↩️ Đơn đã hủy (đã gói)</td><td class="num">{vr["match_canc"] or ""}</td></tr>')
        _mv = vr.get("missing_video", 0)
        _dup = vr.get("dup") or {}
        vid_note = ('<div style="font-size:10px;color:#6b7280;margin:8px 0 0;line-height:1.5">'
                    f'ℹ️ Video ({vr["total"]}) nhiều hơn đơn đang mở vì gồm <b>đơn hỏa tốc đã giao xong</b> '
                    f'({vr["done_express"]}) &amp; <b>đơn đã hủy đã gói</b> ({vr["match_canc"]}) — '
                    'vẫn quay lúc đóng gói nên hợp lệ.</div>')
        _w = []
        if _mv:
            _w.append(f'<b>{_mv} đơn đã đóng gói nhưng CHƯA có video</b> — nhân viên cần quay bổ sung '
                      '(đủ bằng chứng khi khiếu nại).')
        if _dup:
            _dl = ", ".join(f'{_e(str(k))}×{v}' for k, v in _dup.items())
            _w.append(f'<b>{len(_dup)} đơn quay TRÙNG (≥2 lần)</b>: {_dl}.')
        vid_warn = ('<div class="warn" style="margin-top:12px">'
                    '<div class="wh">⚠️ Cảnh báo video đóng gói</div>'
                    + "".join(f'<div class="wb">• {w}</div>' for w in _w) + '</div>') if _w else ''
    else:
        iii_rows = (f'<tr><td class="l">🎥 Tổng video đóng hàng hôm nay</td><td class="num">{video_total}</td></tr>'
                    f'<tr><td class="l">📦 Đơn đã đóng gói</td><td class="num">{t["dong_goi"]}</td></tr>')
        vid_note = vid_warn = ''
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
        clip_note = ('<div style="font-size:11px;color:#dc2626;margin-top:6px">'
                     '⚠️ Chưa kết nối Dohana — không kiểm tra được clip khui hàng.</div>')
        warn_box = ''
    else:
        ok = clip_co == n_ret
        col = "#15803d" if ok else "#dc2626"
        clip_summary = (f' <span style="font-size:11px;color:{col}">({clip_co}/{n_ret} có clip)</span>'
                        if n_ret else '')
        clip_note = ('' if ok or not n_ret else
                     f'<div style="font-size:11px;color:#dc2626;margin-top:6px;font-weight:700">'
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
    kpis = [
        ("📦 Đơn đóng gói", t["dong_goi"], False),
        ("🚚 Đã bàn giao ĐVVC", t["shipper_nhan"], False),
        ("⏳ Còn lại (chờ giao)", t["con_lai"], False),
        ("❌ Hủy hôm nay", t["huy"], True),
    ]
    kpi_html = "".join(
        f'<div class="kpi{" hot" if hot and v else ""}"><div class="l">{l}</div>'
        f'<div class="v">{v}</div></div>' for l, v, hot in kpis)

    page1 = f"""<div class="page">
  <div class="hd">
    <div><div class="brand">VITRAN BOUTIQUE</div>
      <div class="sub">Hệ thống vận hành đơn hàng</div></div>
    <div class="meta">Ngày báo cáo<br><b>{_e(rep["date"])}</b><br>
      <span style="font-size:10px">In lúc: {_e(now_str)}</span></div>
  </div>

  <div class="title">Báo cáo vận hành cuối ngày</div>
  <div class="title-sub">Phần 1 — Đơn giao đi · đóng gói · soạn hàng · video (dữ liệu Sapo, giờ VN)</div>

  <div class="kpis">{kpi_html}</div>

  <div class="sec">I. Số lượng đơn theo đơn vị vận chuyển</div>
  <table>
    <thead><tr><th class="l">Đơn vị vận chuyển</th><th>Đơn đóng gói</th><th>Đơn hủy</th>
      <th>Shipper thực nhận</th><th>Còn lại</th></tr></thead>
    <tbody>{_carrier_rows(rep["by_carrier"], t)}</tbody>
  </table>

  <div class="sec">II. Số lượng hàng theo đợt soạn</div>
  <table>
    <thead><tr><th class="l">Đợt lấy hàng</th><th>Giờ</th><th>Số đơn</th><th>Số SP</th></tr></thead>
    <tbody>{_batch_rows(rep["batches"], rep["tong_don_soan"], rep["tong_sp_soan"])}</tbody>
  </table>

  <div class="two" style="margin-top:16px">
    <div>
      <div class="sec" style="margin-top:0">III. Đối chiếu video đóng gói (Dohana)</div>
      <table><tbody>{iii_rows}</tbody></table>
    </div>
    <div>
      <div class="sec" style="margin-top:0">IV. Xuất kho hôm nay</div>
      <table><tbody>
        <tr><td class="l">📤 Đã giao ĐVVC (shipper nhận)</td><td class="num">{t["shipper_nhan"]}</td></tr>
        <tr><td class="l">⏳ Còn lại chờ giao</td><td class="num">{t["con_lai"]}</td></tr>
        <tr><td class="l">❌ Hủy đã gói (cần lấy lại)</td><td class="num">{rep["huy_da_goi"]}</td></tr>
      </tbody></table>
    </div>
  </div>
  {vid_note}
  {vid_warn}

  <div class="sec">V. Ghi chú / Sự cố trong ngày</div>
  <div class="note"><span style="color:#9aa3af;font-size:11px">(Ghi tay: đơn GHN còn lại, hỏa tốc tìm tài xế, đơn lỗi…)</span>
    <div class="lines"><div></div><div></div></div></div>

  <div class="sign">
    <div><div class="role">NV soạn hàng</div><div class="space"></div><div class="hint">(Ký, ghi rõ họ tên)</div></div>
    <div><div class="role">NV kho</div><div class="space"></div><div class="hint">(Ký, ghi rõ họ tên)</div></div>
    <div><div class="role">Quản lý</div><div class="space"></div><div class="hint">(Ký, ghi rõ họ tên)</div></div>
  </div>

  <div class="foot">VITRAN BOUTIQUE · Trang 1/2 — Vận hành đơn giao đi · {_e(rep["date"])}</div>
</div>"""

    page2 = f"""<div class="page page2">
  <div class="hd">
    <div><div class="brand">VITRAN BOUTIQUE</div>
      <div class="sub">Báo cáo đơn hàng hoàn trả</div></div>
    <div class="meta">Ngày báo cáo<br><b>{_e(rep["date"])}</b><br>
      <span style="font-size:10px">Trang 2 / 2</span></div>
  </div>

  <div class="title">Báo cáo đơn hàng hoàn trả</div>
  <div class="title-sub">Phần 2 — Hàng hoàn nhận về · nhập kho · video khui hàng (Sapo + Dohana)</div>

  <div class="kpis k3">{r_kpis_html}</div>

  {warn_box}

  <div class="sec">A. Chi tiết đơn hàng hoàn nhận hôm nay{clip_summary}</div>
  <table>
    <thead><tr><th>#</th><th class="l">Mã vận đơn</th><th>ĐVVC</th>
      <th class="l">Sản phẩm (SKU × SL)</th><th class="l">Lý do trả</th>
      <th>🎥 Clip khui hàng</th></tr></thead>
    <tbody>{_returns_clip_rows(nk_detail)}</tbody>
  </table>
  {clip_note}

  <div class="sec">B. Ghi chú đơn hoàn / khiếu nại</div>
  <div class="note"><span style="color:#9aa3af;font-size:11px">(Ghi tay: tình trạng hàng hoàn, đơn cần khiếu nại sàn, thiếu/sai SP…)</span>
    <div class="lines"><div></div><div></div></div></div>

  <div class="sign s2">
    <div><div class="role">NV kho nhận hàng hoàn</div><div class="space"></div><div class="hint">(Ký, ghi rõ họ tên)</div></div>
    <div><div class="role">Quản lý</div><div class="space"></div><div class="hint">(Ký, ghi rõ họ tên)</div></div>
  </div>

  <div class="foot">VITRAN BOUTIQUE · Trang 2/2 — Đơn hàng hoàn trả · {_e(rep["date"])}</div>
</div>"""

    body = page1 + page2

    js = (
        "function printA4(){"
        "var html=document.getElementById('rp').innerHTML;"
        "var f=document.createElement('iframe');"
        "f.style.cssText='position:fixed;right:0;bottom:0;width:0;height:0;border:0';"
        "document.body.appendChild(f);var d=f.contentWindow.document;d.open();"
        "d.write('<!doctype html><html><head><meta charset=\\\"utf-8\\\"><style>'+"
        + json.dumps(_CSS) + "+'</style></head><body>'+html+'</body></html>');"
        "d.close();f.onload=function(){f.contentWindow.focus();f.contentWindow.print();"
        "setTimeout(function(){document.body.removeChild(f);},700);};}"
    )
    return (
        "<style>" + _CSS + "</style>"
        "<div class='toolbar'><button class='printbtn' onclick='printA4()'>🖨️ In báo cáo A4 / Lưu PDF</button></div>"
        "<div id='rp'>" + body + "</div>"
        "<script>" + js + "</script>"
    )
