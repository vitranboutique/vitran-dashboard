"""Trang CHI PHÍ ĐẦU VÀO — nhúng 3 công cụ HTML (GIỮ NGUYÊN, không sửa) + lưu vào Gist.

3 công cụ đọc verbatim từ tools/cost/*.html. Mỗi công cụ được nhúng qua components.html; vì iframe
KHÔNG gửi được dữ liệu thẳng về server (giới hạn Streamlit), ta chèn thêm 1 THANH LƯU (bridge) ở
cuối iframe: nút "Lưu vào chi phí đầu vào" đọc dữ liệu từ chính state/DOM của công cụ → gom JSON gọn
→ tự sao chép. Người dùng dán (Ctrl+V) vào ô bên dưới khung rồi bấm Lưu → picklog.add_input_cost().
Bản thân file công cụ trên đĩa KHÔNG bị thay đổi (bridge chèn lúc render, nối chuỗi ở Python)."""

import os
import io
import re
import json
import unicodedata

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

import picklog

_TOOL_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tools", "cost")

_TYPE_LABEL = {
    "mua_vai_ke": "Bảng kê mua vải",
    "thanh_toan_mua_vai": "Thanh toán mua vải",
    "gia_cong": "Thanh toán gia công",
    "so_quy_chi": "Sổ quỹ (chi)",
    "khac": "Chi phí khác",
}
_TYPE_ICON = {"mua_vai_ke": "🧾", "thanh_toan_mua_vai": "💳", "gia_cong": "🧵",
              "so_quy_chi": "🏦", "khac": "📌"}


def _fmt(n):
    try:
        return f"{int(round(float(n))):,}".replace(",", ".")
    except Exception:
        return "0"


def _read_tool(fname):
    try:
        with open(os.path.join(_TOOL_DIR, fname), encoding="utf-8") as f:
            return f.read()
    except Exception:
        return None


def _month_of(date_str):
    """dd/mm/yyyy → 'mm/yyyy' (rỗng nếu không parse được)."""
    s = str(date_str or "").strip()
    p = s.split("/")
    if len(p) == 3 and p[1] and p[2]:
        return f"{('0'+p[1])[-2:]}/{p[2]}"
    return ""


# ── Bridge chèn vào cuối iframe (thanh lưu + JS đọc dữ liệu từ công cụ) ──
_BAR_HTML = r'''
<style>
  #__vitran_bar{position:sticky;bottom:0;left:0;right:0;z-index:99999;background:#064e3b;color:#fff;
    padding:10px 14px;font-family:Arial,Helvetica,sans-serif;box-shadow:0 -2px 10px rgba(0,0,0,.3)}
  #__vitran_bar .row{display:flex;gap:10px;align-items:center;flex-wrap:wrap}
  #__vitran_btn{padding:9px 16px;font-size:15px;font-weight:700;background:#22c55e;color:#052e1b;
    border:none;border-radius:8px;cursor:pointer}
  #__vitran_btn:hover{background:#16a34a;color:#fff}
  #__vitran_status{font-size:13px;line-height:1.35}
  #__vitran_out{display:none;margin-top:8px;width:100%;height:60px;font-family:monospace;font-size:12px;
    border:1px solid #10b981;border-radius:6px;padding:6px;background:#022c22;color:#a7f3d0}
  @media print{#__vitran_bar{display:none!important}}
</style>
<div id="__vitran_bar">
  <div class="row">
    <button type="button" id="__vitran_btn">&#128190; Lưu vào chi phí đầu vào</button>
    <span id="__vitran_status">Nhập xong, bấm nút này để gom số liệu &amp; sao chép.</span>
  </div>
  <textarea id="__vitran_out" readonly></textarea>
</div>
'''

_EMIT_JS = r'''
function __vitranEmit(payload){
  try{
    payload.__v = 1;
    var s = JSON.stringify(payload);
    var out = document.getElementById('__vitran_out');
    var stt = document.getElementById('__vitran_status');
    out.style.display = 'block';
    out.value = s;
    out.focus(); out.select();
    var copied = false;
    try { copied = document.execCommand('copy'); } catch(e){}
    try { if (navigator.clipboard && navigator.clipboard.writeText) navigator.clipboard.writeText(s); } catch(e){}
    stt.innerHTML = copied
      ? '✅ Đã sao chép! Kéo xuống ô "Dán dữ liệu" ngay dưới khung này, bấm Ctrl+V rồi bấm Lưu.'
      : '⚠️ Đã bôi đen sẵn ở ô dưới — bấm Ctrl+C, rồi dán vào ô "Dán dữ liệu" dưới khung.';
  }catch(err){
    var s2 = document.getElementById('__vitran_status');
    if (s2) s2.textContent = 'Lỗi gom dữ liệu: ' + err;
  }
}
function __vitranWarn(msg){ var s=document.getElementById('__vitran_status'); if(s) s.textContent=msg; }
'''

