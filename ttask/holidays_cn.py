from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
import json
from pathlib import Path
from urllib.request import Request, urlopen

# Official mainland China schedules:
# 2025: https://www.gov.cn/zhengce/zhengceku/202411/content_6986383.htm
# 2026: https://www.gov.cn/zhengce/zhengceku/202511/content_7047091.htm


@dataclass(frozen=True, slots=True)
class DayInfo:
    name: str = ""
    is_holiday: bool = False
    is_adjusted_workday: bool = False
    data_available: bool = True

def _days(start: str, end: str, name: str) -> dict[str, DayInfo]:
    current = date.fromisoformat(start)
    finish = date.fromisoformat(end)
    result: dict[str, DayInfo] = {}
    while current <= finish:
        result[current.isoformat()] = DayInfo(name=name, is_holiday=True)
        current += timedelta(days=1)
    return result


def _year_2025() -> dict[str, DayInfo]:
    values: dict[str, DayInfo] = {}
    for start, end, name in (
        ("2025-01-01", "2025-01-01", "元旦"),
        ("2025-01-28", "2025-02-04", "春节"),
        ("2025-04-04", "2025-04-06", "清明节"),
        ("2025-05-01", "2025-05-05", "劳动节"),
        ("2025-05-31", "2025-06-02", "端午节"),
        ("2025-10-01", "2025-10-08", "国庆节·中秋节"),
    ):
        values.update(_days(start, end, name))
    for value in ("2025-01-26", "2025-02-08", "2025-04-27", "2025-09-28", "2025-10-11"):
        values[value] = DayInfo(name="调休上班", is_adjusted_workday=True)
    return values


def _year_2026() -> dict[str, DayInfo]:
    values: dict[str, DayInfo] = {}
    for start, end, name in (
        ("2026-01-01", "2026-01-03", "元旦"),
        ("2026-02-15", "2026-02-23", "春节"),
        ("2026-04-04", "2026-04-06", "清明节"),
        ("2026-05-01", "2026-05-05", "劳动节"),
        ("2026-06-19", "2026-06-21", "端午节"),
        ("2026-09-25", "2026-09-27", "中秋节"),
        ("2026-10-01", "2026-10-07", "国庆节"),
    ):
        values.update(_days(start, end, name))
    for value in ("2026-01-04", "2026-02-14", "2026-02-28", "2026-05-09", "2026-09-20", "2026-10-10"):
        values[value] = DayInfo(name="调休上班", is_adjusted_workday=True)
    return values


HOLIDAY_DATA = {2025: _year_2025(), 2026: _year_2026()}
USER_DATA_PATH = Path.home() / ".ttask" / "holidays.json"
_downloaded: dict[int, dict[str, DayInfo]] = {}
_manual: dict[str, DayInfo] = {}


def _load_user_data() -> None:
    _downloaded.clear()
    _manual.clear()
    try:
        payload = json.loads(USER_DATA_PATH.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, ValueError, TypeError):
        return
    for year_text, days in payload.get("downloaded", {}).items():
        try:
            year = int(year_text)
            _downloaded[year] = {
                value["date"]: DayInfo(
                    name=str(value.get("name", "")),
                    is_holiday=bool(value.get("is_holiday")),
                    is_adjusted_workday=bool(value.get("is_adjusted_workday")),
                )
                for value in days
                if date.fromisoformat(value["date"]).year == year
            }
        except (KeyError, TypeError, ValueError):
            continue
    for iso, value in payload.get("manual", {}).items():
        try:
            date.fromisoformat(iso)
            _manual[iso] = DayInfo(
                name=str(value.get("name", "")),
                is_holiday=value.get("kind") == "holiday",
                is_adjusted_workday=value.get("kind") == "workday",
            )
        except (TypeError, ValueError):
            continue


