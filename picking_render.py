"""
picking_render.py — Render PHIẾU NHẶT HÀNG (khổ K80) từ dữ liệu get_picking().
Trả về 1 chuỗi HTML (nhúng bằng st.components.v1.html) gồm: nút In K80 + các phiếu
(hỏa tốc trên, thường dưới), in liền khối khổ 80mm không bị cắt giữa chừng.
"""
import json
import re
from html import escape as _esc

RECEIPT_CSS = """
  body{font-family:system-ui,-apple-system,Segoe UI,Roboto,Arial,sans-serif;margin:0;background:#f6f6f6;color:#111;}
  .toolbar{padding:10px;text-align:center;position:sticky;top:0;background:#f6f6f6;z-index:5;}
  .printbtn{background:#E24B4A;color:#fff;border:0;border-radius:10px;padding:11px 20px;font-size:15px;font-weight:800;cursor:pointer;}
  #slips{display:flex;flex-direction:column;gap:14px;align-items:center;padding:6px 6px 30px;}
  .receipt{width:302px;background:#fff;color:#000;border:1px solid #e6e6e6;border-radius:10px;padding:10px 10px 14px;box-sizing:border-box;box-shadow:0 1px 6px rgba(0,0,0,.06);}
  .title{text-align:center;font-weight:900;font-size:21px;margin:2px 0 8px;}
  .kv{display:grid;grid-template-columns:1fr auto;gap:2px 8px;font-size:15px;font-weight:800;}
  .kv .v{text-align:right;}
  .section{margin-top:8px;}
  .section h3{margin:8px 0 3px;font-size:16px;font-weight:900;}
  .subkv{display:grid;grid-template-columns:1fr auto;gap:2px 8px;font-size:13px;font-weight:700;}
  .subkv .v{text-align:right;}
  .line{border-top:2px solid #111;margin:8px 0;}
  .skuhead{display:grid;grid-template-columns:1fr 52px;font-size:13px;font-weight:900;border:2px solid #111;border-bottom:0;text-align:center;}
  .skuhead>div,.skurow>div{padding:4px 6px;}
  .skuhead>div:first-child,.skurow>div:first-child{border-right:1px solid #111;}
  .skutable{border:2px solid #111;border-top:0;margin-top:0;}
  .skurow{display:grid;grid-template-columns:1fr 52px;border-bottom:1px solid #777;font-size:13px;font-weight:800;}
  .skurow .qty{text-align:right;}
  .skusep{border-top:2px dashed #111;margin:4px 0;}
  .footer-line{border-top:2px solid #111;margin:12px 0 8px;}
  .sign{display:grid;grid-template-columns:1fr 1fr;gap:10px;font-size:12px;font-weight:800;text-align:center;}
"""

PRINT_CSS = """
  @page{size:80mm auto;margin:0;}
  html,body{width:80mm;margin:0;padding:0;background:#fff;}
  #slips{display:block;padding:0;margin:0;}
  .receipt{width:80mm;border:0;border-radius:0;box-shadow:none;padding:0 2mm 5mm;margin:0 0 4mm;box-sizing:border-box;color:#000;
           font-family:system-ui,-apple-system,Segoe UI,Roboto,Arial,sans-serif;}
  .title{text-align:center;font-weight:900;font-size:22px;margin:4px 0 8px;}
  .kv{display:grid;grid-template-columns:1fr auto;gap:2px 8px;font-size:15px;font-weight:800;}
  .kv .v{text-align:right;}
  .section{margin-top:8px;page-break-inside:avoid;break-inside:avoid;}
  .section h3{margin:8px 0 3px;font-size:16px;font-weight:900;}
  .subkv{display:grid;grid-template-columns:1fr auto;gap:2px 8px;font-size:13px;font-weight:700;}
  .subkv .v{text-align:right;}
  .line{border-top:2px solid #111;margin:8px 0;}
  .skuhead{display:grid;grid-template-columns:1fr 52px;font-size:13px;font-weight:900;border:2px solid #111;border-bottom:0;text-align:center;}
  .skuhead>div,.skurow>div{padding:4px 6px;}
  .skuhead>div:first-child,.skurow>div:first-child{border-right:1px solid #111;}
  .skutable{border:2px solid #111;border-top:0;margin-top:0;}
  .skurow{display:grid;grid-template-columns:1fr 52px;border-bottom:1px solid #777;font-size:13px;font-weight:800;page-break-inside:avoid;break-inside:avoid;}
  .skurow .qty{text-align:right;}
  .skusep{border-top:2px dashed #111;margin:4px 0;page-break-after:avoid;break-after:avoid;}
  .footer-line{border-top:2px solid #111;margin:12px 0 8px;}
  .sign{display:grid;grid-template-columns:1fr 1fr;gap:10px;font-size:12px;font-weight:800;text-align:center;page-break-inside:avoid;break-inside:avoid;}
  *{-webkit-print-color-adjust:exact;print-color-adjust:exact;}
"""