_COLLECT = {
    "mua_vai_ke": r'''
    var s = (typeof collectState==='function') ? collectState() : (typeof state!=='undefined'?state:{});
    var rows = (s.rows||[]).filter(function(r){ return (typeof rowHasContent==='function') ? rowHasContent(r) : !!(r&&(r.name||r.qty||r.price)); });
    if(!rows.length){ __vitranWarn('⚠️ Chưa có dòng vải nào để lưu.'); return; }
    var pq=(typeof parseQty==='function')?parseQty:function(v){return parseFloat(v)||0;};
    var pp=(typeof parsePrice==='function')?parsePrice:function(v){return parseFloat(String(v).replace(/[^\d]/g,''))||0;};
    var total = rows.reduce(function(t,r){ return t + pq(r.qty)*pp(r.price); },0);
    var dd=String(s.day||'').trim(), mm=String(s.month||'').trim(), yy=String(s.year||'').trim();
    var date=(dd&&mm&&yy)?(('0'+dd).slice(-2)+'/'+('0'+mm).slice(-2)+'/'+yy):'';
    var sel=document.querySelectorAll('table.meta .bold-value');
    var partner=sel.length>1?sel[1].textContent.trim():(sel.length?sel[0].textContent.trim():'');
    __vitranEmit({type:'mua_vai_ke', date:date, amount:Math.round(total), partner:partner, count:rows.length, rows:rows});
    ''',
    "thanh_toan_mua_vai": r'''
    var arr=(typeof data!=='undefined'&&Array.isArray(data))?data:[];
    if(!arr.length){ __vitranWarn('⚠️ Chưa có giao dịch nào trong bảng để lưu.'); return; }
    function vn(x){ if(!x) return ''; var p=String(x).split('-'); return p.length===3?(p[2]+'/'+p[1]+'/'+p[0]):x; }
    var total=arr.reduce(function(t,x){ return t+(Number(x.amount)||0); },0);
    var ds=arr.map(function(x){return x.date;}).filter(Boolean).sort();
    var sender=((document.getElementById('senderNameText')||{}).textContent)||'';
    __vitranEmit({type:'thanh_toan_mua_vai', date:vn(ds[ds.length-1]||''), date_from:vn(ds[0]||''), date_to:vn(ds[ds.length-1]||''), quarter:(arr[0]?arr[0].quarter:''), amount:total, sender:sender, count:arr.length, rows:arr});
    ''',
    "gia_cong": r'''
    function num(t){ return Number(String(t==null?'':t).replace(/[^\d]/g,''))||0; }
    var net=num((document.getElementById('netPay')||{}).textContent);
    if(!net){ __vitranWarn('⚠️ Tổng thực nhận đang = 0, chưa có gì để lưu.'); return; }
    var partner=((document.getElementById('b_ten')||{}).value)||'';
    var date=((document.getElementById('ngay')||{}).value)||'';
    var ng=((document.getElementById('ngay_giao')||{}).value)||'';
    if(!date&&ng){ var p=ng.split('-'); date=p.length===3?(p[2]+'/'+p[1]+'/'+p[0]):ng; }
    var skus=[];
    document.querySelectorAll('#spBody tr').forEach(function(tr){
      var g=function(c){ var el=tr.querySelector('input.'+c); return el?el.value:''; };
      if(g('sku')||g('qty')||g('unit')) skus.push({sku:g('sku'),qty:g('qty'),unit:g('unit'),bad:g('bad')});
    });
    var gv=function(id){var el=document.getElementById(id); if(!el) return '';
      return (el.value!==undefined && el.value!==null)? el.value : (el.textContent||''); };
    var advs=[]; document.querySelectorAll('#advBody tr').forEach(function(tr){
      var n=tr.querySelector('input.advNote'), a=tr.querySelector('input.advAmt');
      if((n&&n.value)||(a&&a.value)) advs.push({note:n?n.value:'', amt:a?a.value:''}); });
    var mats=[]; document.querySelectorAll('#matBody tr').forEach(function(tr){
      var n=tr.querySelector('input.matName'), q=tr.querySelector('input.matQty'), u=tr.querySelector('input.matUnit');
      if((n&&n.value)||(q&&q.value)) mats.push({name:n?n.value:'', qty:q?q.value:'', unit:u?u.value:''}); });
    __vitranEmit({type:'gia_cong', date:date, partner:partner, so_lo:gv('so_lo'), amount:net,
      gross:num((document.getElementById('sumGross')||{}).textContent),
      defect:num((document.getElementById('sumDefect')||{}).textContent),
      adv:num((document.getElementById('sumAdv')||{}).textContent),
      mat:num((document.getElementById('sumMat')||{}).textContent),
      qty:num((document.getElementById('sumQty')||{}).textContent),
      bad_qty:num((document.getElementById('sumBadQty')||{}).textContent),
      tai:gv('tai'), ngay_giao:gv('ngay_giao'), pttt:gv('pttt'), hinh_thuc:gv('hinh_thuc'),
      ctk:gv('ctk'), stk:gv('stk'), tdtt:gv('tdtt'),
      ben_a:{ten:gv('a_ten'), daidien:gv('a_daidien'), cccd:gv('a_cccd'), diachi:gv('a_diachi'), sdt:gv('a_sdt')},
      ben_b:{ten:gv('b_ten'), cccd:gv('b_cccd'), diachi:gv('b_diachi'), sdt:gv('b_sdt')},
      advs:advs, mats:mats, count:skus.length, skus:skus});
    ''',
}


