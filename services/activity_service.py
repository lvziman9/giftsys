from __future__ import annotations

from calendar import monthrange
from datetime import date, datetime, timedelta
from typing import Any

from config import ADMIN_PASSWORD, BUILDINGS, DEFAULT_SLOT_CAPACITY, DEFAULT_TIME_RANGES
from database import fetch_all, fetch_one, get_connection, row_to_dict, rows_to_dicts


def list_employees() -> list[dict[str, Any]]:
    return fetch_all(
        """
        SELECT *
        FROM employees
        ORDER BY department, employee_no
        """
    )


def list_departments() -> list[str]:
    rows = fetch_all(
        """
        SELECT DISTINCT department
        FROM employees
        WHERE department IS NOT NULL AND department != ''
        ORDER BY department
        """
    )
    return [row["department"] for row in rows]


def list_buildings(active_only: bool = True) -> list[dict[str, Any]]:
    where = "WHERE is_active = 1" if active_only else ""
    return fetch_all(
        f"""
        SELECT *
        FROM buildings
        {where}
        ORDER BY id
        """
    )


def add_building(name: str) -> dict[str, Any]:
    building_name = name.strip()
    if not building_name:
        raise ValueError("楼宇名称不能为空")

    with get_connection() as conn:
        conn.execute(
            """
            INSERT OR IGNORE INTO buildings (name, is_active)
            VALUES (?, 1)
            """,
            (building_name,),
        )
    return fetch_one("SELECT * FROM buildings WHERE name = ?", (building_name,)) or {}


def list_activity_buildings(activity_id: int) -> list[dict[str, Any]]:
    return fetch_all(
        """
        SELECT DISTINCT i.building AS name
        FROM inventory i
        WHERE i.activity_id = ?
        ORDER BY i.building
        """,
        (activity_id,),
    )


def get_employee(employee_id: int) -> dict[str, Any] | None:
    return fetch_one("SELECT * FROM employees WHERE id = ?", (employee_id,))


def authenticate_admin(password: str) -> dict[str, Any] | None:
    if password != ADMIN_PASSWORD:
        return None
    return fetch_one("SELECT * FROM admins ORDER BY id LIMIT 1")


def list_published_activities() -> list[dict[str, Any]]:
    return fetch_all(
        """
        SELECT *
        FROM activities
        WHERE status = 'published'
        ORDER BY published_at DESC, id DESC
        """
    )


def get_activity(activity_id: int) -> dict[str, Any] | None:
    return fetch_one("SELECT * FROM activities WHERE id = ?", (activity_id,))


def get_latest_activity() -> dict[str, Any] | None:
    activities = list_published_activities()
    return activities[0] if activities else None


def _parse_config_date(value: Any, label: str) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value

    raw = str(value or "").strip()
    if not raw:
        raise ValueError(f"{label}不能为空")

    for fmt in ("%Y-%m-%d", "%Y/%m/%d"):
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue

    raise ValueError(f"{label}格式需为 yyyy/mm/dd")


def _date_range(start_value: Any, end_value: Any) -> list[date]:
    start = _parse_config_date(start_value, "开始日期")
    end = _parse_config_date(end_value, "结束日期")
    if start > end:
        raise ValueError("开始日期不能晚于结束日期")

    days = (end - start).days
    return [start + timedelta(days=offset) for offset in range(days + 1)]


def activity_date_options(activity: dict[str, Any]) -> list[str]:
    return [item.isoformat() for item in _date_range(activity["start_date"], activity["end_date"])]


def _normalize_date(value: Any, label: str) -> str:
    return _parse_config_date(value, label).isoformat()


def _default_time_slots(start_date: str, end_date: str) -> list[dict[str, Any]]:
    slots: list[dict[str, Any]] = []
    for slot_date in _date_range(start_date, end_date):
        for start_time, end_time in DEFAULT_TIME_RANGES:
            slots.append(
                {
                    "date": slot_date.isoformat(),
                    "start_time": start_time,
                    "end_time": end_time,
                    "capacity": DEFAULT_SLOT_CAPACITY,
                }
            )
    return slots


