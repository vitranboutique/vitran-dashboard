"""Trang CHI PHÍ ĐẦU VÀO — nhúng 3 công cụ HTML (GIỮ NGUYÊN, không sửa) + lưu vào Gist.

3 công cụ đọc verbatim từ tools/cost/*.html. Mỗi công cụ được nhúng qua components.html; vì iframe
KHÔNG gửi được dữ liệu thẳng về server (giới hạn Streamlit), ta chèn thêm 1 THANH LƯU (bridge) ở
cuối iframe: nút "Lưu vào chi phí đầu vào" đọc dữ liệu từ chính state/DOM của công cụ → gom JSON gọn
→ tự sao chép. Người dùng dán (Ctrl+V) vào ô bên dưới khung rồi bấm Lưu → picklog.add_input_cost().
Bản thân file công cụ trên đĩa KHÔNG bị thay đổi (bridge chèn lúc render, nối chuỗi ở Python)."""

import os
import json

import streamlit as st
import streamlit.components.v1 as components

import picklog

_TOOL_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tools", "cost")

_TYPE_LABEL = {
    "mua_vai_ke": "Bảng kê mua vải",
    "thanh_toan_mua_vai": "Thanh toán mua vải",
    "gia_cong": "Thanh toán gia công",
    "khac": "Chi phí khác",
}
_TYPE_ICON = {"mua_vai_ke": "🧾", "thanh_toan_mua_vai": "💳", "gia_cong": "🧵", "khac": "📌"}


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
    __vitranEmit({type:'gia_cong', date:date, partner:partner, so_lo:((document.getElementById('so_lo')||{}).value)||'', amount:net,
      gross:num((document.getElementById('sumGross')||{}).textContent),
      defect:num((document.getElementById('sumDefect')||{}).textContent),
      adv:num((document.getElementById('sumAdv')||{}).textContent),
      mat:num((document.getElementById('sumMat')||{}).textContent), count:skus.length, skus:skus});
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
    m = st.columns(4)
    m[0].metric("💸 Tổng chi phí đầu vào", _fmt(total_all) + "đ",
                help="Tổng tất cả chi phí đầu vào đã lưu trong phạm vi lọc.")
    m[1].metric("🧾 Mua vải (bảng kê)", _fmt(by_type.get("mua_vai_ke", 0)) + "đ")
    m[2].metric("💳 Thanh toán mua vải", _fmt(by_type.get("thanh_toan_mua_vai", 0)) + "đ")
    m[3].metric("🧵 Gia công", _fmt(by_type.get("gia_cong", 0)) + "đ")
    khac = by_type.get("khac", 0)
    if khac:
        st.caption(f"📌 Chi phí khác: {_fmt(khac)}đ")

    st.divider()
    if not view:
        st.info("Chưa có chi phí nào được lưu. Nhập ở 3 tab công cụ rồi bấm Lưu, hoặc thêm tay bên dưới.")
    else:
        h = st.columns([2.2, 1.3, 3, 1.8, 0.9])
        for col, t in zip(h, ["Loại", "Ngày", "Đối tác / nội dung", "Số tiền", ""]):
            col.markdown(f"**{t}**")
        for x in view:
            cid = str(x.get("id") or "")
            c = st.columns([2.2, 1.3, 3, 1.8, 0.9])
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
            c[2].write((x.get("partner") or "—") + _extra + (f" — {x.get('note')}" if x.get("note") else ""))
            c[3].write(f"**{_fmt(x.get('amount'))}đ**")
            c[4].button("🗑️", key=f"del_{cid}", help="Xoá chi phí này", on_click=_do_delete, args=(cid,))

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
        _saved_tab()
