from __future__ import annotations

import re
from datetime import date, timedelta
from typing import Any

KNOWN_DEPARTMENTS = ["技术部", "销售部", "职能部", "产品部", "运营部", "市场部", "财务部", "人事部"]
KNOWN_GIFTS = ["机械键盘", "降噪耳机", "500元购物卡", "购物卡", "零食大礼包", "零食礼包", "保温杯", "电影卡"]


def _clean_text(text: str) -> str:
    return re.sub(r"\s+", "", text)


def _date_range_from_text(text: str) -> tuple[str, str]:
    year_match = re.search(r"(\d{4})年", text)
    year = int(year_match.group(1)) if year_match else date.today().year

    date_match = re.search(
        r"(\d{1,2})月(\d{1,2})日(?:到|至|-|~)(?:(\d{1,2})月)?(\d{1,2})日",
        text,
    )
    if date_match:
        start_month = int(date_match.group(1))
        start_day = int(date_match.group(2))
        end_month = int(date_match.group(3) or start_month)
        end_day = int(date_match.group(4))
        return (
            f"{year:04d}-{start_month:02d}-{start_day:02d}",
            f"{year:04d}-{end_month:02d}-{end_day:02d}",
        )

    start = date.today() + timedelta(days=3)
    end = start + timedelta(days=4)
    return start.isoformat(), end.isoformat()


def _activity_name_from_text(text: str) -> str:
    match = re.search(r"(\d{4}年[^，。；;]{2,16}福利)", text)
    if match:
        return match.group(1)
    if "春节" in text:
        return "春节福利活动"
    if "中秋" in text:
        return "中秋福利活动"
    if "端午" in text:
        return "端午福利活动"
    return "福利领取活动"


def _split_gift_names(raw: str) -> list[str]:
    cleaned = raw
    cleaned = re.sub(r"(二选一|任选一|每人|统一|一份|可额外领取|可选|领取|可领)", "", cleaned)
    parts = re.split(r"或|、|和|/|，|,|\+|及", cleaned)
    result = []
    for part in parts:
        name = part.strip(" 。；;")
        if not name:
            continue
        result.append(name)
    return result


def _extract_eligibility(text: str) -> dict[str, list[str]]:
    rules: dict[str, list[str]] = {}
    normalized = _clean_text(text)
    clauses = [clause for clause in re.split(r"[，,。；;]", normalized) if clause]

    for clause in clauses:
        for department in KNOWN_DEPARTMENTS:
            match = re.search(
                rf"{department}(?:每人)?(?:可选|可领|领取|每人可领)(.+)",
                clause,
            )
            if match:
                rules[department] = _split_gift_names(match.group(1))

        all_match = re.search(r"全员(?:统一)?(?:每人)?(?:可领|领取)(.+)", clause)
        if all_match:
            rules["ALL"] = _split_gift_names(all_match.group(1))

    if not rules:
        rules = {
            "技术部": ["机械键盘", "降噪耳机"],
            "销售部": ["500元购物卡"],
            "ALL": ["零食大礼包"],
        }

    return rules


def _normalize_gift_name(name: str) -> str:
    normalized = name.replace(" ", "")
    if normalized == "购物卡":
        return "500元购物卡"
    if normalized == "零食礼包":
        return "零食大礼包"
    return normalized


def _stock_for_gift(name: str) -> int:
    if "键盘" in name or "耳机" in name:
        return 30
    if "购物卡" in name:
        return 40
    if "零食" in name:
        return 100
    return 60


def _extract_gift_rules(
    rules: dict[str, list[str]],
    allocation: dict[str, int],
) -> list[dict[str, Any]]:
    gift_rules: list[dict[str, Any]] = []
    for department, names in rules.items():
        for name in names:
            normalized = _normalize_gift_name(name)
            gift_rules.append(
                {
                    "name": normalized,
                    "department": "全员" if department == "ALL" else department,
                    "total_stock": _stock_for_gift(normalized),
                    "description": "文案快速配置生成，可在确认页修改",
                    "building_allocation": allocation,
                    "per_person_limit": 1,
                }
            )

    return gift_rules


def _extract_allocations(text: str) -> dict[str, int]:
    normalized = _clean_text(text)
    matches = re.findall(r"([A-ZＡ-Ｚ])楼(?:分配)?(\d+)%?", normalized)
    if matches:
        return {f"{letter.upper()}楼": int(value) for letter, value in matches}
    return {"A楼": 50, "B楼": 30, "C楼": 20}


def parse_activity_text(text: str) -> dict[str, Any]:
    source = text.strip()
    if not source:
        source = (
            "2026年端午福利，技术部可选机械键盘或降噪耳机，销售部领取500元购物卡，"
            "全员可领零食大礼包。A楼分配50%，B楼30%，C楼20%。"
            "活动日期为6月8日到6月10日。"
        )

    start_date, end_date = _date_range_from_text(source)
    eligibility = _extract_eligibility(source)
    allocations = _extract_allocations(source)
    gift_rules = _extract_gift_rules(eligibility, allocations)

    return {
        "activity": {
            "name": _activity_name_from_text(source),
            "activity_type": "节日福利",
            "description": source,
            "start_date": start_date,
            "end_date": end_date,
            "allow_cancel": True,
            "expire_release": True,
        },
        "gift_rules": gift_rules,
    }