def _bridged(html, typ):
    """Nối thanh lưu + JS đọc dữ liệu vào cuối công cụ (không sửa nội dung công cụ)."""
    bridge = (_BAR_HTML + "<script>" + _EMIT_JS
              + "document.getElementById('__vitran_btn').addEventListener('click', function(){"
              + _COLLECT[typ] + "});</script>")
    if "</body>" in html:
        head, tail = html.rsplit("</body>", 1)
        return head + bridge + "</body>" + tail
    return html + bridge


def _do_save(typ):
    """Callback nút Lưu: đọc ô dán, parse JSON, ghi vào Gist. Chạy TRƯỚC khi widget dựng lại."""
    raw = str(st.session_state.get(f"paste_{typ}", "") or "").strip()
    if not raw:
        st.session_state[f"msg_{typ}"] = ("warning", "Chưa có dữ liệu — bấm nút xanh trong công cụ để sao chép trước, rồi dán vào đây.")
        return
    try:
        obj = json.loads(raw)
    except Exception:
        st.session_state[f"msg_{typ}"] = ("error", "Dữ liệu dán vào không đúng định dạng. Bấm lại nút xanh trong công cụ để sao chép chuẩn.")
        return
    if not isinstance(obj, dict) or not obj.get("type"):
        st.session_state[f"msg_{typ}"] = ("error", "Dữ liệu không hợp lệ (thiếu loại).")
        return
    entry = {
        "type": obj.get("type"),
        "date": str(obj.get("date") or ""),
        "amount": int(obj.get("amount") or 0),
        "partner": str(obj.get("partner") or obj.get("sender") or ""),
        "note": "",
        "detail": obj,
    }
    ok = picklog.add_input_cost(entry)
    if ok:
        st.session_state[f"paste_{typ}"] = ""
        st.session_state[f"msg_{typ}"] = ("success",
            f"Đã lưu {_TYPE_LABEL.get(entry['type'], 'chi phí')} — {_fmt(entry['amount'])}đ"
            + (f" · ngày {entry['date']}" if entry["date"] else "") + ".")
    else:
        st.session_state[f"msg_{typ}"] = ("error", "Lưu thất bại (không ghi được vào kho dữ liệu). Kiểm tra kết nối rồi thử lại.")


def _do_delete(cid):
    ok = picklog.remove_input_cost(cid)
    st.session_state["msg_list"] = ("success", "Đã xoá 1 chi phí.") if ok else ("error", "Xoá thất bại.")


def _do_manual_add():
    typ = st.session_state.get("man_type", "khac")
    amt = int(st.session_state.get("man_amount", 0) or 0)
    if amt <= 0:
        st.session_state["msg_list"] = ("warning", "Số tiền phải lớn hơn 0.")
        return
    d = st.session_state.get("man_date")
    date_str = d.strftime("%d/%m/%Y") if d else ""
    entry = {
        "type": typ,
        "date": date_str,
        "amount": amt,
        "partner": str(st.session_state.get("man_partner", "") or ""),
        "note": str(st.session_state.get("man_note", "") or ""),
        "detail": {"manual": True},
    }
    ok = picklog.add_input_cost(entry)
    if ok:
        st.session_state["man_amount"] = 0
        st.session_state["man_partner"] = ""
        st.session_state["man_note"] = ""
        st.session_state["msg_list"] = ("success", f"Đã thêm {_TYPE_LABEL.get(typ, 'chi phí')} — {_fmt(amt)}đ.")
    else:
        st.session_state["msg_list"] = ("error", "Thêm thất bại.")


def _tool_tab(typ, fname, height, hint):
    html = _read_tool(fname)
    if html is None:
        st.error(f"Không đọc được công cụ `{fname}`. Kiểm tra thư mục tools/cost trong repo.")
        return
    st.caption(hint)
    components.html(_bridged(html, typ), height=height, scrolling=True)
    st.markdown('**Bước lưu:** bấm nút xanh **💾 Lưu vào chi phí đầu vào** ở cuối khung trên → '
                'dán (Ctrl+V) vào ô dưới đây → bấm **Lưu**.')
    c1, c2 = st.columns([5, 1])
    c1.text_area("Dán dữ liệu", key=f"paste_{typ}", height=76, label_visibility="collapsed",
                 placeholder="Dán (Ctrl+V) dữ liệu vừa sao chép từ nút xanh phía trên…")
    c2.button("💾 Lưu", key=f"savebtn_{typ}", use_container_width=True, on_click=_do_save, args=(typ,))
    msg = st.session_state.pop(f"msg_{typ}", None)
    if msg:
        getattr(st, msg[0])(msg[1])


# ══════════════ TAB SỔ QUỸ SAPO: nhập file "Xuất file" → lọc phiếu CHI ══════════════
# Sapo Open API chặn /admin/vouchers.json (403) nên không kéo tự động được → nhập qua file Excel/CSV
# do user bấm "Xuất file". Bộ đọc tự dò dòng tiêu đề + map cột (có ánh xạ tay dự phòng), chỉ lấy phiếu CHI.

def _norm(s):
    s = unicodedata.normalize("NFD", str(s or ""))
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    s = s.replace("đ", "d").replace("Đ", "D")   # NFD KHÔNG tách chữ đ → phải fold tay
    return re.sub(r"\s+", " ", s).strip().lower()


