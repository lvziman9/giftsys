from __future__ import annotations

import streamlit as st

from config import CLAIM_STATUS_LABELS
from services.after_sale_service import (
    AFTER_SALE_EXPECTED_RESOLUTIONS,
    AFTER_SALE_ISSUE_TYPES,
    AFTER_SALE_INVENTORY_ACTIONS,
    AFTER_SALE_STATUS_LABELS,
    cancel_after_sale,
    create_after_sale,
    list_after_sales_by_claims,
    list_after_sales_for_employee,
)
from services.activity_service import (
    authenticate_employee,
    get_employee,
    get_latest_activity,
    list_activity_buildings,
    list_eligible_gifts,
    list_employee_available_activities,
    list_employee_claims,
    list_inventory_for_gift,
    list_time_slots,
)
from services.claim_service import cancel_claim, create_claim
from services.notification_service import (
    count_unread_notifications,
    list_notifications,
    mark_all_notifications_read,
    mark_notification_read,
    respond_reschedule_notification,
)
from utils.codegen import demo_qr_svg_data_uri


EMPLOYEE_SECTIONS = ["福利领取", "我的领取", "我的售后"]


def _format_employee(employee: dict) -> str:
    return f"{employee['name']} / {employee['employee_no']} / {employee['department']}"


def _format_slot(slot: dict) -> str:
    time_label = (
        f"{slot['start_time']}-{slot['end_time']}"
        if slot.get("start_time") and slot.get("end_time")
        else "全天"
    )
    return (
        f"{slot['slot_date']} {time_label} "
        f"(剩余 {slot['remaining']}/{slot['capacity']})"
    )


def _format_after_sale_id(after_sale_id: int) -> str:
    return f"AS-{after_sale_id:05d}"


def _after_sale_status_label(status: str) -> str:
    return AFTER_SALE_STATUS_LABELS.get(status, status)


def _after_sale_issue_label(issue_type: str) -> str:
    return AFTER_SALE_ISSUE_TYPES.get(issue_type, issue_type)


def _after_sale_resolution_label(resolution: str) -> str:
    return AFTER_SALE_EXPECTED_RESOLUTIONS.get(resolution, resolution)


def _after_sale_inventory_action_label(action: str) -> str:
    return AFTER_SALE_INVENTORY_ACTIONS.get(action, action)


def _render_building_info(building: dict) -> None:
    details = []
    if building.get("address"):
        details.append(f"地址：{building['address']}")
    if building.get("pickup_location"):
        details.append(f"领取点：{building['pickup_location']}")
    if building.get("manager_name"):
        contact = f" {building['manager_contact']}" if building.get("manager_contact") else ""
        details.append(f"负责人：{building['manager_name']}{contact}")
    if building.get("note"):
        details.append(f"备注：{building['note']}")

    if details:
        with st.container(border=True):
            for item in details:
                st.caption(item)


def _current_employee() -> dict | None:
    employee_id = st.session_state.get("employee_id")
    if not employee_id:
        return None

    employee = get_employee(int(employee_id))
    if not employee:
        st.session_state.pop("employee_id", None)
        return None
    return employee


def _render_login() -> None:
    st.header("员工端")
    with st.form("employee_login_form"):
        employee_no = st.text_input("工号", placeholder="例如 E1001")
        phone_suffix = st.text_input("手机号后四位", type="password", max_chars=4)
        submitted = st.form_submit_button("登录", type="primary")

    if submitted:
        employee = authenticate_employee(employee_no, phone_suffix)
        if employee:
            st.session_state["employee_id"] = employee["id"]
            st.session_state["employee_feedback"] = f"已登录：{_format_employee(employee)}"
            st.rerun()
        else:
            st.error("工号或手机号后四位不正确")


def _notification_status(notification: dict) -> str:
    if notification["type"] == "reschedule_request":
        status_map = {
            "pending": "待确认",
            "accepted": "已同意",
            "declined": "已不同意",
        }
        return status_map.get(notification["action_status"], notification["action_status"])
    return "未读" if not notification["is_read"] else "已读"


