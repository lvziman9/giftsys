from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from config import BASE_DIR, BUILDINGS
from services.nl_parser import parse_activity_text as parse_with_rules


AI_API_KEY = os.getenv("GIFTSYS_AI_API_KEY") or os.getenv("OPENAI_API_KEY")
AI_BASE_URL = os.getenv("GIFTSYS_AI_BASE_URL", "https://api.openai.com/v1").rstrip("/")
AI_MODEL = os.getenv("GIFTSYS_AI_MODEL", "gpt-4o-mini")
AI_TIMEOUT_SECONDS = float(os.getenv("GIFTSYS_AI_TIMEOUT_SECONDS", "15"))

GEMINI_API_KEY_FILE = Path(
    os.getenv("GIFTSYS_GEMINI_API_KEY_FILE", BASE_DIR / ".secrets" / "google_ai_studio_api_key.txt")
)
GEMINI_API_KEY = (
    os.getenv("GIFTSYS_GEMINI_API_KEY")
    or os.getenv("GOOGLE_AI_STUDIO_API_KEY")
    or os.getenv("GEMINI_API_KEY")
)
GEMINI_MODEL = os.getenv("GIFTSYS_GEMINI_MODEL", "gemini-3.5-flash")
GEMINI_BASE_URL = os.getenv(
    "GIFTSYS_GEMINI_BASE_URL",
    "https://generativelanguage.googleapis.com/v1beta",
).rstrip("/")


SYSTEM_PROMPT = """
你是 GiftFlow 福利领取系统的活动配置解析助手。
你的任务是把行政人员粘贴的福利活动文案转换为严格 JSON。

只返回 JSON，不要返回 Markdown，不要解释。

目标 JSON 结构：
{
  "activity": {
    "name": "活动名称",
    "activity_type": "节日福利",
    "description": "原始活动说明或整理后的说明",
    "start_date": "yyyy-mm-dd",
    "end_date": "yyyy-mm-dd",
    "allow_cancel": true,
    "expire_release": true
  },
  "gift_rules": [
    {
      "name": "礼物名称",
      "department": "技术部/销售部/全员等",
      "total_stock": 30,
      "description": "礼物说明",
      "building_allocation": {
        "A楼": 50,
        "B楼": 30,
        "C楼": 20
      },
      "per_person_limit": 1
    }
  ]
}

规则：
1. 日期必须输出 yyyy-mm-dd。
2. 如果文案没有说明年份，使用当前年份。
3. 如果文案没有说明部门，department 使用“全员”。
4. 如果文案没有说明库存，请根据礼物类型给出合理初始值，后续管理员会人工确认。
5. 如果文案没有说明楼宇分配，使用 A楼 50%、B楼 30%、C楼 20%。
6. building_allocation 的百分比合计必须等于 100。
7. 不输出 timeslots，系统会根据活动日期自动生成默认领取时间段。
8. 不要输出 null，不确定的信息用可人工修改的合理默认值。
""".strip()


def _source_text(text: str) -> str:
    source = text.strip()
    if source:
        return source
    return (
        "2026年端午福利，技术部可选机械键盘或降噪耳机，销售部领取500元购物卡，"
        "全员可领零食大礼包。A楼分配50%，B楼30%，C楼20%。"
        "活动日期为6月8日到6月10日。"
    )


def _today_context() -> str:
    today = date.today()
    return f"当前日期：{today.isoformat()}；当前年份：{today.year}。"


def _chat_completion_payload(source: str) -> dict[str, Any]:
    return {
        "model": AI_MODEL,
        "temperature": 0.1,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": f"{_today_context()}\n\n活动文案：\n{source}",
            },
        ],
    }


def _gemini_api_key() -> str | None:
    if GEMINI_API_KEY:
        return GEMINI_API_KEY.strip()
    try:
        key = GEMINI_API_KEY_FILE.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return key or None


def _gemini_payload(source: str) -> dict[str, Any]:
    return {
        "systemInstruction": {
            "parts": [{"text": SYSTEM_PROMPT}],
        },
        "contents": [
            {
                "role": "user",
                "parts": [{"text": f"{_today_context()}\n\n活动文案：\n{source}"}],
            }
        ],
        "generationConfig": {
            "temperature": 0.1,
            "responseMimeType": "application/json",
        },
    }


def _request_gemini_config(source: str) -> dict[str, Any]:
    api_key = _gemini_api_key()
    if not api_key:
        raise ValueError("未配置 Google AI Studio API Key")

    body = json.dumps(_gemini_payload(source), ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        f"{GEMINI_BASE_URL}/models/{GEMINI_MODEL}:generateContent?key={api_key}",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=AI_TIMEOUT_SECONDS) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise ValueError(f"Gemini 快速配置调用失败：{exc}") from exc

    try:
        parts = payload["candidates"][0]["content"]["parts"]
        content = "".join(str(part.get("text", "")) for part in parts)
    except (KeyError, IndexError, TypeError) as exc:
        raise ValueError("Gemini 快速配置返回格式无效") from exc

    return _loads_json_object(content)


