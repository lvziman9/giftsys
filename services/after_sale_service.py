from __future__ import annotations

from typing import Any

from database import fetch_all, fetch_one, get_connection, row_to_dict
from services.inventory_service import write_inventory_log
from services.notification_service import create_notification


AFTER_SALE_STATUS_LABELS = {
    "pending": "待处理",
    "processing": "处理中",
    "resolved": "已完成",
    "rejected": "已拒绝",
    "cancelled": "已取消",
}

AFTER_SALE_ISSUE_TYPES = {
    "damaged": "破损",
    "wrong_item": "发错礼品",
    "spec_mismatch": "规格不符",
    "unusable": "无法使用",
    "other": "其他",
}

AFTER_SALE_EXPECTED_RESOLUTIONS = {
    "exchange": "更换",
    "reissue": "补发",
    "return_register": "退回登记",
    "contact": "人工联系",
}

AFTER_SALE_INVENTORY_ACTIONS = {
    "none": "不调整库存",
    "reissue": "补发出库",
    "return_restock": "退回可再发",
    "exchange_restock": "换货：退回可再发 + 新发出库",
    "exchange_scrap": "换货：退回报废 + 新发出库",
    "return_scrap": "退回报废",
}

ACTIVE_AFTER_SALE_STATUSES = {"pending", "processing"}


def _clean_text(value: Any) -> str:
    return str(value or "").strip()


def _load_claim_for_after_sale(conn, claim_id: int) -> dict[str, Any]:
    row = conn.execute(
        """
        SELECT
            c.*,
            e.name AS employee_name,
            e.employee_no,
            e.department,
            e.phone AS employee_phone,
            a.name AS activity_name,
            g.name AS gift_name,
            t.slot_date,
            t.start_time,
            t.end_time
        FROM claims c
        JOIN employees e ON e.id = c.employee_id
        JOIN activities a ON a.id = c.activity_id
        JOIN gifts g ON g.id = c.gift_id
        JOIN time_slots t ON t.id = c.time_slot_id
        WHERE c.id = ?
        """,
        (claim_id,),
    ).fetchone()
    claim = row_to_dict(row)
    if not claim:
        raise ValueError("领取记录不存在")
    return claim


def _load_after_sale(conn, after_sale_id: int) -> dict[str, Any]:
    row = conn.execute(
        "SELECT * FROM after_sales WHERE id = ?",
        (after_sale_id,),
    ).fetchone()
    after_sale = row_to_dict(row)
    if not after_sale:
        raise ValueError("售后单不存在")
    return after_sale


def _load_inventory(conn, inventory_id: int) -> dict[str, Any]:
    row = conn.execute(
        "SELECT * FROM inventory WHERE id = ?",
        (inventory_id,),
    ).fetchone()
    inventory = row_to_dict(row)
    if not inventory:
        raise ValueError("库存记录不存在")
    return inventory


