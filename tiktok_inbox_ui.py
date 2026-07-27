"""TikTok Shop Customer Service UI used while API access is under review.

The page uses clearly labelled test data. It never calls TikTok APIs or writes
to operational data.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from html import escape

import streamlit as st


_CONVERSATIONS = [
    {
        "id": "test-001",
        "buyer": "Nguyễn Minh Anh",
        "avatar": "MA",
        "status": "Đang hỗ trợ",
        "unread": 2,
        "last": "Mình muốn đổi sang size M được không shop?",
        "time": "19:18",
        "order": {
            "code": "576321908441250136",
            "product": "Đầm midi cổ vuông VITRAN",
            "variant": "Đen / Size S",
            "quantity": 1,
            "amount": "629.000đ",
            "payment": "Đã thanh toán",
        },
        "shipping": {
            "carrier": "J&T Express",
            "tracking": "841923650771",
            "status": "Chờ lấy hàng",
            "estimate": "29/07/2026",
        },
        "after_sale": {
            "status": "Chưa phát sinh",
            "request": "—",
            "refund": "0đ",
        },
        "messages": [
            {"sender": "buyer", "text": "Shop ơi đơn này đã giao cho vận chuyển chưa ạ?", "time": "19:12"},
            {"sender": "shop", "text": "Chào chị Minh Anh, đơn đã đóng gói và đang chờ J&T đến lấy trong hôm nay ạ.", "time": "19:14"},
            {"sender": "buyer", "text": "Mình muốn đổi sang size M được không shop?", "time": "19:18"},
        ],
    },
    {
        "id": "test-002",
        "buyer": "Trần Thu Hà",
        "avatar": "TH",
        "status": "Chờ phản hồi",
        "unread": 1,
        "last": "Mẫu này chất có co giãn không?",
        "time": "18:46",
        "order": {
            "code": "Chưa có đơn hàng",
            "product": "Áo kiểu tay lỡ VITRAN",
            "variant": "Kem / Size M",
            "quantity": 0,
            "amount": "—",
            "payment": "—",
        },
        "shipping": {
            "carrier": "—",
            "tracking": "—",
            "status": "Chưa phát sinh",
            "estimate": "—",
        },
        "after_sale": {
            "status": "Chưa phát sinh",
            "request": "—",
            "refund": "0đ",
        },
        "messages": [
            {"sender": "buyer", "text": "Mẫu này chất có co giãn không?", "time": "18:46"},
        ],
    },
    {
        "id": "test-003",
        "buyer": "Lê Ngọc Trâm",
        "avatar": "NT",
        "status": "Đã giải quyết",
        "unread": 0,
        "last": "Cảm ơn shop, mình nhận được tiền rồi.",
        "time": "17:30",
        "order": {
            "code": "576204498301775220",
            "product": "Quần suông cạp cao VITRAN",
            "variant": "Nâu / Size L",
            "quantity": 1,
            "amount": "489.000đ",
            "payment": "Đã thanh toán",
        },
        "shipping": {
            "carrier": "BEST Express",
            "tracking": "BESTVN23049817",
            "status": "Đã hoàn về kho",
            "estimate": "Đã hoàn tất",
        },
        "after_sale": {
            "status": "Đã hoàn tiền",
            "request": "Khách trả hàng do không vừa",
            "refund": "489.000đ",
        },
        "messages": [
            {"sender": "buyer", "text": "Shop kiểm tra giúp mình tiền hoàn đơn này nhé.", "time": "17:20"},
            {"sender": "shop", "text": "Shop đã kiểm tra: TikTok đã hoàn 489.000đ về phương thức thanh toán ban đầu của chị.", "time": "17:25"},
            {"sender": "buyer", "text": "Cảm ơn shop, mình nhận được tiền rồi.", "time": "17:30"},
        ],
    },
]


def _init_state() -> None:
    if "tiktok_cs_conversations" not in st.session_state:
        st.session_state["tiktok_cs_conversations"] = deepcopy(_CONVERSATIONS)
    if "tiktok_cs_selected" not in st.session_state:
        st.session_state["tiktok_cs_selected"] = _CONVERSATIONS[0]["id"]


def _card(title: str, rows: list[tuple[str, object]], accent: str = "#fe2c55") -> None:
    body = "".join(
        f'<div class="tt-row"><span>{escape(str(label))}</span>'
        f'<strong>{escape(str(value))}</strong></div>'
        for label, value in rows
    )
    st.markdown(
        f'<section class="tt-info-card" style="--accent:{accent}">'
        f'<h4>{escape(title)}</h4>{body}</section>',
        unsafe_allow_html=True,
    )


def _render_styles() -> None:
    st.markdown(
        """
        <style>
        .tt-head{display:flex;align-items:center;justify-content:space-between;gap:16px;
          padding:18px 22px;border:1px solid #e8e8eb;border-radius:16px;background:#fff;
          box-shadow:0 8px 24px rgba(22,24,35,.05);margin-bottom:14px}
        .tt-title{font-size:1.55rem;font-weight:850;color:#161823;line-height:1.2}
        .tt-sub{color:#6b6f76;font-size:.9rem;margin-top:4px}
        .tt-live{background:#eaf8f1;color:#087f5b;border:1px solid #bce8d6;
          padding:7px 11px;border-radius:999px;font-weight:750;font-size:.78rem}
        .tt-test{background:#fff7e6;border:1px solid #ffd591;color:#8c5a00;
          padding:10px 14px;border-radius:10px;margin:6px 0 16px}
        .tt-person{display:flex;align-items:center;gap:11px;padding:4px 0 12px;
          border-bottom:1px solid #ececef;margin-bottom:10px}
        .tt-avatar{width:42px;height:42px;display:flex;align-items:center;justify-content:center;
          border-radius:50%;font-weight:850;background:linear-gradient(135deg,#25f4ee,#fe2c55);
          color:#fff}
        .tt-person-name{font-weight:850;color:#161823}
        .tt-person-meta{font-size:.8rem;color:#777b82}
        .tt-bubble{max-width:82%;padding:10px 13px;border-radius:14px;margin:7px 0;
          line-height:1.45;font-size:.92rem}
        .tt-buyer{background:#f2f3f5;color:#161823;border-bottom-left-radius:4px}
        .tt-shop{background:#161823;color:#fff;margin-left:auto;border-bottom-right-radius:4px}
        .tt-time{font-size:.7rem;opacity:.68;margin-top:3px}
        .tt-info-card{background:#fff;border:1px solid #e8e8eb;border-top:3px solid var(--accent);
          padding:14px 15px;border-radius:12px;margin-bottom:12px}
        .tt-info-card h4{margin:0 0 9px;color:#161823;font-size:.96rem}
        .tt-row{display:flex;justify-content:space-between;gap:12px;padding:6px 0;
          border-bottom:1px dashed #ececef;font-size:.82rem}
        .tt-row:last-child{border-bottom:0}
        .tt-row span{color:#72767d}.tt-row strong{text-align:right;color:#24262b}
        div[data-testid="stChatInput"]{border-color:#d9d9df}
        </style>
        """,
        unsafe_allow_html=True,
    )


def render() -> None:
    """Render the functional test inbox."""
    _init_state()
    _render_styles()

    st.markdown(
        """
        <div class="tt-head">
          <div>
            <div class="tt-title">TikTok Shop Customer Service</div>
            <div class="tt-sub">Trung tâm hội thoại và hỗ trợ người mua · VITRAN BOUTIQUE</div>
          </div>
          <div class="tt-live">● Hệ thống sẵn sàng</div>
        </div>
        <div class="tt-test"><b>Môi trường phát triển:</b> đang dùng dữ liệu kiểm thử
        trong thời gian chờ TikTok phê duyệt quyền <code>seller.customer_service</code>.
        Không có tin nhắn nào được gửi tới khách thật.</div>
        """,
        unsafe_allow_html=True,
    )

    conversations = st.session_state["tiktok_cs_conversations"]
    unread_total = sum(int(c.get("unread") or 0) for c in conversations)
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Hội thoại hôm nay", len(conversations))
    m2.metric("Tin chưa đọc", unread_total)
    m3.metric("Phản hồi trong 24 giờ", "100%")
    m4.metric("Đã giải quyết", "1")

    st.markdown("#### Hộp thư người mua")
    left, middle, right = st.columns([0.95, 1.7, 1.15], gap="medium")

    with left:
        query = st.text_input("Tìm hội thoại", placeholder="Tên khách hoặc mã đơn", key="tt_cs_search")
        status_filter = st.segmented_control(
            "Trạng thái",
            ["Tất cả", "Chưa đọc", "Đã giải quyết"],
            default="Tất cả",
            key="tt_cs_status_filter",
        )
        shown = conversations
        if query:
            q = query.casefold()
            shown = [
                c for c in shown
                if q in c["buyer"].casefold() or q in str(c["order"]["code"]).casefold()
            ]
        if status_filter == "Chưa đọc":
            shown = [c for c in shown if c.get("unread")]
        elif status_filter == "Đã giải quyết":
            shown = [c for c in shown if c.get("status") == "Đã giải quyết"]

        if not shown:
            st.info("Không tìm thấy hội thoại phù hợp.")
        for conv in shown:
            label = f"{'🔴 ' if conv['unread'] else ''}{conv['buyer']} · {conv['time']}"
            if st.button(
                label,
                key=f"tt_conv_{conv['id']}",
                width="stretch",
                type="primary" if conv["id"] == st.session_state["tiktok_cs_selected"] else "secondary",
                help=conv["last"],
            ):
                st.session_state["tiktok_cs_selected"] = conv["id"]
                conv["unread"] = 0
                st.rerun()
            st.caption(conv["last"])

    selected = next(
        (c for c in conversations if c["id"] == st.session_state["tiktok_cs_selected"]),
        conversations[0],
    )

    with middle:
        st.markdown(
            f'<div class="tt-person"><div class="tt-avatar">{escape(selected["avatar"])}</div>'
            f'<div><div class="tt-person-name">{escape(selected["buyer"])}</div>'
            f'<div class="tt-person-meta">TikTok Shop Buyer · {escape(selected["status"])}</div></div></div>',
            unsafe_allow_html=True,
        )
        message_box = st.container(height=430, border=False)
        with message_box:
            for msg in selected["messages"]:
                css = "tt-shop" if msg["sender"] == "shop" else "tt-buyer"
                who = "VITRAN BOUTIQUE" if msg["sender"] == "shop" else selected["buyer"]
                st.markdown(
                    f'<div class="tt-bubble {css}">{escape(msg["text"])}'
                    f'<div class="tt-time">{escape(who)} · {escape(msg["time"])}</div></div>',
                    unsafe_allow_html=True,
                )

        prompt = st.chat_input("Nhập nội dung trả lời khách…", key=f"tt_chat_{selected['id']}")
        if prompt:
            selected["messages"].append({
                "sender": "shop",
                "text": prompt.strip(),
                "time": datetime.now().strftime("%H:%M"),
            })
            selected["last"] = prompt.strip()
            selected["time"] = datetime.now().strftime("%H:%M")
            selected["status"] = "Đang hỗ trợ"
            st.rerun()

        b1, b2, b3 = st.columns(3)
        if b1.button("✓ Đánh dấu đã đọc", key="tt_mark_read", width="stretch"):
            selected["unread"] = 0
            st.rerun()
        if b2.button("✓ Hoàn tất", key="tt_resolve", width="stretch"):
            selected["status"] = "Đã giải quyết"
            st.rerun()
        if b3.button("↗ Chuyển nhân viên", key="tt_transfer", width="stretch"):
            st.toast("Đã chuyển hội thoại cho CSKH VITRAN (dữ liệu kiểm thử).")

    with right:
        _card("🛍️ Thông tin đơn hàng", [
            ("Mã đơn", selected["order"]["code"]),
            ("Sản phẩm", selected["order"]["product"]),
            ("Phân loại", selected["order"]["variant"]),
            ("Số lượng", selected["order"]["quantity"]),
            ("Khách thanh toán", selected["order"]["amount"]),
            ("Thanh toán", selected["order"]["payment"]),
        ])
        _card("🚚 Vận chuyển", [
            ("Đơn vị vận chuyển", selected["shipping"]["carrier"]),
            ("Mã vận đơn", selected["shipping"]["tracking"]),
            ("Trạng thái", selected["shipping"]["status"]),
            ("Dự kiến giao", selected["shipping"]["estimate"]),
        ], accent="#25b7b1")
        _card("↩️ Trả hàng & hoàn tiền", [
            ("Trạng thái", selected["after_sale"]["status"]),
            ("Yêu cầu", selected["after_sale"]["request"]),
            ("Số tiền hoàn", selected["after_sale"]["refund"]),
        ], accent="#f59e0b")

    st.divider()
    st.caption(
        "Phạm vi sau khi được TikTok duyệt: nhận webhook hội thoại mới, đọc và đánh dấu tin nhắn, "
        "trả lời văn bản/hình ảnh, tra cứu đơn hàng liên quan và lưu nhật ký thao tác."
    )


if __name__ == "__main__":
    st.set_page_config(page_title="TikTok Inbox · VITRAN", page_icon="💬", layout="wide")
    render()
