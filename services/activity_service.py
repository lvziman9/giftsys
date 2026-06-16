from __future__ import annotations

from calendar import monthrange
from datetime import date, datetime, timedelta
from typing import Any

from config import ADMIN_PASSWORD, BUILDINGS, DEFAULT_SLOT_CAPACITY, DEFAULT_TIME_RANGES
from database import fetch_all, fetch_one, get_connection, row_to_dict, rows_to_dicts
from services.inventory_service import write_inventory_log
from services.notification_service import create_notification, notify_activity_published


def auto_end_expired_activities(conn=None) -> None:
    today = date.today().isoformat()
    sql = """
        UPDATE activities
        SET status = 'ended'
        WHERE status IN ('published', 'offline')
          AND end_date < ?
    """
    if conn is not None:
        conn.execute(sql, (today,))
        return

    with get_connection() as local_conn:
        local_conn.execute(sql, (today,))


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
        ORDER BY sort_order, id
        """
    )


def _clean_text(value: Any) -> str:
    return str(value or "").strip()


def _next_building_sort_order(conn) -> int:
    row = conn.execute(
        "SELECT COALESCE(MAX(sort_order), 0) + 1 AS next_sort FROM buildings"
    ).fetchone()
    return int(row["next_sort"] or 1)


def add_building(
    name: str,
    address: str = "",
    pickup_location: str = "",
    manager_name: str = "",
    manager_contact: str = "",
    backup_manager: str = "",
    note: str = "",
    sort_order: int | None = None,
    is_active: bool = True,
    admin_id: int | None = None,
) -> dict[str, Any]:
    building_name = name.strip()
    if not building_name:
        raise ValueError("楼宇名称不能为空")

    with get_connection() as conn:
        normalized_sort_order = int(sort_order) if sort_order is not None else _next_building_sort_order(conn)
        conn.execute(
            """
            INSERT INTO buildings (
                name, address, pickup_location, manager_name, manager_contact,
                backup_manager, note, sort_order, is_active, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(name) DO UPDATE SET
                address = CASE
                    WHEN excluded.address != '' THEN excluded.address
                    ELSE buildings.address
                END,
                pickup_location = CASE
                    WHEN excluded.pickup_location != '' THEN excluded.pickup_location
                    ELSE buildings.pickup_location
                END,
                manager_name = CASE
                    WHEN excluded.manager_name != '' THEN excluded.manager_name
                    ELSE buildings.manager_name
                END,
                manager_contact = CASE
                    WHEN excluded.manager_contact != '' THEN excluded.manager_contact
                    ELSE buildings.manager_contact
                END,
                backup_manager = CASE
                    WHEN excluded.backup_manager != '' THEN excluded.backup_manager
                    ELSE buildings.backup_manager
                END,
                note = CASE
                    WHEN excluded.note != '' THEN excluded.note
                    ELSE buildings.note
                END,
                sort_order = excluded.sort_order,
                is_active = excluded.is_active,
                updated_at = CURRENT_TIMESTAMP
            """,
            (
                building_name,
                _clean_text(address),
                _clean_text(pickup_location),
                _clean_text(manager_name),
                _clean_text(manager_contact),
                _clean_text(backup_manager),
                _clean_text(note),
                normalized_sort_order,
                1 if is_active else 0,
            ),
        )
        building = conn.execute(
            "SELECT * FROM buildings WHERE name = ?",
            (building_name,),
        ).fetchone()
        building_id = building["id"] if building else None
        conn.execute(
            """
            INSERT INTO operation_logs (admin_id, action, target_type, target_id, note)
            VALUES (?, 'upsert_building', 'building', ?, ?)
            """,
            (admin_id, building_id, f"维护楼宇基础信息：{building_name}"),
        )
    return fetch_one("SELECT * FROM buildings WHERE name = ?", (building_name,)) or {}


def update_building(
    building_id: int,
    address: str,
    pickup_location: str,
    manager_name: str,
    manager_contact: str,
    backup_manager: str,
    note: str,
    sort_order: int,
    is_active: bool,
    admin_id: int | None = None,
) -> dict[str, Any]:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM buildings WHERE id = ?",
            (building_id,),
        ).fetchone()
        if not row:
            raise ValueError("楼宇不存在")

        conn.execute(
            """
            UPDATE buildings
            SET address = ?,
                pickup_location = ?,
                manager_name = ?,
                manager_contact = ?,
                backup_manager = ?,
                note = ?,
                sort_order = ?,
                is_active = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (
                _clean_text(address),
                _clean_text(pickup_location),
                _clean_text(manager_name),
                _clean_text(manager_contact),
                _clean_text(backup_manager),
                _clean_text(note),
                int(sort_order),
                1 if is_active else 0,
                building_id,
            ),
        )
        conn.execute(
            """
            INSERT INTO operation_logs (admin_id, action, target_type, target_id, note)
            VALUES (?, 'update_building', 'building', ?, ?)
            """,
            (admin_id, building_id, f"更新楼宇基础信息：{row['name']}"),
        )

    return fetch_one("SELECT * FROM buildings WHERE id = ?", (building_id,)) or {}