def _num(v):
    s = str(v if v is not None else "")
    neg = s.strip().startswith("-") or "(" in s
    digits = re.sub(r"[^\d]", "", s)
    if not digits:
        return 0
    n = int(digits)
    return -n if neg else n


def _date_str(v):
    if hasattr(v, "strftime"):
        try:
            return v.strftime("%d/%m/%Y")
        except Exception:
            pass
    s = str(v or "").strip()
    m = re.match(r"(\d{4})-(\d{1,2})-(\d{1,2})", s)
    if m:
        return f"{int(m.group(3)):02d}/{int(m.group(2)):02d}/{m.group(1)}"
    m = re.match(r"(\d{1,2})[/-](\d{1,2})[/-](\d{2,4})", s)
    if m:
        return f"{int(m.group(1)):02d}/{int(m.group(2)):02d}/{m.group(3)}"
    return s


_HEADER_HINTS = ["ma phieu", "so tien", "ngay ghi nhan", "ly do thu chi", "loai chung tu",
                 "dien giai", "tham chieu", "ten doi tuong"]
_ALIASES = {
    "ma_phieu": ["ma phieu", "so phieu", "ma chung tu", "so chung tu"],
    "ngay": ["ngay ghi nhan", "ngay hach toan", "ngay chung tu", "ngay tao", "ngay"],
    "doi_tuong": ["ten doi tuong", "doi tuong", "khach hang", "nha cung cap", "ncc"],
    "ly_do": ["ly do thu chi", "ly do", "loai thu chi"],
    "so_tien": ["so tien", "gia tri", "thanh tien"],
    "tham_chieu": ["tham chieu", "chung tu goc", "chung tu tham chieu"],
    "loai_ct": ["loai chung tu", "loai phieu", "phan loai", "phuong thuc"],
    "dien_giai": ["dien giai", "ghi chu", "noi dung", "mo ta"],
}


def _find_exact(cols, names):
    for c in cols:
        if _norm(c) in names:
            return c
    return ""


def _automap(cols):
    ncols = [(c, _norm(c)) for c in cols]
    out = {}
    for field, aliases in _ALIASES.items():
        pick = ""
        for a in aliases:                       # ưu tiên khớp CHÍNH XÁC tên cột
            for c, nc in ncols:
                if nc == a:
                    pick = c
                    break
            if pick:
                break
        if not pick:                            # rồi mới tới khớp CHỨA
            for a in aliases:
                for c, nc in ncols:
                    if a in nc:
                        pick = c
                        break
                if pick:
                    break
        out[field] = pick
    return out


def _read_soquy_table(uploaded):
    name = (uploaded.name or "").lower()
    raw = uploaded.getvalue()

    def _read(header):
        if name.endswith(".csv"):
            for enc in ("utf-8-sig", "utf-8", "cp1258", "latin-1"):
                try:
                    return pd.read_csv(io.BytesIO(raw), header=header, dtype=str, encoding=enc)
                except Exception:
                    continue
            return None
        try:
            return pd.read_excel(io.BytesIO(raw), header=header, dtype=str, engine="openpyxl")
        except Exception:
            return None

    probe = _read(None)
    if probe is None or probe.empty:
        return None
    header_row, best = 0, -1
    for i in range(min(15, len(probe))):
        vals = [_norm(x) for x in probe.iloc[i].tolist()]
        hits = sum(1 for h in _HEADER_HINTS if any(h in v for v in vals))
        if hits > best:
            best, header_row = hits, i
    df = _read(header_row if best > 0 else 0)
    if df is None:
        return None
    df = df.dropna(how="all")
    df.columns = [str(c).strip() for c in df.columns]
    return df


def _parse_soquy_rows(df, m, thu_col, chi_col):
    rows = []
    for _, r in df.iterrows():
        def g(f):
            c = m.get(f)
            if c and c in r and pd.notna(r[c]):
                return r[c]
            return ""
        ma = str(g("ma_phieu") or "").strip()
        loai = str(g("loai_ct") or "")
        nloai = _norm(loai)
        amt = _num(g("so_tien"))
        thu_v = _num(r[thu_col]) if (thu_col and thu_col in r) else 0
        chi_v = _num(r[chi_col]) if (chi_col and chi_col in r) else 0
        if chi_col or thu_col:                        # file có cột Thu/Chi riêng
            if chi_v > 0:
                kind, amount = "chi", chi_v
            elif thu_v > 0:
                kind, amount = "thu", thu_v
            else:
                kind, amount = "?", abs(amt)
        elif "chi" in nloai and "thu" not in nloai:   # phân loại theo "Loại chứng từ"
            kind, amount = "chi", abs(amt)
        elif "thu" in nloai:
            kind, amount = "thu", abs(amt)
        elif amt < 0:
            kind, amount = "chi", -amt
        else:
            kind, amount = "?", abs(amt)
        date = _date_str(g("ngay"))
        dt = str(g("doi_tuong") or "").strip()
        if not ma and not date and not amount:
            continue
        if not amount:
            continue
        if not ma and _norm(dt).startswith("tong"):   # bỏ dòng tổng cộng
            continue
        rows.append({
            "voucher_code": ma, "date": date, "doi_tuong": dt,
            "ly_do": str(g("ly_do") or "").strip(), "amount": int(amount),
            "tham_chieu": str(g("tham_chieu") or "").strip(), "loai_ct": loai.strip(),
            "dien_giai": str(g("dien_giai") or "").strip(), "kind": kind,
        })
    return rows


