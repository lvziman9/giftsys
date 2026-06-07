from __future__ import annotations

from typing import Any

from config import BLOCKING_CLAIM_STATUSES, STATUS_RESERVED
from database import fetch_one, get_connection, row_to_dict
from services.inventory_service import (
    redeem_stock,
    release_stock,
    reserve_stock,
    write_inventory_log,
)
from utils.codegen import generate_claim_code


def get_claim_by_id(claim_id: int) -> dict[str, Any] | None:
    return fetch_one(
        """
        SELECT
            c.*,
            a.name AS activity_name,
            g.name AS gift_name,
            g.spec AS gift_spec,
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
        WHERE c.id = ?
        """,
        (claim_id,),
    )


def _generate_unique_claim_code(conn) -> str:
    for _ in range(20):
        code = generate_claim_code()
        exists = conn.execute("SELECT 1 FROM claims WHERE claim_code = ?", (code,)).fetchone()
        if not exists:
            return code
    raise ValueError("无法生成唯一凭证码，请重试")


def _check_eligibility(conn, employee_id: int, activity_id: int, gift_id: int) -> None:
    row = conn.execute(
        """
        SELECT 1
        FROM employees e
        JOIN eligibility_rules er
          ON er.activity_id = ?
         AND er.gift_id = ?
         AND (er.department = e.department OR er.department = 'ALL')
        WHERE e.id = ?
        LIMIT 1
        """,
        (activity_id, gift_id, employee_id),
    ).fetchone()
    if not row:
        raise ValueError("当前员工没有领取该礼物的资格")


def create_claim(
    employee_id: int,
    activity_id: int,
    gift_id: int,
    building: str,
    time_slot_id: int,
) -> dict[str, Any]:
    conn = get_connection()
    try:
        conn.execute("BEGIN IMMEDIATE")

        blocking_statuses = ",".join("?" for _ in BLOCKING_CLAIM_STATUSES)
        existing = conn.execute(
            f"""
            SELECT status
            FROM claims
            WHERE activity_id = ?
              AND employee_id = ?
              AND status IN ({blocking_statuses})
            ORDER BY id DESC
            LIMIT 1
            """,
            (activity_id, employee_id, *BLOCKING_CLAIM_STATUSES),
        ).fetchone()
        if existing:
            if existing["status"] == "reserved":
                raise ValueError("你已经预约过该活动，不能重复预约")
            if existing["status"] == "redeemed":
                raise ValueError("你已经领取过该活动福利")
            raise ValueError("该活动已有最终处理记录，不能重新预约")

        _check_eligibility(conn, employee_id, activity_id, gift_id)

        inventory = conn.execute(
            """
            SELECT *
            FROM inventory
            WHERE activity_id = ? AND gift_id = ? AND building = ?
            """,
            (activity_id, gift_id, building),
        ).fetchone()
        if not inventory:
            raise ValueError("所选楼栋没有该礼物库存")

        slot = conn.execute(
            """
            SELECT *
            FROM time_slots
            WHERE id = ? AND activity_id = ? AND building = ?
            """,
            (time_slot_id, activity_id, building),
        ).fetchone()
        if not slot:
            raise ValueError("所选时间段无效")
        if not slot["is_available"]:
            raise ValueError("所选时间段当前不可领取")
        if slot["reserved_count"] >= slot["capacity"]:
            raise ValueError("所选时间段已满，请选择其他时间")

        before, after = reserve_stock(conn, inventory["id"], quantity=1)
        conn.execute(
            """
            UPDATE time_slots
            SET reserved_count = reserved_count + 1
            WHERE id = ?
            """,
            (time_slot_id,),
        )

        claim_code = _generate_unique_claim_code(conn)
        claim_id = conn.execute(
            """
            INSERT INTO claims (
                activity_id, employee_id, gift_id, inventory_id, time_slot_id,
                building, status, claim_code
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                activity_id,
                employee_id,
                gift_id,
                inventory["id"],
                time_slot_id,
                building,
                STATUS_RESERVED,
                claim_code,
            ),
        ).lastrowid
        write_inventory_log(conn, before, after, "reserve", claim_id, note="员工预约占用库存")

        conn.commit()
        return {"ok": True, "message": "预约成功", "claim": get_claim_by_id(claim_id)}
    except ValueError as exc:
        conn.rollback()
        return {"ok": False, "message": str(exc)}
    finally:
        conn.close()


def cancel_claim(claim_id: int, employee_id: int | None = None) -> dict[str, Any]:
    conn = get_connection()
    try:
        conn.execute("BEGIN IMMEDIATE")
        claim = conn.execute("SELECT * FROM claims WHERE id = ?", (claim_id,)).fetchone()
        claim_dict = row_to_dict(claim)
        if not claim_dict:
            raise ValueError("领取记录不存在")
        if employee_id and claim_dict["employee_id"] != employee_id:
            raise ValueError("只能取消自己的预约")
        if claim_dict["status"] != "reserved":
            raise ValueError("只有已预约状态可以取消")

        before, after = release_stock(conn, claim_dict["inventory_id"], quantity=1)
        conn.execute(
            """
            UPDATE time_slots
            SET reserved_count = MAX(reserved_count - 1, 0)
            WHERE id = ?
            """,
            (claim_dict["time_slot_id"],),
        )
        conn.execute(
            """
            UPDATE claims
            SET status = 'cancelled',
                cancelled_at = CURRENT_TIMESTAMP,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (claim_id,),
        )
        write_inventory_log(conn, before, after, "cancel", claim_id, note="员工取消预约释放库存")
        conn.commit()
        return {"ok": True, "message": "预约已取消"}
    except ValueError as exc:
        conn.rollback()
        return {"ok": False, "message": str(exc)}
    finally:
        conn.close()