def list_activity_buildings(activity_id: int) -> list[dict[str, Any]]:
    return fetch_all(
        """
        SELECT DISTINCT
            i.building AS name,
            b.id,
            b.address,
            b.pickup_location,
            b.manager_name,
            b.manager_contact,
            b.backup_manager,
            b.note,
            b.sort_order,
            b.is_active
        FROM inventory i
        JOIN buildings b ON b.name = i.building
        WHERE i.activity_id = ?
          AND b.is_active = 1
        ORDER BY b.sort_order, i.building
        """,
        (activity_id,),
    )


def get_employee(employee_id: int) -> dict[str, Any] | None:
    return fetch_one("SELECT * FROM employees WHERE id = ?", (employee_id,))


def authenticate_employee(employee_no: str, phone_suffix: str) -> dict[str, Any] | None:
    employee = fetch_one(
        """
        SELECT *
        FROM employees
        WHERE UPPER(employee_no) = UPPER(?)
        """,
        (employee_no.strip(),),
    )
    if not employee:
        return None

    suffix = phone_suffix.strip()
    phone = str(employee.get("phone") or "")
    if not suffix or not phone.endswith(suffix):
        return None
    return employee


def authenticate_admin(password: str) -> dict[str, Any] | None:
    if password != ADMIN_PASSWORD:
        return None
    return fetch_one("SELECT * FROM admins ORDER BY id LIMIT 1")


def list_published_activities() -> list[dict[str, Any]]:
    auto_end_expired_activities()
    return fetch_all(
        """
        SELECT *
        FROM activities
        WHERE status = 'published'
        ORDER BY published_at DESC, id DESC
        """
    )


def list_employee_available_activities(employee_id: int) -> list[dict[str, Any]]:
    auto_end_expired_activities()
    return fetch_all(
        """
        SELECT DISTINCT a.*
        FROM activities a
        JOIN eligibility_rules er ON er.activity_id = a.id
        JOIN employees e
          ON e.id = ?
         AND (er.department = e.department OR er.department = 'ALL')
        WHERE a.status = 'published'
        ORDER BY a.published_at DESC, a.id DESC
        """,
        (employee_id,),
    )


def list_admin_activities() -> list[dict[str, Any]]:
    auto_end_expired_activities()
    return fetch_all(
        """
        SELECT
            a.*,
            (SELECT COUNT(*) FROM gifts g WHERE g.activity_id = a.id) AS gift_count,
            (
                SELECT COUNT(*)
                FROM claims c
                WHERE c.activity_id = a.id
                  AND c.status = 'reserved'
            ) AS reserved_count,
            (
                SELECT COUNT(*)
                FROM claims c
                WHERE c.activity_id = a.id
                  AND c.status = 'redeemed'
            ) AS redeemed_count,
            (
                SELECT COUNT(*)
                FROM claims c
                WHERE c.activity_id = a.id
            ) AS claim_count
        FROM activities a
        WHERE a.status IN ('published', 'offline')
        ORDER BY a.published_at DESC, a.id DESC
        """
    )


