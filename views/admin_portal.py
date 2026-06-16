from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta
from html import escape
from typing import Any
from zoneinfo import ZoneInfo

import streamlit as st

from config import CLAIM_STATUS_LABELS, DEFAULT_SLOT_CAPACITY, DEFAULT_TIME_RANGES
from seed_data import seed_demo_data
from services.after_sale_service import (
    AFTER_SALE_EXPECTED_RESOLUTIONS,
    AFTER_SALE_INVENTORY_ACTIONS,
    AFTER_SALE_ISSUE_TYPES,
    AFTER_SALE_STATUS_LABELS,
    get_after_sale,
    list_after_sales_for_admin,
    mark_after_sale_processing,
    reject_after_sale,
    resolve_after_sale,
)
from services.activity_service import (
    add_gift_to_activity,
    add_building,
    adjust_activity_inventory,
    authenticate_admin,
    activity_date_options,
    dashboard_summary,
    delete_time_slot,
    get_reschedule_context,
    list_activity_buildings,
    list_activity_gift_rules,
    list_admin_activities,
    list_buildings,
    list_claims_for_admin,
    list_day_schedule,
    list_departments,
    list_eligible_gifts,
    list_employee_available_activities,
    list_employee_claims,
    list_employees,
    list_inventory_rows,
    list_published_activities,
    list_reschedule_time_slots,
    list_schedule_calendar_counts,
    list_time_slots,
    list_time_slots_for_admin,
    publish_activity_from_config,
    publish_time_slot,
    send_reschedule_sms,
    set_activity_status,
    set_time_slot_availability,
    update_activity_basic,
    update_time_slot,
    update_building,
)
from services.claim_service import create_claim, redeem_claim_by_code
from services.ai_parser import parse_activity_text


DEFAULT_NL_TEXT = (
    "2026年端午福利，技术部可选机械键盘或降噪耳机，销售部领取500元购物卡，"
    "全员可领零食大礼包。A楼分配50%，B楼30%，C楼20%。"
    "活动日期为6月8日到6月10日。"
)

LOCAL_TIMEZONE = ZoneInfo("Asia/Shanghai")


def _slot_time_label(item: dict[str, Any]) -> str:
    if item.get("start_time") and item.get("end_time"):
        return f"{item['start_time']}-{item['end_time']}"
    return "全天"


def _time_range_options() -> list[str]:
    return [f"{start_time}-{end_time}" for start_time, end_time in DEFAULT_TIME_RANGES]


def _split_time_range(label: str) -> tuple[str, str]:
    start_time, end_time = label.split("-", 1)
    return start_time, end_time


def _streamlit_calendar():
    try:
        from streamlit_calendar import calendar
    except ImportError:
        return None
    return calendar


def _open_dialog(title: str, body, width: str = "small") -> None:
    dialog = getattr(st, "dialog", None)
    if not dialog:
        with st.container(border=True):
            st.markdown(f"**{title}**")
            body()
        return

    try:
        dialog(title, width=width)(body)()
    except TypeError:
        dialog(title)(body)()


def _render_compact_action_styles() -> None:
    st.markdown(
        """
        <style>
            .st-key-offline_activity_button button,
            .st-key-time_slot_delete_toggle button,
            .st-key-time_slot_delete_dialog_confirm button {
                min-height: 32px;
                padding: 0.25rem 0.75rem;
                background: #fff !important;
                border-color: #fecdd3 !important;
            }
            .st-key-offline_activity_button button p,
            .st-key-time_slot_delete_toggle button p,
            .st-key-time_slot_delete_dialog_confirm button p {
                color: #ff4b4b !important;
                font-size: 0.86rem;
                font-weight: 700;
            }
            .st-key-time_slot_add_toggle button,
            .st-key-save_slot_capacity button {
                min-height: 32px;
                padding: 0.25rem 0.75rem;
            }
            .st-key-time_slot_add_toggle button p,
            .st-key-save_slot_capacity button p {
                font-size: 0.86rem;
                font-weight: 700;
            }
            div[data-testid="stDialog"] {
                align-items: center !important;
                justify-content: center !important;
            }
            div[data-testid="stDialog"] div[role="dialog"] {
                margin: auto !important;
                max-height: min(86vh, 760px);
            }
            div[data-testid="stDialog"] div[role="dialog"] [data-testid="stForm"] {
                width: 100%;
            }
        </style>
        """,
        unsafe_allow_html=True,
    )


ADMIN_NAV_ITEMS = [
    ("config", "活动发布"),
    ("publish", "预约管理"),
    ("redeem", "预约核销"),
    ("after_sale", "售后处理"),
    ("dashboard", "数据看板"),
]

def _current_admin_page() -> str:
    page = st.session_state.get("admin_page", "config")
    allowed = {key for key, _ in ADMIN_NAV_ITEMS}
    if page not in allowed:
        page = "config"
        st.session_state["admin_page"] = page
    return page


def _current_admin_tool() -> str | None:
    tool = st.query_params.get("tool")
    if isinstance(tool, list):
        tool = tool[0] if tool else None
    return tool if tool == "reservation_test" else None


def _render_admin_nav(current_page: str) -> str:
    st.sidebar.markdown(
        """
        <style>
            section[data-testid="stSidebar"] .admin-nav-title {
                margin: 20px 0 8px;
                color: #64748b;
                font-size: 0.78rem;
                font-weight: 700;
            }
            section[data-testid="stSidebar"] div[data-testid="stRadio"] {
                width: 100% !important;
                max-width: 100% !important;
            }
            section[data-testid="stSidebar"] div[data-testid="stRadio"] > div,
            section[data-testid="stSidebar"] div[data-testid="stRadio"] [role="radiogroup"] > div,
            section[data-testid="stSidebar"] div[data-testid="stRadio"] [role="radiogroup"] > label,
            section[data-testid="stSidebar"] div[data-testid="stRadio"] div:has(> label[data-baseweb="radio"]) {
                width: 100% !important;
                max-width: 100% !important;
            }
            section[data-testid="stSidebar"] div[data-testid="stRadio"] [role="radiogroup"] {
                display: flex;
                flex-direction: column;
                gap: 6px;
                align-items: stretch;
                width: 100% !important;
                max-width: 100% !important;
            }
            section[data-testid="stSidebar"] div[data-testid="stRadio"] label[data-baseweb="radio"] {
                display: flex !important;
                align-items: center;
                justify-content: flex-start;
                box-sizing: border-box;
                width: 100% !important;
                min-width: 100% !important;
                max-width: 100%;
                align-self: stretch !important;
                flex: 1 1 100% !important;
                min-height: 38px;
                padding: 9px 12px;
                margin: 0 !important;
                border-radius: 8px;
                border: 1px solid transparent;
                background: transparent;
                color: #334155;
                cursor: pointer;
            }
            section[data-testid="stSidebar"] div[data-testid="stRadio"] label[data-baseweb="radio"]:hover {
                background: #f1f5f9;
            }
            section[data-testid="stSidebar"] div[data-testid="stRadio"] label[data-baseweb="radio"] > div:first-child {
                display: none;
            }
            section[data-testid="stSidebar"] div[data-testid="stRadio"] label[data-baseweb="radio"] > div:last-child {
                width: 100%;
            }
            section[data-testid="stSidebar"] div[data-testid="stRadio"] label[data-baseweb="radio"] p {
                color: #334155;
                font-size: 0.92rem;
                font-weight: 600;
                line-height: 1.25;
                margin: 0 !important;
            }
            section[data-testid="stSidebar"] div[data-testid="stRadio"] label[data-baseweb="radio"]:has(input:checked) {
                background: #e5e7eb;
                border-color: #d1d5db;
                width: 100% !important;
                min-width: 100% !important;
            }
            section[data-testid="stSidebar"] div[data-testid="stRadio"] label[data-baseweb="radio"]:has(input:checked) p {
                color: #ff4b4b;
                font-weight: 700;
            }
            section.main div[data-testid="stRadio"] [role="radiogroup"],
            section[data-testid="stMain"] div[data-testid="stRadio"] [role="radiogroup"] {
                display: inline-flex;
                flex-direction: row;
                flex-wrap: wrap;
                gap: 4px;
                margin: 0 0 18px;
                padding: 4px;
                border-radius: 10px;
                border: 1px solid #e5e7eb;
                background: #f1f5f9;
            }
            section.main div[data-testid="stRadio"] label[data-baseweb="radio"],
            section[data-testid="stMain"] div[data-testid="stRadio"] label[data-baseweb="radio"] {
                display: inline-flex;
                align-items: center;
                justify-content: center;
                min-height: 34px;
                min-width: 108px;
                padding: 7px 16px;
                margin: 0 !important;
                border-radius: 7px;
                background: transparent;
                color: #475569;
                cursor: pointer;
            }
            section.main div[data-testid="stRadio"] label[data-baseweb="radio"] > div:first-child,
            section[data-testid="stMain"] div[data-testid="stRadio"] label[data-baseweb="radio"] > div:first-child {
                display: none;
            }
            section.main div[data-testid="stRadio"] label[data-baseweb="radio"] p,
            section[data-testid="stMain"] div[data-testid="stRadio"] label[data-baseweb="radio"] p {
                color: #475569;
                font-size: 0.92rem;
                font-weight: 600;
                line-height: 1;
                margin: 0 !important;
            }
            section.main div[data-testid="stRadio"] label[data-baseweb="radio"]:hover,
            section[data-testid="stMain"] div[data-testid="stRadio"] label[data-baseweb="radio"]:hover {
                background: #fff;
            }
            section.main div[data-testid="stRadio"] label[data-baseweb="radio"]:has(input:checked),
            section[data-testid="stMain"] div[data-testid="stRadio"] label[data-baseweb="radio"]:has(input:checked) {
                background: #fff;
                box-shadow: 0 1px 2px rgba(15, 23, 42, 0.08);
            }
            section.main div[data-testid="stRadio"] label[data-baseweb="radio"]:has(input:checked) p,
            section[data-testid="stMain"] div[data-testid="stRadio"] label[data-baseweb="radio"]:has(input:checked) p {
                color: #ff4b4b;
                font-weight: 700;
            }
        </style>
        <div class="admin-nav-title">管理菜单</div>
        """,
        unsafe_allow_html=True,
    )

    labels = [label for _, label in ADMIN_NAV_ITEMS]
    if st.session_state.get("admin_nav_radio") not in labels:
        st.session_state.pop("admin_nav_radio", None)
    current_index = next(
        (index for index, (key, _) in enumerate(ADMIN_NAV_ITEMS) if key == current_page),
        0,
    )
    selected_label = st.sidebar.radio(
        "管理菜单",
        labels,
        index=current_index,
        key="admin_nav_radio",
        label_visibility="collapsed",
    )
    selected_key = next(key for key, label in ADMIN_NAV_ITEMS if label == selected_label)
    st.session_state["admin_page"] = selected_key
    return selected_key


