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


def report_html(rep, dv, now_str):
    t = rep["totals"]
    video_total = (dv or {}).get("total", "—")
    kpis = [
        ("📦 Đơn đóng gói", t["dong_goi"], False),
        ("🚚 Đã bàn giao ĐVVC", t["shipper_nhan"], False),
        ("⏳ Còn lại (chờ giao)", t["con_lai"], False),
        ("❌ Hủy hôm nay", t["huy"], True),
    ]
    kpi_html = "".join(
        f'<div class="kpi{" hot" if hot and v else ""}"><div class="l">{l}</div>'
        f'<div class="v">{v}</div></div>' for l, v, hot in kpis)

    body = f"""<div class="page">
  <div class="hd">
    <div><div class="brand">VITRAN BOUTIQUE</div>
      <div class="sub">Hệ thống vận hành đơn hàng</div></div>
    <div class="meta">Ngày báo cáo<br><b>{_e(rep["date"])}</b><br>
      <span style="font-size:10px">In lúc: {_e(now_str)}</span></div>
  </div>

  <div class="title">Báo cáo vận hành cuối ngày</div>
  <div class="title-sub">Tổng hợp đóng gói · bàn giao · soạn hàng · video — dữ liệu Sapo (giờ VN)</div>

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
      <div class="sec" style="margin-top:0">III. Video đóng hàng (Dohana)</div>
      <table><tbody>
        <tr><td class="l">🎥 Tổng video đóng hàng hôm nay</td><td class="num">{video_total}</td></tr>
        <tr><td class="l">📦 Đơn đã đóng gói</td><td class="num">{t["dong_goi"]}</td></tr>
        <tr><td class="l">❌ Đơn hủy đã gói (cần lấy lại)</td><td class="num">{rep["huy_da_goi"]}</td></tr>
      </tbody></table>
    </div>
    <div>
      <div class="sec" style="margin-top:0">IV. Nhập – Xuất kho</div>
      <table><tbody>
        <tr><td class="l">📤 Xuất kho (đã gửi đi)</td><td class="num">{t["shipper_nhan"]}</td></tr>
        <tr><td class="l">📥 Nhập kho (hàng hoàn nhận lại)</td><td class="num">&nbsp;</td></tr>
        <tr><td class="l">↩️ Đơn hoàn trả cần xử lý</td><td class="num">&nbsp;</td></tr>
      </tbody></table>
    </div>
  </div>

  <div class="sec">V. Ghi chú / Sự cố trong ngày</div>
  <div class="note"><span style="color:#9aa3af;font-size:11px">(Ghi tay: đơn GHN còn lại, hỏa tốc tìm tài xế, đơn lỗi…)</span>
    <div class="lines"><div></div><div></div></div></div>

  <div class="sign">
    <div><div class="role">NV soạn hàng</div><div class="space"></div><div class="hint">(Ký, ghi rõ họ tên)</div></div>
    <div><div class="role">NV kho</div><div class="space"></div><div class="hint">(Ký, ghi rõ họ tên)</div></div>
    <div><div class="role">Quản lý</div><div class="space"></div><div class="hint">(Ký, ghi rõ họ tên)</div></div>
  </div>

  <div class="foot">VITRAN BOUTIQUE · Báo cáo tạo tự động từ dashboard vận hành · {_e(rep["date"])}</div>
</div>"""

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