def list_eligible_gifts(
    employee_id: int,
    activity_id: int,
    building: str | None = None,
) -> list[dict[str, Any]]:
    employee = get_employee(employee_id)
    if not employee:
        return []

    if building:
        return fetch_all(
            """
            SELECT
                g.*,
                COALESCE(SUM(i.total_stock), 0) AS inventory_total,
                COALESCE(SUM(i.available_stock), 0) AS available_stock,
                COALESCE(SUM(i.reserved_stock), 0) AS reserved_stock,
                COALESCE(SUM(i.redeemed_stock), 0) AS redeemed_stock
            FROM gifts g
            JOIN eligibility_rules er ON er.gift_id = g.id
            JOIN inventory i
              ON i.gift_id = g.id
             AND i.activity_id = g.activity_id
             AND i.building = ?
            WHERE g.activity_id = ?
              AND er.activity_id = ?
              AND (er.department = ? OR er.department = 'ALL')
            GROUP BY g.id
            HAVING COALESCE(SUM(i.total_stock), 0) > 0
            ORDER BY g.name
            """,
            (building, activity_id, activity_id, employee["department"]),
        )

    return fetch_all(
        """
        SELECT
            g.*,
            COALESCE(SUM(i.total_stock), 0) AS inventory_total,
            COALESCE(SUM(i.available_stock), 0) AS available_stock,
            COALESCE(SUM(i.reserved_stock), 0) AS reserved_stock,
            COALESCE(SUM(i.redeemed_stock), 0) AS redeemed_stock
        FROM gifts g
        JOIN eligibility_rules er ON er.gift_id = g.id
        LEFT JOIN inventory i ON i.gift_id = g.id
        WHERE g.activity_id = ?
          AND er.activity_id = ?
          AND (er.department = ? OR er.department = 'ALL')
        GROUP BY g.id
        ORDER BY g.name
        """,
        (activity_id, activity_id, employee["department"]),
    )


def list_inventory_for_gift(activity_id: int, gift_id: int) -> list[dict[str, Any]]:
    return fetch_all(
        """
        SELECT i.*, g.name AS gift_name
        FROM inventory i
        JOIN gifts g ON g.id = i.gift_id
        WHERE i.activity_id = ? AND i.gift_id = ?
        ORDER BY i.building
        """,
        (activity_id, gift_id),
    )


def list_time_slots(activity_id: int, building: str) -> list[dict[str, Any]]:
    return fetch_all(
        """
        SELECT *,
               capacity - reserved_count AS remaining
        FROM time_slots
        WHERE activity_id = ?
          AND building = ?
          AND is_available = 1
        ORDER BY slot_date, start_time
        """,
        (activity_id, building),
    )


def list_time_slots_for_admin(
    activity_id: int | None = None,
    slot_date: str | None = None,
) -> list[dict[str, Any]]:
    params: list[Any] = []
    where_parts: list[str] = []
    if activity_id:
        where_parts.append("t.activity_id = ?")
        params.append(activity_id)
    if slot_date:
        where_parts.append("t.slot_date = ?")
        params.append(_normalize_date(slot_date, "领取日期"))

    where = f"WHERE {' AND '.join(where_parts)}" if where_parts else ""

    return fetch_all(
        f"""
        SELECT
            t.*,
            a.name AS activity_name,
            t.capacity - t.reserved_count AS remaining
        FROM time_slots t
        JOIN activities a ON a.id = t.activity_id
        {where}
        ORDER BY t.slot_date, t.building DESC, t.start_time, t.end_time
        """,
        tuple(params),
    )


def list_employee_claims(employee_id: int) -> list[dict[str, Any]]:
    return fetch_all(
        """
        SELECT
            c.*,
            a.name AS activity_name,
            g.name AS gift_name,
            g.spec AS gift_spec,
            e.name AS employee_name,
            e.employee_no,
            t.slot_date,
            t.start_time,
            t.end_time
        FROM claims c
        JOIN activities a ON a.id = c.activity_id
        JOIN gifts g ON g.id = c.gift_id
        JOIN employees e ON e.id = c.employee_id
        JOIN time_slots t ON t.id = c.time_slot_id
        WHERE c.employee_id = ?
        ORDER BY c.id DESC
        """,
        (employee_id,),
    )


