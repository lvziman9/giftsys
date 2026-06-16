from seed_data import seed_demo_data
from services.after_sale_service import (
    create_after_sale,
    list_after_sales_for_admin,
    list_after_sales_for_employee,
    mark_after_sale_processing,
    resolve_after_sale,
)
from services.activity_service import (
    add_building,
    add_gift_to_activity,
    adjust_activity_inventory,
    authenticate_employee,
    dashboard_summary,
    delete_time_slot,
    list_activity_buildings,
    list_activity_gift_rules,
    list_admin_activities,
    list_buildings,
    list_day_schedule,
    list_eligible_gifts,
    list_employee_available_activities,
    list_employee_claims,
    list_employees,
    list_inventory_for_gift,
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
    update_building,
    update_time_slot,
)
from services.claim_service import cancel_claim, create_claim, redeem_claim_by_code
from services.nl_parser import parse_activity_text
from services.notification_service import (
    count_unread_notifications,
    list_notifications,
    respond_reschedule_notification,
)


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
        assert authenticate_employee(tech["employee_no"], tech["phone"][-4:])["id"] == tech["id"]
        assert authenticate_employee(tech["employee_no"], "0000") is None

        activity = list_published_activities()[0]
        assert activity["id"] in {
            item["id"]
            for item in list_employee_available_activities(tech["id"])
        }
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
        reserved_notification = _pick(
            list_notifications(tech["id"]),
            lambda item: item["type"] == "claim_reserved" and item["claim_id"] == claim["id"],
            "缺少预约成功通知",
        )
        assert not reserved_notification["is_read"]
        assert count_unread_notifications(tech["id"]) >= 1

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
        assert any(
            item["type"] == "claim_cancelled" and item["claim_id"] == claim["id"]
            for item in list_notifications(tech["id"])
        )
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
        reschedule_slots = list_reschedule_time_slots(
            second["claim"]["activity_id"],
            second["claim"]["building"],
            second["claim"]["slot_date"],
        )
        target_slot = _pick(
            reschedule_slots,
            lambda item: item["remaining"] > 0 and item["id"] != second["claim"]["time_slot_id"],
            "缺少可用于改期短信的目标时间段",
        )
        sms_result = send_reschedule_sms(
            second["claim"]["id"],
            target_slot["id"],
            admin_id=1,
        )
        assert sms_result["phone"] == tech["phone"]
        assert "建议改为" in sms_result["sms_content"]
        reschedule_notification = _pick(
            list_notifications(tech["id"]),
            lambda item: (
                item["type"] == "reschedule_request"
                and item["claim_id"] == second["claim"]["id"]
                and item["action_status"] == "pending"
            ),
            "缺少改期请求通知",
        )
        accepted = respond_reschedule_notification(
            reschedule_notification["id"],
            tech["id"],
            accepted=True,
        )
        assert accepted["ok"], accepted["message"]
        updated_claim = _pick(
            list_employee_claims(tech["id"]),
            lambda item: item["id"] == second["claim"]["id"],
            "缺少已改期预约",
        )
        assert updated_claim["time_slot_id"] == target_slot["id"]

        redeemed = redeem_claim_by_code(second["claim"]["claim_code"], admin_id=1)
        assert redeemed["ok"], redeemed["message"]
        assert any(
            item["type"] == "claim_redeemed" and item["claim_id"] == second["claim"]["id"]
            for item in list_notifications(tech["id"])
        )

        before_after_sale_inventory = _pick(
            list_inventory_for_gift(activity["id"], gift["id"]),
            lambda item: item["id"] == updated_claim["inventory_id"],
            "缺少售后测试库存",
        )
        after_sale = create_after_sale(
            claim_id=updated_claim["id"],
            employee_id=tech["id"],
            issue_type="damaged",
            expected_resolution="exchange",
            description="键帽破损，需要更换",
            contact_phone=tech["phone"],
        )
        assert after_sale["status"] == "pending"
        assert any(
            item["type"] == "after_sale_submitted" and item["claim_id"] == updated_claim["id"]
            for item in list_notifications(tech["id"])
        )
        assert any(item["id"] == after_sale["id"] for item in list_after_sales_for_employee(tech["id"]))
        mark_after_sale_processing(after_sale["id"], "已联系仓库准备换货", admin_id=1)
        resolved_after_sale = resolve_after_sale(
            after_sale["id"],
            inventory_action="exchange_scrap",
            admin_note="退回报废并重新发放",
            admin_id=1,
        )
        assert resolved_after_sale["status"] == "resolved"
        assert any(
            item["type"] == "after_sale_resolved" and item["claim_id"] == updated_claim["id"]
            for item in list_notifications(tech["id"])
        )
        assert any(
            item["id"] == after_sale["id"]
            for item in list_after_sales_for_admin(status="resolved")
        )
        after_after_sale_inventory = _pick(
            list_inventory_for_gift(activity["id"], gift["id"]),
            lambda item: item["id"] == updated_claim["inventory_id"],
            "缺少售后后库存",
        )
        assert (
            after_after_sale_inventory["available_stock"]
            == before_after_sale_inventory["available_stock"] - 1
        )
        assert (
            after_after_sale_inventory["redeemed_stock"]
            == before_after_sale_inventory["redeemed_stock"] + 1
        )
        try:
            create_after_sale(
                claim_id=updated_claim["id"],
                employee_id=tech["id"],
                issue_type="damaged",
                expected_resolution="exchange",
                description="重复提交",
                contact_phone=tech["phone"],
            )
        except ValueError:
            pass
        else:
            raise AssertionError("不应允许同一领取记录重复提交售后")

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
        assert any(
            item["type"] == "activity_published" and item["activity_id"] == parsed_activity_id
            for item in list_notifications(tech["id"])
        )
        parsed_tech_gifts = list_eligible_gifts(tech["id"], parsed_activity_id)
        parsed_tech_names = {gift["name"] for gift in parsed_tech_gifts}
        assert "机械键盘" in parsed_tech_names
        assert "零食大礼包" in parsed_tech_names
        parsed_slots = list_time_slots_for_admin(parsed_activity_id)
        assert len(parsed_slots) == 72
        assert any(item["id"] == parsed_activity_id for item in list_admin_activities())

        update_activity_basic(
            parsed_activity_id,
            name="2026 端午福利更新",
            description="延长一天",
            start_date="2026-06-08",
            end_date="2026-06-11",
            allow_cancel=True,
            expire_release=True,
            admin_id=1,
        )
        assert len(list_time_slots_for_admin(parsed_activity_id)) == 96

        update_activity_basic(
            parsed_activity_id,
            name="2026 端午福利更新",
            description="缩短到两天",
            start_date="2026-06-08",
            end_date="2026-06-09",
            allow_cancel=True,
            expire_release=True,
            admin_id=1,
        )
        assert len(list_time_slots_for_admin(parsed_activity_id)) == 48

        added_gift_id = add_gift_to_activity(
            parsed_activity_id,
            {
                "name": "保温杯",
                "department": "全员",
                "total_stock": 12,
                "description": "不锈钢保温杯",
                "building_allocation": {"A楼": 50, "B楼": 30, "C楼": 20},
            },
            admin_id=1,
        )
        assert added_gift_id
        assert "保温杯" in {
            gift["name"]
            for gift in list_activity_gift_rules(parsed_activity_id)
        }
        tumbler_inventory = _pick(
            list_inventory_for_gift(parsed_activity_id, added_gift_id),
            lambda item: item["building"] == "A楼",
            "缺少保温杯 A楼库存",
        )
        increased = adjust_activity_inventory(
            tumbler_inventory["id"],
            adjustment_type="increase",
            quantity=3,
            reason="测试补充库存",
            admin_id=1,
        )
        assert increased["available_stock"] == tumbler_inventory["available_stock"] + 3
        decreased = adjust_activity_inventory(
            tumbler_inventory["id"],
            adjustment_type="decrease",
            quantity=2,
            reason="测试减少库存",
            admin_id=1,
        )
        assert decreased["available_stock"] == increased["available_stock"] - 2
        try:
            adjust_activity_inventory(
                tumbler_inventory["id"],
                adjustment_type="decrease",
                quantity=decreased["available_stock"] + 1,
                reason="超过可用库存",
                admin_id=1,
            )
        except ValueError:
            pass
        else:
            raise AssertionError("不应允许减少超过可用库存的数量")

        set_activity_status(parsed_activity_id, "offline", admin_id=1)
        assert parsed_activity_id not in {
            item["id"]
            for item in list_published_activities()
        }
        offline_gift = _pick(
            list_eligible_gifts(tech["id"], parsed_activity_id),
            lambda item: item["name"] == "保温杯",
            "缺少增发保温杯",
        )
        offline_inventory = _pick(
            list_inventory_for_gift(parsed_activity_id, offline_gift["id"]),
            lambda item: item["available_stock"] > 0,
            "保温杯没有可用库存",
        )
        offline_slot = _pick(
            list_time_slots(parsed_activity_id, offline_inventory["building"]),
            lambda item: item["remaining"] > 0,
            "下线活动缺少可测试时间段",
        )
        offline_claim = create_claim(
            employee_id=tech["id"],
            activity_id=parsed_activity_id,
            gift_id=offline_gift["id"],
            building=offline_inventory["building"],
            time_slot_id=offline_slot["id"],
        )
        assert not offline_claim["ok"]
        set_activity_status(parsed_activity_id, "published", admin_id=1)
        assert parsed_activity_id in {
            item["id"]
            for item in list_published_activities()
        }

        try:
            update_activity_basic(
                activity["id"],
                name=activity["name"],
                description=activity["description"],
                start_date="2026-06-09",
                end_date=activity["end_date"],
                allow_cancel=True,
                expire_release=True,
                admin_id=1,
            )
        except ValueError:
            pass
        else:
            raise AssertionError("不应允许缩短已有预约记录的活动日期")

        a_building = _pick(list_buildings(), lambda item: item["name"] == "A楼", "缺少 A楼")
        assert a_building["address"]
        assert a_building["manager_name"]

        add_building("D楼")
        d_building = _pick(list_buildings(), lambda item: item["name"] == "D楼", "缺少 D楼")
        update_building(
            d_building["id"],
            address="上海市浦东新区世纪大道 400 号",
            pickup_location="2层行政服务台",
            manager_name="吴迪",
            manager_contact="13800001004",
            backup_manager="周晴",
            note="测试新增楼宇",
            sort_order=4,
            is_active=True,
            admin_id=1,
        )
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
        activity_buildings = list_activity_buildings(rule_activity_id)
        d_activity_building = _pick(
            activity_buildings,
            lambda item: item["name"] == "D楼",
            "活动楼宇缺少 D楼",
        )
        assert d_activity_building["pickup_location"] == "2层行政服务台"

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