def _do_save_soquy(new_rows):
    entries = [{
        "type": "so_quy_chi", "date": r.get("date", ""), "amount": int(r.get("amount") or 0),
        "partner": r.get("doi_tuong", ""), "note": r.get("ly_do", "") or r.get("dien_giai", ""),
        "detail": r,
    } for r in new_rows]
    ok = picklog.add_input_costs(entries)
    st.session_state["msg_soquy"] = (("success", f"Đã lưu {len(entries)} phiếu chi từ sổ quỹ Sapo.")
                                     if ok else ("error", "Lưu thất bại (không ghi được vào kho dữ liệu)."))


def _soquy_tab():
    st.caption("Sapo chặn API sổ quỹ (403) nên nhập qua **file**: trên trang Sổ quỹ Sapo bấm **Xuất file** "
               "→ tải Excel → kéo lên đây. Em tự lọc **phiếu CHI**, chống trùng theo Mã phiếu.")
    msg = st.session_state.pop("msg_soquy", None)
    if msg:
        getattr(st, msg[0])(msg[1])
    up = st.file_uploader("File sổ quỹ Sapo (.xlsx / .csv)", type=["xlsx", "xls", "csv"], key="soquy_file")
    if not up:
        st.info("Chưa có file. Xuất file từ Sổ quỹ Sapo rồi kéo lên đây.")
        return
    df = _read_soquy_table(up)
    if df is None or df.empty:
        st.error("Không đọc được file. Đảm bảo là file Excel/CSV xuất từ Sổ quỹ Sapo.")
        return
    cols = list(df.columns)
    m = _automap(cols)
    thu_col = _find_exact(cols, {"thu", "tien thu", "so tien thu"})
    chi_col = _find_exact(cols, {"chi", "tien chi", "so tien chi"})

    with st.expander("⚙️ Ánh xạ cột (chỉ mở nếu nhận diện sai)"):
        opts = ["(không có)"] + cols

        def _sel(label, field):
            cur = m.get(field, "")
            idx = opts.index(cur) if cur in opts else 0
            pick = st.selectbox(label, opts, index=idx, key=f"soqmap_{field}")
            m[field] = "" if pick == "(không có)" else pick
        _sel("Cột Số tiền", "so_tien")
        _sel("Cột Loại chứng từ (phân biệt thu/chi)", "loai_ct")
        _sel("Cột Ngày", "ngay")
        _sel("Cột Mã phiếu", "ma_phieu")
        _sel("Cột Đối tượng", "doi_tuong")
        _sel("Cột Lý do", "ly_do")
        _sel("Cột Diễn giải", "dien_giai")

    if not m.get("so_tien") and not (thu_col or chi_col):
        st.error("Chưa xác định được cột **Số tiền**. Mở '⚙️ Ánh xạ cột' để chọn tay.")
        st.caption("Các cột trong file: " + ", ".join(cols))
        return

    allrows = _parse_soquy_rows(df, m, thu_col, chi_col)
    chi_rows = [r for r in allrows if r["kind"] == "chi"]
    thu_n = sum(1 for r in allrows if r["kind"] == "thu")
    unk = [r for r in allrows if r["kind"] == "?"]

    existing = {str((x.get("detail") or {}).get("voucher_code") or "").strip()
                for x in picklog.read_input_costs() if x.get("type") == "so_quy_chi"}
    existing.discard("")
    new_rows = [r for r in chi_rows if r["voucher_code"] and r["voucher_code"] not in existing]
    new_rows += [r for r in chi_rows if not r["voucher_code"]]     # phiếu không mã: vẫn cho lưu
    dup_n = sum(1 for r in chi_rows if r["voucher_code"] and r["voucher_code"] in existing)

    st.success(f"Đọc {len(allrows)} dòng · **{len(chi_rows)} phiếu CHI** · {thu_n} phiếu thu (bỏ qua) · "
               f"{len(unk)} chưa rõ.")
    c = st.columns(3)
    c[0].metric("Phiếu CHI mới", f"{len(new_rows)}")
    c[1].metric("Tổng tiền CHI mới", _fmt(sum(r['amount'] for r in new_rows)) + "đ")
    c[2].metric("Đã có (bỏ qua)", f"{dup_n}")
    if unk:
        st.warning(f"{len(unk)} dòng không phân biệt được thu/chi → KHÔNG lưu. Nếu file dùng cột khác để "
                   "phân loại thu/chi, chỉnh lại ở '⚙️ Ánh xạ cột'.")

    prev = new_rows if new_rows else chi_rows
    if prev:
        st.dataframe(pd.DataFrame([{
            "Mã phiếu": r["voucher_code"], "Ngày": r["date"], "Đối tượng": r["doi_tuong"],
            "Lý do": r["ly_do"], "Số tiền": _fmt(r["amount"]) + "đ", "Diễn giải": r["dien_giai"],
        } for r in prev[:200]]), use_container_width=True, hide_index=True)
        if len(prev) > 200:
            st.caption(f"(hiển thị 200/{len(prev)} dòng đầu — vẫn lưu đủ khi bấm)")

    st.button(f"💾 Lưu {len(new_rows)} phiếu CHI vào Chi phí đầu vào", type="primary",
              disabled=not new_rows, key="soquy_save", on_click=_do_save_soquy, args=(new_rows,))