def list_claims_for_admin(activity_id: int | None = None) -> list[dict[str, Any]]:
    params: tuple[Any, ...] = ()
    where = ""
    if activity_id:
        where = "WHERE c.activity_id = ?"
        params = (activity_id,)

    return fetch_all(
        f"""
        SELECT
            c.*,
            a.name AS activity_name,
            g.name AS gift_name,
            e.name AS employee_name,
            e.employee_no,
            e.department,
            t.slot_date,
            t.start_time,
            t.end_time
        FROM claims c
        JOIN activities a ON a.id = c.activity_id
        JOIN gifts g ON g.id = c.gift_id
        JOIN employees e ON e.id = c.employee_id
        JOIN time_slots t ON t.id = c.time_slot_id
        {where}
        ORDER BY c.id DESC
        """,
        params,
    )


def list_inventory_rows(activity_id: int | None = None) -> list[dict[str, Any]]:
    params: tuple[Any, ...] = ()
    where = ""
    if activity_id:
        where = "WHERE i.activity_id = ?"
        params = (activity_id,)

    return fetch_all(
        f"""
        SELECT
            i.*,
            a.name AS activity_name,
            g.name AS gift_name,
            g.category
        FROM inventory i
        JOIN activities a ON a.id = i.activity_id
        JOIN gifts g ON g.id = i.gift_id
        {where}
        ORDER BY a.id DESC, g.name, i.building
        """,
        params,
    )


def dashboard_summary(activity_id: int | None = None) -> dict[str, Any]:
    params: tuple[Any, ...] = ()
    claim_where = ""
    inv_where = ""
    if activity_id:
        params = (activity_id,)
        claim_where = "WHERE activity_id = ?"
        inv_where = "WHERE activity_id = ?"

    claims = fetch_all(
        f"""
        SELECT status, COUNT(*) AS count
        FROM claims
        {claim_where}
        GROUP BY status
        """,
        params,
    )
    inventory = fetch_one(
        f"""
        SELECT
            COALESCE(SUM(total_stock), 0) AS total_stock,
            COALESCE(SUM(available_stock), 0) AS available_stock,
            COALESCE(SUM(reserved_stock), 0) AS reserved_stock,
            COALESCE(SUM(redeemed_stock), 0) AS redeemed_stock,
            COALESCE(SUM(released_stock), 0) AS released_stock
        FROM inventory
        {inv_where}
        """,
        params,
    )
    claim_counts = {row["status"]: row["count"] for row in claims}
    return {
        "claims": claim_counts,
        "inventory": inventory or {},
        "reserved_claims": claim_counts.get("reserved", 0),
        "redeemed_claims": claim_counts.get("redeemed", 0),
        "cancelled_claims": claim_counts.get("cancelled", 0),
        "expired_claims": claim_counts.get("expired", 0),
    }


def _allocate_stock(total_stock: int, allocations: dict[str, int]) -> dict[str, int]:
    if not allocations:
        allocations = {building: 1 for building in BUILDINGS}

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


def _normalize_name(value: str) -> str:
    return value.strip().replace("，", "").replace("。", "")


def _normalize_department(value: str) -> str:
    department = value.strip()
    if department in {"全员", "ALL", "all"}:
        return "ALL"
    return department


def _active_building_names(conn) -> list[str]:
    rows = conn.execute(
        """
        SELECT name
        FROM buildings
        WHERE is_active = 1
        ORDER BY id
        """
    ).fetchall()
    return [row["name"] for row in rows]


