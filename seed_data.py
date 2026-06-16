from __future__ import annotations

from datetime import date, timedelta

from config import ADMIN_PASSWORD, BUILDINGS, DEFAULT_SLOT_CAPACITY, DEFAULT_TIME_RANGES
from database import get_connection, init_db


DEMO_BUILDINGS = {
    "A楼": {
        "address": "上海市浦东新区世纪大道 100 号",
        "pickup_location": "1层行政前台",
        "manager_name": "周晴",
        "manager_contact": "13800001001",
        "backup_manager": "陈宇",
        "note": "工作日 10:00-18:30 可领取，需携带工牌。",
        "sort_order": 1,
    },
    "B楼": {
        "address": "上海市浦东新区世纪大道 200 号",
        "pickup_location": "3层行政服务台",
        "manager_name": "林浩",
        "manager_contact": "13800001002",
        "backup_manager": "赵琪",
        "note": "午休时段可在 12:00-12:30 领取。",
        "sort_order": 2,
    },
    "C楼": {
        "address": "上海市浦东新区世纪大道 300 号",
        "pickup_location": "B1 仓储发放点",
        "manager_name": "许安",
        "manager_contact": "13800001003",
        "backup_manager": "李娜",
        "note": "进入仓储区需由负责人带领。",
        "sort_order": 3,
    },
}


def _clear_all(conn) -> None:
    tables = [
        "inventory_logs",
        "operation_logs",
        "notifications",
        "after_sales",
        "claims",
        "time_slots",
        "inventory",
        "eligibility_rules",
        "gifts",
        "activities",
        "admins",
        "employees",
        "buildings",
    ]
    for table in tables:
        conn.execute(f"DELETE FROM {table}")
    conn.execute("DELETE FROM sqlite_sequence")


def _ensure_buildings(conn) -> None:
    for building in BUILDINGS:
        profile = DEMO_BUILDINGS.get(building, {})
        conn.execute(
            """
            INSERT INTO buildings (
                name, address, pickup_location, manager_name, manager_contact,
                backup_manager, note, sort_order, is_active, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, CURRENT_TIMESTAMP)
            ON CONFLICT(name) DO UPDATE SET
                address = CASE
                    WHEN buildings.address = '' THEN excluded.address
                    ELSE buildings.address
                END,
                pickup_location = CASE
                    WHEN buildings.pickup_location = '' THEN excluded.pickup_location
                    ELSE buildings.pickup_location
                END,
                manager_name = CASE
                    WHEN buildings.manager_name = '' THEN excluded.manager_name
                    ELSE buildings.manager_name
                END,
                manager_contact = CASE
                    WHEN buildings.manager_contact = '' THEN excluded.manager_contact
                    ELSE buildings.manager_contact
                END,
                backup_manager = CASE
                    WHEN buildings.backup_manager = '' THEN excluded.backup_manager
                    ELSE buildings.backup_manager
                END,
                note = CASE
                    WHEN buildings.note = '' THEN excluded.note
                    ELSE buildings.note
                END,
                sort_order = CASE
                    WHEN buildings.sort_order = 0 THEN excluded.sort_order
                    ELSE buildings.sort_order
                END
            """,
            (
                building,
                profile.get("address", ""),
                profile.get("pickup_location", ""),
                profile.get("manager_name", ""),
                profile.get("manager_contact", ""),
                profile.get("backup_manager", ""),
                profile.get("note", ""),
                int(profile.get("sort_order", 0)),
            ),
        )


def _allocate_stock(total_stock: int, allocations: dict[str, int]) -> dict[str, int]:
    buildings = list(allocations.keys())
    total_weight = sum(allocations.values()) or len(buildings)
    result: dict[str, int] = {}
    used = 0

    for building in buildings[:-1]:
        qty = int(total_stock * allocations[building] / total_weight)
        result[building] = qty
        used += qty

    result[buildings[-1]] = total_stock - used
    return result


