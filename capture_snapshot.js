/* ════════════════════════════════════════════════════════════════════════
   capture_snapshot.js — Chụp dữ liệu "Báo cáo sáng" từ Sapo ra file JSON.

   CÁCH DÙNG (tự phục vụ, không cần cookie/API):
   1. Mở & đăng nhập https://vitranboutiquehcm.mysapo.net/admin/orders
   2. Nhấn F12 → tab Console → dán TOÀN BỘ file này → Enter
   3. Đợi ~30 giây → trình duyệt tự tải file "sapo_snapshot.json" về Downloads
   4. Chép file đó đè vào thư mục dự án (cạnh app.py) rồi bấm 🔄 trên dashboard.
      (Hoặc nhờ Claude: "cập nhật dữ liệu" — Claude sẽ chạy lại giúp.)

   Có deadline-guard 38s: tự dừng vòng lặp trước khi treo, không để loop chạy ngầm.
   ════════════════════════════════════════════════════════════════════════ */
(async () => {
  const t0 = Date.now();
  const j = async (p) => (await fetch(p)).json();

  // ---- 1. CHỜ XÁC NHẬN (status=open & issue_status=pending) ----
  const od = await j('/admin/orders.json?limit=250&page=1&status=open');
  const pending = (od.orders || []).filter(o => o.issue_status === 'pending');
  const now = new Date();
  const todayUTC = new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate(), 17, 0, 0));
  const todayStart = new Date(todayUTC.getTime() - 86400000).toISOString().replace('Z', '');     // 00:00 VN
  const yestStart  = new Date(todayUTC.getTime() - 2 * 86400000).toISOString().replace('Z', '');
  const sources = {}, carriers = {}, skuMap = {};
  let totalItems = 0, fast = 0, express = 0;
  pending.forEach(o => {
    sources[o.source_name || 'Khác'] = (sources[o.source_name || 'Khác'] || 0) + 1;
    const sl = (o.shipping_lines && o.shipping_lines[0]) || {};
    let c = sl.carrier_name || sl.title || 'Chưa rõ';
    if (sl.code === 'sapo_fulfillment_by_seller' && !sl.carrier_name) c = 'NB tự VC';
    carriers[c] = (carriers[c] || 0) + 1;
    if (o.shipment_category === 'express') express++; else fast++;
    (o.line_items || []).forEach(li => {
      const s = li.sku || 'N/A';
      if (!skuMap[s]) skuMap[s] = { sku: s, name: li.title || s, qty: 0, orders: 0 };
      skuMap[s].qty += li.quantity; skuMap[s].orders += 1; totalItems += li.quantity;
    });
  });
  const pendingOut = {
    total: pending.length,
    today: pending.filter(o => o.created_on >= todayStart).length,
    yesterday: pending.filter(o => o.created_on >= yestStart && o.created_on < todayStart).length,
    total_items: totalItems, sku_count: Object.keys(skuMap).length,
    sources, carriers, fast, express,
    skus: Object.values(skuMap).sort((a, b) => b.qty - a.qty),
  };

  // ---- Tập đơn KHÁNG NGHỊ THÀNH CÔNG + gom phiếu trả (30 ngày) ----
  const cutoff30 = new Date(Date.now() - 30 * 86400000).toISOString();
  const appealed = new Set();
  let allReturns = [];
  for (let p = 1; p <= 20; p++) {
    if (Date.now() - t0 > 38000) break;
    const rd = await j('/admin/order_returns.json?limit=250&page=' + p);
    const rs = rd.order_returns || [];
    if (!rs.length) break;
    allReturns = allReturns.concat(rs);
    rs.forEach(x => { if (x.status === 'canceled') appealed.add(x.order_id); });
    if (rs[rs.length - 1].created_on < cutoff30) break;
  }

  // ---- 2. ĐÃ ĐẨY VC → HỦY (7 ngày), loại trừ kháng nghị ----
  const weekAgo = new Date(Date.now() - 7 * 86400000).toISOString();
  let allCx = [];
  for (let p = 1; p <= 25; p++) {
    if (Date.now() - t0 > 38000) break;
    const d = await j('/admin/orders.json?limit=250&status=cancelled&page=' + p);
    const os = d.orders || [];
    if (!os.length) break;
    allCx = allCx.concat(os.filter(o => o.fulfillments && o.fulfillments.length > 0
      && o.cancelled_on >= weekAgo && !appealed.has(o.id)));
    if (os.length < 250) break;
  }
  const slim = o => ({
    id: o.id, name: o.name, cancelled_on: o.cancelled_on,
    shipping_lines: [{ carrier_name: (o.shipping_lines && o.shipping_lines[0] && o.shipping_lines[0].carrier_name) || null }],
    fulfillments: [{
      tracking_number: o.fulfillments[0].tracking_number,
      tracking_company: o.fulfillments[0].tracking_company,
      packed_status: o.fulfillments[0].packed_status,
    }],
    line_items: (o.line_items || []).map(li => ({ sku: li.sku, quantity: li.quantity })),
  });
  const cancelledOut = {
    total: allCx.length, excluded_appeal: appealed.size,
    packed: allCx.filter(o => o.fulfillments[0].packed_status === 'packed').map(slim),
    not_packed: allCx.filter(o => o.fulfillments[0].packed_status !== 'packed').map(slim),
  };

  // ---- 3. ĐƠN TRẢ HÀNG (7 ngày), tách theo trạng thái ----
  const recent = allReturns.filter(x => x.created_on >= weekAgo);
  const by = s => recent.filter(x => x.status === s).length;
  const returnsOut = {
    recent7d_total: recent.length, open: by('open'), closed: by('closed'),
    canceled: by('canceled'), active: recent.filter(x => x.status !== 'canceled').length,
  };

  // ---- Đóng gói payload + tải về ----
  const payload = {
    generated_at_vn: new Date(Date.now() + 7 * 3600000).toISOString().slice(0, 19).replace('T', ' '),
    pending: pendingOut, cancelled: cancelledOut, returns: returnsOut,
  };
  const blob = new Blob([JSON.stringify(payload)], { type: 'application/json' });
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = 'sapo_snapshot.json';
  document.body.appendChild(a);
  a.click();
  setTimeout(() => { URL.revokeObjectURL(a.href); a.remove(); }, 1500);
  console.log('✅ Đã tải sapo_snapshot.json | chờ xác nhận:', pendingOut.total,
    '| đơn hủy 7d:', cancelledOut.total, '| phiếu trả 7d:', returnsOut.recent7d_total,
    '| thời gian:', (Date.now() - t0) + 'ms');
  return payload.generated_at_vn;
})();
