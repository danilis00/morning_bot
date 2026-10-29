import os
import json
from datetime import datetime, date, timedelta

import gspread
from google.oauth2.service_account import Credentials


SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

HEADERS = ["date", "good", "better", "blocked", "improve", "tasks", "goal_step"]


class SheetsDB:
    def __init__(self):
        creds_json = os.environ.get("GOOGLE_CREDS_JSON")
        spreadsheet_id = os.environ.get("SPREADSHEET_ID")

        self.spreadsheet = None
        if not creds_json or not spreadsheet_id:
            print("⚠️  GOOGLE_CREDS_JSON or SPREADSHEET_ID not set — running without DB")
            self.sheet = None
            return

        creds_data = json.loads(creds_json)
        creds = Credentials.from_service_account_info(creds_data, scopes=SCOPES)
        client = gspread.authorize(creds)
        spreadsheet = client.open_by_key(spreadsheet_id)
        self.spreadsheet = spreadsheet  # нужен сетке Харады для своих листов

        # Use first sheet, create headers if empty
        self.sheet = spreadsheet.sheet1
        if not self.sheet.row_values(1):
            self.sheet.append_row(HEADERS)

    def save_entry(self, data: dict):
        if not self.sheet:
            print("DB not configured, skipping save:", data)
            return
        row = [
            datetime.now().strftime("%Y-%m-%d"),
            data.get("good", ""),
            data.get("better", ""),
            data.get("blocked", ""),
            data.get("improve", ""),
            data.get("tasks", ""),
            data.get("goal_step", ""),
        ]
        self.sheet.append_row(row)

    def get_last_entries(self, n: int = 7) -> list[dict]:
        if not self.sheet:
            return []
        rows = self.sheet.get_all_records()
        return rows[-n:] if len(rows) >= n else rows

    def get_stats(self) -> dict:
        if not self.sheet:
            return {"total": 0, "streak": 0, "first_date": "—"}

        rows = self.sheet.get_all_records()
        if not rows:
            return {"total": 0, "streak": 0, "first_date": "—"}

        total = len(rows)
        first_date = rows[0].get("date", "—")

        # Calculate streak
        dates = set()
        for r in rows:
            try:
                dates.add(datetime.strptime(r["date"], "%Y-%m-%d").date())
            except Exception:
                pass

        streak = 0
        check = date.today()
        while check in dates:
            streak += 1
            check -= timedelta(days=1)

        return {"total": total, "streak": streak, "first_date": first_date}