def _esc_c(v):
    return (str(v if v is not None else "").replace("&", "&amp;")
            .replace("<", "&lt;").replace(">", "&gt;"))


def _detail_print_html(x):
    """Dựng lại CHỨNG TỪ đã lưu để XEM + IN A4 — đầy đủ như bản gốc (2 bên, lô hàng,
    bảng SP, tạm ứng, NVL, hình thức thanh toán, ô ký)."""
    d = x.get("detail") or {}
    typ = x.get("type") or ""
    ttl = {"gia_cong": "BIÊN BẢN GIAO NHẬN VÀ THANH TOÁN GIA CÔNG",
           "mua_vai_ke": "BẢNG KÊ MUA VẢI",
           "thanh_toan_mua_vai": "PHIẾU THANH TOÁN MUA VẢI",
           "so_quy_chi": "PHIẾU CHI (SỔ QUỸ)"}.get(typ, "CHỨNG TỪ CHI PHÍ ĐẦU VÀO")
    A, B = d.get("ben_a") or {}, d.get("ben_b") or {}

    _BL = '<span class="bl"></span>'          # gạch trống để ĐIỀN TAY khi chưa có dữ liệu

    def _party(t, o, is_a=False):
        """Chưa lưu trường nào thì CHỪA GẠCH TRỐNG để điền tay (không mượn tên bên kia)."""
        r = f'<div class="pt"><div class="pth">{t}</div>'
        _ten = o.get("ten") or ("" if is_a else (x.get("partner") or ""))
        r += f'<div><b>Tên:</b> {_esc_c(_ten) if _ten else _BL}</div>'
        if is_a:
            r += f'<div><b>Đại diện:</b> {_esc_c(o.get("daidien")) if o.get("daidien") else _BL}</div>'
        for k, lb in (("cccd", "CMND/CCCD"), ("diachi", "Địa chỉ"), ("sdt", "Điện thoại")):
            r += f'<div><b>{lb}:</b> {_esc_c(o[k]) if o.get(k) else _BL}</div>'
        return r + "</div>"

    money = [("gross", "Tiền gia công"), ("defect", "Trừ hàng lỗi"),
             ("adv", "Đã tạm ứng"), ("mat", "NVL bên B mua hộ")]
    rows = ""
    for k, lb in money:
        if d.get(k):
            rows += f'<tr><td class="l">{lb}</td><td class="r">{_fmt(d[k])}đ</td></tr>'
    for k, lb in (("qty", "Tổng SL nhận"), ("bad_qty", "SL lỗi"), ("so_lo", "Số lô"),
                  ("ngay_giao", "Ngày giao")):
        if d.get(k) not in (None, "", 0):
            rows += f'<tr><td class="l">{lb}</td><td class="r">{_esc_c(d[k])}</td></tr>'

    def _tbl(items, cols, keys, title):
        if not isinstance(items, list) or not items:
            return ""
        tr = ""
        for n, it in enumerate(items, 1):
            if not isinstance(it, dict):
                continue
            tr += f'<tr><td class="c">{n}</td>' + "".join(
                f'<td class="{("r" if _k not in keys[:1] else "")}">{_esc_c(it.get(_k))}</td>' for _k in keys) + "</tr>"
        if not tr:
            return ""
        th = "".join(f"<th>{c}</th>" for c in cols)
        return (f'<div class="sec">{title}</div><table class="tb"><thead><tr><th>#</th>{th}</tr></thead>'
                f'<tbody>{tr}</tbody></table>')

    css = ("*{box-sizing:border-box}body{margin:0;font-family:Tahoma,Arial,sans-serif;color:#111}"
           ".wrap{max-width:190mm;margin:0 auto;padding:6mm}"
           ".ttl{text-align:center;font-size:18px;font-weight:800;margin:2px 0 8px}"
           ".meta{font-size:12.5px;margin-bottom:8px}"
           ".pts{display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-bottom:8px}"
           ".pt{border:1px solid #999;padding:6px 8px;font-size:12.5px;line-height:1.55}"
           ".pth{font-weight:800;margin-bottom:3px}"
           ".sec{font-weight:800;font-size:13px;margin:10px 0 3px}"
           "table{border-collapse:collapse;width:100%;font-size:12.5px}"
           "th,td{border:1px solid #999;padding:4px 7px}th{background:#eee}"
           "td.l{width:45%;font-weight:600}td.r{text-align:right}td.c{text-align:center;width:9mm}"
           ".tot{margin-top:10px;font-size:16px;font-weight:800;text-align:right}"
           ".bl{display:inline-block;min-width:42mm;border-bottom:1px dotted #666;height:12px}"
           ".sign{display:flex;justify-content:space-around;margin-top:22px;font-size:12.5px;text-align:center}"
           "@page{size:A4;margin:12mm}")
    body = (f'<div class="wrap"><div class="ttl">{ttl}</div>'
            f'<div class="meta">Hôm nay, ngày <b>{_esc_c(x.get("date") or "—")}</b>'
            + (f' &nbsp;tại: <b>{_esc_c(d.get("tai"))}</b>' if d.get("tai") else "")
            + f' &nbsp;·&nbsp; <span style="color:#666">lưu lúc {_esc_c(x.get("saved_at") or "")}</span></div>'
            + '<div class="pts">' + _party("BÊN A (BÊN ĐẶT GIA CÔNG)", A, True)
            + _party("BÊN B (BÊN NHẬN GIA CÔNG)", B) + '</div>'
            + (f'<div class="sec">I. THÔNG TIN LÔ HÀNG & THANH TOÁN</div><table>{rows}</table>' if rows else "")
            + _tbl(d.get("skus"), ["SKU / Mặt hàng", "SL", "Đơn giá", "Lỗi"],
                   ["sku", "qty", "unit", "bad"], "II. CHI TIẾT SẢN PHẨM")
            + _tbl(d.get("advs"), ["Nội dung tạm ứng", "Số tiền"], ["note", "amt"], "III. TẠM ỨNG")
            + _tbl(d.get("mats"), ["Nội dung NVL", "SL", "Đơn giá"], ["name", "qty", "unit"],
                   "IV. NVL BÊN B MUA HỘ")
            + f'<div class="tot">TỔNG THỰC TRẢ: {_fmt(x.get("amount"))}đ</div>'
            + '<div class="sec">V. THÔNG TIN CHUYỂN KHOẢN</div>'
            + '<table>'
            + f'<tr><td class="l">Hình thức thanh toán</td><td class="r">{_esc_c(d.get("pttt")) or _BL}</td></tr>'
            + f'<tr><td class="l">Ngân hàng</td><td class="r">{_esc_c(d.get("hinh_thuc")) or _BL}</td></tr>'
            + f'<tr><td class="l">Chủ tài khoản</td><td class="r">{_esc_c(d.get("ctk")) or _BL}</td></tr>'
            + f'<tr><td class="l">Số tài khoản</td><td class="r">{_esc_c(d.get("stk")) or _BL}</td></tr>'
            + f'<tr><td class="l">Ngày chuyển khoản</td><td class="r">{_BL}</td></tr>'
            + f'<tr><td class="l">Số tiền đã chuyển</td><td class="r">{_BL}</td></tr>'
            + f'<tr><td class="l">Nội dung / mã giao dịch</td><td class="r">{_BL}</td></tr>'
            + '</table>'
            + (f'<div class="meta">{_esc_c(d.get("tdtt"))}</div>' if d.get("tdtt") else "")
            + '<div class="sign"><div>BÊN A (đặt gia công)<br><br><br>_______________</div>'
            '<div>BÊN B (nhận gia công)<br><br><br>_______________</div></div></div>')
    js = ("function pr(){var h=document.getElementById('doc').innerHTML;"
          "var f=document.createElement('iframe');"
          "f.style.cssText='position:fixed;right:0;bottom:0;width:0;height:0;border:0';"
          "document.body.appendChild(f);var d=f.contentWindow.document;d.open();"
          "d.write('<!doctype html><html><head><meta charset=\"utf-8\"><style>'+"
          + json.dumps(css) +
          "+'</style></head><body>'+h+'</body></html>');d.close();"
          "f.onload=function(){f.contentWindow.focus();f.contentWindow.print();"
          "setTimeout(function(){try{document.body.removeChild(f);}catch(e){}},800);};}")
    return ("<style>" + css + ".btn{background:#2563eb;color:#fff;border:0;border-radius:6px;"
            "padding:8px 16px;font-weight:700;cursor:pointer}</style>"
            "<div style='text-align:right;margin:6px'>"
            "<button class='btn' onclick='pr()'>🖨️ In A4 / Lưu PDF</button></div>"
            "<div id='doc'>" + body + "</div><script>" + js + "</script>")