def seed_demo_data(force: bool = False) -> None:
    init_db()

    with get_connection() as conn:
        _ensure_buildings(conn)
        existing = conn.execute("SELECT COUNT(*) AS count FROM activities").fetchone()["count"]
        if existing and not force:
            return

        if force:
            _clear_all(conn)
            _ensure_buildings(conn)

        employees = [
            ("E1001", "张晨", "技术部", "P6", "13800000001"),
            ("E1002", "李娜", "销售部", "P5", "13800000002"),
            ("E1003", "王敏", "职能部", "P4", "13800000003"),
            ("E1004", "陈宇", "技术部", "P7", "13800000004"),
            ("E1005", "赵琪", "运营部", "P5", "13800000005"),
            ("E1006", "刘洋", "技术部", "P5", "13800000006"),
            ("E1007", "孙雨", "销售部", "P6", "13800000007"),
            ("E1008", "周宁", "职能部", "P5", "13800000008"),
            ("E1009", "吴迪", "运营部", "P4", "13800000009"),
            ("E1010", "何佳", "财务部", "P6", "13800000010"),
        ]
        conn.executemany(
            """
            INSERT INTO employees (employee_no, name, department, level, phone)
            VALUES (?, ?, ?, ?, ?)
            """,
            employees,
        )

        conn.execute(
            """
            INSERT INTO admins (username, password, display_name)
            VALUES (?, ?, ?)
            """,
            ("admin", ADMIN_PASSWORD, "行政管理员"),
        )

        activity_id = conn.execute(
            """
            INSERT INTO activities (
                name, activity_type, description, start_date, end_date, status,
                allow_cancel, expire_release, published_at
            )
            VALUES (?, ?, ?, ?, ?, 'published', 1, 1, CURRENT_TIMESTAMP)
            """,
            (
                "2026 端午福利",
                "节日福利",
                "演示用活动：技术部可选键盘或耳机，销售部可领购物卡，全员可领零食礼包。",
                "2026-06-08",
                "2026-06-12",
            ),
        ).lastrowid

        gift_specs = [
            ("机械键盘", "87 键无线机械键盘", "数码类", 30),
            ("降噪耳机", "头戴式主动降噪耳机", "数码类", 20),
            ("500元购物卡", "通用购物卡，面值 500 元", "生活用品类", 40),
            ("零食大礼包", "节日零食组合装", "零食类", 100),
        ]
        gift_ids: dict[str, int] = {}
        for name, spec, category, total_stock in gift_specs:
            gift_ids[name] = conn.execute(
                """
                INSERT INTO gifts (activity_id, name, spec, category, total_stock)
                VALUES (?, ?, ?, ?, ?)
                """,
                (activity_id, name, spec, category, total_stock),
            ).lastrowid

        rules = {
            "技术部": ["机械键盘", "降噪耳机"],
            "销售部": ["500元购物卡"],
            "ALL": ["零食大礼包"],
        }
        for department, gift_names in rules.items():
            for gift_name in gift_names:
                conn.execute(
                    """
                    INSERT INTO eligibility_rules (activity_id, department, gift_id)
                    VALUES (?, ?, ?)
                    """,
                    (activity_id, department, gift_ids[gift_name]),
                )

        allocations = {"A楼": 50, "B楼": 30, "C楼": 20}
        for gift_name, gift_id in gift_ids.items():
            total_stock = next(item[3] for item in gift_specs if item[0] == gift_name)
            per_building = _allocate_stock(total_stock, allocations)
            for building in BUILDINGS:
                qty = per_building.get(building, 0)
                conn.execute(
                    """
                    INSERT INTO inventory (
                        activity_id, gift_id, building, total_stock, available_stock
                    )
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (activity_id, gift_id, building, qty, qty),
                )

        first_slot_date = date(2026, 6, 8)
        slot_dates = [(first_slot_date + timedelta(days=offset)).isoformat() for offset in range(5)]
        for building in BUILDINGS:
            for slot_date in slot_dates:
                for start_time, end_time in DEFAULT_TIME_RANGES:
                    conn.execute(
                        """
                        INSERT INTO time_slots (
                            activity_id, building, slot_date, start_time, end_time, capacity
                        )
                        VALUES (?, ?, ?, ?, ?, ?)
                        """,
                        (
                            activity_id,
                            building,
                            slot_date,
                            start_time,
                            end_time,
                            DEFAULT_SLOT_CAPACITY,
                        ),
                    )

        conn.execute(
            """
            INSERT INTO operation_logs (action, target_type, target_id, note)
            VALUES ('seed_demo_data', 'activity', ?, '初始化演示活动和基础数据')
            """,
            (activity_id,),
        )


if __name__ == "__main__":
    seed_demo_data(force=True)
    print("Sample data seeded.")
