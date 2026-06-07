from seed_data import seed_demo_data
from services.activity_service import (
    add_building,
    dashboard_summary,
    delete_time_slot,
    list_buildings,
    list_day_schedule,
    list_eligible_gifts,
    list_employees,
    list_inventory_for_gift,
    list_published_activities,
    list_schedule_calendar_counts,
    list_time_slots,
    list_time_slots_for_admin,
    publish_activity_from_config,
    publish_time_slot,
    set_time_slot_availability,
    update_time_slot,
)
from services.claim_service import cancel_claim, create_claim, redeem_claim_by_code
from services.nl_parser import parse_activity_text


def _pick(items, predicate, message):
    for item in items:
        if predicate(item):
            return item
    raise AssertionError(message)


def main() -> None:
    seed_demo_data(force=True)

    try:
        employees = list_employees()
        tech = _pick(employees, lambda item: item["department"] == "技术部", "缺少技术部员工")
        sales = _pick(employees, lambda item: item["department"] == "销售部", "缺少销售部员工")

        activity = list_published_activities()[0]
        tech_gifts = list_eligible_gifts(tech["id"], activity["id"])
        sales_gifts = list_eligible_gifts(sales["id"], activity["id"])

        tech_names = {gift["name"] for gift in tech_gifts}
        sales_names = {gift["name"] for gift in sales_gifts}
        assert "机械键盘" in tech_names
        assert "降噪耳机" in tech_names
        assert "零食大礼包" in tech_names
        assert "500元购物卡" in sales_names
        assert "机械键盘" not in sales_names

        gift = _pick(tech_gifts, lambda item: item["name"] == "机械键盘", "缺少机械键盘")
        inventory = _pick(
            list_inventory_for_gift(activity["id"], gift["id"]),
            lambda item: item["available_stock"] > 0,
            "机械键盘没有可用库存",
        )
        slot = _pick(
            list_time_slots(activity["id"], inventory["building"]),
            lambda item: item["remaining"] > 0,
            "没有可用时间段",
        )

        first = create_claim(
            employee_id=tech["id"],
            activity_id=activity["id"],
            gift_id=gift["id"],
            building=inventory["building"],
            time_slot_id=slot["id"],
        )
        assert first["ok"], first["message"]
        claim = first["claim"]

        duplicate = create_claim(
            employee_id=tech["id"],
            activity_id=activity["id"],
            gift_id=gift["id"],
            building=inventory["building"],
            time_slot_id=slot["id"],
        )
        assert not duplicate["ok"]

        summary = dashboard_summary(activity["id"])
        assert summary["reserved_claims"] == 1

        cancelled = cancel_claim(claim["id"], employee_id=tech["id"])
        assert cancelled["ok"], cancelled["message"]
        summary = dashboard_summary(activity["id"])
        assert summary["cancelled_claims"] == 1

        second = create_claim(
            employee_id=tech["id"],
            activity_id=activity["id"],
            gift_id=gift["id"],
            building=inventory["building"],
            time_slot_id=slot["id"],
        )
        assert second["ok"], second["message"]
        redeemed = redeem_claim_by_code(second["claim"]["claim_code"], admin_id=1)
        assert redeemed["ok"], redeemed["message"]

        repeated = redeem_claim_by_code(second["claim"]["claim_code"], admin_id=1)
        assert not repeated["ok"]

        summary = dashboard_summary(activity["id"])
        assert summary["redeemed_claims"] == 1
        day_schedule = list_day_schedule(slot["slot_date"])
        assert any(
            claim["claim_code"] == second["claim"]["claim_code"]
            for schedule_slot in day_schedule
            for claim in schedule_slot["claims"]
        )
        calendar_counts = list_schedule_calendar_counts(2026, 6)
        assert slot["slot_date"] in calendar_counts

        draft = parse_activity_text(
            "2026年端午福利，技术部可选机械键盘或降噪耳机，销售部领取500元购物卡，"
            "全员可领零食大礼包。A楼分配50%，B楼30%，C楼20%。"
            "活动日期为6月8日到6月10日。"
        )
        parsed_rules = {
            (rule["department"], rule["name"])
            for rule in draft["gift_rules"]
        }
        assert ("技术部", "机械键盘") in parsed_rules
        assert ("技术部", "降噪耳机") in parsed_rules
        assert ("销售部", "500元购物卡") in parsed_rules
        assert ("全员", "零食大礼包") in parsed_rules

        parsed_activity_id = publish_activity_from_config(draft, admin_id=1)
        parsed_tech_gifts = list_eligible_gifts(tech["id"], parsed_activity_id)
        parsed_tech_names = {gift["name"] for gift in parsed_tech_gifts}
        assert "机械键盘" in parsed_tech_names
        assert "零食大礼包" in parsed_tech_names
        parsed_slots = list_time_slots_for_admin(parsed_activity_id)
        assert len(parsed_slots) == 72

        add_building("D楼")
        building_names = [building["name"] for building in list_buildings()]
        assert "D楼" in building_names

        rule_activity_id = publish_activity_from_config(
            {
                "activity": {
                    "name": "规则行配置活动",
                    "activity_type": "节日福利",
                    "description": "测试礼物规则行和楼宇分配",
                    "start_date": "2026-06-11",
                    "end_date": "2026-06-11",
                    "allow_cancel": True,
                    "expire_release": True,
                },
                "gift_rules": [
                    {
                        "name": "测试礼物",
                        "department": "技术部",
                        "total_stock": 10,
                        "description": "用于验证楼宇过滤",
                        "building_allocation": {"A楼": 50, "B楼": 30, "C楼": 20, "D楼": 0},
                        "per_person_limit": 1,
                    }
                ],
            },
            admin_id=1,
        )
        admin_slots = list_time_slots_for_admin(rule_activity_id)
        assert len(admin_slots) == 32

        updated_slots = publish_time_slot(
            activity_id=rule_activity_id,
            slot_date="2026-06-11",
            start_time="11:00",
            end_time="12:00",
            capacity=10,
            building=None,
            admin_id=1,
        )
        assert updated_slots == 4
        admin_slots = list_time_slots_for_admin(rule_activity_id)
        assert len(admin_slots) == 32

        editable_slot = _pick(
            admin_slots,
            lambda item: item["building"] == "A楼" and item["start_time"] == "10:00",
            "缺少可编辑时间段",
        )
        update_time_slot(editable_slot["id"], capacity=12, is_available=True, admin_id=1)
        updated_slot = _pick(
            list_time_slots_for_admin(rule_activity_id),
            lambda item: item["id"] == editable_slot["id"],
            "缺少已更新时间段",
        )
        assert updated_slot["capacity"] == 12

        set_time_slot_availability(updated_slot["id"], False, admin_id=1)
        available_slots = list_time_slots(rule_activity_id, updated_slot["building"])
        assert all(slot["id"] != updated_slot["id"] for slot in available_slots)

        deletable_slot = _pick(
            list_time_slots_for_admin(rule_activity_id),
            lambda item: item["building"] == "D楼" and item["start_time"] == "18:00",
            "缺少可删除时间段",
        )
        delete_time_slot(deletable_slot["id"], admin_id=1)
        assert all(
            slot["id"] != deletable_slot["id"]
            for slot in list_time_slots_for_admin(rule_activity_id)
        )

        a_building_gifts = list_eligible_gifts(tech["id"], rule_activity_id, building="A楼")
        d_building_gifts = list_eligible_gifts(tech["id"], rule_activity_id, building="D楼")
        assert "测试礼物" in {gift["name"] for gift in a_building_gifts}
        assert "测试礼物" not in {gift["name"] for gift in d_building_gifts}

        print("Smoke test passed.")
    finally:
        seed_demo_data(force=True)


if __name__ == "__main__":
    main()