def _saved_tab():
    items = list(picklog.read_input_costs() or [])
    items.sort(key=lambda x: str(x.get("saved_at", "")), reverse=True)

    msg = st.session_state.pop("msg_list", None)
    if msg:
        getattr(st, msg[0])(msg[1])

    # bộ lọc tháng
    months = sorted({_month_of(x.get("date")) for x in items if _month_of(x.get("date"))}, reverse=True)
    pick = st.selectbox("Lọc theo tháng", ["Tất cả"] + months, key="cost_month_filter")
    view = items if pick == "Tất cả" else [x for x in items if _month_of(x.get("date")) == pick]

    total_all = sum(int(x.get("amount") or 0) for x in view)
    by_type = {}
    for x in view:
        by_type[x.get("type")] = by_type.get(x.get("type"), 0) + int(x.get("amount") or 0)
    present = sorted(by_type.items(), key=lambda kv: -kv[1])
    m = st.columns(1 + min(4, len(present)))
    m[0].metric("💸 Tổng chi phí đầu vào", _fmt(total_all) + "đ",
                help="Tổng tất cả chi phí đầu vào đã lưu trong phạm vi lọc.")
    for i, (t, v) in enumerate(present[:4]):
        m[i + 1].metric(f"{_TYPE_ICON.get(t, '📌')} {_TYPE_LABEL.get(t, t)}", _fmt(v) + "đ")
    if len(present) > 4:
        st.caption("Khác: " + " · ".join(f"{_TYPE_LABEL.get(t, t)}: {_fmt(v)}đ" for t, v in present[4:]))

    st.divider()
    if not view:
        st.info("Chưa có chi phí nào được lưu. Nhập ở 3 tab công cụ rồi bấm Lưu, hoặc thêm tay bên dưới.")
    else:
        h = st.columns([2.2, 1.3, 3, 1.8, 0.7, 0.7])
        for col, t in zip(h, ["Loại", "Ngày", "Đối tác / nội dung", "Số tiền", "Xem", ""]):
            col.markdown(f"**{t}**")
        for x in view:
            cid = str(x.get("id") or "")
            c = st.columns([2.2, 1.3, 3, 1.8, 0.7, 0.7])
            c[0].write(f"{_TYPE_ICON.get(x.get('type'), '📌')} {_TYPE_LABEL.get(x.get('type'), x.get('type'))}")
            c[1].write(x.get("date") or "—")
            _extra = ""
            det = x.get("detail") or {}
            if x.get("type") == "thanh_toan_mua_vai" and det.get("count"):
                _extra = f" · {det.get('count')} GD"
            elif x.get("type") == "mua_vai_ke" and det.get("count"):
                _extra = f" · {det.get('count')} dòng vải"
            elif x.get("type") == "gia_cong" and det.get("so_lo"):
                _extra = f" · lô {det.get('so_lo')}"
            elif x.get("type") == "so_quy_chi" and det.get("voucher_code"):
                _extra = f" · {det.get('voucher_code')}"
            c[2].write((x.get("partner") or "—") + _extra + (f" — {x.get('note')}" if x.get("note") else ""))
            c[3].write(f"**{_fmt(x.get('amount'))}đ**")
            if c[4].button("👁️", key=f"view_{cid}", help="Xem lại & IN chứng từ đã lưu"):
                st.session_state["cost_view_id"] = ("" if st.session_state.get("cost_view_id") == cid else cid)
            c[5].button("🗑️", key=f"del_{cid}", help="Xoá chi phí này", on_click=_do_delete, args=(cid,))

        # XEM LẠI + IN chứng từ đã lưu (dựng từ dữ liệu đã lưu lúc bấm Lưu)
        _vid = str(st.session_state.get("cost_view_id") or "")
        if _vid:
            _x = next((y for y in view if str(y.get("id") or "") == _vid), None)
            if _x:
                st.divider()
                st.markdown(f"#### 🧾 Chứng từ: {_TYPE_LABEL.get(_x.get('type'), _x.get('type'))}"
                            f" — {_x.get('partner') or ''} · {_x.get('date') or ''}")
                components.html(_detail_print_html(_x), height=760, scrolling=True)
                st.caption("Bản dựng lại từ dữ liệu đã lưu (số liệu + danh sách SP). "
                           "Muốn bản gốc đầy đủ CCCD/địa chỉ thì nhập lại ở tab công cụ rồi bấm In A4 tại đó.")

    st.divider()
    with st.expander("➕ Thêm chi phí khác (nhập tay) — cho khoản không dùng 3 công cụ trên"):
        a = st.columns([1.6, 1.3, 1.5])
        a[0].selectbox("Loại", list(_TYPE_LABEL), key="man_type",
                       format_func=lambda k: _TYPE_LABEL[k], index=len(_TYPE_LABEL) - 1)
        a[1].date_input("Ngày", key="man_date")
        a[2].number_input("Số tiền (đ)", min_value=0, step=100000, key="man_amount")
        b = st.columns([2, 3, 1])
        b[0].text_input("Đối tác / nhà cung cấp", key="man_partner")
        b[1].text_input("Ghi chú", key="man_note")
        b[2].button("Thêm", use_container_width=True, on_click=_do_manual_add)