def list_history_activities(keyword: str = "") -> list[dict[str, Any]]:
    auto_end_expired_activities()
    search = f"%{keyword.strip()}%"
    params: tuple[Any, ...] = ()
    where = "WHERE a.status = 'ended'"
    if keyword.strip():
        where += " AND (a.name LIKE ? OR a.description LIKE ?)"
        params = (search, search)

    return fetch_all(
        f"""
        SELECT
            a.*,
            (SELECT COUNT(*) FROM gifts g WHERE g.activity_id = a.id) AS gift_count,
            (
                SELECT COUNT(*)
                FROM claims c
                WHERE c.activity_id = a.id
                  AND c.status = 'reserved'
            ) AS reserved_count,
            (
                SELECT COUNT(*)
                FROM claims c
                WHERE c.activity_id = a.id
                  AND c.status = 'redeemed'
            ) AS redeemed_count,
            (
                SELECT COUNT(DISTINCT c.employee_id)
                FROM claims c
                WHERE c.activity_id = a.id
                  AND c.status IN ('reserved', 'redeemed')
            ) AS claimed_employee_count,
            (
                SELECT COALESCE(SUM(i.total_stock), 0)
                FROM inventory i
                WHERE i.activity_id = a.id
            ) AS total_stock,
            (
                SELECT COALESCE(SUM(i.available_stock), 0)
                FROM inventory i
                WHERE i.activity_id = a.id
            ) AS available_stock,
            (
                SELECT COALESCE(SUM(i.reserved_stock), 0)
                FROM inventory i
                WHERE i.activity_id = a.id
            ) AS reserved_stock,
            (
                SELECT COALESCE(SUM(i.redeemed_stock), 0)
                FROM inventory i
                WHERE i.activity_id = a.id
            ) AS redeemed_stock
        FROM activities a
        {where}
        ORDER BY a.end_date DESC, a.id DESC
        """,
        params,
    )


def get_activity(activity_id: int) -> dict[str, Any] | None:
    auto_end_expired_activities()
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


def _allocation_percentages(weights: dict[str, int], buildings: list[str]) -> dict[str, int]:
    if not buildings:
        return {}

    total_weight = sum(max(int(weights.get(building, 0)), 0) for building in buildings)
    if total_weight <= 0:
        base = 100 // len(buildings)
        allocation = {building: base for building in buildings}
        allocation[buildings[-1]] += 100 - sum(allocation.values())
        return allocation

    raw = {
        building: (max(int(weights.get(building, 0)), 0) * 100 / total_weight)
        for building in buildings
    }
    allocation = {building: int(value) for building, value in raw.items()}
    remainder = 100 - sum(allocation.values())
    if remainder > 0:
        ranked = sorted(
            buildings,
            key=lambda building: raw[building] - int(raw[building]),
            reverse=True,
        )
        for building in ranked[:remainder]:
            allocation[building] += 1
    return allocation


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
    auto_end_expired_activities()
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
    auto_end_expired_activities()
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
    auto_end_expired_activities()
    return fetch_all(
        """
        SELECT
            t.*,
            t.capacity - t.reserved_count AS remaining
        FROM time_slots t
        JOIN activities a ON a.id = t.activity_id
        WHERE t.activity_id = ?
          AND t.building = ?
          AND t.is_available = 1
          AND a.status = 'published'
          AND a.end_date >= ?
        ORDER BY slot_date, start_time
        """,
        (activity_id, building, date.today().isoformat()),
    )


def list_time_slots_for_admin(
    activity_id: int | None = None,
    slot_date: str | None = None,
) -> list[dict[str, Any]]:
    auto_end_expired_activities()
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
    auto_end_expired_activities()
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
    auto_end_expired_activities()
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
    auto_end_expired_activities()
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
    auto_end_expired_activities()
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