def _parse_date_value(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value

    raw = str(value or "").strip()
    if not raw:
        return None

    for fmt in ("%Y-%m-%d", "%Y/%m/%d"):
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    return None


def _iter_month_labels(start: date, end: date) -> list[str]:
    current = date(start.year, start.month, 1)
    last = date(end.year, end.month, 1)
    labels = []

    while current <= last:
        labels.append(current.strftime("%Y-%m"))
        if current.month == 12:
            current = date(current.year + 1, 1, 1)
        else:
            current = date(current.year, current.month + 1, 1)

    return labels


def _month_options(activities: list[dict[str, Any]]) -> list[str]:
    options: set[str] = set()
    for activity in activities:
        start = _parse_date_value(activity.get("start_date"))
        end = _parse_date_value(activity.get("end_date"))
        if not start and not end:
            continue
        if not start:
            start = end
        if not end:
            end = start
        if start and end and start > end:
            start, end = end, start
        if start and end:
            options.update(_iter_month_labels(start, end))

    if not options:
        options.add(date.today().strftime("%Y-%m"))

    return sorted(options)


def _empty_gift() -> dict[str, Any]:
    return {
        "name": "",
        "department": "全员",
        "total_stock": 1,
        "description": "",
        "building_allocation": {},
        "per_person_limit": 1,
    }


def _default_manual_config() -> dict[str, Any]:
    return {
        "activity": {
            "name": "",
            "activity_type": "节日福利",
            "description": "",
            "start_date": "",
            "end_date": "",
            "allow_cancel": True,
            "expire_release": True,
        },
        "gift_rules": [],
    }


def _clear_config_widget_state() -> None:
    prefixes = (
        "gift_name_",
        "gift_department_",
        "gift_stock_",
        "gift_description_",
        "gift_allocation_",
    )
    for key in list(st.session_state.keys()):
        if key.startswith(prefixes):
            del st.session_state[key]


def _ensure_admin() -> dict[str, Any] | None:
    if st.session_state.get("admin"):
        return st.session_state["admin"]

    with st.form("admin_login_form"):
        password = st.text_input("管理员密码", type="password")
        submitted = st.form_submit_button("登录管理后台")

    if submitted:
        admin = authenticate_admin(password)
        if admin:
            st.session_state["admin"] = admin
            st.success("管理员登录成功")
            st.rerun()
        else:
            st.error("管理员密码错误")

    return None


def _department_options() -> list[str]:
    departments = ["全员"]
    for department in list_departments():
        if department not in departments:
            departments.append(department)
    return departments


def _building_names() -> list[str]:
    return [building["name"] for building in list_buildings(active_only=True)]


def _default_allocation(buildings: list[str]) -> dict[str, int]:
    if not buildings:
        return {}
    base = 100 // len(buildings)
    allocation = {building: base for building in buildings}
    allocation[buildings[-1]] += 100 - sum(allocation.values())
    return allocation


def _rule_department_label(department: str) -> str:
    return "全员" if department == "ALL" else department


def _activity_status_label(status: str) -> str:
    labels = {
        "published": "已上线",
        "offline": "已下线",
        "draft": "草稿",
    }
    return labels.get(status, status)


def _after_sale_status_label(status: str) -> str:
    return AFTER_SALE_STATUS_LABELS.get(status, status)


def _after_sale_issue_label(issue_type: str) -> str:
    return AFTER_SALE_ISSUE_TYPES.get(issue_type, issue_type)


def _after_sale_resolution_label(resolution: str) -> str:
    return AFTER_SALE_EXPECTED_RESOLUTIONS.get(resolution, resolution)


def _after_sale_inventory_action_label(action: str) -> str:
    return AFTER_SALE_INVENTORY_ACTIONS.get(action, action)


def _format_after_sale_id(after_sale_id: int) -> str:
    return f"AS-{after_sale_id:05d}"


def _gift_rules_from_draft(draft: dict[str, Any], buildings: list[str]) -> list[dict[str, Any]]:
    rules = []
    for rule in draft.get("gift_rules", []):
        allocation = rule.get("building_allocation") or _default_allocation(buildings)
        rules.append(
            {
                "name": rule.get("name", ""),
                "department": _rule_department_label(rule.get("department", "全员")),
                "total_stock": int(rule.get("total_stock", 1)),
                "description": rule.get("description", ""),
                "building_allocation": {building: int(allocation.get(building, 0)) for building in buildings},
                "per_person_limit": 1,
            }
        )
    return rules


def _request_activity_status_change(activity: dict[str, Any], target_status: str) -> None:
    st.session_state["pending_activity_status_change"] = {
        "activity_id": activity["id"],
        "activity_name": activity["name"],
        "target_status": target_status,
        "reserved_count": int(activity.get("reserved_count", 0)),
    }
    st.rerun()


def _render_activity_status_dialog(admin: dict[str, Any]) -> None:
    pending = st.session_state.get("pending_activity_status_change")
    if not pending:
        return

    going_offline = pending["target_status"] == "offline"
    action_label = "下线" if going_offline else "恢复上线"

    def dialog_body() -> None:
        st.write(f"确认将活动“{pending['activity_name']}”{action_label}？")
        if going_offline and pending["reserved_count"] > 0:
            st.warning(f"该活动仍有 {pending['reserved_count']} 条未核销预约，下线后员工端不再展示。")

        cols = st.columns(2)
        with cols[0]:
            if st.button("确认", type="primary", use_container_width=True):
                try:
                    set_activity_status(
                        pending["activity_id"],
                        pending["target_status"],
                        admin_id=admin["id"],
                    )
                    st.session_state.pop("pending_activity_status_change", None)
                    st.success(f"活动已{action_label}")
                    st.rerun()
                except ValueError as exc:
                    st.error(str(exc))
        with cols[1]:
            if st.button("取消", use_container_width=True):
                st.session_state.pop("pending_activity_status_change", None)
                st.rerun()

    dialog = getattr(st, "dialog", None)
    if dialog:
        dialog("确认活动状态变更")(dialog_body)()
    else:
        with st.container(border=True):
            st.markdown("**确认活动状态变更**")
            dialog_body()


def _render_activity_table(activities: list[dict[str, Any]]) -> None:
    rows = [
        {
            "活动": activity["name"],
            "状态": _activity_status_label(activity["status"]),
            "日期": f"{activity['start_date']} 至 {activity['end_date']}",
            "礼物数": activity.get("gift_count", 0),
            "已预约": activity.get("reserved_count", 0),
            "已核销": activity.get("redeemed_count", 0),
        }
        for activity in activities
    ]
    st.dataframe(rows, use_container_width=True, hide_index=True)


def _render_activity_details(activity: dict[str, Any]) -> None:
    gifts = list_activity_gift_rules(activity["id"])
    inventory_rows = list_inventory_rows(activity["id"])

    st.markdown("**活动配置预览**")
    gift_table = [
        {
            "礼物": gift["name"],
            "部门": gift.get("departments", ""),
            "描述": gift["spec"],
            "总库存": gift["inventory_total"],
            "可用": gift["available_stock"],
            "已预约": gift["reserved_stock"],
            "已发放": gift["redeemed_stock"],
        }
        for gift in gifts
    ]
    st.dataframe(gift_table, use_container_width=True, hide_index=True)

    with st.expander("楼宇库存明细"):
        inventory_table = [
            {
                "礼物": row["gift_name"],
                "楼宇": row["building"],
                "总库存": row["total_stock"],
                "可用": row["available_stock"],
                "已预约": row["reserved_stock"],
                "已发放": row["redeemed_stock"],
            }
            for row in inventory_rows
        ]
        st.dataframe(inventory_table, use_container_width=True, hide_index=True)


def _render_activity_edit_form(activity: dict[str, Any], admin: dict[str, Any]) -> None:
    st.markdown("**基础信息**")
    with st.form(f"manage_activity_form_{activity['id']}"):
        name = st.text_input(
            "活动名称",
            value=activity["name"],
            key=f"manage_activity_name_{activity['id']}",
        )
        description = st.text_area(
            "活动描述",
            value=activity.get("description", ""),
            height=88,
            key=f"manage_activity_description_{activity['id']}",
        )
        cols = st.columns(2)
        with cols[0]:
            start_date = st.text_input(
                "开始日期",
                value=activity["start_date"],
                placeholder="yyyy/mm/dd",
                key=f"manage_activity_start_{activity['id']}",
            )
        with cols[1]:
            end_date = st.text_input(
                "结束日期",
                value=activity["end_date"],
                placeholder="yyyy/mm/dd",
                key=f"manage_activity_end_{activity['id']}",
            )
        allow_cancel = st.checkbox(
            "允许取消预约",
            value=bool(activity.get("allow_cancel", True)),
            key=f"manage_activity_cancel_{activity['id']}",
        )
        expire_release = st.checkbox(
            "过期释放库存",
            value=bool(activity.get("expire_release", True)),
            key=f"manage_activity_expire_{activity['id']}",
        )
        saved = st.form_submit_button("保存活动信息", type="primary")

    if saved:
        try:
            update_activity_basic(
                activity_id=activity["id"],
                name=name,
                description=description,
                start_date=start_date,
                end_date=end_date,
                allow_cancel=allow_cancel,
                expire_release=expire_release,
                admin_id=admin["id"],
            )
            st.success("活动信息已保存")
            st.rerun()
        except ValueError as exc:
            st.error(str(exc))


def _render_activity_gift_form(
    activity: dict[str, Any],
    admin: dict[str, Any],
    buildings: list[str],
    departments: list[str],
) -> None:
    st.markdown("**新增礼物**")
    if not buildings:
        st.caption("当前活动暂无可分配楼宇。")
        return

    with st.form(f"add_activity_gift_form_{activity['id']}"):
        cols = st.columns([1.2, 1, 1, 2])
        with cols[0]:
            gift_name = st.text_input("礼物名称", key=f"add_gift_name_{activity['id']}")
        with cols[1]:
            department = st.selectbox(
                "部门",
                departments,
                key=f"add_gift_department_{activity['id']}",
            )
        with cols[2]:
            total_stock = st.number_input(
                "初始数量",
                min_value=1,
                value=1,
                step=1,
                key=f"add_gift_stock_{activity['id']}",
            )
        with cols[3]:
            gift_description = st.text_input(
                "描述",
                key=f"add_gift_description_{activity['id']}",
            )

        st.markdown("楼宇分配")
        default_allocation = _default_allocation(buildings)
        allocation_cols = st.columns(len(buildings))
        allocation = {}
        for index, building in enumerate(buildings):
            with allocation_cols[index]:
                allocation[building] = st.slider(
                    building,
                    min_value=0,
                    max_value=100,
                    value=default_allocation.get(building, 0),
                    step=1,
                    key=f"add_gift_allocation_{activity['id']}_{building}",
                )
        total_allocation = sum(allocation.values())
        if total_allocation != 100:
            st.caption(f"当前合计 {total_allocation}%，保存前需调整为 100%。")

        submitted = st.form_submit_button("增发礼物", type="primary")

    if submitted:
        try:
            gift_id = add_gift_to_activity(
                activity["id"],
                {
                    "name": gift_name,
                    "department": department,
                    "total_stock": int(total_stock),
                    "description": gift_description,
                    "building_allocation": allocation,
                    "per_person_limit": 1,
                },
                admin_id=admin["id"],
            )
            st.success(f"礼物已增发，礼物 ID：{gift_id}")
            st.rerun()
        except ValueError as exc:
            st.error(str(exc))


def _render_activity_inventory_adjustment_form(
    activity: dict[str, Any],
    admin: dict[str, Any],
) -> None:
    st.markdown("**调整已有礼物库存**")
    inventory_rows = list_inventory_rows(activity["id"])
    if not inventory_rows:
        st.caption("当前活动暂无可调整库存。")
        return

    with st.form(f"adjust_activity_inventory_form_{activity['id']}"):
        gift_options = []
        seen_gift_ids = set()
        for row in inventory_rows:
            if row["gift_id"] in seen_gift_ids:
                continue
            seen_gift_ids.add(row["gift_id"])
            gift_options.append(row)

        selected_gift = st.selectbox(
            "礼物",
            gift_options,
            format_func=lambda item: item["gift_name"],
            key=f"adjust_inventory_gift_{activity['id']}",
        )
        building_options = [
            row
            for row in inventory_rows
            if row["gift_id"] == selected_gift["gift_id"]
        ]
        inventory = st.selectbox(
            "楼宇",
            building_options,
            format_func=lambda item: (
                f"{item['building']}（总 {item['total_stock']}，可用 {item['available_stock']}，"
                f"已预约 {item['reserved_stock']}，已发放 {item['redeemed_stock']}）"
            ),
            key=f"adjust_inventory_building_{activity['id']}_{selected_gift['gift_id']}",
        )
        adjustment_label = st.selectbox(
            "调整类型",
            ["补充库存", "减少可用库存"],
            key=f"adjust_inventory_type_{activity['id']}",
        )
        quantity = st.number_input(
            "调整数量",
            min_value=1,
            value=1,
            step=1,
            key=f"adjust_inventory_quantity_{activity['id']}",
        )
        reason = st.text_input(
            "调整原因",
            placeholder="例如 供应商补货、盘点修正",
            key=f"adjust_inventory_reason_{activity['id']}",
        )
        if adjustment_label == "减少可用库存":
            st.caption(f"当前最多可减少 {inventory['available_stock']}，不会影响已预约和已发放库存。")
        submitted = st.form_submit_button("确认调整库存", type="primary")

    if submitted:
        try:
            adjusted = adjust_activity_inventory(
                inventory_id=inventory["id"],
                adjustment_type="increase" if adjustment_label == "补充库存" else "decrease",
                quantity=int(quantity),
                reason=reason,
                admin_id=admin["id"],
            )
            st.success(
                f"库存已调整：{adjusted['gift_name']} / {adjusted['building']} "
                f"当前可用 {adjusted['available_stock']}"
            )
            st.rerun()
        except ValueError as exc:
            st.error(str(exc))


def _render_activity_management_section(
    admin: dict[str, Any],
    departments: list[str],
) -> None:
    st.subheader("已发布活动管理")
    _render_activity_status_dialog(admin)

    activities = list_admin_activities()
    if not activities:
        st.caption("暂无可管理活动。")
        return

    _render_activity_table(activities)
    selected = st.selectbox(
        "选择要管理的活动",
        activities,
        format_func=lambda item: (
            f"{item['name']}（{_activity_status_label(item['status'])} / ID {item['id']}）"
        ),
        key="manage_activity_selector",
    )

    summary = dashboard_summary(selected["id"])
    metric_cols = st.columns(4)
    metric_cols[0].metric("礼物数", selected.get("gift_count", 0))
    metric_cols[1].metric("已预约", summary["reserved_claims"])
    metric_cols[2].metric("已核销", summary["redeemed_claims"])
    metric_cols[3].metric("状态", _activity_status_label(selected["status"]))

    _render_activity_edit_form(selected, admin)

    status_cols = st.columns([0.75, 4.25])
    with status_cols[0]:
        if selected["status"] == "published":
            if st.button("下线活动", use_container_width=True, key="offline_activity_button"):
                _request_activity_status_change(selected, "offline")
        else:
            if st.button("恢复上线", type="primary", use_container_width=True, key="online_activity_button"):
                _request_activity_status_change(selected, "published")

    _render_activity_details(selected)

    activity_buildings = [building["name"] for building in list_activity_buildings(selected["id"])]
    if not activity_buildings:
        activity_buildings = _building_names()
    st.markdown("**礼物与库存管理**")
    _render_activity_gift_form(selected, admin, activity_buildings, departments)
    _render_activity_inventory_adjustment_form(selected, admin)


def _render_config_tab(admin: dict[str, Any]) -> None:
    buildings = _building_names()
    departments = _department_options()

    config_tab, management_tab = st.tabs(["活动配置", "活动管理"])
    with config_tab:
        st.subheader("配置活动")
        if st.button("配置活动", type="primary"):
            _clear_config_widget_state()
            st.session_state["config_draft"] = _default_manual_config()
            st.rerun()

        st.markdown("或者复制文字进行快速配置")
        text = st.text_area(
            "活动规则文案",
            value="",
            height=140,
            placeholder=DEFAULT_NL_TEXT,
            label_visibility="collapsed",
        )
        _, action_col = st.columns([4, 1])
        with action_col:
            quick_submit = st.button("文案快速配置", use_container_width=True)

        if quick_submit:
            _clear_config_widget_state()
            try:
                st.session_state["config_draft"] = parse_activity_text(text)
                st.rerun()
            except ValueError as exc:
                st.error(str(exc))

        draft = st.session_state.get("config_draft")
        if draft:
            st.subheader("配置详情")
            with st.form("publish_config_form"):
                activity = draft["activity"]
                name = st.text_input("活动名称", value=activity["name"])
                start_date = st.text_input("开始日期", value=activity["start_date"], placeholder="yyyy/mm/dd")
                end_date = st.text_input("结束日期", value=activity["end_date"], placeholder="yyyy/mm/dd")
                description = st.text_area("活动描述", value=activity.get("description", ""), height=90)
                allow_cancel = st.checkbox("允许取消预约", value=activity.get("allow_cancel", True))
                expire_release = st.checkbox("过期释放库存", value=activity.get("expire_release", True))

                st.markdown("**礼物规则**")
                current_rules = _gift_rules_from_draft(draft, buildings)
                edited_rules = []
                for index, rule in enumerate(current_rules):
                    cols = st.columns([1.2, 1, 1, 2])
                    with cols[0]:
                        gift_name = st.text_input("礼物名称", value=rule["name"], key=f"gift_name_{index}")
                    with cols[1]:
                        selected_department = rule.get("department", "全员")
                        department_index = (
                            departments.index(selected_department)
                            if selected_department in departments
                            else 0
                        )
                        department = st.selectbox(
                            "部门",
                            departments,
                            index=department_index,
                            key=f"gift_department_{index}",
                        )
                    with cols[2]:
                        total_stock = st.number_input(
                            "初始数量",
                            min_value=1,
                            value=int(rule.get("total_stock", 1)),
                            step=1,
                            key=f"gift_stock_{index}",
                        )
                    with cols[3]:
                        gift_description = st.text_input(
                            "描述",
                            value=rule.get("description", ""),
                            key=f"gift_description_{index}",
                        )

                    allocation = {}
                    if buildings:
                        st.markdown(f"{gift_name or '未命名礼物'} 楼宇分配")
                        allocation_cols = st.columns(len(buildings))
                        for building_index, building in enumerate(buildings):
                            with allocation_cols[building_index]:
                                allocation[building] = st.slider(
                                    building,
                                    min_value=0,
                                    max_value=100,
                                    value=int(rule.get("building_allocation", {}).get(building, 0)),
                                    step=1,
                                    key=f"gift_allocation_{index}_{building}",
                                )
                        total_allocation = sum(allocation.values())
                        if total_allocation != 100:
                            st.caption(f"当前合计 {total_allocation}%，发布前需调整为 100%。")

                    edited_rules.append(
                        {
                            "name": gift_name,
                            "department": department,
                            "total_stock": int(total_stock),
                            "description": gift_description,
                            "building_allocation": allocation,
                            "per_person_limit": 1,
                        }
                    )

                add_gift = st.form_submit_button("新增礼物")

                submitted = st.form_submit_button("确认发布活动", type="primary")

            config = {
                "activity": {
                    "name": name,
                    "activity_type": "节日福利",
                    "description": description,
                    "start_date": start_date,
                    "end_date": end_date,
                    "allow_cancel": allow_cancel,
                    "expire_release": expire_release,
                },
                "gift_rules": edited_rules,
            }

            if add_gift:
                new_rule = _empty_gift()
                new_rule["department"] = departments[0] if departments else "全员"
                new_rule["building_allocation"] = _default_allocation(buildings)
                config["gift_rules"].append(new_rule)
                st.session_state["config_draft"] = config
                st.rerun()

            if submitted:
                try:
                    activity_id = publish_activity_from_config(config, admin_id=admin["id"])
                    st.success(f"活动已发布，活动 ID：{activity_id}")
                    st.session_state.pop("config_draft", None)
                except ValueError as exc:
                    st.error(str(exc))

    with management_tab:
        _render_activity_management_section(admin, departments)


def _select_activity(key: str, include_offline: bool = True) -> dict[str, Any] | None:
    activities = list_admin_activities() if include_offline else list_published_activities()
    if not activities:
        st.warning("暂无已发布活动。")
        return None
    return st.selectbox(
        "选择活动",
        activities,
        format_func=lambda item: (
            f"{item['name']}（{_activity_status_label(item.get('status', 'published'))} / ID {item['id']}）"
        ),
        key=key,
    )


def _render_redeem_tab(admin: dict[str, Any]) -> None:
    st.subheader("现场核销")
    activity = _select_activity("redeem_activity_selector")
    code = st.text_input("输入员工凭证验证码", placeholder="例如 GF-ABC123")
    if st.button("核销", type="primary"):
        result = redeem_claim_by_code(code, admin_id=admin["id"])
        if result["ok"]:
            claim = result["claim"]
            st.success(
                f"核销成功：{claim['employee_name']} / {claim['gift_name']} / {claim['building']}"
            )
        else:
            st.error(result["message"])

    st.subheader("预约列表")
    claims = list_claims_for_admin(activity["id"] if activity else None)
    if not claims:
        st.caption("暂无预约记录。")
        return

    table = []
    for claim in claims:
        table.append(
            {
                "员工": claim["employee_name"],
                "部门": claim["department"],
                "礼物": claim["gift_name"],
                "楼栋": claim["building"],
                "时间": f"{claim['slot_date']} {_slot_time_label(claim)}",
                "状态": CLAIM_STATUS_LABELS.get(claim["status"], claim["status"]),
                "验证码": claim["claim_code"],
            }
        )
    st.dataframe(table, use_container_width=True, hide_index=True)


def _render_building_tab(admin: dict[str, Any]) -> None:
    st.subheader("楼宇设置")
    buildings = list_buildings(active_only=False)
    table = [
        {
            "楼宇": building["name"],
            "地址": building.get("address", ""),
            "领取点": building.get("pickup_location", ""),
            "负责人": building.get("manager_name", ""),
            "联系方式": building.get("manager_contact", ""),
            "备用负责人": building.get("backup_manager", ""),
            "显示顺序": building.get("sort_order", 0),
            "状态": "启用" if building["is_active"] else "停用",
            "备注": building.get("note", ""),
        }
        for building in buildings
    ]
    st.dataframe(table, use_container_width=True, hide_index=True)

    st.markdown("**新增楼宇**")
    with st.form("add_building_form"):
        building_name = st.text_input("楼宇名称", placeholder="例如 D楼")
        address = st.text_input("楼宇地址", placeholder="例如 上海市 xx 路 xx 号")
        pickup_location = st.text_input("领取点位置", placeholder="例如 1层行政前台")
        manager_name = st.text_input("负责人姓名")
        manager_contact = st.text_input("负责人联系方式")
        backup_manager = st.text_input("备用负责人")
        note = st.text_area("备注", height=78)
        sort_order = st.number_input(
            "显示顺序",
            min_value=1,
            value=(max((int(item.get("sort_order", 0)) for item in buildings), default=0) + 1),
            step=1,
        )
        is_active = st.checkbox("启用楼宇", value=True)
        submitted = st.form_submit_button("添加楼宇", type="primary")

    if submitted:
        try:
            add_building(
                building_name,
                address=address,
                pickup_location=pickup_location,
                manager_name=manager_name,
                manager_contact=manager_contact,
                backup_manager=backup_manager,
                note=note,
                sort_order=int(sort_order),
                is_active=is_active,
                admin_id=admin["id"],
            )
            st.success("楼宇已添加")
            st.rerun()
        except ValueError as exc:
            st.error(str(exc))

    st.divider()
    st.markdown("**编辑楼宇信息**")
    if not buildings:
        st.caption("暂无楼宇。")
    else:
        selected = st.selectbox(
            "选择楼宇",
            buildings,
            format_func=lambda item: item["name"],
            key="edit_building_selector",
        )
        with st.form(f"edit_building_form_{selected['id']}"):
            st.text_input("楼宇名称", value=selected["name"], disabled=True)
            address = st.text_input("楼宇地址", value=selected.get("address", ""))
            pickup_location = st.text_input(
                "领取点位置",
                value=selected.get("pickup_location", ""),
            )
            manager_name = st.text_input(
                "负责人姓名",
                value=selected.get("manager_name", ""),
            )
            manager_contact = st.text_input(
                "负责人联系方式",
                value=selected.get("manager_contact", ""),
            )
            backup_manager = st.text_input(
                "备用负责人",
                value=selected.get("backup_manager", ""),
            )
            note = st.text_area("备注", value=selected.get("note", ""), height=78)
            sort_order = st.number_input(
                "显示顺序",
                min_value=1,
                value=max(1, int(selected.get("sort_order", 0))),
                step=1,
                key=f"building_sort_{selected['id']}",
            )
            is_active = st.selectbox(
                "楼宇状态",
                [True, False],
                index=0 if selected.get("is_active") else 1,
                format_func=lambda value: "启用" if value else "停用",
                key=f"building_active_{selected['id']}",
            )
            saved = st.form_submit_button("保存楼宇信息", type="primary")

        if saved:
            try:
                update_building(
                    building_id=selected["id"],
                    address=address,
                    pickup_location=pickup_location,
                    manager_name=manager_name,
                    manager_contact=manager_contact,
                    backup_manager=backup_manager,
                    note=note,
                    sort_order=int(sort_order),
                    is_active=bool(is_active),
                    admin_id=admin["id"],
                )
                st.success("楼宇信息已更新")
                st.rerun()
            except ValueError as exc:
                st.error(str(exc))


def _request_slot_toggle(slot: dict[str, Any]) -> None:
    enable = not bool(slot["is_available"])
    st.session_state["pending_slot_toggle"] = {
        "time_slot_id": slot["id"],
        "enable": enable,
        "activity_name": slot.get("activity_name", ""),
        "building": slot["building"],
        "slot_date": slot["slot_date"],
        "time": _slot_time_label(slot),
        "reserved_count": slot["reserved_count"],
    }
    st.rerun()


def _render_slot_toggle_dialog(admin: dict[str, Any]) -> None:
    pending = st.session_state.get("pending_slot_toggle")
    if not pending:
        return

    action_label = "恢复可领取" if pending["enable"] else "设为不可领取"

    def dialog_body() -> None:
        activity_text = f"{pending['activity_name']} / " if pending.get("activity_name") else ""
        st.write(
            f"{activity_text}{pending['building']} / {pending['slot_date']} {pending['time']} "
            f"将被{action_label}。"
        )
        if pending["reserved_count"] > 0 and not pending["enable"]:
            st.error("该时间段已有预约，不能直接设为不可领取。")

        cols = st.columns(2)
        with cols[0]:
            if st.button(
                "确认",
                type="primary",
                disabled=pending["reserved_count"] > 0 and not pending["enable"],
                use_container_width=True,
            ):
                try:
                    set_time_slot_availability(
                        pending["time_slot_id"],
                        pending["enable"],
                        admin_id=admin["id"],
                    )
                    st.session_state.pop("pending_slot_toggle", None)
                    st.success("时间段状态已更新")
                    st.rerun()
                except ValueError as exc:
                    st.error(str(exc))
        with cols[1]:
            if st.button("取消", use_container_width=True):
                st.session_state.pop("pending_slot_toggle", None)
                st.rerun()

    dialog = getattr(st, "dialog", None)
    if dialog:
        dialog("确认变更领取时间")(dialog_body)()
    else:
        with st.container(border=True):
            st.markdown("**确认变更领取时间**")
            dialog_body()


def _request_reschedule_sms(claim_id: int) -> None:
    st.session_state["pending_reschedule_claim_id"] = int(claim_id)
    st.rerun()


def _reschedule_slot_label(slot: dict[str, Any]) -> str:
    return f"{_slot_time_label(slot)}（剩余 {slot['remaining']}）"


def _render_reschedule_sms_dialog(admin: dict[str, Any]) -> None:
    claim_id = st.session_state.get("pending_reschedule_claim_id")
    if not claim_id:
        return

    def close_dialog() -> None:
        st.session_state.pop("pending_reschedule_claim_id", None)
        st.rerun()

    def dialog_body() -> None:
        try:
            context = get_reschedule_context(int(claim_id))
        except ValueError as exc:
            st.error(str(exc))
            if st.button("关闭", use_container_width=True):
                close_dialog()
            return

        current_time = f"{context['slot_date']} {_slot_time_label(context)}"
        st.write(
            f"{context['employee_name']} / {context['department']} / "
            f"{context['activity_name']} / {context['gift_name']}"
        )
        st.caption(
            f"原领取时间：{current_time}；手机号：{context.get('employee_phone') or '未维护'}。"
        )
        st.caption("此操作会模拟发送固定短信、生成员工端改期通知并记录日志，不自动修改预约时间。")

        if context["status"] != "reserved":
            st.error("只有已预约记录可以联系改期。")
            if st.button("关闭", use_container_width=True):
                close_dialog()
            return

        date_options = activity_date_options(context)
        if not date_options:
            st.error("当前活动日期配置无效。")
            if st.button("关闭", use_container_width=True):
                close_dialog()
            return

        date_index = (
            date_options.index(context["slot_date"])
            if context["slot_date"] in date_options
            else 0
        )
        target_date = st.selectbox(
            "目标日期",
            date_options,
            index=date_index,
            key=f"reschedule_target_date_{claim_id}",
        )
        target_slots = list_reschedule_time_slots(
            context["activity_id"],
            context["building"],
            target_date,
        )
        if not target_slots:
            st.warning("该日期没有可用于改期建议的可领取时间段。")
            selected_slot = None
        else:
            selected_slot = st.selectbox(
                "目标时间段",
                target_slots,
                format_func=_reschedule_slot_label,
                key=f"reschedule_target_slot_{claim_id}_{target_date}",
            )

        cols = st.columns(2)
        with cols[0]:
            if st.button(
                "发送短信",
                type="primary",
                disabled=selected_slot is None,
                use_container_width=True,
            ):
                try:
                    result = send_reschedule_sms(
                        int(claim_id),
                        int(selected_slot["id"]),
                        admin_id=admin["id"],
                    )
                    st.success(f"短信已模拟发送至 {result['phone']}，员工端改期通知已生成")
                    st.code(result["sms_content"], language="text")
                except ValueError as exc:
                    st.error(str(exc))
        with cols[1]:
            if st.button("关闭", use_container_width=True):
                close_dialog()

    dialog = getattr(st, "dialog", None)
    if dialog:
        dialog("联系改期")(dialog_body)()
    else:
        with st.container(border=True):
            st.markdown("**联系改期**")
            dialog_body()


def _close_add_time_slot_dialog() -> None:
    st.session_state.pop("show_add_time_slot_dialog", None)


def _close_delete_time_slot_dialog() -> None:
    st.session_state.pop("show_delete_time_slot_dialog", None)


def _render_add_time_slot_dialog(
    admin: dict[str, Any],
    activity: dict[str, Any],
    date_options: list[str],
    selected_date: str,
    building_options: list[str],
) -> None:
    if not st.session_state.get("show_add_time_slot_dialog", False):
        return

    def dialog_body() -> None:
        st.caption(f"当前活动：{activity['name']}")
        with st.form("publish_time_slot_dialog_form"):
            cols = st.columns(2)
            with cols[0]:
                slot_date = st.selectbox(
                    "领取日期",
                    date_options,
                    index=date_options.index(selected_date) if selected_date in date_options else 0,
                )
            with cols[1]:
                slot_range = st.selectbox("领取时段", _time_range_options())

            cols = st.columns(2)
            with cols[0]:
                building = st.selectbox("楼宇", building_options)
            with cols[1]:
                capacity = st.number_input(
                    "容量",
                    min_value=1,
                    value=DEFAULT_SLOT_CAPACITY,
                    step=1,
                )
            submitted = st.form_submit_button("发布 / 更新领取时间", type="primary")

        if submitted:
            start_time, end_time = _split_time_range(slot_range)
            try:
                count = publish_time_slot(
                    activity_id=activity["id"],
                    slot_date=slot_date,
                    start_time=start_time,
                    end_time=end_time,
                    capacity=int(capacity),
                    building=None if building == "全部楼宇" else building,
                    admin_id=admin["id"],
                )
                st.success(f"已发布 {count} 条领取时间")
                _close_add_time_slot_dialog()
                st.rerun()
            except ValueError as exc:
                st.error(str(exc))

        if st.button("关闭", key="close_add_time_slot_dialog"):
            _close_add_time_slot_dialog()
            st.rerun()

    _open_dialog("新增时间段", dialog_body, width="large")


def _render_delete_time_slot_dialog(
    admin: dict[str, Any],
    slots: list[dict[str, Any]],
) -> None:
    if not st.session_state.get("show_delete_time_slot_dialog", False):
        return

    def dialog_body() -> None:
        if not slots:
            st.caption("当前日期暂无可删除时间段。")
            if st.button("关闭", key="close_empty_delete_time_slot_dialog"):
                _close_delete_time_slot_dialog()
                st.rerun()
            return

        current_delete_slot = st.session_state.get("delete_time_slot_dialog_selector")
        if isinstance(current_delete_slot, dict) and all(
            slot["id"] != current_delete_slot.get("id") for slot in slots
        ):
            st.session_state.pop("delete_time_slot_dialog_selector", None)

        delete_slot = st.selectbox(
            "选择要删除的时间段",
            slots,
            format_func=lambda item: (
                f"{item['building']} {item['slot_date']} "
                f"{_slot_time_label(item)} "
                f"{'可领取' if item['is_available'] else '不可领取'}"
            ),
            key="delete_time_slot_dialog_selector",
        )
        if delete_slot["reserved_count"] > 0:
            st.caption("该时间段已有预约，不能删除。")

        cols = st.columns(2)
        with cols[0]:
            if st.button(
                "删除时间段",
                disabled=delete_slot["reserved_count"] > 0,
                key="time_slot_delete_dialog_confirm",
                use_container_width=True,
            ):
                try:
                    delete_time_slot(delete_slot["id"], admin_id=admin["id"])
                    st.success("领取时间已删除")
                    _close_delete_time_slot_dialog()
                    st.rerun()
                except ValueError as exc:
                    st.error(str(exc))
        with cols[1]:
            if st.button("关闭", key="close_delete_time_slot_dialog", use_container_width=True):
                _close_delete_time_slot_dialog()
                st.rerun()

    _open_dialog("删除时间段", dialog_body, width="medium")


def _render_time_editor(admin: dict[str, Any]) -> None:
    st.subheader("时间段管理")
    activity = _select_activity("time_activity_selector")
    if not activity:
        return

    building_rows = list_buildings(active_only=True)
    building_options = ["全部楼宇"] + [building["name"] for building in building_rows]
    date_options = activity_date_options(activity)
    if not date_options:
        st.warning("当前活动日期配置无效。")
        return

    if st.session_state.get("time_slot_filter_date") not in date_options:
        selected_schedule_date = st.session_state.get("selected_schedule_date")
        if selected_schedule_date in date_options:
            st.session_state["time_slot_filter_date"] = selected_schedule_date
        else:
            st.session_state.pop("time_slot_filter_date", None)

    selected_date = st.selectbox("查看日期", date_options, key="time_slot_filter_date")
    slots = list_time_slots_for_admin(activity["id"], selected_date)

    action_cols = st.columns([0.75, 0.75, 4.5])
    with action_cols[0]:
        if st.button(
            "新增时间段",
            type="primary",
            key="time_slot_add_toggle",
            use_container_width=True,
        ):
            st.session_state["show_add_time_slot_dialog"] = True
            st.session_state["show_delete_time_slot_dialog"] = False
            st.rerun()
    with action_cols[1]:
        if st.button(
            "删除时间段",
            key="time_slot_delete_toggle",
            use_container_width=True,
        ):
            st.session_state["show_delete_time_slot_dialog"] = True
            st.session_state["show_add_time_slot_dialog"] = False
            st.rerun()

    _render_add_time_slot_dialog(admin, activity, date_options, selected_date, building_options)
    _render_delete_time_slot_dialog(admin, slots)

    if not slots:
        st.caption("当日暂无领取时间。")
        return

    st.markdown("**当日领取时间**")
    table = [
        {
            "楼宇": slot["building"],
            "日期": slot["slot_date"],
            "时间": _slot_time_label(slot),
            "容量": slot["capacity"],
            "已预约": slot["reserved_count"],
            "状态": "可领取" if slot["is_available"] else "不可领取",
        }
        for slot in slots
    ]
    st.dataframe(table, use_container_width=True, hide_index=True)

    st.markdown("**容量管理**")
    current_slot = st.session_state.get("capacity_time_slot_selector")
    if isinstance(current_slot, dict) and all(slot["id"] != current_slot.get("id") for slot in slots):
        st.session_state.pop("capacity_time_slot_selector", None)
    slot = st.selectbox(
        "选择要调整容量的时间段",
        slots,
        format_func=lambda item: (
            f"{item['building']} {item['slot_date']} "
            f"{_slot_time_label(item)} "
            f"{'可领取' if item['is_available'] else '不可领取'}"
        ),
        key="capacity_time_slot_selector",
    )
    cols = st.columns([1, 0.75, 3.75])
    with cols[0]:
        new_capacity = st.number_input(
            "修改容量",
            min_value=max(1, int(slot["reserved_count"])),
            value=int(slot["capacity"]),
            step=1,
            key=f"edit_slot_capacity_{slot['id']}",
        )
    with cols[1]:
        st.write("")
        st.write("")
        if st.button(
            "保存容量",
            type="primary",
            key="save_slot_capacity",
            use_container_width=True,
        ):
            try:
                update_time_slot(
                    time_slot_id=slot["id"],
                    capacity=int(new_capacity),
                    is_available=bool(slot["is_available"]),
                    admin_id=admin["id"],
                )
                st.success("容量已更新")
                st.rerun()
            except ValueError as exc:
                st.error(str(exc))


def _slot_button_label(slot: dict[str, Any]) -> str:
    claim_count = len(slot.get("claims", []))
    if not slot["is_available"]:
        status = "关闭"
    elif claim_count:
        status = f"{claim_count}已约"
    else:
        status = "可领"
    return f"{_slot_time_label(slot)} {status}"


def _slot_button_type(slot: dict[str, Any]) -> str:
    if slot["is_available"]:
        return "primary"
    return "secondary"


def _slot_button_key(slot: dict[str, Any]) -> str:
    return f"quick_slot_{slot['id']}"


def _render_quick_timeslot_button_styles(slots: list[dict[str, Any]]) -> None:
    rules = []
    for slot in slots:
        key = _slot_button_key(slot)
        if not slot["is_available"]:
            background = "#e5e7eb"
            border = "#cbd5e1"
            color = "#64748b"
        elif slot.get("claims"):
            background = "#fff1f2"
            border = "#fb7185"
            color = "#be123c"
        else:
            background = "#ffffff"
            border = "#fecaca"
            color = "#b91c1c"

        rules.append(
            f"""
            .st-key-{key} button {{
                min-height: 28px !important;
                height: 28px !important;
                padding: 0.12rem 0.35rem !important;
                border-radius: 999px !important;
                border-color: {border} !important;
                background: {background} !important;
                color: {color} !important;
                box-shadow: none !important;
            }}
            .st-key-{key} button p {{
                color: {color} !important;
                font-size: 0.72rem !important;
                font-weight: 700 !important;
                line-height: 1 !important;
                white-space: nowrap !important;
                overflow: hidden !important;
                text-overflow: ellipsis !important;
            }}
            """
        )

    if rules:
        st.markdown("<style>" + "\n".join(rules) + "</style>", unsafe_allow_html=True)


def _render_schedule_styles() -> None:
    st.markdown(
        """
        <style>
            .schedule-activity {
                margin: 18px 0 20px;
            }
            .schedule-building {
                margin: 18px 0 22px;
                padding: 14px 14px 12px;
                border: 1px solid #e5e7eb;
                border-radius: 8px;
                background: #fff;
            }
            .schedule-building-title {
                margin: 0 0 8px;
                color: #1f2937;
                font-size: 1rem;
                font-weight: 700;
            }
            .schedule-activity-title {
                margin: 10px 0 6px;
                color: #475569;
                font-size: 0.86rem;
                font-weight: 700;
            }
            .booked-slot-title {
                margin: 12px 0 8px;
                color: #1f2937;
                font-size: 0.96rem;
                font-weight: 700;
            }
            .claim-table-header {
                padding: 8px 10px;
                border: 1px solid #e5e7eb;
                border-radius: 7px;
                background: #f8fafc;
                color: #64748b;
                font-size: 0.86rem;
                font-weight: 700;
            }
            .claim-table-cell {
                padding: 6px 10px;
                min-height: 36px;
                border-bottom: 1px solid #eef2f7;
                color: #1f2937;
                font-size: 0.9rem;
            }
        </style>
        """,
        unsafe_allow_html=True,
    )


def _claim_table_rows(slots: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for slot in slots:
        for claim in slot.get("claims", []):
            rows.append(
                {
                    "员工": claim["employee_name"],
                    "部门": claim["department"],
                    "礼物": claim["gift_name"],
                    "时间": f"{slot['slot_date']} {_slot_time_label(slot)}",
                    "状态": CLAIM_STATUS_LABELS.get(claim["status"], claim["status"]),
                    "验证码": claim["claim_code"],
                    "_claim_id": claim["id"],
                    "_claim_status": claim["status"],
                }
            )
    return rows


def _render_contact_button_styles(rows: list[dict[str, Any]]) -> None:
    rules = []
    for row in rows:
        key = f"contact_claim_{row['_claim_id']}"
        rules.append(
            f"""
            .st-key-{key} button {{
                min-height: 30px !important;
                height: 30px !important;
                padding: 0.14rem 0.45rem !important;
                border-radius: 7px !important;
            }}
            .st-key-{key} button p {{
                font-size: 0.78rem !important;
                line-height: 1 !important;
                white-space: nowrap !important;
            }}
            """
        )
    if rules:
        st.markdown("<style>" + "\n".join(rules) + "</style>", unsafe_allow_html=True)


def _render_claim_table(slots: list[dict[str, Any]], admin: dict[str, Any], key_prefix: str) -> None:
    rows = _claim_table_rows(slots)
    if not rows:
        return

    _render_contact_button_styles(rows)

    headers = ["员工", "部门", "礼物", "时间", "状态", "验证码", "操作"]
    widths = [1.0, 1.0, 1.25, 1.8, 0.85, 1.2, 0.65]
    header_cols = st.columns(widths)
    for index, header in enumerate(headers):
        header_cols[index].markdown(
            f'<div class="claim-table-header">{escape(header)}</div>',
            unsafe_allow_html=True,
        )

    for row in rows:
        cols = st.columns(widths)
        for index, field in enumerate(headers[:-1]):
            cols[index].markdown(
                f'<div class="claim-table-cell">{escape(str(row[field]))}</div>',
                unsafe_allow_html=True,
            )
        with cols[-1]:
            if st.button(
                "联系改期",
                key=f"contact_claim_{row['_claim_id']}",
                disabled=row["_claim_status"] != "reserved",
            ):
                _request_reschedule_sms(row["_claim_id"])


def _calendar_event_color(slot: dict[str, Any]) -> tuple[str, str]:
    if not slot["is_available"]:
        return "#f3f4f6", "#d1d5db"
    if slot.get("claims"):
        return "#fff1f2", "#fb7185"
    return "#f8fafc", "#cbd5e1"


def _selected_schedule_date() -> str:
    parsed = _parse_date_value(st.session_state.get("selected_schedule_date"))
    if not parsed:
        parsed = date.today()
    selected_date = parsed.isoformat()
    st.session_state["selected_schedule_date"] = selected_date
    return selected_date


def _month_calendar_events(activities: list[dict[str, Any]], selected_date: str) -> list[dict[str, Any]]:
    parsed_selected_date = _parse_date_value(selected_date) or date.today()
    selected_end_date = parsed_selected_date + timedelta(days=1)
    events = [
        {
            "id": f"selected-{parsed_selected_date.isoformat()}",
            "start": parsed_selected_date.isoformat(),
            "end": selected_end_date.isoformat(),
            "display": "background",
            "backgroundColor": "#ffe4e6",
            "classNames": ["selected-calendar-day"],
        }
    ]
    for month_label in _month_options(activities):
        year, month = [int(item) for item in month_label.split("-")]
        for day_value, info in sorted(list_schedule_calendar_counts(year, month).items()):
            reservation_count = int(info["reservation_count"])
            title = f"{info['activity_count']}活动"
            if reservation_count:
                title = f"{title} / {reservation_count}约"
            else:
                title = f"{title} / {info['available_slot_count']}时段"

            events.append(
                {
                    "id": f"day-{day_value}",
                    "title": title,
                    "start": day_value,
                    "allDay": True,
                    "backgroundColor": "#fff1f2" if reservation_count else "#f8fafc",
                    "borderColor": "#fb7185" if reservation_count else "#cbd5e1",
                    "textColor": "#1f2937",
                }
            )
    return events


def _day_calendar_events(slots: list[dict[str, Any]]) -> list[dict[str, Any]]:
    events = []
    for slot in slots:
        background_color, border_color = _calendar_event_color(slot)
        claim_count = len(slot.get("claims", []))
        title_parts = [slot["activity_name"]]
        if claim_count:
            title_parts.append(f"{claim_count}人预约")
        elif not slot["is_available"]:
            title_parts.append("不可领取")
        else:
            title_parts.append("空")

        events.append(
            {
                "id": f"slot-{slot['id']}",
                "title": " / ".join(title_parts),
                "start": f"{slot['slot_date']}T{slot['start_time']}:00",
                "end": f"{slot['slot_date']}T{slot['end_time']}:00",
                "resourceId": slot["building"],
                "backgroundColor": background_color,
                "borderColor": border_color,
                "textColor": "#1f2937",
            }
        )
    return events


def _calendar_state_date(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        parsed = value.astimezone(LOCAL_TIMEZONE) if value.tzinfo else value
        return parsed.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()

    raw = str(value).strip()
    if not raw:
        return None
    if "T" not in raw:
        parsed_date = _parse_date_value(raw[:10])
        return parsed_date.isoformat() if parsed_date else None

    normalized = raw.replace("Z", "+00:00")
    try:
        parsed_datetime = datetime.fromisoformat(normalized)
    except ValueError:
        parsed_date = _parse_date_value(raw[:10])
        return parsed_date.isoformat() if parsed_date else None

    if parsed_datetime.tzinfo:
        parsed_datetime = parsed_datetime.astimezone(LOCAL_TIMEZONE)
    return parsed_datetime.date().isoformat()


def _date_from_calendar_state(state: Any, current_view: str) -> str | None:
    if not isinstance(state, dict):
        return None

    if current_view != "日视图":
        date_click = state.get("dateClick")
        if isinstance(date_click, dict):
            value = date_click.get("dateStr") or date_click.get("date")
            if value:
                return _calendar_state_date(value)

        event_click = state.get("eventClick")
        if isinstance(event_click, dict):
            event = event_click.get("event") if isinstance(event_click.get("event"), dict) else event_click
            event_id = str(event.get("id", ""))
            if event_id.startswith("day-"):
                return event_id.removeprefix("day-")[:10]
            value = event.get("start") or event.get("startStr")
            if value:
                return _calendar_state_date(value)

    dates_set = state.get("datesSet")
    if current_view == "日视图" and isinstance(dates_set, dict):
        value = dates_set.get("startStr") or dates_set.get("start")
        if value:
            return _calendar_state_date(value)

    return None


def _sync_calendar_selected_date(next_date: str | None, selected_date: str) -> None:
    parsed = _parse_date_value(next_date)
    if not parsed:
        return

    normalized = parsed.isoformat()
    if normalized == selected_date:
        return

    st.session_state["selected_schedule_date"] = normalized
    st.session_state["time_slot_filter_date"] = normalized
    st.rerun()


def _render_streamlit_calendar(
    selected_date: str,
    slots: list[dict[str, Any]],
    activities: list[dict[str, Any]],
    view_mode: str,
) -> None:
    calendar = _streamlit_calendar()
    if calendar is None:
        st.warning("请先安装 streamlit-calendar 以显示领取时间日历。")
        return

    if view_mode == "月视图":
        events = _month_calendar_events(activities, selected_date)
        calendar_options = {
            "initialDate": selected_date,
            "initialView": "dayGridMonth",
            "locale": "zh-cn",
            "editable": False,
            "selectable": True,
            "height": 620,
            "headerToolbar": {
                "left": "prev,next today",
                "center": "title",
                "right": "",
            },
            "buttonText": {"today": "今天"},
        }
    else:
        buildings = sorted({slot["building"] for slot in slots}, reverse=True)
        resources = [
            {"id": building, "title": building, "building": building}
            for building in buildings
        ]
        events = _day_calendar_events(slots)
        calendar_options = {
            "initialDate": selected_date,
            "initialView": "resourceTimelineDay",
            "locale": "zh-cn",
            "resourceAreaHeaderContent": "楼宇",
            "resourceGroupField": "building",
            "resources": resources,
            "editable": False,
            "selectable": True,
            "height": 520,
            "slotMinTime": "09:00:00",
            "slotMaxTime": "19:00:00",
            "headerToolbar": {
                "left": "prev,next today",
                "center": "title",
                "right": "",
            },
            "buttonText": {"today": "今天"},
        }

    custom_css = """
        .fc .fc-toolbar-title {
            font-size: 1rem;
            font-weight: 700;
        }
        .fc .fc-event-title {
            font-weight: 700;
        }
        .fc .fc-day-today {
            background: #fff7ed !important;
            box-shadow: inset 0 0 0 1px #fdba74;
        }
        .fc .fc-day-today .fc-daygrid-day-number {
            color: #c2410c;
            font-weight: 800;
        }
        .fc .fc-bg-event.selected-calendar-day {
            background: #ffe4e6 !important;
            opacity: 1 !important;
        }
        .fc .fc-bg-event.selected-calendar-day + .fc-daygrid-day-frame,
        .fc .fc-daygrid-day:has(.selected-calendar-day) {
            box-shadow: inset 0 0 0 2px #f43f5e;
        }
        .fc .fc-resource-timeline-divider {
            width: 0;
        }
        .fc .fc-daygrid-event {
            border-radius: 999px;
            padding: 2px 6px;
        }
    """

    state = calendar(
        events=events,
        options=calendar_options,
        custom_css=custom_css,
        key=f"schedule_calendar_{view_mode}_{selected_date}",
    )
    _sync_calendar_selected_date(
        _date_from_calendar_state(state, view_mode),
        selected_date,
    )


def _render_calendar_tab(admin: dict[str, Any]) -> None:
    st.subheader("时间管理")
    activities = list_published_activities()
    if not activities:
        st.warning("暂无已发布活动。")
        return

    selected_date = _selected_schedule_date()
    slots = list_day_schedule(selected_date)

    _render_schedule_styles()
    view_mode = st.radio(
        "日历视图",
        ["月视图", "日视图"],
        horizontal=True,
        key="schedule_calendar_view",
        label_visibility="collapsed",
    )
    _render_streamlit_calendar(selected_date, slots, activities, view_mode)

    st.markdown(f"**{selected_date} 快捷显示timeslot**")
    if not slots:
        st.caption("当日暂无在线活动或领取时间。")
        return

    _render_quick_timeslot_button_styles(slots)

    slots_by_building: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for slot in slots:
        slots_by_building[slot["building"]].append(slot)

    st.write("当日在线活动：" + "、".join(sorted({slot["activity_name"] for slot in slots})))

    for building, building_slots in sorted(slots_by_building.items()):
        with st.container(border=True):
            slots_by_activity: dict[str, list[dict[str, Any]]] = defaultdict(list)
            for slot in building_slots:
                slots_by_activity[slot["activity_name"]].append(slot)

            st.markdown(
                f'<div class="schedule-building-title">{escape(building)}</div>',
                unsafe_allow_html=True,
            )
            for activity_name, activity_slots in sorted(slots_by_activity.items()):
                st.markdown(
                    f'<div class="schedule-activity-title">{escape(activity_name)}</div>',
                    unsafe_allow_html=True,
                )
                cols = st.columns(8)
                for index, slot in enumerate(activity_slots):
                    with cols[index % len(cols)]:
                        if st.button(
                            _slot_button_label(slot),
                            key=_slot_button_key(slot),
                            type=_slot_button_type(slot),
                            use_container_width=True,
                            help="点击后确认开启或关闭此领取时间",
                        ):
                            _request_slot_toggle(slot)

            booked_slots = [slot for slot in building_slots if slot.get("claims")]
            if booked_slots:
                st.markdown(
                    f'<div class="booked-slot-title">{escape(building)} 预约列表</div>',
                    unsafe_allow_html=True,
                )
                _render_claim_table(booked_slots, admin, key_prefix=f"schedule_{selected_date}_{building}")


def _render_schedule_tab(admin: dict[str, Any]) -> None:
    _render_slot_toggle_dialog(admin)
    _render_reschedule_sms_dialog(admin)
    _render_calendar_tab(admin)
    st.divider()
    _render_time_editor(admin)


def _render_reservation_management_tab(admin: dict[str, Any]) -> None:
    schedule_tab, building_tab = st.tabs(["时间管理", "楼宇管理"])
    with schedule_tab:
        _render_schedule_tab(admin)
    with building_tab:
        _render_building_tab(admin)


def _render_after_sale_table(rows: list[dict[str, Any]]) -> None:
    table = [
        {
            "售后单": _format_after_sale_id(row["id"]),
            "员工": f"{row['employee_name']}（{row['employee_no']}）",
            "部门": row["department"],
            "活动": row["activity_name"],
            "礼物": row["gift_name"],
            "楼宇": row["building"],
            "类型": _after_sale_issue_label(row["issue_type"]),
            "期望处理": _after_sale_resolution_label(row["expected_resolution"]),
            "状态": _after_sale_status_label(row["status"]),
            "提交时间": row["created_at"],
        }
        for row in rows
    ]
    st.dataframe(table, use_container_width=True, hide_index=True)


def _request_after_sale_admin_dialog(after_sale_id: int) -> None:
    st.session_state["admin_after_sale_dialog_id"] = int(after_sale_id)


def _close_after_sale_admin_dialog() -> None:
    st.session_state.pop("admin_after_sale_dialog_id", None)


def _render_after_sale_rows(rows: list[dict[str, Any]], action_label: str) -> None:
    if not rows:
        st.caption("暂无售后单。")
        return

    header_cols = st.columns([1, 1.1, 1, 1.4, 1.3, 0.9, 1, 0.7])
    headers = ["售后单", "员工", "部门", "活动", "礼物", "状态", "提交时间", ""]
    for col, header in zip(header_cols, headers):
        col.caption(header)

    for row in rows:
        cols = st.columns([1, 1.1, 1, 1.4, 1.3, 0.9, 1, 0.7])
        cols[0].write(_format_after_sale_id(row["id"]))
        cols[1].write(f"{row['employee_name']}（{row['employee_no']}）")
        cols[2].write(row["department"])
        cols[3].write(row["activity_name"])
        cols[4].write(row["gift_name"])
        cols[5].write(_after_sale_status_label(row["status"]))
        cols[6].write(row["created_at"])
        if cols[7].button(
            action_label,
            key=f"open_after_sale_{action_label}_{row['id']}",
            use_container_width=True,
        ):
            _request_after_sale_admin_dialog(row["id"])
            st.rerun()


def _render_after_sale_detail(after_sale: dict[str, Any], admin: dict[str, Any]) -> None:
    st.markdown(f"**{_format_after_sale_id(after_sale['id'])} 详情**")
    detail_cols = st.columns(3)
    detail_cols[0].write(f"员工：{after_sale['employee_name']}（{after_sale['employee_no']}）")
    detail_cols[0].write(f"部门：{after_sale['department']}")
    detail_cols[1].write(f"活动：{after_sale['activity_name']}")
    detail_cols[1].write(f"礼物：{after_sale['gift_name']}")
    detail_cols[2].write(f"楼宇：{after_sale['building']}")
    detail_cols[2].write(
        f"原时间：{after_sale['slot_date']} {after_sale['start_time']}-{after_sale['end_time']}"
    )
    st.write(f"问题类型：{_after_sale_issue_label(after_sale['issue_type'])}")
    st.write(f"期望处理：{_after_sale_resolution_label(after_sale['expected_resolution'])}")
    st.write(f"问题描述：{after_sale['description']}")
    st.write(f"联系方式：{after_sale['contact_phone']}")
    st.caption(
        f"当前库存：可用 {after_sale['available_stock']}，已发放 {after_sale['redeemed_stock']}；"
        f"验证码 {after_sale['claim_code']}"
    )
    if after_sale.get("admin_note"):
        st.info(f"当前备注：{after_sale['admin_note']}")

    if after_sale["status"] not in {"pending", "processing"}:
        st.caption("该售后单已结束。")
        if st.button("关闭", key=f"after_sale_close_{after_sale['id']}"):
            _close_after_sale_admin_dialog()
            st.rerun()
        return

    admin_note = st.text_area(
        "处理备注",
        value=after_sale.get("admin_note", ""),
        height=88,
        key=f"after_sale_admin_note_{after_sale['id']}",
    )
    inventory_action = st.selectbox(
        "完成售后的库存动作",
        list(AFTER_SALE_INVENTORY_ACTIONS.keys()),
        format_func=_after_sale_inventory_action_label,
        key=f"after_sale_inventory_action_{after_sale['id']}",
    )

    cols = st.columns(3)
    with cols[0]:
        if st.button(
            "标记处理中",
            disabled=after_sale["status"] != "pending",
            use_container_width=True,
            key=f"after_sale_processing_{after_sale['id']}",
        ):
            try:
                mark_after_sale_processing(after_sale["id"], admin_note, admin_id=admin["id"])
                st.success("售后单已标记处理中")
                _close_after_sale_admin_dialog()
                st.rerun()
            except ValueError as exc:
                st.error(str(exc))
    with cols[1]:
        if st.button(
            "完成售后",
            type="primary",
            use_container_width=True,
            key=f"after_sale_resolve_{after_sale['id']}",
        ):
            try:
                resolve_after_sale(
                    after_sale["id"],
                    inventory_action,
                    admin_note,
                    admin_id=admin["id"],
                )
                st.success("售后单已完成")
                _close_after_sale_admin_dialog()
                st.rerun()
            except ValueError as exc:
                st.error(str(exc))
    with cols[2]:
        if st.button(
            "拒绝售后",
            use_container_width=True,
            key=f"after_sale_reject_{after_sale['id']}",
        ):
            try:
                reject_after_sale(after_sale["id"], admin_note, admin_id=admin["id"])
                st.success("售后单已拒绝")
                _close_after_sale_admin_dialog()
                st.rerun()
            except ValueError as exc:
                st.error(str(exc))

    if st.button("关闭", key=f"after_sale_close_active_{after_sale['id']}"):
        _close_after_sale_admin_dialog()
        st.rerun()


def _render_after_sale_admin_dialog(admin: dict[str, Any]) -> None:
    after_sale_id = st.session_state.get("admin_after_sale_dialog_id")
    if not after_sale_id:
        return

    after_sale = get_after_sale(int(after_sale_id))
    if not after_sale:
        _close_after_sale_admin_dialog()
        st.warning("售后单不存在或已被删除。")
        return

    def dialog_body() -> None:
        _render_after_sale_detail(after_sale, admin)

    dialog = getattr(st, "dialog", None)
    if dialog:
        dialog("处理售后")(dialog_body)()
    else:
        with st.container(border=True):
            dialog_body()


def _render_after_sale_tab(admin: dict[str, Any]) -> None:
    st.subheader("售后处理")
    _render_after_sale_admin_dialog(admin)
    activities = list_admin_activities()
    activity_options = [{"id": None, "name": "全部活动", "status": "all"}] + activities
    filter_cols = st.columns([1.2, 1.4])
    with filter_cols[0]:
        selected_activity = st.selectbox(
            "活动",
            activity_options,
            format_func=lambda item: (
                "全部活动"
                if item["id"] is None
                else f"{item['name']}（{_activity_status_label(item.get('status', 'published'))}）"
            ),
            key="after_sale_activity_filter",
        )
    with filter_cols[1]:
        keyword = st.text_input("搜索", placeholder="员工、工号、礼物或验证码", key="after_sale_keyword")

    rows = list_after_sales_for_admin(
        activity_id=selected_activity["id"],
        status="all",
        keyword=keyword,
    )
    active_rows = [row for row in rows if row["status"] in {"pending", "processing"}]
    history_rows = [row for row in rows if row["status"] not in {"pending", "processing"}]

    pending_tab, history_tab = st.tabs(["待处理", "历史售后"])
    with pending_tab:
        _render_after_sale_rows(active_rows, "处理")
    with history_tab:
        _render_after_sale_rows(history_rows, "查看")


def _render_dashboard_tab() -> None:
    st.subheader("数据看板")
    activity = _select_activity("dashboard_activity_selector")
    if not activity:
        return

    summary = dashboard_summary(activity["id"])
    inventory = summary["inventory"]
    cols = st.columns(4)
    cols[0].metric("已预约", summary["reserved_claims"])
    cols[1].metric("已核销", summary["redeemed_claims"])
    cols[2].metric("已取消", summary["cancelled_claims"])
    cols[3].metric("已过期", summary["expired_claims"])

    inv_cols = st.columns(4)
    inv_cols[0].metric("总库存", inventory.get("total_stock", 0))
    inv_cols[1].metric("可用库存", inventory.get("available_stock", 0))
    inv_cols[2].metric("占用库存", inventory.get("reserved_stock", 0))
    inv_cols[3].metric("已发放库存", inventory.get("redeemed_stock", 0))

    rows = list_inventory_rows(activity["id"])
    st.markdown("**库存明细**")
    inventory_table = [
        {
            "礼物": row["gift_name"],
            "分类": row["category"],
            "楼栋": row["building"],
            "总库存": row["total_stock"],
            "可用": row["available_stock"],
            "已预约": row["reserved_stock"],
            "已发放": row["redeemed_stock"],
            "已释放": row["released_stock"],
        }
        for row in rows
    ]
    st.dataframe(inventory_table, use_container_width=True, hide_index=True)

    st.markdown("**预约状态**")
    status_table = [
        {"状态": "已预约", "数量": summary["reserved_claims"]},
        {"状态": "已核销", "数量": summary["redeemed_claims"]},
        {"状态": "已取消", "数量": summary["cancelled_claims"]},
        {"状态": "已过期", "数量": summary["expired_claims"]},
    ]
    st.dataframe(status_table, use_container_width=True, hide_index=True)

    gift_totals: dict[str, dict[str, int]] = {}
    for row in rows:
        item = gift_totals.setdefault(
            row["gift_name"],
            {"总库存": 0, "剩余库存": 0, "占用库存": 0, "已发放库存": 0},
        )
        item["总库存"] += row["total_stock"]
        item["剩余库存"] += row["available_stock"]
        item["占用库存"] += row["reserved_stock"]
        item["已发放库存"] += row["redeemed_stock"]

    st.markdown("**礼物汇总**")
    gift_table = [{"礼物": gift_name, **totals} for gift_name, totals in gift_totals.items()]
    st.dataframe(gift_table, use_container_width=True, hide_index=True)


def _format_test_employee(employee: dict[str, Any]) -> str:
    return f"{employee['name']} / {employee['employee_no']} / {employee['department']}"


def _format_test_activity(activity: dict[str, Any]) -> str:
    return f"{activity['name']}（{activity['start_date']} 至 {activity['end_date']}）"


def _format_test_gift(gift: dict[str, Any]) -> str:
    available = gift.get("available_stock", 0)
    category = gift.get("category") or "未分类"
    return f"{gift['name']} · {category} · 可用 {available}"


def _format_test_slot(slot: dict[str, Any]) -> str:
    return (
        f"{slot['slot_date']} {slot['start_time']}-{slot['end_time']} "
        f"剩余 {slot['remaining']}/{slot['capacity']}"
    )


def _render_test_result_table(results: list[dict[str, Any]]) -> None:
    if not results:
        return
    st.markdown("**最近一次测试结果**")
    st.dataframe(results, use_container_width=True, hide_index=True)


def _reservation_test_gift_options(activity_id: int, building_name: str) -> list[dict[str, Any]]:
    gift_options: dict[int, dict[str, Any]] = {}
    for row in list_inventory_rows(activity_id):
        if row["building"] != building_name:
            continue
        gift_options[int(row["gift_id"])] = {
            "id": int(row["gift_id"]),
            "name": row["gift_name"],
            "category": row.get("category", ""),
            "available_stock": int(row.get("available_stock", 0)),
        }
    return sorted(gift_options.values(), key=lambda item: item["name"])


def _claim_result_row(
    employee: dict[str, Any],
    gift_name: str,
    result: dict[str, Any],
) -> dict[str, Any]:
    claim = result.get("claim") or {}
    return {
        "员工": employee["name"],
        "工号": employee["employee_no"],
        "部门": employee["department"],
        "礼物": gift_name,
        "结果": "成功" if result.get("ok") else "失败",
        "说明": result.get("message", ""),
        "验证码": claim.get("claim_code", ""),
    }


def _render_single_reservation_test() -> None:
    employees = list_employees()
    if not employees:
        st.warning("暂无员工数据。")
        return

    employee = st.selectbox(
        "测试员工",
        employees,
        format_func=_format_test_employee,
        key="reservation_test_single_employee",
    )
    activities = list_employee_available_activities(employee["id"])
    if not activities:
        st.warning("该员工暂无可预约活动。")
        return

    activity = st.selectbox(
        "活动",
        activities,
        format_func=_format_test_activity,
        key="reservation_test_single_activity",
    )
    buildings = list_activity_buildings(activity["id"])
    if not buildings:
        st.warning("该活动暂无可领取楼宇。")
        return

    building = st.selectbox(
        "楼宇",
        buildings,
        format_func=lambda item: item["name"],
        key="reservation_test_single_building",
    )
    gifts = [
        gift
        for gift in list_eligible_gifts(employee["id"], activity["id"], building=building["name"])
        if int(gift.get("available_stock", 0)) > 0
    ]
    if not gifts:
        st.warning("该员工在当前楼宇暂无可领且有库存的礼物。")
        return

    gift = st.selectbox(
        "礼物",
        gifts,
        format_func=_format_test_gift,
        key="reservation_test_single_gift",
    )
    slots = [
        slot
        for slot in list_time_slots(activity["id"], building["name"])
        if int(slot.get("remaining", 0)) > 0
    ]
    if not slots:
        st.warning("该楼宇暂无可预约时间段。")
        return

    slot = st.selectbox(
        "领取时间段",
        slots,
        format_func=_format_test_slot,
        key="reservation_test_single_slot",
    )

    if st.button("模拟该员工预约", type="primary", use_container_width=True):
        result = create_claim(
            employee_id=employee["id"],
            activity_id=activity["id"],
            gift_id=gift["id"],
            building=building["name"],
            time_slot_id=slot["id"],
        )
        st.session_state["reservation_test_results"] = [
            _claim_result_row(employee, gift["name"], result)
        ]
        if result["ok"]:
            st.success(result["message"])
        else:
            st.error(result["message"])

    claims = list_employee_claims(employee["id"])
    if claims:
        st.markdown("**该员工已有领取记录**")
        st.dataframe(
            [
                {
                    "活动": claim["activity_name"],
                    "礼物": claim["gift_name"],
                    "楼宇": claim["building"],
                    "时间": f"{claim['slot_date']} {_slot_time_label(claim)}",
                    "状态": CLAIM_STATUS_LABELS.get(claim["status"], claim["status"]),
                    "验证码": claim["claim_code"],
                }
                for claim in claims
            ],
            use_container_width=True,
            hide_index=True,
        )


def _render_batch_reservation_test() -> None:
    activities = list_published_activities()
    if not activities:
        st.warning("暂无已上线活动。")
        return

    activity = st.selectbox(
        "活动",
        activities,
        format_func=_format_test_activity,
        key="reservation_test_batch_activity",
    )
    buildings = list_activity_buildings(activity["id"])
    if not buildings:
        st.warning("该活动暂无可领取楼宇。")
        return

    building = st.selectbox(
        "楼宇",
        buildings,
        format_func=lambda item: item["name"],
        key="reservation_test_batch_building",
    )
    slots = [
        slot
        for slot in list_time_slots(activity["id"], building["name"])
        if int(slot.get("remaining", 0)) > 0
    ]
    if not slots:
        st.warning("该楼宇暂无可预约时间段。")
        return

    slot = st.selectbox(
        "领取时间段",
        slots,
        format_func=_format_test_slot,
        key="reservation_test_batch_slot",
    )

    employees = list_employees()
    employee_by_id = {int(employee["id"]): employee for employee in employees}
    selected_employee_ids = st.multiselect(
        "测试员工",
        list(employee_by_id.keys()),
        format_func=lambda employee_id: _format_test_employee(employee_by_id[int(employee_id)]),
        key="reservation_test_batch_employees",
    )

    gift_strategy = st.radio(
        "礼物策略",
        ["自动选择每人第一个可领礼物", "指定同一礼物"],
        horizontal=True,
        key="reservation_test_batch_gift_strategy",
    )
    selected_gift: dict[str, Any] | None = None
    if gift_strategy == "指定同一礼物":
        gift_options = _reservation_test_gift_options(activity["id"], building["name"])
        if not gift_options:
            st.warning("该楼宇暂无礼物库存。")
            return
        selected_gift = st.selectbox(
            "指定礼物",
            gift_options,
            format_func=_format_test_gift,
            key="reservation_test_batch_gift",
        )

    if st.button("批量模拟预约", type="primary", use_container_width=True):
        if not selected_employee_ids:
            st.warning("请至少选择一个测试员工。")
            return

        results = []
        for employee_id in selected_employee_ids:
            employee = employee_by_id[int(employee_id)]
            if gift_strategy == "自动选择每人第一个可领礼物":
                gifts = [
                    gift
                    for gift in list_eligible_gifts(
                        employee["id"],
                        activity["id"],
                        building=building["name"],
                    )
                    if int(gift.get("available_stock", 0)) > 0
                ]
                if not gifts:
                    results.append(
                        {
                            "员工": employee["name"],
                            "工号": employee["employee_no"],
                            "部门": employee["department"],
                            "礼物": "",
                            "结果": "失败",
                            "说明": "该员工无可领礼物或当前楼宇库存不足",
                            "验证码": "",
                        }
                    )
                    continue
                gift = gifts[0]
            else:
                gift = selected_gift

            if not gift:
                results.append(
                    {
                        "员工": employee["name"],
                        "工号": employee["employee_no"],
                        "部门": employee["department"],
                        "礼物": "",
                        "结果": "失败",
                        "说明": "未选择礼物",
                        "验证码": "",
                    }
                )
                continue

            result = create_claim(
                employee_id=employee["id"],
                activity_id=activity["id"],
                gift_id=gift["id"],
                building=building["name"],
                time_slot_id=slot["id"],
            )
            results.append(_claim_result_row(employee, gift["name"], result))

        st.session_state["reservation_test_results"] = results
        success_count = sum(1 for row in results if row["结果"] == "成功")
        st.success(f"批量预约完成：成功 {success_count}，失败 {len(results) - success_count}")

    claims = list_claims_for_admin(activity["id"])
    if claims:
        st.markdown("**当前活动预约概览**")
        st.dataframe(
            [
                {
                    "员工": claim["employee_name"],
                    "部门": claim["department"],
                    "礼物": claim["gift_name"],
                    "楼宇": claim["building"],
                    "时间": f"{claim['slot_date']} {_slot_time_label(claim)}",
                    "状态": CLAIM_STATUS_LABELS.get(claim["status"], claim["status"]),
                    "验证码": claim["claim_code"],
                }
                for claim in claims[:80]
            ],
            use_container_width=True,
            hide_index=True,
        )


def _render_reservation_test_tool(admin: dict[str, Any]) -> None:
    st.subheader("隐藏测试工具：员工预约")
    st.warning("该页面用于功能级测试，会真实创建预约记录、占用库存并生成员工通知。")
    st.caption("访问方式：`?portal=admin&tool=reservation_test`。该入口不会出现在正式管理菜单中。")

    mode = st.radio(
        "测试模式",
        ["单人模拟预约", "批量模拟预约"],
        horizontal=True,
        label_visibility="collapsed",
        key="reservation_test_mode",
    )
    if mode == "单人模拟预约":
        _render_single_reservation_test()
    else:
        _render_batch_reservation_test()

    _render_test_result_table(st.session_state.get("reservation_test_results", []))


def _render_hidden_tool_sidebar() -> None:
    st.sidebar.markdown(
        """
        <div class="portal-nav-title">隐藏测试工具</div>
        <div class="portal-nav">
            <a class="portal-nav-item active" href="?portal=admin&tool=reservation_test" target="_self">员工预约测试</a>
            <a class="portal-nav-item" href="?portal=admin" target="_self">返回管理后台</a>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.sidebar.markdown('<div class="admin-sidebar-spacer"></div>', unsafe_allow_html=True)
    if st.sidebar.button("重新初始化演示数据"):
        seed_demo_data(force=True)
        st.session_state.pop("config_draft", None)
        st.session_state.pop("reservation_test_results", None)
        st.success("演示数据已重置")
        st.rerun()
    if st.sidebar.button("退出管理后台"):
        st.session_state.pop("admin", None)
        st.session_state.pop("admin_page", None)
        st.session_state.pop("admin_nav_radio", None)
        st.session_state.pop("reservation_test_results", None)
        st.rerun()


def render() -> None:
    st.header("管理后台")
    admin = _ensure_admin()
    if not admin:
        return

    _render_compact_action_styles()

    if _current_admin_tool() == "reservation_test":
        _render_hidden_tool_sidebar()
        _render_reservation_test_tool(admin)
        return

    page = _current_admin_page()
    page = _render_admin_nav(page)

    with st.sidebar:
        st.markdown('<div class="admin-sidebar-spacer"></div>', unsafe_allow_html=True)
        if st.button("重新初始化演示数据"):
            seed_demo_data(force=True)
            st.session_state.pop("config_draft", None)
            st.success("演示数据已重置")
            st.rerun()
        if st.button("退出管理后台"):
            st.session_state.pop("admin", None)
            st.session_state.pop("admin_page", None)
            st.session_state.pop("admin_nav_radio", None)
            st.rerun()

    if page == "config":
        _render_config_tab(admin)
    elif page == "publish":
        _render_reservation_management_tab(admin)
    elif page == "redeem":
        _render_redeem_tab(admin)
    elif page == "after_sale":
        _render_after_sale_tab(admin)
    else:
        _render_dashboard_tab()
