from __future__ import annotations

import streamlit as st

from config import CLAIM_STATUS_LABELS
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


def _render_claim_card(claim: dict) -> None:
    status_label = CLAIM_STATUS_LABELS.get(claim["status"], claim["status"])
    with st.container(border=True):
        st.subheader(f"{claim['gift_name']} · {status_label}")
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

    st.subheader("我的领取记录")
    claims = list_employee_claims(employee["id"])
    if not claims:
        st.caption("暂无领取记录。")
    else:
        for claim in claims:
            _render_claim_card(claim)