def _subkv(d):
    if not d:
        return '<div>-</div><div class="v">0</div>'
    return "".join(f'<div>{_esc(str(k))}:</div><div class="v">{v}</div>' for k, v in d.items())


def _natural_key(text):
    return [int(p) if p.isdigit() else p.lower() for p in re.split(r"(\d+)", str(text))]


def _sku_group(sku):
    first = str(sku or "N/A").strip().split("-", 1)[0].strip()
    return first.upper() if first else "N/A"


def _grouped_sku_rows(skus):
    groups = {}
    for sku, qty in skus or []:
        try:
            q = int(qty)
        except Exception:
            q = qty or 0
        group = _sku_group(sku)
        groups.setdefault(group, {"total": 0, "rows": []})
        groups[group]["total"] += q if isinstance(q, int) else 0
        groups[group]["rows"].append((str(sku), q))

    if not groups:
        return '<div class="skurow"><div>-</div><div class="qty">0</div></div>'

    html = []
    ordered_groups = sorted(groups.items(), key=lambda x: (-x[1]["total"], _natural_key(x[0])))
    for idx, (_group, info) in enumerate(ordered_groups):
        if idx:
            html.append('<div class="skusep"></div>')
        rows = sorted(info["rows"], key=lambda x: (-(x[1] if isinstance(x[1], int) else 0), _natural_key(x[0])))
        html.extend(
            f'<div class="skurow"><div>{_esc(sku)}</div><div class="qty">{qty}</div></div>'
            for sku, qty in rows
        )
    return "".join(html)


def _slip(title, accent, g, now_str):
    skurows = _grouped_sku_rows(g.get("skus"))
    late = ""
    if g["late"]:
        late = (f'<div class="kv" style="color:#c00"><div>&#9888; XÁC NHẬN TRỄ:</div>'
                f'<div class="v">{g["late"]}</div></div>')
    return f"""<div class="receipt">
  <div class="title" style="color:{accent}">{_esc(title)}</div>
  <div class="kv"><div>Giờ in:</div><div class="v">{_esc(now_str)}</div></div>
  <div class="line"></div>
  <div class="kv">
    <div>TỔNG ĐƠN:</div><div class="v">{g['total_orders']}</div>
    <div>TỔNG SP:</div><div class="v">{g['total_qty']}</div>
    <div>SỐ SKU:</div><div class="v">{g['sku_count']}</div>
  </div>
  <div class="kv">
    <div>Đơn MỚI (nay):</div><div class="v">{g['new']}</div>
    <div>Đơn CŨ (tồn):</div><div class="v">{g['old']}</div>
  </div>
  {late}
  <div class="section"><h3>KÊNH BÁN</h3><div class="subkv">{_subkv(g.get('channels'))}</div></div>
  <div class="section"><h3>GIAN HÀNG</h3><div class="subkv">{_subkv(g.get('stores'))}</div></div>
  <div class="section"><h3>ĐỐI TÁC GIAO HÀNG</h3><div class="subkv">{_subkv(g.get('carriers'))}</div></div>
  <div class="section"><h3>DỊCH VỤ VC</h3><div class="subkv">{_subkv(g.get('services'))}</div></div>
  <div class="line"></div>
  <div class="skuhead"><div>SKU</div><div>SL</div></div>
  <div class="skutable">{skurows}</div>
  <div class="footer-line"></div>
  <div class="sign"><div>NV kho ký</div><div>NV đóng hàng ký</div></div>
</div>"""


