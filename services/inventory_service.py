from __future__ import annotations

from database import row_to_dict


def _load_inventory(conn, inventory_id: int) -> dict:
    row = conn.execute(
        """
        SELECT *
        FROM inventory
        WHERE id = ?
        """,
        (inventory_id,),
    ).fetchone()
    inventory = row_to_dict(row)
    if not inventory:
        raise ValueError("库存记录不存在")
    return inventory


def _update_inventory(conn, inventory_id: int, fields: dict[str, int]) -> dict:
    conn.execute(
        """
        UPDATE inventory
        SET available_stock = ?,
            reserved_stock = ?,
            redeemed_stock = ?,
            released_stock = ?,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        (
            fields["available_stock"],
            fields["reserved_stock"],
            fields["redeemed_stock"],
            fields["released_stock"],
            inventory_id,
        ),
    )
    return _load_inventory(conn, inventory_id)


def reserve_stock(conn, inventory_id: int, quantity: int = 1) -> tuple[dict, dict]:
    before = _load_inventory(conn, inventory_id)
    if before["available_stock"] < quantity:
        raise ValueError("库存不足，无法预约")

    after_fields = {
        "available_stock": before["available_stock"] - quantity,
        "reserved_stock": before["reserved_stock"] + quantity,
        "redeemed_stock": before["redeemed_stock"],
        "released_stock": before["released_stock"],
    }
    after = _update_inventory(conn, inventory_id, after_fields)
    return before, after


def release_stock(conn, inventory_id: int, quantity: int = 1) -> tuple[dict, dict]:
    before = _load_inventory(conn, inventory_id)
    if before["reserved_stock"] < quantity:
        raise ValueError("占用库存不足，无法释放")

    after_fields = {
        "available_stock": before["available_stock"] + quantity,
        "reserved_stock": before["reserved_stock"] - quantity,
        "redeemed_stock": before["redeemed_stock"],
        "released_stock": before["released_stock"] + quantity,
    }
    after = _update_inventory(conn, inventory_id, after_fields)
    return before, after


def redeem_stock(conn, inventory_id: int, quantity: int = 1) -> tuple[dict, dict]:
    before = _load_inventory(conn, inventory_id)
    if before["reserved_stock"] < quantity:
        raise ValueError("占用库存不足，无法核销")

    after_fields = {
        "available_stock": before["available_stock"],
        "reserved_stock": before["reserved_stock"] - quantity,
        "redeemed_stock": before["redeemed_stock"] + quantity,
        "released_stock": before["released_stock"],
    }
    after = _update_inventory(conn, inventory_id, after_fields)
    return before, after


def write_inventory_log(
    conn,
    before: dict,
    after: dict,
    action: str,
    claim_id: int | None = None,
    quantity: int = 1,
    note: str | None = None,
) -> None:
    conn.execute(
        """
        INSERT INTO inventory_logs (
            activity_id, gift_id, inventory_id, claim_id, action, quantity,
            before_available, after_available,
            before_reserved, after_reserved,
            before_redeemed, after_redeemed,
            before_released, after_released,
            note
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            before["activity_id"],
            before["gift_id"],
            before["id"],
            claim_id,
            action,
            quantity,
            before["available_stock"],
            after["available_stock"],
            before["reserved_stock"],
            after["reserved_stock"],
            before["redeemed_stock"],
            after["redeemed_stock"],
            before["released_stock"],
            after["released_stock"],
            note,
        ),
    )