def _update_inventory(
    conn,
    inventory_id: int,
    available_stock: int,
    redeemed_stock: int,
) -> dict[str, Any]:
    if available_stock < 0:
        raise ValueError("可用库存不足，无法完成该售后库存动作")
    if redeemed_stock < 0:
        raise ValueError("已发放库存不足，无法完成该售后库存动作")

    conn.execute(
        """
        UPDATE inventory
        SET available_stock = ?,
            redeemed_stock = ?,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        (available_stock, redeemed_stock, inventory_id),
    )
    return _load_inventory(conn, inventory_id)


def _inventory_out(conn, inventory_id: int, action: str, claim_id: int, note: str) -> None:
    before = _load_inventory(conn, inventory_id)
    if before["available_stock"] < 1:
        raise ValueError("可用库存不足，无法完成补发或换货出库")

    after = _update_inventory(
        conn,
        inventory_id,
        available_stock=before["available_stock"] - 1,
        redeemed_stock=before["redeemed_stock"] + 1,
    )
    write_inventory_log(conn, before, after, action, claim_id=claim_id, note=note)


def _inventory_return_restock(conn, inventory_id: int, claim_id: int, note: str) -> None:
    before = _load_inventory(conn, inventory_id)
    if before["redeemed_stock"] < 1:
        raise ValueError("已发放库存不足，无法退回入库")

    after = _update_inventory(
        conn,
        inventory_id,
        available_stock=before["available_stock"] + 1,
        redeemed_stock=before["redeemed_stock"] - 1,
    )
    write_inventory_log(
        conn,
        before,
        after,
        "after_sale_return_restock",
        claim_id=claim_id,
        note=note,
    )


def _inventory_scrap(conn, inventory_id: int, claim_id: int, note: str) -> None:
    before = _load_inventory(conn, inventory_id)
    write_inventory_log(
        conn,
        before,
        before,
        "after_sale_scrap",
        claim_id=claim_id,
        note=note,
    )


def _apply_inventory_action(
    conn,
    after_sale: dict[str, Any],
    inventory_action: str,
    admin_note: str,
) -> None:
    claim_id = int(after_sale["claim_id"])
    inventory_id = int(after_sale["inventory_id"])
    note = admin_note or AFTER_SALE_INVENTORY_ACTIONS[inventory_action]

    if inventory_action == "none":
        return
    if inventory_action == "reissue":
        _inventory_out(conn, inventory_id, "after_sale_reissue", claim_id, note)
        return
    if inventory_action == "return_restock":
        _inventory_return_restock(conn, inventory_id, claim_id, note)
        return
    if inventory_action == "exchange_restock":
        _inventory_return_restock(conn, inventory_id, claim_id, f"{note} / 退回可再发")
        _inventory_out(conn, inventory_id, "after_sale_exchange_out", claim_id, f"{note} / 换货出库")
        return
    if inventory_action == "exchange_scrap":
        _inventory_scrap(conn, inventory_id, claim_id, f"{note} / 退回报废")
        _inventory_out(conn, inventory_id, "after_sale_exchange_out", claim_id, f"{note} / 换货出库")
        return
    if inventory_action == "return_scrap":
        _inventory_scrap(conn, inventory_id, claim_id, note)
        return

    raise ValueError("售后库存动作无效")


def _after_sale_detail_sql(where: str = "") -> str:
    return f"""
        SELECT
            s.*,
            e.name AS employee_name,
            e.employee_no,
            e.department,
            a.name AS activity_name,
            g.name AS gift_name,
            c.claim_code,
            c.building,
            t.slot_date,
            t.start_time,
            t.end_time,
            i.available_stock,
            i.redeemed_stock
        FROM after_sales s
        JOIN employees e ON e.id = s.employee_id
        JOIN activities a ON a.id = s.activity_id
        JOIN gifts g ON g.id = s.gift_id
        JOIN claims c ON c.id = s.claim_id
        JOIN time_slots t ON t.id = c.time_slot_id
        JOIN inventory i ON i.id = s.inventory_id
        {where}
    """


def get_after_sale(after_sale_id: int) -> dict[str, Any] | None:
    return fetch_one(
        _after_sale_detail_sql("WHERE s.id = ?"),
        (after_sale_id,),
    )


def list_after_sales_for_employee(employee_id: int) -> list[dict[str, Any]]:
    return fetch_all(
        _after_sale_detail_sql("WHERE s.employee_id = ? ORDER BY s.id DESC"),
        (employee_id,),
    )


def list_after_sales_for_admin(
    activity_id: int | None = None,
    status: str | None = None,
    keyword: str = "",
) -> list[dict[str, Any]]:
    params: list[Any] = []
    where_parts: list[str] = []
    if activity_id:
        where_parts.append("s.activity_id = ?")
        params.append(activity_id)
    if status and status != "all":
        where_parts.append("s.status = ?")
        params.append(status)

    clean_keyword = _clean_text(keyword)
    if clean_keyword:
        where_parts.append(
            "(e.name LIKE ? OR e.employee_no LIKE ? OR g.name LIKE ? OR c.claim_code LIKE ?)"
        )
        like_value = f"%{clean_keyword}%"
        params.extend([like_value, like_value, like_value, like_value])

    where = f"WHERE {' AND '.join(where_parts)}" if where_parts else ""
    return fetch_all(
        _after_sale_detail_sql(f"{where} ORDER BY s.id DESC"),
        tuple(params),
    )


def get_active_after_sale_by_claim(claim_id: int) -> dict[str, Any] | None:
    return fetch_one(
        """
        SELECT *
        FROM after_sales
        WHERE claim_id = ?
          AND status IN ('pending', 'processing')
        ORDER BY id DESC
        LIMIT 1
        """,
        (claim_id,),
    )


def list_after_sales_by_claims(claim_ids: list[int]) -> dict[int, dict[str, Any]]:
    if not claim_ids:
        return {}
    placeholders = ",".join("?" for _ in claim_ids)
    rows = fetch_all(
        f"""
        SELECT *
        FROM after_sales
        WHERE claim_id IN ({placeholders})
        ORDER BY id DESC
        """,
        tuple(claim_ids),
    )
    result: dict[int, dict[str, Any]] = {}
    for row in rows:
        result.setdefault(row["claim_id"], row)
    return result


def create_after_sale(
    claim_id: int,
    employee_id: int,
    issue_type: str,
    expected_resolution: str,
    description: str,
    contact_phone: str,
) -> dict[str, Any]:
    if issue_type not in AFTER_SALE_ISSUE_TYPES:
        raise ValueError("售后类型无效")
    if expected_resolution not in AFTER_SALE_EXPECTED_RESOLUTIONS:
        raise ValueError("期望处理方式无效")

    clean_description = _clean_text(description)
    if not clean_description:
        raise ValueError("问题描述不能为空")
    clean_phone = _clean_text(contact_phone)
    if not clean_phone:
        raise ValueError("联系方式不能为空")

    with get_connection() as conn:
        claim = _load_claim_for_after_sale(conn, claim_id)
        if claim["employee_id"] != employee_id:
            raise ValueError("只能为自己的领取记录申请售后")
        if claim["status"] != "redeemed":
            raise ValueError("只有已核销记录可以申请售后")

        existing = conn.execute(
            """
            SELECT *
            FROM after_sales
            WHERE claim_id = ?
            LIMIT 1
            """,
            (claim_id,),
        ).fetchone()
        if existing:
            raise ValueError("该领取记录已经提交过售后")

        after_sale_id = conn.execute(
            """
            INSERT INTO after_sales (
                claim_id, employee_id, activity_id, gift_id, inventory_id,
                issue_type, expected_resolution, description, contact_phone, status
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending')
            """,
            (
                claim_id,
                employee_id,
                claim["activity_id"],
                claim["gift_id"],
                claim["inventory_id"],
                issue_type,
                expected_resolution,
                clean_description,
                clean_phone,
            ),
        ).lastrowid
        create_notification(
            conn,
            employee_id,
            "after_sale_submitted",
            "售后申请已提交",
            f"{claim['activity_name']} / {claim['gift_name']} 的售后申请已提交，请等待管理员处理。",
            activity_id=claim["activity_id"],
            claim_id=claim_id,
        )

    return get_after_sale(int(after_sale_id)) or {}


def cancel_after_sale(after_sale_id: int, employee_id: int) -> dict[str, Any]:
    with get_connection() as conn:
        after_sale = _load_after_sale(conn, after_sale_id)
        if after_sale["employee_id"] != employee_id:
            raise ValueError("只能取消自己的售后申请")
        if after_sale["status"] != "pending":
            raise ValueError("只有待处理售后可以取消")

        conn.execute(
            """
            UPDATE after_sales
            SET status = 'cancelled',
                cancelled_at = CURRENT_TIMESTAMP,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (after_sale_id,),
        )
        create_notification(
            conn,
            employee_id,
            "after_sale_cancelled",
            "售后申请已取消",
            f"售后单 AS-{after_sale_id:05d} 已取消。",
            activity_id=after_sale["activity_id"],
            claim_id=after_sale["claim_id"],
        )

    return get_after_sale(after_sale_id) or {}


def mark_after_sale_processing(
    after_sale_id: int,
    admin_note: str = "",
    admin_id: int | None = None,
) -> dict[str, Any]:
    with get_connection() as conn:
        after_sale = _load_after_sale(conn, after_sale_id)
        if after_sale["status"] != "pending":
            raise ValueError("只有待处理售后可以标记处理中")

        note = _clean_text(admin_note)
        conn.execute(
            """
            UPDATE after_sales
            SET status = 'processing',
                admin_note = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (note, after_sale_id),
        )
        create_notification(
            conn,
            after_sale["employee_id"],
            "after_sale_processing",
            "售后处理中",
            f"售后单 AS-{after_sale_id:05d} 已进入处理中。",
            activity_id=after_sale["activity_id"],
            claim_id=after_sale["claim_id"],
        )
        conn.execute(
            """
            INSERT INTO operation_logs (admin_id, action, target_type, target_id, note)
            VALUES (?, 'after_sale_processing', 'after_sale', ?, ?)
            """,
            (admin_id, after_sale_id, note or "售后标记处理中"),
        )

    return get_after_sale(after_sale_id) or {}


def reject_after_sale(
    after_sale_id: int,
    admin_note: str,
    admin_id: int | None = None,
) -> dict[str, Any]:
    note = _clean_text(admin_note)
    if not note:
        raise ValueError("拒绝售后时需要填写处理备注")

    with get_connection() as conn:
        after_sale = _load_after_sale(conn, after_sale_id)
        if after_sale["status"] not in {"pending", "processing"}:
            raise ValueError("当前售后状态不能拒绝")

        conn.execute(
            """
            UPDATE after_sales
            SET status = 'rejected',
                admin_note = ?,
                rejected_at = CURRENT_TIMESTAMP,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (note, after_sale_id),
        )
        create_notification(
            conn,
            after_sale["employee_id"],
            "after_sale_rejected",
            "售后申请被拒绝",
            f"售后单 AS-{after_sale_id:05d} 已被拒绝：{note}",
            activity_id=after_sale["activity_id"],
            claim_id=after_sale["claim_id"],
        )
        conn.execute(
            """
            INSERT INTO operation_logs (admin_id, action, target_type, target_id, note)
            VALUES (?, 'after_sale_rejected', 'after_sale', ?, ?)
            """,
            (admin_id, after_sale_id, note),
        )

    return get_after_sale(after_sale_id) or {}


def resolve_after_sale(
    after_sale_id: int,
    inventory_action: str,
    admin_note: str = "",
    admin_id: int | None = None,
) -> dict[str, Any]:
    if inventory_action not in AFTER_SALE_INVENTORY_ACTIONS:
        raise ValueError("售后库存动作无效")

    with get_connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
            after_sale = _load_after_sale(conn, after_sale_id)
            if after_sale["status"] not in {"pending", "processing"}:
                raise ValueError("当前售后状态不能完成")

            note = _clean_text(admin_note)
            _apply_inventory_action(conn, after_sale, inventory_action, note)
            action_label = AFTER_SALE_INVENTORY_ACTIONS[inventory_action]
            conn.execute(
                """
                UPDATE after_sales
                SET status = 'resolved',
                    inventory_action = ?,
                    admin_note = ?,
                    resolved_at = CURRENT_TIMESTAMP,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (inventory_action, note, after_sale_id),
            )
            create_notification(
                conn,
                after_sale["employee_id"],
                "after_sale_resolved",
                "售后已完成",
                f"售后单 AS-{after_sale_id:05d} 已完成，库存处理：{action_label}。",
                activity_id=after_sale["activity_id"],
                claim_id=after_sale["claim_id"],
            )
            conn.execute(
                """
                INSERT INTO operation_logs (admin_id, action, target_type, target_id, note)
                VALUES (?, 'after_sale_resolved', 'after_sale', ?, ?)
                """,
                (admin_id, after_sale_id, f"{action_label} / {note or '售后完成'}"),
            )
            conn.commit()
        except ValueError:
            conn.rollback()
            raise

    return get_after_sale(after_sale_id) or {}