def expire_claim(claim_id: int) -> dict[str, Any]:
    conn = get_connection()
    try:
        conn.execute("BEGIN IMMEDIATE")
        claim = conn.execute("SELECT * FROM claims WHERE id = ?", (claim_id,)).fetchone()
        claim_dict = row_to_dict(claim)
        if not claim_dict:
            raise ValueError("领取记录不存在")
        if claim_dict["status"] != "reserved":
            raise ValueError("只有已预约状态可以过期释放")

        before, after = release_stock(conn, claim_dict["inventory_id"], quantity=1)
        conn.execute(
            """
            UPDATE time_slots
            SET reserved_count = MAX(reserved_count - 1, 0)
            WHERE id = ?
            """,
            (claim_dict["time_slot_id"],),
        )
        conn.execute(
            """
            UPDATE claims
            SET status = 'expired',
                expired_at = CURRENT_TIMESTAMP,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (claim_id,),
        )
        write_inventory_log(conn, before, after, "expire", claim_id, note="过期未领取释放库存")
        conn.commit()
        return {"ok": True, "message": "预约已标记为过期并释放库存"}
    except ValueError as exc:
        conn.rollback()
        return {"ok": False, "message": str(exc)}
    finally:
        conn.close()


def redeem_claim_by_code(claim_code: str, admin_id: int | None = None) -> dict[str, Any]:
    normalized_code = claim_code.strip().upper()
    conn = get_connection()
    try:
        conn.execute("BEGIN IMMEDIATE")
        claim = conn.execute(
            """
            SELECT *
            FROM claims
            WHERE claim_code = ?
            """,
            (normalized_code,),
        ).fetchone()
        claim_dict = row_to_dict(claim)
        if not claim_dict:
            raise ValueError("验证码错误，未找到对应预约")
        if claim_dict["status"] == "redeemed":
            raise ValueError("该凭证已核销，不能重复核销")
        if claim_dict["status"] == "cancelled":
            raise ValueError("该预约已取消，不能核销")
        if claim_dict["status"] == "expired":
            raise ValueError("该预约已过期，不能核销")
        if claim_dict["status"] == "rejected":
            raise ValueError("该预约已拒绝，不能核销")

        before, after = redeem_stock(conn, claim_dict["inventory_id"], quantity=1)
        conn.execute(
            """
            UPDATE claims
            SET status = 'redeemed',
                redeemed_at = CURRENT_TIMESTAMP,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (claim_dict["id"],),
        )
        write_inventory_log(conn, before, after, "redeem", claim_dict["id"], note="管理员现场核销")
        conn.execute(
            """
            INSERT INTO operation_logs (admin_id, action, target_type, target_id, note)
            VALUES (?, 'redeem_claim', 'claim', ?, ?)
            """,
            (admin_id, claim_dict["id"], f"核销凭证 {normalized_code}"),
        )
        conn.commit()
        return {"ok": True, "message": "核销成功", "claim": get_claim_by_id(claim_dict["id"])}
    except ValueError as exc:
        conn.rollback()
        return {"ok": False, "message": str(exc)}
    finally:
        conn.close()