def _save_user_data() -> None:
    USER_DATA_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": 1,
        "downloaded": {
            str(year): [
                {
                    "date": iso,
                    "name": info.name,
                    "is_holiday": info.is_holiday,
                    "is_adjusted_workday": info.is_adjusted_workday,
                }
                for iso, info in sorted(days.items())
            ]
            for year, days in sorted(_downloaded.items())
        },
        "manual": {
            iso: {
                "kind": "holiday" if info.is_holiday else "workday",
                "name": info.name,
            }
            for iso, info in sorted(_manual.items())
        },
    }
    temporary = USER_DATA_PATH.with_suffix(".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(USER_DATA_PATH)


def downloaded_years() -> list[int]:
    return sorted(_downloaded)


def holiday_data_path() -> Path:
    return USER_DATA_PATH


def export_user_data(destination: str | Path) -> None:
    _save_user_data()
    Path(destination).write_text(USER_DATA_PATH.read_text(encoding="utf-8"), encoding="utf-8")


def import_user_data(source: str | Path) -> None:
    payload = json.loads(Path(source).read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or not isinstance(payload.get("downloaded", {}), dict):
        raise ValueError("节假日数据文件格式无效")
    USER_DATA_PATH.parent.mkdir(parents=True, exist_ok=True)
    temporary = USER_DATA_PATH.with_suffix(".import.tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(USER_DATA_PATH)
    _load_user_data()


def reset_user_data() -> None:
    _downloaded.clear()
    _manual.clear()
    try:
        USER_DATA_PATH.unlink()
    except FileNotFoundError:
        pass


def manual_info(value: date) -> DayInfo | None:
    return _manual.get(value.isoformat())


def day_source(value: date) -> str:
    if value.isoformat() in _manual:
        return "手工设置"
    if value.year in _downloaded:
        return "在线更新"
    if value.year in HOLIDAY_DATA:
        return "程序内置"
    return "周末规则"


def set_manual_day(value: date, kind: str | None, name: str = "") -> None:
    iso = value.isoformat()
    if kind is None:
        _manual.pop(iso, None)
    elif kind == "holiday":
        _manual[iso] = DayInfo(name=name.strip() or "自定义节假日", is_holiday=True)
    elif kind == "workday":
        _manual[iso] = DayInfo(name=name.strip() or "自定义工作日", is_adjusted_workday=True)
    else:
        raise ValueError("未知的日期类型")
    _save_user_data()


def update_years(years: list[int], timeout: int = 12) -> list[int]:
    """Download and atomically save validated holiday-cn yearly JSON files."""
    updated: dict[int, dict[str, DayInfo]] = {}
    errors: list[str] = []
    for year in years:
        payload = None
        for template in (
            "https://raw.githubusercontent.com/NateScarlet/holiday-cn/master/{year}.json",
            "https://cdn.jsdelivr.net/gh/NateScarlet/holiday-cn@master/{year}.json",
        ):
            try:
                request = Request(template.format(year=year), headers={"User-Agent": "TTask/1.0"})
                with urlopen(request, timeout=timeout) as response:
                    payload = json.loads(response.read().decode("utf-8"))
                break
            except Exception as exc:
                errors.append(f"{year}: {exc}")
        if not isinstance(payload, dict) or int(payload.get("year", 0)) != year:
            continue
        days: dict[str, DayInfo] = {}
        try:
            for item in payload["days"]:
                iso = str(item["date"])
                if date.fromisoformat(iso).year != year:
                    continue
                off = bool(item["isOffDay"])
                days[iso] = DayInfo(
                    name=str(item["name"]),
                    is_holiday=off,
                    is_adjusted_workday=not off,
                )
        except (KeyError, TypeError, ValueError):
            continue
        if days:
            updated[year] = days
    if not updated:
        detail = errors[-1] if errors else "返回数据格式无效"
        raise RuntimeError(f"未能下载有效的节假日数据：{detail}")
    _downloaded.update(updated)
    _save_user_data()
    return sorted(updated)


def day_info(value: date) -> DayInfo:
    manual = _manual.get(value.isoformat())
    if manual is not None:
        return manual
    year_data = _downloaded.get(value.year) or HOLIDAY_DATA.get(value.year)
    if year_data is None:
        return DayInfo(data_available=False)
    return year_data.get(value.isoformat(), DayInfo())


def is_workday(value: date) -> bool:
    """Return the mainland China workday status, including adjusted weekends."""
    info = day_info(value)
    if info.is_adjusted_workday:
        return True
    if info.is_holiday:
        return False
    return value.weekday() < 5


_load_user_data()