def _render_notification_center(employee: dict) -> None:
    unread_count = count_unread_notifications(employee["id"])
    with st.expander(f"通知中心（{unread_count} 未读）", expanded=unread_count > 0):
        notifications = list_notifications(employee["id"])
        if not notifications:
            st.caption("暂无通知。")
            return

        if unread_count:
            if st.button("全部标为已读", key="mark_all_notifications_read"):
                mark_all_notifications_read(employee["id"])
                st.rerun()

        for notification in notifications:
            with st.container(border=True):
                st.markdown(f"**{notification['title']}**")
                st.caption(f"{notification['created_at']} · {_notification_status(notification)}")
                st.write(notification["content"])

                if (
                    notification["type"] == "reschedule_request"
                    and notification["action_status"] == "pending"
                ):
                    cols = st.columns(2)
                    with cols[0]:
                        if st.button(
                            "同意改期",
                            type="primary",
                            key=f"accept_reschedule_{notification['id']}",
                            use_container_width=True,
                        ):
                            result = respond_reschedule_notification(
                                notification["id"],
                                employee["id"],
                                accepted=True,
                            )
                            if result["ok"]:
                                st.session_state["employee_feedback"] = result["message"]
                                st.rerun()
                            else:
                                st.error(result["message"])
                    with cols[1]:
                        if st.button(
                            "不同意",
                            key=f"decline_reschedule_{notification['id']}",
                            use_container_width=True,
                        ):
                            result = respond_reschedule_notification(
                                notification["id"],
                                employee["id"],
                                accepted=False,
                            )
                            if result["ok"]:
                                st.session_state["employee_feedback"] = result["message"]
                                st.rerun()
                            else:
                                st.error(result["message"])
                elif not notification["is_read"]:
                    if st.button("标为已读", key=f"read_notification_{notification['id']}"):
                        mark_notification_read(notification["id"], employee["id"])
                        st.rerun()


def _request_after_sale(claim_id: int) -> None:
    st.session_state["pending_after_sale_claim_id"] = int(claim_id)
    st.rerun()


def _render_after_sale_dialog(employee: dict) -> None:
    claim_id = st.session_state.get("pending_after_sale_claim_id")
    if not claim_id:
        return

    claims = list_employee_claims(employee["id"])
    claim = next((item for item in claims if item["id"] == int(claim_id)), None)
    if not claim:
        st.session_state.pop("pending_after_sale_claim_id", None)
        return

    def close_dialog() -> None:
        st.session_state.pop("pending_after_sale_claim_id", None)
        st.rerun()

    def dialog_body() -> None:
        st.write(f"{claim['activity_name']} / {claim['gift_name']}")
        st.caption(f"领取记录：{claim['claim_code']} / {claim['building']}")
        with st.form(f"after_sale_form_{claim['id']}"):
            issue_type = st.selectbox(
                "售后类型",
                list(AFTER_SALE_ISSUE_TYPES.keys()),
                format_func=_after_sale_issue_label,
            )
            expected_resolution = st.selectbox(
                "期望处理方式",
                list(AFTER_SALE_EXPECTED_RESOLUTIONS.keys()),
                format_func=_after_sale_resolution_label,
            )
            description = st.text_area(
                "问题描述",
                placeholder="请描述破损、发错、规格不符或无法使用等情况",
                height=100,
            )
            contact_phone = st.text_input(
                "联系方式",
                value=employee.get("phone", ""),
            )
            submitted = st.form_submit_button("提交售后申请", type="primary")

        if submitted:
            try:
                after_sale = create_after_sale(
                    claim_id=claim["id"],
                    employee_id=employee["id"],
                    issue_type=issue_type,
                    expected_resolution=expected_resolution,
                    description=description,
                    contact_phone=contact_phone,
                )
                st.session_state["employee_feedback"] = (
                    f"售后申请已提交：{_format_after_sale_id(after_sale['id'])}"
                )
                st.session_state.pop("pending_after_sale_claim_id", None)
                st.rerun()
            except ValueError as exc:
                st.error(str(exc))

        if st.button("关闭", key=f"close_after_sale_dialog_{claim['id']}"):
            close_dialog()

    dialog = getattr(st, "dialog", None)
    if dialog:
        dialog("申请售后")(dialog_body)()
    else:
        with st.container(border=True):
            st.markdown("**申请售后**")
            dialog_body()