def _allocation_for_buildings(raw: dict[str, Any], buildings: list[str]) -> dict[str, int]:
    if not buildings:
        raise ValueError("至少需要配置一个楼宇")

    if not raw:
        base = 100 // len(buildings)
        allocation = {building: base for building in buildings}
        allocation[buildings[-1]] += 100 - sum(allocation.values())
        return allocation

    allocation = {building: int(raw.get(building, 0)) for building in buildings}
    if sum(allocation.values()) != 100:
        raise ValueError("每个礼物的楼宇分配比例合计必须等于 100%")
    return allocation


def publish_activity_from_config(config: dict[str, Any], admin_id: int | None = None) -> int:
    activity = config["activity"]
    gift_rules = config.get("gift_rules") or []
    gifts = config.get("gifts") or []
    eligibility = config.get("eligibility") or {}
    allocations = config.get("inventory_allocation") or {}

    if not activity.get("name"):
        raise ValueError("活动名称不能为空")
    start_date = _normalize_date(activity.get("start_date"), "开始日期")
    end_date = _normalize_date(activity.get("end_date"), "结束日期")
    time_slots = config.get("time_slots") or _default_time_slots(start_date, end_date)
    if not gift_rules and not gifts:
        raise ValueError("至少需要配置一个礼物")
    if not gift_rules and not eligibility:
        raise ValueError("至少需要配置一条资格规则")
    if not gift_rules and not allocations:
        raise ValueError("至少需要配置一个楼栋库存分配")
    with get_connection() as conn:
        active_buildings = _active_building_names(conn)
        activity_id = conn.execute(
            """
            INSERT INTO activities (
                name, activity_type, description, start_date, end_date, status,
                allow_cancel, expire_release, published_at
            )
            VALUES (?, ?, ?, ?, ?, 'published', ?, ?, CURRENT_TIMESTAMP)
            """,
            (
                activity["name"],
                activity.get("activity_type", "节日福利"),
                activity.get("description", ""),
                start_date,
                end_date,
                1 if activity.get("allow_cancel", True) else 0,
                1 if activity.get("expire_release", True) else 0,
            ),
        ).lastrowid

        if gift_rules:
            for rule in gift_rules:
                gift_name = _normalize_name(rule.get("name", ""))
                department = _normalize_department(rule.get("department", ""))
                total_stock = int(rule.get("total_stock", 0))
                description = rule.get("description", "").strip()
                if not gift_name:
                    raise ValueError("礼物名称不能为空")
                if not department:
                    raise ValueError("礼物所属部门不能为空")
                if total_stock <= 0:
                    raise ValueError("礼物初始数量必须大于 0")

                allocation = _allocation_for_buildings(
                    rule.get("building_allocation") or {},
                    active_buildings,
                )
                gift_id = conn.execute(
                    """
                    INSERT INTO gifts (
                        activity_id, name, spec, category, total_stock, per_person_limit
                    )
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        activity_id,
                        gift_name,
                        description or "Demo 配置礼物",
                        "其他",
                        total_stock,
                        int(rule.get("per_person_limit", 1)),
                    ),
                ).lastrowid
                conn.execute(
                    """
                    INSERT INTO eligibility_rules (activity_id, department, gift_id)
                    VALUES (?, ?, ?)
                    """,
                    (activity_id, department, gift_id),
                )

                per_building = _allocate_stock(total_stock, allocation)
                for building, qty in per_building.items():
                    conn.execute(
                        """
                        INSERT INTO inventory (
                            activity_id, gift_id, building, total_stock, available_stock
                        )
                        VALUES (?, ?, ?, ?, ?)
                        """,
                        (activity_id, gift_id, building, qty, qty),
                    )

            _insert_time_slots(conn, activity_id, active_buildings, time_slots)

            conn.execute(
                """
                INSERT INTO operation_logs (admin_id, action, target_type, target_id, note)
                VALUES (?, 'publish_activity', 'activity', ?, ?)
                """,
                (admin_id, activity_id, "通过礼物规则配置发布活动"),
            )
            return activity_id

        gift_name_to_id: dict[str, int] = {}
        for gift in gifts:
            gift_name = _normalize_name(gift["name"])
            total_stock = int(gift.get("total_stock", 0))
            if not gift_name or total_stock <= 0:
                raise ValueError("礼物名称不能为空，库存必须大于 0")
            gift_id = conn.execute(
                """
                INSERT INTO gifts (
                    activity_id, name, spec, category, total_stock, per_person_limit
                )
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    activity_id,
                    gift_name,
                    gift.get("spec", "Demo 配置礼物"),
                    gift.get("category", "其他"),
                    total_stock,
                    int(gift.get("per_person_limit", 1)),
                ),
            ).lastrowid
            gift_name_to_id[gift_name] = gift_id

            per_building = _allocate_stock(total_stock, allocations)
            for building, qty in per_building.items():
                conn.execute(
                    """
                    INSERT INTO inventory (
                        activity_id, gift_id, building, total_stock, available_stock
                    )
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (activity_id, gift_id, building, qty, qty),
                )

        for department, gift_names in eligibility.items():
            for gift_name in gift_names:
                normalized = _normalize_name(gift_name)
                gift_id = gift_name_to_id.get(normalized)
                if not gift_id:
                    continue
                conn.execute(
                    """
                    INSERT INTO eligibility_rules (activity_id, department, gift_id)
                    VALUES (?, ?, ?)
                    """,
                    (activity_id, department.strip() or "ALL", gift_id),
                )

        if not conn.execute(
            "SELECT 1 FROM eligibility_rules WHERE activity_id = ? LIMIT 1",
            (activity_id,),
        ).fetchone():
            raise ValueError("资格规则没有匹配到任何礼物")

        _insert_time_slots(conn, activity_id, list(allocations.keys()), time_slots)

        conn.execute(
            """
            INSERT INTO operation_logs (admin_id, action, target_type, target_id, note)
            VALUES (?, 'publish_activity', 'activity', ?, ?)
            """,
            (admin_id, activity_id, "通过配置确认页发布活动"),
        )

    return activity_id


def _insert_time_slots(
    conn,
    activity_id: int,
    buildings: list[str],
    time_slots: list[dict[str, Any]],
) -> None:
    for building in buildings:
        for slot in time_slots:
            slot_date = _normalize_date(slot.get("date") or slot.get("slot_date"), "领取日期")
            start_time = str(slot.get("start_time") or "").strip()
            end_time = str(slot.get("end_time") or "").strip()
            if not start_time or not end_time:
                raise ValueError("领取时间段必须包含开始时间和结束时间")
            conn.execute(
                """
                INSERT OR IGNORE INTO time_slots (
                    activity_id, building, slot_date, start_time, end_time, capacity, is_available
                )
                VALUES (?, ?, ?, ?, ?, ?, 1)
                """,
                (
                    activity_id,
                    building,
                    slot_date,
                    start_time,
                    end_time,
                    int(slot.get("capacity", DEFAULT_SLOT_CAPACITY)),
                ),
            )


def publish_time_slot(
    activity_id: int,
    slot_date: str,
    start_time: str,
    end_time: str,
    capacity: int,
    building: str | None = None,
    admin_id: int | None = None,
) -> int:
    if not activity_id:
        raise ValueError("请选择活动")
    normalized_date = _normalize_date(slot_date, "领取日期")
    normalized_start_time = start_time.strip()
    normalized_end_time = end_time.strip()
    if not normalized_start_time or not normalized_end_time:
        raise ValueError("开始时间和结束时间不能为空")
    if capacity <= 0:
        raise ValueError("容量必须大于 0")

    with get_connection() as conn:
        activity = conn.execute(
            "SELECT * FROM activities WHERE id = ?",
            (activity_id,),
        ).fetchone()
        if not activity:
            raise ValueError("活动不存在")
        allowed_dates = {item.isoformat() for item in _date_range(activity["start_date"], activity["end_date"])}
        if normalized_date not in allowed_dates:
            raise ValueError("领取日期必须在活动日期范围内")

        buildings = [building] if building else _active_building_names(conn)
        if not buildings:
            raise ValueError("至少需要配置一个楼宇")

        created_or_updated = 0
        for item in buildings:
            existing = conn.execute(
                """
                SELECT reserved_count
                FROM time_slots
                WHERE activity_id = ?
                  AND building = ?
                  AND slot_date = ?
                  AND start_time = ?
                  AND end_time = ?
                """,
                (activity_id, item, normalized_date, normalized_start_time, normalized_end_time),
            ).fetchone()
            if existing and capacity < existing["reserved_count"]:
                raise ValueError("容量不能小于该时间段已预约人数")

            conn.execute(
                """
                INSERT INTO time_slots (
                    activity_id, building, slot_date, start_time, end_time,
                    capacity, reserved_count, is_available
                )
                VALUES (?, ?, ?, ?, ?, ?, 0, 1)
                ON CONFLICT(activity_id, building, slot_date, start_time, end_time)
                DO UPDATE SET
                    capacity = excluded.capacity,
                    is_available = 1
                """,
                (
                    activity_id,
                    item,
                    normalized_date,
                    normalized_start_time,
                    normalized_end_time,
                    int(capacity),
                ),
            )
            created_or_updated += 1

        conn.execute(
            """
            INSERT INTO operation_logs (admin_id, action, target_type, target_id, note)
            VALUES (?, 'publish_time_slot', 'activity', ?, ?)
            """,
            (
                admin_id,
                activity_id,
                f"{normalized_date} {normalized_start_time}-{normalized_end_time} 发布到 {len(buildings)} 个楼宇",
            ),
        )
    return created_or_updated


def set_time_slot_availability(
    time_slot_id: int,
    is_available: bool,
    admin_id: int | None = None,
) -> None:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM time_slots WHERE id = ?",
            (time_slot_id,),
        ).fetchone()
        if not row:
            raise ValueError("时间段不存在")
        if row["reserved_count"] > 0 and not is_available:
            raise ValueError("该时间段已有预约，不能直接设为不可领取")

        conn.execute(
            """
            UPDATE time_slots
            SET is_available = ?
            WHERE id = ?
            """,
            (1 if is_available else 0, time_slot_id),
        )
        conn.execute(
            """
            INSERT INTO operation_logs (admin_id, action, target_type, target_id, note)
            VALUES (?, ?, 'time_slot', ?, ?)
            """,
            (
                admin_id,
                "enable_time_slot" if is_available else "disable_time_slot",
                time_slot_id,
                "时间段可用状态变更",
            ),
        )


def update_time_slot(
    time_slot_id: int,
    capacity: int,
    is_available: bool,
    admin_id: int | None = None,
) -> None:
    if capacity <= 0:
        raise ValueError("容量必须大于 0")

    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM time_slots WHERE id = ?",
            (time_slot_id,),
        ).fetchone()
        if not row:
            raise ValueError("时间段不存在")
        if capacity < row["reserved_count"]:
            raise ValueError("容量不能小于该时间段已预约人数")
        if row["reserved_count"] > 0 and not is_available:
            raise ValueError("该时间段已有预约，不能直接设为不可领取")

        conn.execute(
            """
            UPDATE time_slots
            SET capacity = ?,
                is_available = ?
            WHERE id = ?
            """,
            (capacity, 1 if is_available else 0, time_slot_id),
        )
        conn.execute(
            """
            INSERT INTO operation_logs (admin_id, action, target_type, target_id, note)
            VALUES (?, 'update_time_slot', 'time_slot', ?, ?)
            """,
            (admin_id, time_slot_id, "修改领取时间段容量或状态"),
        )


def delete_time_slot(time_slot_id: int, admin_id: int | None = None) -> None:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM time_slots WHERE id = ?",
            (time_slot_id,),
        ).fetchone()
        if not row:
            raise ValueError("时间段不存在")
        if row["reserved_count"] > 0:
            raise ValueError("该时间段已有预约，不能删除")
        claim_count = conn.execute(
            "SELECT COUNT(*) AS count FROM claims WHERE time_slot_id = ?",
            (time_slot_id,),
        ).fetchone()["count"]
        if claim_count > 0:
            raise ValueError("该时间段已有预约记录，不能删除")

        conn.execute("DELETE FROM time_slots WHERE id = ?", (time_slot_id,))
        conn.execute(
            """
            INSERT INTO operation_logs (admin_id, action, target_type, target_id, note)
            VALUES (?, 'delete_time_slot', 'time_slot', ?, ?)
            """,
            (admin_id, time_slot_id, "删除未预约的领取时间段"),
        )


def list_schedule_calendar_counts(year: int, month: int) -> dict[str, dict[str, int]]:
    last_day = monthrange(year, month)[1]
    start = date(year, month, 1).isoformat()
    end = date(year, month, last_day).isoformat()
    rows = fetch_all(
        """
        SELECT
            t.slot_date,
            COUNT(DISTINCT t.activity_id) AS activity_count,
            COUNT(*) AS slot_count,
            SUM(CASE WHEN t.is_available = 1 THEN 1 ELSE 0 END) AS available_slot_count,
            COALESCE(SUM(t.reserved_count), 0) AS reservation_count
        FROM time_slots t
        JOIN activities a ON a.id = t.activity_id
        WHERE a.status = 'published'
          AND t.slot_date BETWEEN ? AND ?
        GROUP BY t.slot_date
        """,
        (start, end),
    )
    return {
        row["slot_date"]: {
            "activity_count": int(row["activity_count"] or 0),
            "slot_count": int(row["slot_count"] or 0),
            "available_slot_count": int(row["available_slot_count"] or 0),
            "reservation_count": int(row["reservation_count"] or 0),
        }
        for row in rows
    }


def list_day_schedule(slot_date: str) -> list[dict[str, Any]]:
    normalized_date = _normalize_date(slot_date, "领取日期")
    with get_connection() as conn:
        slots = rows_to_dicts(
            conn.execute(
                """
                SELECT
                    t.*,
                    a.name AS activity_name,
                    t.capacity - t.reserved_count AS remaining
                FROM time_slots t
                JOIN activities a ON a.id = t.activity_id
                WHERE a.status = 'published'
                  AND t.slot_date = ?
                ORDER BY a.name, t.start_time, t.end_time, t.building
                """,
                (normalized_date,),
            ).fetchall()
        )
        if not slots:
            return []

        slot_ids = [slot["id"] for slot in slots]
        placeholders = ",".join("?" for _ in slot_ids)
        claims = rows_to_dicts(
            conn.execute(
                f"""
                SELECT
                    c.*,
                    e.name AS employee_name,
                    e.department,
                    a.name AS activity_name,
                    g.name AS gift_name
                FROM claims c
                JOIN employees e ON e.id = c.employee_id
                JOIN activities a ON a.id = c.activity_id
                JOIN gifts g ON g.id = c.gift_id
                WHERE c.time_slot_id IN ({placeholders})
                  AND c.status IN ('reserved', 'redeemed')
                ORDER BY c.id
                """,
                tuple(slot_ids),
            ).fetchall()
        )

    claims_by_slot: dict[int, list[dict[str, Any]]] = {}
    for claim in claims:
        claims_by_slot.setdefault(claim["time_slot_id"], []).append(claim)

    for slot in slots:
        slot["claims"] = claims_by_slot.get(slot["id"], [])
    return slots


def log_reschedule_contact(claim_id: int, admin_id: int | None = None) -> dict[str, Any]:
    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT
                c.*,
                e.name AS employee_name,
                e.department,
                g.name AS gift_name
            FROM claims c
            JOIN employees e ON e.id = c.employee_id
            JOIN gifts g ON g.id = c.gift_id
            WHERE c.id = ?
            """,
            (claim_id,),
        ).fetchone()
        claim = row_to_dict(row)
        if not claim:
            raise ValueError("预约记录不存在")

        conn.execute(
            """
            INSERT INTO operation_logs (admin_id, action, target_type, target_id, note)
            VALUES (?, 'contact_reschedule', 'claim', ?, ?)
            """,
            (
                admin_id,
                claim_id,
                f"联系 {claim['employee_name']} 调整领取时间",
            ),
        )
    return claim
