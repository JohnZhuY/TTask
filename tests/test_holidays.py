import json
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

import ttask.holidays_cn as holidays


class _Response:
    def __init__(self, payload):
        self.payload = json.dumps(payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return self.payload


class HolidayTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.old_path = holidays.USER_DATA_PATH
        self.old_downloaded = dict(holidays._downloaded)
        self.old_manual = dict(holidays._manual)
        holidays.USER_DATA_PATH = Path(self.temp.name) / "holidays.json"
        holidays._downloaded.clear()
        holidays._manual.clear()

    def tearDown(self):
        holidays.USER_DATA_PATH = self.old_path
        holidays._downloaded.clear()
        holidays._downloaded.update(self.old_downloaded)
        holidays._manual.clear()
        holidays._manual.update(self.old_manual)
        self.temp.cleanup()

    def test_update_two_years_and_manual_override(self):
        def fake_open(request, timeout=0):
            year = int(request.full_url.rsplit("/", 1)[-1].split(".", 1)[0])
            return _Response({
                "year": year,
                "papers": ["https://www.gov.cn/example"],
                "days": [
                    {"name": "元旦", "date": f"{year}-01-01", "isOffDay": True},
                    {"name": "元旦调休", "date": f"{year}-01-04", "isOffDay": False},
                ],
            })

        with patch.object(holidays, "urlopen", fake_open):
            self.assertEqual(holidays.update_years([2027, 2028]), [2027, 2028])
        self.assertTrue(holidays.USER_DATA_PATH.exists())
        self.assertTrue(holidays.day_info(date(2027, 1, 1)).is_holiday)
        self.assertTrue(holidays.day_info(date(2028, 1, 4)).is_adjusted_workday)

        holidays.set_manual_day(date(2027, 1, 1), "workday", "临时上班")
        self.assertTrue(holidays.is_workday(date(2027, 1, 1)))
        self.assertEqual(holidays.day_source(date(2027, 1, 1)), "手工设置")
        holidays.set_manual_day(date(2027, 1, 1), None)
        self.assertFalse(holidays.is_workday(date(2027, 1, 1)))


if __name__ == "__main__":
    unittest.main()