def _render_claim_card(
    claim: dict,
    employee: dict,
    after_sales_by_claim: dict[int, dict],
) -> None:
    status_label = CLAIM_STATUS_LABELS.get(claim["status"], claim["status"])
    with st.container(border=True):
        title_cols = st.columns([7, 1])
        with title_cols[0]:
            st.subheader(f"{claim['gift_name']} · {status_label}")
        with title_cols[1]:
            after_sale = after_sales_by_claim.get(claim["id"])
            if claim["status"] == "redeemed":
                if after_sale:
                    st.caption(f"售后：{_after_sale_status_label(after_sale['status'])}")
                elif st.button(
                    "申请售后",
                    key=f"apply_after_sale_{claim['id']}",
                    type="primary",
                    use_container_width=True,
                ):
                    _request_after_sale(claim["id"])

        st.write(f"活动：{claim['activity_name']}")
        st.write(f"领取人：{claim['employee_name']}（{claim['employee_no']}）")
        st.write(f"地点：{claim['building']}")
        time_label = (
            f"{claim['start_time']}-{claim['end_time']}"
            if claim.get("start_time") and claim.get("end_time")
            else "全天"
        )
        st.write(f"时间：{claim['slot_date']} {time_label}")
        st.code(claim["claim_code"], language=None)

        if claim["status"] == "reserved":
            qr_uri = demo_qr_svg_data_uri(claim["claim_code"])
            st.markdown(
                f'<img src="{qr_uri}" width="168" height="168" alt="领取凭证二维码模拟图">',
                unsafe_allow_html=True,
            )
            if st.button("取消预约", key=f"cancel_{claim['id']}"):
                result = cancel_claim(claim["id"], employee_id=claim["employee_id"])
                if result["ok"]:
                    st.session_state["employee_feedback"] = result["message"]
                    st.rerun()
                else:
                    st.error(result["message"])


def _render_benefit_section(employee: dict) -> None:
    st.subheader("我的可领活动")
    activities = list_employee_available_activities(employee["id"])
    if not activities:
        st.warning("暂无适用于你的已上线活动。")
        return

    latest = get_latest_activity()
    default_index = 0
    if latest:
        for index, item in enumerate(activities):
            if item["id"] == latest["id"]:
                default_index = index
                break

    activity = st.selectbox(
        "当前活动",
        activities,
        index=default_index,
        format_func=lambda item: f"{item['name']}（{item['start_date']} 至 {item['end_date']}）",
        key="employee_activity_selector",
    )

    claims = list_employee_claims(employee["id"])
    active_claim = next(
        (claim for claim in claims if claim["activity_id"] == activity["id"] and claim["status"] == "reserved"),
        None,
    )

    if active_claim:
        st.info("你已预约该活动。可在下方查看凭证或取消预约。")

    building_options = list_activity_buildings(activity["id"])
    if not building_options:
        st.warning("当前活动暂无可领取楼宇。")
        return

    building = st.selectbox(
        "选择领取办公楼",
        building_options,
        format_func=lambda item: item["name"],
        key="employee_building_selector",
        disabled=bool(active_claim),
    )
    _render_building_info(building)

    st.subheader("可领取礼物")
    gifts = list_eligible_gifts(employee["id"], activity["id"], building=building["name"])
    if not gifts:
        st.warning("当前楼宇暂无你可领取的礼物。")
    else:
        gift = st.selectbox(
            "选择礼物",
            gifts,
            format_func=lambda item: (
                f"{item['name']} · {item['category']} · 可用库存 {item['available_stock']}"
            ),
            key="gift_selector",
            disabled=bool(active_claim),
        )

        inventory_rows = list_inventory_for_gift(activity["id"], gift["id"])
        building_rows = [
            row
            for row in inventory_rows
            if row["building"] == building["name"] and row["available_stock"] > 0
        ]

        if not building_rows:
            st.error("该楼宇该礼物库存不足。")
        else:
            building_row = building_rows[0]
            st.caption(
                f"{building_row['building']} 可用 {building_row['available_stock']}，"
                f"已预约 {building_row['reserved_stock']}"
            )

            slots = [
                slot
                for slot in list_time_slots(activity["id"], building_row["building"])
                if slot["remaining"] > 0
            ]
            if not slots:
                st.error("该楼栋暂无可预约时间段。")
            else:
                slot = st.selectbox(
                    "选择领取时间段",
                    slots,
                    format_func=_format_slot,
                    key="slot_selector",
                    disabled=bool(active_claim),
                )

                if st.button("确认预约", type="primary", disabled=bool(active_claim)):
                    result = create_claim(
                        employee_id=employee["id"],
                        activity_id=activity["id"],
                        gift_id=gift["id"],
                        building=building_row["building"],
                        time_slot_id=slot["id"],
                    )
                    if result["ok"]:
                        st.session_state["employee_feedback"] = result["message"]
                        st.rerun()
                    else:
                        st.error(result["message"])