def history_slips_html(batches, now_str):
    """Render phiếu nhặt cho TỪNG ĐỢT đã soạn hôm nay — xem lại & in lại từng đợt."""
    if not batches:
        return "<div style='padding:12px;font-family:sans-serif'>Chưa có đợt nào hôm nay.</div>"
    items = []
    for b in batches:
        sid = "dot%s" % b["dot"]
        title = "PHIẾU NHẶT — ĐỢT %s (%s)" % (b["dot"], b["gio"])
        slip = _slip(title, "#16233f", b["summary"], now_str)
        items.append(
            "<div style='margin-bottom:4px'>"
            "<div style='text-align:center;margin:4px 0 8px'>"
            "<button class='printbtn' onclick=\"printOne('%s')\">&#128424;&#65039; In lại đợt %s</button></div>"
            "<div id='%s'>%s</div></div>" % (sid, b["dot"], sid, slip)
        )
    body = "<div style='height:10px'></div>".join(items)
    js = (
        "var PRINT_CSS=" + json.dumps(PRINT_CSS) + ";"
        "function printOne(id){"
        "var html=document.getElementById(id).innerHTML;"
        "var f=document.createElement('iframe');"
        "f.style.cssText='position:fixed;right:0;bottom:0;width:0;height:0;border:0';"
        "document.body.appendChild(f);"
        "var d=f.contentWindow.document;d.open();"
        "d.write('<!doctype html><html><head><meta charset=\\\"utf-8\\\"><style>'+PRINT_CSS+'</style></head><body><div id=\\\"slips\\\">'+html+'</div></body></html>');"
        "d.close();"
        "f.onload=function(){f.contentWindow.focus();f.contentWindow.print();setTimeout(function(){document.body.removeChild(f);},600);};"
        "}"
    )
    return (
        "<style>" + RECEIPT_CSS + "</style>"
        "<div id='hist'>" + body + "</div>"
        "<script>" + js + "</script>"
    )


def picking_html(data, now_str, auto_print=False):
    """auto_print=True → tự bung hộp in khi tải (dùng sau khi bấm nút Streamlit 'In + lưu đợt')."""
    parts = []
    if data["express"]["total_orders"] > 0:
        parts.append(_slip("PHIẾU NHẶT — HỎA TỐC", "#E24B4A", data["express"], now_str))
    if data["normal"]["total_orders"] > 0:
        parts.append(_slip("PHIẾU NHẶT — THƯỜNG", "#111111", data["normal"], now_str))
    if not parts:
        blocks = '<div class="receipt"><div class="title">Không có đơn cần nhặt 👍</div></div>'
    else:
        blocks = '<div style="height:10px"></div>'.join(parts)

    js = (
        "var PRINT_CSS=" + json.dumps(PRINT_CSS) + ";"
        "function printK80(){"
        "var html=document.getElementById('slips').innerHTML;"
        "var f=document.createElement('iframe');"
        "f.style.cssText='position:fixed;right:0;bottom:0;width:0;height:0;border:0';"
        "document.body.appendChild(f);"
        "var d=f.contentWindow.document;d.open();"
        "d.write('<!doctype html><html><head><meta charset=\\\"utf-8\\\"><style>'+PRINT_CSS+'</style></head><body><div id=\\\"slips\\\">'+html+'</div></body></html>');"
        "d.close();"
        "f.onload=function(){f.contentWindow.focus();f.contentWindow.print();setTimeout(function(){document.body.removeChild(f);},600);};"
        "}"
        + ("setTimeout(printK80,500);" if auto_print else "")
    )
    return (
        "<style>" + RECEIPT_CSS + "</style>"
        "<div class='toolbar'><button class='printbtn' onclick='printK80()'>🖨️ In lại (in liền khối, hỏa tốc trên)</button></div>"
        "<div id='slips'>" + blocks + "</div>"
        "<script>" + js + "</script>"
    )
