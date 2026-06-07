from __future__ import annotations

import streamlit as st

from config import CLAIM_STATUS_LABELS
from services.activity_service import (
    get_latest_activity,
    list_activity_buildings,
    list_eligible_gifts,
    list_employee_claims,
    list_employees,
    list_inventory_for_gift,
    list_published_activities,
    list_time_slots,
)
from services.claim_service import cancel_claim, create_claim
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
                    st.success(result["message"])
                    st.rerun()
                else:
                    st.error(result["message"])


def render() -> None:
    st.header("员工端")

    employees = list_employees()
    if not employees:
        st.warning("暂无员工数据，请先初始化演示数据。")
        return

    employee = st.selectbox(
        "选择员工身份",
        employees,
        format_func=_format_employee,
        key="employee_selector",
    )

    activities = list_published_activities()
    if not activities:
        st.warning("暂无已发布活动，请在管理后台创建并发布活动。")
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
                        st.success(result["message"])
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