def render():
    st.title("💸 Chi phí đầu vào")
    st.caption("3 công cụ lập chứng từ mua vải / gia công (giữ nguyên như bản gốc). Nhập xong bấm "
               "**💾 Lưu vào chi phí đầu vào** ở cuối mỗi khung để ghi nhận vào sổ. Nút **In A4 / Xuất Excel / "
               "Lưu file** của công cụ vẫn dùng bình thường.")
    tabs = st.tabs([
        "🧾 Bảng kê mua vải",
        "💳 Thanh toán mua vải",
        "🧵 Thanh toán gia công",
        "🏦 Sổ quỹ Sapo",
        "📊 Chi phí đã lưu",
    ])
    with tabs[0]:
        _tool_tab("mua_vai_ke", "bang-ke-mua-vai.html", 1200,
                  "Kê chi tiết từng loại vải mua vào. Tổng = Σ (số lượng × đơn giá) các dòng.")
    with tabs[1]:
        _tool_tab("thanh_toan_mua_vai", "xac-nhan-thanh-toan-mua-vai.html", 900,
                  "Ghi các giao dịch chuyển khoản thanh toán tiền vải (theo quý). Tổng = Σ số tiền các dòng.")
    with tabs[2]:
        _tool_tab("gia_cong", "bien-ban-gia-cong.html", 1550,
                  "Biên bản giao nhận & thanh toán gia công. Lưu theo TỔNG TIỀN THỰC NHẬN của bên gia công.")
    with tabs[3]:
        _soquy_tab()
    with tabs[4]:
        _saved_tab()