def list_activity_gift_rules(activity_id: int) -> list[dict[str, Any]]:
    auto_end_expired_activities()
    return fetch_all(
        """
        SELECT
            g.id,
            g.name,
            g.spec,
            g.category,
            g.total_stock,
            g.per_person_limit,
            (
                SELECT GROUP_CONCAT(
                    CASE
                        WHEN er.department = 'ALL' THEN '全员'
                        ELSE er.department
                    END,
                    '、'
                )
                FROM eligibility_rules er
                WHERE er.gift_id = g.id
            ) AS departments,
            (
                SELECT COALESCE(SUM(i.total_stock), 0)
                FROM inventory i
                WHERE i.gift_id = g.id
            ) AS inventory_total,
            (
                SELECT COALESCE(SUM(i.available_stock), 0)
                FROM inventory i
                WHERE i.gift_id = g.id
            ) AS available_stock,
            (
                SELECT COALESCE(SUM(i.reserved_stock), 0)
                FROM inventory i
                WHERE i.gift_id = g.id
            ) AS reserved_stock,
            (
                SELECT COALESCE(SUM(i.redeemed_stock), 0)
                FROM inventory i
                WHERE i.gift_id = g.id
            ) AS redeemed_stock
        FROM gifts g
        WHERE g.activity_id = ?
        ORDER BY g.id
        """,
        (activity_id,),
    )


def _activity_building_names(conn, activity_id: int) -> list[str]:
    rows = conn.execute(
        """
        SELECT DISTINCT building AS name
        FROM time_slots
        WHERE activity_id = ?
        ORDER BY building
        """,
        (activity_id,),
    ).fetchall()
    if rows:
        return [row["name"] for row in rows]

    rows = conn.execute(
        """
        SELECT DISTINCT building AS name
        FROM inventory
        WHERE activity_id = ?
        ORDER BY building
        """,
        (activity_id,),
    ).fetchall()
    if rows:
        return [row["name"] for row in rows]

    return _active_building_names(conn)


def _default_time_slots_for_dates(slot_dates: set[date]) -> list[dict[str, Any]]:
    slots: list[dict[str, Any]] = []
    for slot_date in sorted(slot_dates):
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


def update_activity_basic(
    activity_id: int,
    name: str,
    description: str,
    start_date: Any,
    end_date: Any,
    allow_cancel: bool,
    expire_release: bool,
    admin_id: int | None = None,
) -> dict[str, Any]:
    activity_name = _clean_text(name)
    if not activity_name:
        raise ValueError("活动名称不能为空")

    normalized_start = _normalize_date(start_date, "开始日期")
    normalized_end = _normalize_date(end_date, "结束日期")
    new_dates = set(_date_range(normalized_start, normalized_end))

    with get_connection() as conn:
        auto_end_expired_activities(conn)
        activity = conn.execute(
            "SELECT * FROM activities WHERE id = ?",
            (activity_id,),
        ).fetchone()
        if not activity:
            raise ValueError("活动不存在")
        if activity["status"] == "ended":
            raise ValueError("历史活动不能修改，请使用再次发布创建新活动")

        old_dates = set(_date_range(activity["start_date"], activity["end_date"]))
        removed_dates = old_dates - new_dates
        added_dates = new_dates - old_dates

        if removed_dates:
            placeholders = ",".join("?" for _ in removed_dates)
            rows = conn.execute(
                f"""
                SELECT COUNT(*) AS count
                FROM claims c
                JOIN time_slots t ON t.id = c.time_slot_id
                WHERE c.activity_id = ?
                  AND t.slot_date IN ({placeholders})
                """,
                (activity_id, *(item.isoformat() for item in removed_dates)),
            ).fetchone()
            if rows["count"]:
                raise ValueError("缩短日期范围会移除已有预约记录的日期，请先联系改期或处理预约")

            conn.execute(
                f"""
                DELETE FROM time_slots
                WHERE activity_id = ?
                  AND slot_date IN ({placeholders})
                """,
                (activity_id, *(item.isoformat() for item in removed_dates)),
            )

        if added_dates:
            _insert_time_slots(
                conn,
                activity_id,
                _activity_building_names(conn, activity_id),
                _default_time_slots_for_dates(added_dates),
            )

        next_status = (
            "ended"
            if _parse_config_date(normalized_end, "结束日期") < date.today()
            else activity["status"]
        )
        conn.execute(
            """
            UPDATE activities
            SET name = ?,
                description = ?,
                start_date = ?,
                end_date = ?,
                status = ?,
                allow_cancel = ?,
                expire_release = ?
            WHERE id = ?
            """,
            (
                activity_name,
                _clean_text(description),
                normalized_start,
                normalized_end,
                next_status,
                1 if allow_cancel else 0,
                1 if expire_release else 0,
                activity_id,
            ),
        )
        conn.execute(
            """
            INSERT INTO operation_logs (admin_id, action, target_type, target_id, note)
            VALUES (?, 'update_activity', 'activity', ?, ?)
            """,
            (
                admin_id,
                activity_id,
                (
                    f"活动基础信息更新；新增日期 {len(added_dates)} 天，"
                    f"移除日期 {len(removed_dates)} 天"
                ),
            ),
        )

    return get_activity(activity_id) or {}