def _request_openai_config(source: str) -> dict[str, Any]:
    if not AI_API_KEY:
        raise ValueError("未配置 AI API Key")

    body = json.dumps(_chat_completion_payload(source), ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        f"{AI_BASE_URL}/chat/completions",
        data=body,
        headers={
            "Authorization": f"Bearer {AI_API_KEY}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=AI_TIMEOUT_SECONDS) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise ValueError(f"AI 快速配置调用失败：{exc}") from exc

    try:
        content = payload["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise ValueError("AI 快速配置返回格式无效") from exc

    return _loads_json_object(str(content))


def _loads_json_object(content: str) -> dict[str, Any]:
    cleaned = content.strip()
    fenced = re.search(r"```(?:json)?\s*(.*?)```", cleaned, flags=re.S)
    if fenced:
        cleaned = fenced.group(1).strip()

    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError:
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start < 0 or end < start:
            raise
        parsed = json.loads(cleaned[start : end + 1])

    if not isinstance(parsed, dict):
        raise ValueError("AI 快速配置结果必须是 JSON object")
    return parsed


def _normalize_date(value: Any, fallback: str) -> str:
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()

    raw = str(value or "").strip()
    if not raw:
        return fallback

    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y年%m月%d日"):
        try:
            return datetime.strptime(raw, fmt).date().isoformat()
        except ValueError:
            continue

    match = re.search(r"(\d{4})[年/-](\d{1,2})[月/-](\d{1,2})", raw)
    if match:
        year, month, day = [int(item) for item in match.groups()]
        return f"{year:04d}-{month:02d}-{day:02d}"

    return fallback


def _default_allocation() -> dict[str, int]:
    if not BUILDINGS:
        return {"A楼": 50, "B楼": 30, "C楼": 20}
    base = 100 // len(BUILDINGS)
    allocation = {building: base for building in BUILDINGS}
    allocation[BUILDINGS[-1]] += 100 - sum(allocation.values())
    return allocation


def _normalize_allocation(value: Any, fallback: dict[str, int]) -> dict[str, int]:
    if not isinstance(value, dict):
        return dict(fallback)

    result: dict[str, int] = {}
    for building, ratio in value.items():
        name = str(building or "").strip()
        if not name:
            continue
        if not name.endswith("楼"):
            name = f"{name}楼"
        try:
            result[name] = max(0, int(float(str(ratio).replace("%", ""))))
        except ValueError:
            continue

    total = sum(result.values())
    if not result or total <= 0:
        return dict(fallback)

    if total != 100:
        scaled = {key: int(round(value * 100 / total)) for key, value in result.items()}
        drift = 100 - sum(scaled.values())
        first_key = next(iter(scaled))
        scaled[first_key] += drift
        result = scaled

    return result


def _normalize_gift_rules(value: Any, fallback_rules: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return fallback_rules

    normalized_rules: list[dict[str, Any]] = []
    fallback_allocation = _default_allocation()
    for item in value:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        if not name:
            continue
        department = str(item.get("department") or "全员").strip() or "全员"
        try:
            total_stock = max(1, int(item.get("total_stock") or 1))
        except (TypeError, ValueError):
            total_stock = 1

        normalized_rules.append(
            {
                "name": name,
                "department": department,
                "total_stock": total_stock,
                "description": str(item.get("description") or "AI 快速配置生成，可在确认页修改").strip(),
                "building_allocation": _normalize_allocation(
                    item.get("building_allocation"),
                    fallback_allocation,
                ),
                "per_person_limit": 1,
            }
        )

    return normalized_rules or fallback_rules


def _normalize_config(raw: dict[str, Any], source: str, fallback: dict[str, Any]) -> dict[str, Any]:
    activity = raw.get("activity") if isinstance(raw.get("activity"), dict) else {}
    fallback_activity = fallback["activity"]
    start_date = _normalize_date(activity.get("start_date"), fallback_activity["start_date"])
    end_date = _normalize_date(activity.get("end_date"), fallback_activity["end_date"])

    if start_date > end_date:
        start_date, end_date = end_date, start_date

    return {
        "activity": {
            "name": str(activity.get("name") or fallback_activity["name"]).strip(),
            "activity_type": str(activity.get("activity_type") or "节日福利").strip(),
            "description": str(activity.get("description") or source).strip(),
            "start_date": start_date,
            "end_date": end_date,
            "allow_cancel": bool(activity.get("allow_cancel", True)),
            "expire_release": bool(activity.get("expire_release", True)),
        },
        "gift_rules": _normalize_gift_rules(raw.get("gift_rules"), fallback["gift_rules"]),
    }


def parse_activity_text(text: str) -> dict[str, Any]:
    source = _source_text(text)
    fallback = parse_with_rules(source)

    try:
        ai_config = _request_gemini_config(source)
        return _normalize_config(ai_config, source, fallback)
    except ValueError:
        pass

    try:
        ai_config = _request_openai_config(source)
        return _normalize_config(ai_config, source, fallback)
    except ValueError:
        return fallback
