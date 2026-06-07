from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
DB_PATH = DATA_DIR / "giftflow.db"

APP_NAME = "GiftFlow 福利领取系统"
ADMIN_PASSWORD = "admin123"

BUILDINGS = ["A楼", "B楼", "C楼"]
DEFAULT_SLOT_CAPACITY = 25
DEFAULT_TIME_RANGES = [
    ("10:00", "11:00"),
    ("11:00", "12:00"),
    ("12:00", "12:30"),
    ("14:00", "15:00"),
    ("15:00", "16:00"),
    ("16:00", "17:00"),
    ("17:00", "18:00"),
    ("18:00", "18:30"),
]

STATUS_RESERVED = "reserved"
STATUS_CANCELLED = "cancelled"
STATUS_REDEEMED = "redeemed"
STATUS_EXPIRED = "expired"
STATUS_REJECTED = "rejected"

BLOCKING_CLAIM_STATUSES = (STATUS_RESERVED, STATUS_REDEEMED, STATUS_REJECTED)
CANCELLABLE_CLAIM_STATUSES = (STATUS_RESERVED,)

CLAIM_STATUS_LABELS = {
    STATUS_RESERVED: "已预约",
    STATUS_CANCELLED: "已取消",
    STATUS_REDEEMED: "已核销",
    STATUS_EXPIRED: "已过期",
    STATUS_REJECTED: "已拒绝",
}