def set_activity_status(
    activity_id: int,
    status: str,
    admin_id: int | None = None,
) -> dict[str, Any]:
    if status not in {"published", "offline"}:
        raise ValueError("活动状态无效")

    with get_connection() as conn:
        auto_end_expired_activities(conn)
        activity = conn.execute(
            "SELECT * FROM activities WHERE id = ?",
            (activity_id,),
        ).fetchone()
        if not activity:
            raise ValueError("活动不存在")
        if activity["status"] == "ended":
            raise ValueError("历史活动不能下线或恢复上线，请使用再次发布创建新活动")
        if status == "published" and _parse_config_date(activity["end_date"], "结束日期") < date.today():
            conn.execute("UPDATE activities SET status = 'ended' WHERE id = ?", (activity_id,))
            raise ValueError("活动已超过结束日期，不能恢复上线")

        conn.execute(
            """
            UPDATE activities
            SET status = ?
            WHERE id = ?
            """,
            (status, activity_id),
        )
        conn.execute(
            """
            INSERT INTO operation_logs (admin_id, action, target_type, target_id, note)
            VALUES (?, ?, 'activity', ?, ?)
            """,
            (
                admin_id,
                "publish_activity_again" if status == "published" else "offline_activity",
                activity_id,
                "活动恢复上线" if status == "published" else "活动下线",
            ),
        )
        if status == "published":
            notify_activity_published(conn, activity_id)

    return get_activity(activity_id) or {}


