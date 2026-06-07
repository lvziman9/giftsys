from __future__ import annotations

from typing import Any

from database import fetch_all, fetch_one, get_connection, row_to_dict


def create_notification(
    conn,
    employee_id: int,
    notification_type: str,
    title: str,
    content: str,
    activity_id: int | None = None,
    claim_id: int | None = None,
    target_time_slot_id: int | None = None,
    action_status: str = "none",
) -> int:
    return int(
        conn.execute(
            """
            INSERT INTO notifications (
                employee_id, type, title, content, activity_id, claim_id,
                target_time_slot_id, action_status
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                employee_id,
                notification_type,
                title,
                content,
                activity_id,
                claim_id,
                target_time_slot_id,
                action_status,
            ),
        ).lastrowid
    )


def notify_activity_published(conn, activity_id: int) -> int:
    activity = conn.execute(
        "SELECT * FROM activities WHERE id = ?",
        (activity_id,),
    ).fetchone()
    if not activity:
        return 0

    employees = conn.execute(
        """
        SELECT DISTINCT e.id
        FROM employees e
        JOIN eligibility_rules er
          ON er.activity_id = ?
         AND (er.department = e.department OR er.department = 'ALL')
        ORDER BY e.id
        """,
        (activity_id,),
    ).fetchall()

    count = 0
    for employee in employees:
        create_notification(
            conn,
            employee["id"],
            "activity_published",
            f"活动上线：{activity['name']}",
            f"{activity['start_date']} 至 {activity['end_date']} 可预约，请在员工端选择礼物和领取时间。",
            activity_id=activity_id,
        )
        count += 1
    return count


def list_notifications(employee_id: int, limit: int = 30) -> list[dict[str, Any]]:
    return fetch_all(
        """
        SELECT
            n.*,
            a.name AS activity_name,
            g.name AS gift_name,
            t.slot_date AS target_slot_date,
            t.start_time AS target_start_time,
            t.end_time AS target_end_time
        FROM notifications n
        LEFT JOIN activities a ON a.id = n.activity_id
        LEFT JOIN claims c ON c.id = n.claim_id
        LEFT JOIN gifts g ON g.id = c.gift_id
        LEFT JOIN time_slots t ON t.id = n.target_time_slot_id
        WHERE n.employee_id = ?
        ORDER BY n.id DESC
        LIMIT ?
        """,
        (employee_id, limit),
    )


def count_unread_notifications(employee_id: int) -> int:
    row = fetch_one(
        """
        SELECT COUNT(*) AS count
        FROM notifications
        WHERE employee_id = ?
          AND is_read = 0
        """,
        (employee_id,),
    )
    return int(row["count"] if row else 0)


def mark_notification_read(notification_id: int, employee_id: int) -> None:
    with get_connection() as conn:
        conn.execute(
            """
            UPDATE notifications
            SET is_read = 1,
                read_at = COALESCE(read_at, CURRENT_TIMESTAMP)
            WHERE id = ?
              AND employee_id = ?
            """,
            (notification_id, employee_id),
        )


def mark_all_notifications_read(employee_id: int) -> None:
    with get_connection() as conn:
        conn.execute(
            """
            UPDATE notifications
            SET is_read = 1,
                read_at = COALESCE(read_at, CURRENT_TIMESTAMP)
            WHERE employee_id = ?
              AND is_read = 0
            """,
            (employee_id,),
        )


def _slot_text(slot: dict[str, Any]) -> str:
    return f"{slot['slot_date']} {slot['start_time']}-{slot['end_time']}"


def respond_reschedule_notification(
    notification_id: int,
    employee_id: int,
    accepted: bool,
) -> dict[str, Any]:
    conn = get_connection()
    try:
        conn.execute("BEGIN IMMEDIATE")
        notification = row_to_dict(
            conn.execute(
                """
                SELECT *
                FROM notifications
                WHERE id = ?
                  AND employee_id = ?
                """,
                (notification_id, employee_id),
            ).fetchone()
        )
        if not notification:
            raise ValueError("通知不存在")
        if notification["type"] != "reschedule_request":
            raise ValueError("该通知不是改期请求")
        if notification["action_status"] != "pending":
            raise ValueError("该改期请求已处理")

        claim = row_to_dict(
            conn.execute(
                "SELECT * FROM claims WHERE id = ?",
                (notification["claim_id"],),
            ).fetchone()
        )
        if not claim or claim["employee_id"] != employee_id:
            raise ValueError("预约记录不存在")

        if not accepted:
            conn.execute(
                """
                UPDATE notifications
                SET is_read = 1,
                    read_at = COALESCE(read_at, CURRENT_TIMESTAMP),
                    action_status = 'declined',
                    handled_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (notification_id,),
            )
            conn.execute(
                """
                INSERT INTO operation_logs (admin_id, action, target_type, target_id, note)
                VALUES (NULL, 'decline_reschedule', 'claim', ?, ?)
                """,
                (claim["id"], f"员工 {employee_id} 不同意改期"),
            )
            conn.commit()
            return {"ok": True, "message": "已反馈暂不改期"}

        if claim["status"] != "reserved":
            raise ValueError("当前预约状态不能改期")

        target_slot = row_to_dict(
            conn.execute(
                "SELECT * FROM time_slots WHERE id = ?",
                (notification["target_time_slot_id"],),
            ).fetchone()
        )
        if not target_slot:
            raise ValueError("目标领取时间不存在")
        if target_slot["activity_id"] != claim["activity_id"]:
            raise ValueError("目标时间必须属于同一活动")
        if target_slot["building"] != claim["building"]:
            raise ValueError("目标时间必须属于同一楼宇")
        if not target_slot["is_available"]:
            raise ValueError("目标时间当前不可领取")

        target_is_current = target_slot["id"] == claim["time_slot_id"]
        if not target_is_current and target_slot["reserved_count"] >= target_slot["capacity"]:
            raise ValueError("目标时间已满员，请联系管理员重新安排")

        if not target_is_current:
            conn.execute(
                """
                UPDATE time_slots
                SET reserved_count = MAX(reserved_count - 1, 0)
                WHERE id = ?
                """,
                (claim["time_slot_id"],),
            )
            conn.execute(
                """
                UPDATE time_slots
                SET reserved_count = reserved_count + 1
                WHERE id = ?
                """,
                (target_slot["id"],),
            )
            conn.execute(
                """
                UPDATE claims
                SET time_slot_id = ?,
                    updated_at = CURRENT_TIMESTAMP,
                    notes = COALESCE(notes || char(10), '') || ?
                WHERE id = ?
                """,
                (
                    target_slot["id"],
                    f"员工同意改期至 {_slot_text(target_slot)}",
                    claim["id"],
                ),
            )

        conn.execute(
            """
            UPDATE notifications
            SET is_read = 1,
                read_at = COALESCE(read_at, CURRENT_TIMESTAMP),
                action_status = 'accepted',
                handled_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (notification_id,),
        )
        create_notification(
            conn,
            employee_id,
            "reschedule_result",
            "改期已确认",
            f"你的领取时间已改为 {_slot_text(target_slot)}。",
            activity_id=claim["activity_id"],
            claim_id=claim["id"],
        )
        conn.execute(
            """
            INSERT INTO operation_logs (admin_id, action, target_type, target_id, note)
            VALUES (NULL, 'accept_reschedule', 'claim', ?, ?)
            """,
            (claim["id"], f"员工 {employee_id} 同意改期至 {_slot_text(target_slot)}"),
        )
        conn.commit()
        return {"ok": True, "message": f"改期已确认：{_slot_text(target_slot)}"}
    except ValueError as exc:
        conn.rollback()
        return {"ok": False, "message": str(exc)}
    finally:
        conn.close()
