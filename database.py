import sqlite3
from typing import Any

from config import DATA_DIR, DB_PATH


def get_connection() -> sqlite3.Connection:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def row_to_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return dict(row)


def rows_to_dicts(rows: list[sqlite3.Row]) -> list[dict[str, Any]]:
    return [dict(row) for row in rows]


def fetch_one(sql: str, params: tuple[Any, ...] = ()) -> dict[str, Any] | None:
    with get_connection() as conn:
        row = conn.execute(sql, params).fetchone()
    return row_to_dict(row)


def fetch_all(sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    with get_connection() as conn:
        rows = conn.execute(sql, params).fetchall()
    return rows_to_dicts(rows)


def init_db() -> None:
    with get_connection() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS employees (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                employee_no TEXT NOT NULL UNIQUE,
                name TEXT NOT NULL,
                department TEXT NOT NULL,
                level TEXT,
                phone TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS admins (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL UNIQUE,
                password TEXT NOT NULL,
                display_name TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS buildings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                address TEXT NOT NULL DEFAULT '',
                pickup_location TEXT NOT NULL DEFAULT '',
                manager_name TEXT NOT NULL DEFAULT '',
                manager_contact TEXT NOT NULL DEFAULT '',
                backup_manager TEXT NOT NULL DEFAULT '',
                note TEXT NOT NULL DEFAULT '',
                sort_order INTEGER NOT NULL DEFAULT 0,
                is_active INTEGER NOT NULL DEFAULT 1,
                updated_at TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS activities (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                activity_type TEXT NOT NULL DEFAULT '节日福利',
                description TEXT,
                start_date TEXT NOT NULL,
                end_date TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'draft',
                allow_cancel INTEGER NOT NULL DEFAULT 1,
                expire_release INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                published_at TEXT
            );

            CREATE TABLE IF NOT EXISTS gifts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                activity_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                spec TEXT NOT NULL,
                category TEXT NOT NULL DEFAULT '其他',
                image_url TEXT,
                total_stock INTEGER NOT NULL DEFAULT 0,
                unit_price REAL,
                per_person_limit INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (activity_id) REFERENCES activities(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS eligibility_rules (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                activity_id INTEGER NOT NULL,
                department TEXT NOT NULL,
                gift_id INTEGER NOT NULL,
                rule_type TEXT NOT NULL DEFAULT 'department',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (activity_id) REFERENCES activities(id) ON DELETE CASCADE,
                FOREIGN KEY (gift_id) REFERENCES gifts(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS inventory (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                activity_id INTEGER NOT NULL,
                gift_id INTEGER NOT NULL,
                building TEXT NOT NULL,
                total_stock INTEGER NOT NULL DEFAULT 0,
                available_stock INTEGER NOT NULL DEFAULT 0,
                reserved_stock INTEGER NOT NULL DEFAULT 0,
                redeemed_stock INTEGER NOT NULL DEFAULT 0,
                released_stock INTEGER NOT NULL DEFAULT 0,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (activity_id) REFERENCES activities(id) ON DELETE CASCADE,
                FOREIGN KEY (gift_id) REFERENCES gifts(id) ON DELETE CASCADE,
                UNIQUE (activity_id, gift_id, building)
            );

            CREATE TABLE IF NOT EXISTS time_slots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                activity_id INTEGER NOT NULL,
                building TEXT NOT NULL,
                slot_date TEXT NOT NULL,
                start_time TEXT NOT NULL,
                end_time TEXT NOT NULL,
                capacity INTEGER NOT NULL DEFAULT 25,
                reserved_count INTEGER NOT NULL DEFAULT 0,
                is_available INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (activity_id) REFERENCES activities(id) ON DELETE CASCADE,
                UNIQUE (activity_id, building, slot_date, start_time, end_time)
            );

            CREATE TABLE IF NOT EXISTS claims (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                activity_id INTEGER NOT NULL,
                employee_id INTEGER NOT NULL,
                gift_id INTEGER NOT NULL,
                inventory_id INTEGER NOT NULL,
                time_slot_id INTEGER NOT NULL,
                building TEXT NOT NULL,
                status TEXT NOT NULL CHECK (
                    status IN ('reserved', 'cancelled', 'redeemed', 'expired', 'rejected')
                ),
                claim_code TEXT NOT NULL UNIQUE,
                reserved_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                cancelled_at TEXT,
                redeemed_at TEXT,
                expired_at TEXT,
                rejected_at TEXT,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                notes TEXT,
                FOREIGN KEY (activity_id) REFERENCES activities(id) ON DELETE CASCADE,
                FOREIGN KEY (employee_id) REFERENCES employees(id) ON DELETE CASCADE,
                FOREIGN KEY (gift_id) REFERENCES gifts(id) ON DELETE CASCADE,
                FOREIGN KEY (inventory_id) REFERENCES inventory(id) ON DELETE CASCADE,
                FOREIGN KEY (time_slot_id) REFERENCES time_slots(id) ON DELETE CASCADE
            );

            CREATE UNIQUE INDEX IF NOT EXISTS idx_claims_active_employee_activity
            ON claims (activity_id, employee_id)
            WHERE status = 'reserved';

            CREATE INDEX IF NOT EXISTS idx_claims_code ON claims (claim_code);
            CREATE INDEX IF NOT EXISTS idx_claims_status ON claims (status);

            CREATE TABLE IF NOT EXISTS inventory_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                activity_id INTEGER NOT NULL,
                gift_id INTEGER NOT NULL,
                inventory_id INTEGER NOT NULL,
                claim_id INTEGER,
                action TEXT NOT NULL,
                quantity INTEGER NOT NULL DEFAULT 1,
                before_available INTEGER NOT NULL,
                after_available INTEGER NOT NULL,
                before_reserved INTEGER NOT NULL,
                after_reserved INTEGER NOT NULL,
                before_redeemed INTEGER NOT NULL,
                after_redeemed INTEGER NOT NULL,
                before_released INTEGER NOT NULL,
                after_released INTEGER NOT NULL,
                note TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (activity_id) REFERENCES activities(id) ON DELETE CASCADE,
                FOREIGN KEY (gift_id) REFERENCES gifts(id) ON DELETE CASCADE,
                FOREIGN KEY (inventory_id) REFERENCES inventory(id) ON DELETE CASCADE,
                FOREIGN KEY (claim_id) REFERENCES claims(id) ON DELETE SET NULL
            );

            CREATE TABLE IF NOT EXISTS operation_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                admin_id INTEGER,
                action TEXT NOT NULL,
                target_type TEXT NOT NULL,
                target_id INTEGER,
                note TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (admin_id) REFERENCES admins(id) ON DELETE SET NULL
            );

            CREATE TABLE IF NOT EXISTS notifications (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                employee_id INTEGER NOT NULL,
                type TEXT NOT NULL,
                title TEXT NOT NULL,
                content TEXT NOT NULL,
                activity_id INTEGER,
                claim_id INTEGER,
                target_time_slot_id INTEGER,
                is_read INTEGER NOT NULL DEFAULT 0,
                action_status TEXT NOT NULL DEFAULT 'none',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                read_at TEXT,
                handled_at TEXT,
                FOREIGN KEY (employee_id) REFERENCES employees(id) ON DELETE CASCADE,
                FOREIGN KEY (activity_id) REFERENCES activities(id) ON DELETE CASCADE,
                FOREIGN KEY (claim_id) REFERENCES claims(id) ON DELETE CASCADE,
                FOREIGN KEY (target_time_slot_id) REFERENCES time_slots(id) ON DELETE SET NULL
            );

            CREATE INDEX IF NOT EXISTS idx_notifications_employee
            ON notifications (employee_id, is_read, id);
            """
        )
        _ensure_column(conn, "time_slots", "is_available", "INTEGER NOT NULL DEFAULT 1")
        _ensure_column(conn, "buildings", "address", "TEXT NOT NULL DEFAULT ''")
        _ensure_column(conn, "buildings", "pickup_location", "TEXT NOT NULL DEFAULT ''")
        _ensure_column(conn, "buildings", "manager_name", "TEXT NOT NULL DEFAULT ''")
        _ensure_column(conn, "buildings", "manager_contact", "TEXT NOT NULL DEFAULT ''")
        _ensure_column(conn, "buildings", "backup_manager", "TEXT NOT NULL DEFAULT ''")
        _ensure_column(conn, "buildings", "note", "TEXT NOT NULL DEFAULT ''")
        _ensure_column(conn, "buildings", "sort_order", "INTEGER NOT NULL DEFAULT 0")
        _ensure_column(conn, "buildings", "updated_at", "TEXT")


def _ensure_column(
    conn: sqlite3.Connection,
    table: str,
    column: str,
    definition: str,
) -> None:
    columns = [row["name"] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()]
    if column not in columns:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


if __name__ == "__main__":
    init_db()
    print(f"Database initialized at {DB_PATH}")