def add_gift_to_activity(
    activity_id: int,
    rule: dict[str, Any],
    admin_id: int | None = None,
) -> int:
    with get_connection() as conn:
        auto_end_expired_activities(conn)
        activity = conn.execute(
            "SELECT * FROM activities WHERE id = ?",
            (activity_id,),
        ).fetchone()
        if not activity:
            raise ValueError("活动不存在")
        if activity["status"] == "ended":
            raise ValueError("历史活动不能增发礼物，请使用再次发布创建新活动")

        gift_name = _normalize_name(rule.get("name", ""))
        department = _normalize_department(rule.get("department", ""))
        total_stock = int(rule.get("total_stock", 0))
        description = _clean_text(rule.get("description", ""))
        if not gift_name:
            raise ValueError("礼物名称不能为空")
        if not department:
            raise ValueError("礼物所属部门不能为空")
        if total_stock <= 0:
            raise ValueError("礼物初始数量必须大于 0")

        activity_buildings = _activity_building_names(conn, activity_id)
        allocation = _allocation_for_buildings(
            rule.get("building_allocation") or {},
            activity_buildings,
        )

        gift_id = conn.execute(
            """
            INSERT INTO gifts (
                activity_id, name, spec, category, total_stock, per_person_limit
            )
            VALUES (?, ?, ?, '其他', ?, ?)
            """,
            (
                activity_id,
                gift_name,
                description or "增发礼物",
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

        conn.execute(
            """
            INSERT INTO operation_logs (admin_id, action, target_type, target_id, note)
            VALUES (?, 'add_activity_gift', 'gift', ?, ?)
            """,
            (admin_id, gift_id, f"活动 {activity_id} 增发礼物：{gift_name}"),
        )
        return int(gift_id)


def adjust_activity_inventory(
    inventory_id: int,
    adjustment_type: str,
    quantity: int,
    reason: str = "",
    admin_id: int | None = None,
) -> dict[str, Any]:
    if adjustment_type not in {"increase", "decrease"}:
        raise ValueError("库存调整类型无效")
    if quantity <= 0:
        raise ValueError("调整数量必须大于 0")

    with get_connection() as conn:
        auto_end_expired_activities(conn)
        row = conn.execute(
            """
            SELECT i.*, g.name AS gift_name, a.status AS activity_status
            FROM inventory i
            JOIN gifts g ON g.id = i.gift_id
            JOIN activities a ON a.id = i.activity_id
            WHERE i.id = ?
            """,
            (inventory_id,),
        ).fetchone()
        before = row_to_dict(row)
        if not before:
            raise ValueError("库存记录不存在")
        if before["activity_status"] == "ended":
            raise ValueError("历史活动不能调整库存，请使用再次发布创建新活动")

        if adjustment_type == "decrease" and quantity > before["available_stock"]:
            raise ValueError("减少数量不能超过当前可用库存")

        delta = quantity if adjustment_type == "increase" else -quantity
        after_total = before["total_stock"] + delta
        after_available = before["available_stock"] + delta
        if after_total < 0 or after_available < 0:
            raise ValueError("库存调整后不能小于 0")

        conn.execute(
            """
            UPDATE inventory
            SET total_stock = ?,
                available_stock = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (after_total, after_available, inventory_id),
        )
        conn.execute(
            """
            UPDATE gifts
            SET total_stock = total_stock + ?
            WHERE id = ?
            """,
            (delta, before["gift_id"]),
        )
        after = row_to_dict(
            conn.execute(
                "SELECT * FROM inventory WHERE id = ?",
                (inventory_id,),
            ).fetchone()
        )
        note = _clean_text(reason) or ("补充库存" if adjustment_type == "increase" else "减少可用库存")
        write_inventory_log(
            conn,
            before,
            after,
            "stock_increase" if adjustment_type == "increase" else "stock_decrease",
            quantity=quantity,
            note=note,
        )
        conn.execute(
            """
            INSERT INTO operation_logs (admin_id, action, target_type, target_id, note)
            VALUES (?, ?, 'inventory', ?, ?)
            """,
            (
                admin_id,
                "increase_inventory" if adjustment_type == "increase" else "decrease_inventory",
                inventory_id,
                f"{before['gift_name']} / {before['building']} / {note} / 数量 {quantity}",
            ),
        )

    result = fetch_one(
        """
        SELECT i.*, g.name AS gift_name
        FROM inventory i
        JOIN gifts g ON g.id = i.gift_id
        WHERE i.id = ?
        """,
        (inventory_id,),
    )
    return result or {}


def activity_template_from_history(activity_id: int) -> dict[str, Any]:
    auto_end_expired_activities()
    activity = get_activity(activity_id)
    if not activity:
        raise ValueError("活动不存在")
    if activity["status"] != "ended":
        raise ValueError("只有历史活动可以作为再次发布模板")

    active_buildings = [building["name"] for building in list_buildings(active_only=True)]
    gifts = list_activity_gift_rules(activity_id)
    inventory_rows = list_inventory_rows(activity_id)
    inventory_by_gift: dict[int, dict[str, int]] = {}
    for row in inventory_rows:
        inventory_by_gift.setdefault(row["gift_id"], {})[row["building"]] = int(row["total_stock"] or 0)

    gift_rules: list[dict[str, Any]] = []
    for gift in gifts:
        departments = [
            department.strip()
            for department in str(gift.get("departments") or "全员").split("、")
            if department.strip()
        ]
        gift_rules.append(
            {
                "name": gift["name"],
                "department": departments[0] if departments else "全员",
                "total_stock": int(gift.get("inventory_total") or gift.get("total_stock") or 0),
                "description": gift.get("spec", ""),
                "building_allocation": _allocation_percentages(
                    inventory_by_gift.get(gift["id"], {}),
                    active_buildings,
                ),
                "per_person_limit": int(gift.get("per_person_limit") or 1),
            }
        )

    return {
        "activity": {
            "name": f"{activity['name']} 复用",
            "activity_type": activity.get("activity_type", "节日福利"),
            "description": activity.get("description", ""),
            "start_date": "",
            "end_date": "",
            "allow_cancel": bool(activity.get("allow_cancel", True)),
            "expire_release": bool(activity.get("expire_release", True)),
        },
        "gift_rules": gift_rules,
        "source_activity_id": activity_id,
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
        ORDER BY sort_order, id
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
    initial_status = "ended" if _parse_config_date(end_date, "结束日期") < date.today() else "published"
    with get_connection() as conn:
        active_buildings = _active_building_names(conn)
        activity_id = conn.execute(
            """
            INSERT INTO activities (
                name, activity_type, description, start_date, end_date, status,
                allow_cancel, expire_release, published_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            """,
            (
                activity["name"],
                activity.get("activity_type", "节日福利"),
                activity.get("description", ""),
                start_date,
                end_date,
                initial_status,
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
                        description or "配置礼物",
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
            if initial_status == "published":
                notify_activity_published(conn, activity_id)
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
                    gift.get("spec", "配置礼物"),
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
        if initial_status == "published":
            notify_activity_published(conn, activity_id)

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
        auto_end_expired_activities(conn)
        activity = conn.execute(
            "SELECT * FROM activities WHERE id = ?",
            (activity_id,),
        ).fetchone()
        if not activity:
            raise ValueError("活动不存在")
        if activity["status"] == "ended":
            raise ValueError("历史活动不能新增领取时间，请使用再次发布创建新活动")
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
        auto_end_expired_activities(conn)
        row = conn.execute(
            """
            SELECT t.*, a.status AS activity_status
            FROM time_slots t
            JOIN activities a ON a.id = t.activity_id
            WHERE t.id = ?
            """,
            (time_slot_id,),
        ).fetchone()
        if not row:
            raise ValueError("时间段不存在")
        if row["activity_status"] == "ended":
            raise ValueError("历史活动不能修改领取时间")
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
        auto_end_expired_activities(conn)
        row = conn.execute(
            """
            SELECT t.*, a.status AS activity_status
            FROM time_slots t
            JOIN activities a ON a.id = t.activity_id
            WHERE t.id = ?
            """,
            (time_slot_id,),
        ).fetchone()
        if not row:
            raise ValueError("时间段不存在")
        if row["activity_status"] == "ended":
            raise ValueError("历史活动不能修改领取时间")
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
        auto_end_expired_activities(conn)
        row = conn.execute(
            """
            SELECT t.*, a.status AS activity_status
            FROM time_slots t
            JOIN activities a ON a.id = t.activity_id
            WHERE t.id = ?
            """,
            (time_slot_id,),
        ).fetchone()
        if not row:
            raise ValueError("时间段不存在")
        if row["activity_status"] == "ended":
            raise ValueError("历史活动不能删除领取时间")
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
    auto_end_expired_activities()
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
    auto_end_expired_activities()
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
                    e.phone AS employee_phone,
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


def get_reschedule_context(claim_id: int) -> dict[str, Any]:
    claim = fetch_one(
        """
        SELECT
            c.*,
            e.name AS employee_name,
            e.department,
            e.phone AS employee_phone,
            a.name AS activity_name,
            a.start_date,
            a.end_date,
            a.status AS activity_status,
            g.name AS gift_name,
            t.slot_date,
            t.start_time,
            t.end_time,
            t.building AS slot_building
        FROM claims c
        JOIN employees e ON e.id = c.employee_id
        JOIN activities a ON a.id = c.activity_id
        JOIN gifts g ON g.id = c.gift_id
        JOIN time_slots t ON t.id = c.time_slot_id
        WHERE c.id = ?
        """,
        (claim_id,),
    )
    if not claim:
        raise ValueError("预约记录不存在")
    return claim


def list_reschedule_time_slots(
    activity_id: int,
    building: str,
    slot_date: str,
) -> list[dict[str, Any]]:
    auto_end_expired_activities()
    normalized_date = _normalize_date(slot_date, "目标日期")
    return fetch_all(
        """
        SELECT
            t.*,
            a.name AS activity_name,
            t.capacity - t.reserved_count AS remaining
        FROM time_slots t
        JOIN activities a ON a.id = t.activity_id
        WHERE t.activity_id = ?
          AND t.building = ?
          AND t.slot_date = ?
          AND t.is_available = 1
          AND t.capacity > t.reserved_count
          AND a.status = 'published'
        ORDER BY t.start_time, t.end_time
        """,
        (activity_id, building, normalized_date),
    )


def _format_sms_slot(slot_date: str, start_time: str, end_time: str) -> str:
    return f"{slot_date} {start_time}-{end_time}"


def _reschedule_sms_content(claim: dict[str, Any], target_slot: dict[str, Any]) -> str:
    old_time = _format_sms_slot(
        claim["slot_date"],
        claim["start_time"],
        claim["end_time"],
    )
    target_time = _format_sms_slot(
        target_slot["slot_date"],
        target_slot["start_time"],
        target_slot["end_time"],
    )
    return (
        f"【GiftFlow】{claim['employee_name']}您好，您的{claim['activity_name']}领取时间需调整。"
        f"原时间：{old_time}；建议改为：{target_time}。"
        f"领取礼物：{claim['gift_name']}；地点：{claim['building']}。如有疑问请联系行政。"
    )


def send_reschedule_sms(
    claim_id: int,
    target_time_slot_id: int,
    admin_id: int | None = None,
) -> dict[str, Any]:
    claim = get_reschedule_context(claim_id)
    if claim["status"] != "reserved":
        raise ValueError("只有已预约记录可以联系改期")

    phone = _clean_text(claim.get("employee_phone"))
    if not phone:
        raise ValueError("该员工未维护手机号，无法发送改期短信")

    with get_connection() as conn:
        target_row = conn.execute(
            """
            SELECT
                t.*,
                a.name AS activity_name,
                t.capacity - t.reserved_count AS remaining
            FROM time_slots t
            JOIN activities a ON a.id = t.activity_id
            WHERE t.id = ?
            """,
            (target_time_slot_id,),
        ).fetchone()
        target_slot = row_to_dict(target_row)
        if not target_slot:
            raise ValueError("目标领取时间不存在")
        if target_slot["activity_id"] != claim["activity_id"]:
            raise ValueError("目标时间必须属于同一活动")
        if target_slot["building"] != claim["building"]:
            raise ValueError("目标时间必须属于同一楼宇")
        if not target_slot["is_available"]:
            raise ValueError("目标时间当前不可领取")
        if target_slot["remaining"] <= 0:
            raise ValueError("目标时间已满员")

        content = _reschedule_sms_content(claim, target_slot)
        old_time = _format_sms_slot(
            claim["slot_date"],
            claim["start_time"],
            claim["end_time"],
        )
        target_time = _format_sms_slot(
            target_slot["slot_date"],
            target_slot["start_time"],
            target_slot["end_time"],
        )
        conn.execute(
            """
            INSERT INTO operation_logs (admin_id, action, target_type, target_id, note)
            VALUES (?, 'send_reschedule_sms', 'claim', ?, ?)
            """,
            (
                admin_id,
                claim_id,
                (
                    f"模拟短信发送至 {phone}；"
                    f"员工 {claim['employee_name']}；原时间 {old_time}；目标时间 {target_time}；"
                    f"内容：{content}"
                ),
            ),
        )
        notification_id = create_notification(
            conn,
            claim["employee_id"],
            "reschedule_request",
            "改期提醒",
            content,
            activity_id=claim["activity_id"],
            claim_id=claim_id,
            target_time_slot_id=target_time_slot_id,
            action_status="pending",
        )

    return {
        "claim": claim,
        "target_slot": target_slot,
        "phone": phone,
        "sms_content": content,
        "notification_id": notification_id,
    }


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