def _render_claims_section(employee: dict) -> None:
    st.subheader("我的领取记录")
    claims = list_employee_claims(employee["id"])
    if not claims:
        st.caption("暂无领取记录。")
    else:
        after_sales_by_claim = list_after_sales_by_claims([claim["id"] for claim in claims])
        for claim in claims:
            _render_claim_card(claim, employee, after_sales_by_claim)


def _render_after_sale_record(after_sale: dict, employee: dict) -> None:
    with st.container(border=True):
        title_cols = st.columns([4, 1])
        with title_cols[0]:
            st.subheader(
                f"{_format_after_sale_id(after_sale['id'])} · {_after_sale_status_label(after_sale['status'])}"
            )
        with title_cols[1]:
            if after_sale["status"] == "pending":
                if st.button(
                    "取消售后",
                    key=f"cancel_after_sale_{after_sale['id']}",
                ):
                    try:
                        cancel_after_sale(after_sale["id"], employee["id"])
                        st.session_state["employee_feedback"] = "售后申请已取消"
                        st.rerun()
                    except ValueError as exc:
                        st.error(str(exc))

        st.write(f"活动：{after_sale['activity_name']}")
        st.write(f"礼物：{after_sale['gift_name']}")
        st.write(f"售后类型：{_after_sale_issue_label(after_sale['issue_type'])}")
        st.write(f"期望处理：{_after_sale_resolution_label(after_sale['expected_resolution'])}")
        st.write(
            f"库存处理：{_after_sale_inventory_action_label(after_sale.get('inventory_action', 'none'))}"
        )
        if after_sale.get("admin_note"):
            st.write(f"管理员备注：{after_sale['admin_note']}")
        st.caption(f"提交时间：{after_sale['created_at']}")
        if after_sale.get("resolved_at"):
            st.caption(f"完成时间：{after_sale['resolved_at']}")


def _render_after_sales_section(employee: dict) -> None:
    st.subheader("我的售后记录")
    rows = list_after_sales_for_employee(employee["id"])
    if not rows:
        st.caption("暂无售后记录。")
        return

    for after_sale in rows:
        _render_after_sale_record(after_sale, employee)


def render() -> None:
    employee = _current_employee()
    if not employee:
        _render_login()
        return

    cols = st.columns([4, 1])
    with cols[0]:
        st.header("员工端")
        st.caption(_format_employee(employee))
    with cols[1]:
        st.write("")
        if st.button("退出登录", use_container_width=True):
            st.session_state.pop("employee_id", None)
            st.rerun()

    feedback = st.session_state.pop("employee_feedback", None)
    if feedback:
        st.success(feedback)

    _render_notification_center(employee)
    _render_after_sale_dialog(employee)

    benefit_tab, claims_tab, after_sales_tab = st.tabs(EMPLOYEE_SECTIONS)
    with benefit_tab:
        _render_benefit_section(employee)
    with claims_tab:
        _render_claims_section(employee)
    with after_sales_tab:
        _render_after_sales_section(employee)
