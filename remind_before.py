"""
Forex Factory (Fair Economy feed) -> Discord Webhook 30 分鐘前提醒
每 5 分鐘執行一次,檢查是否有 USD + High Impact 新聞即將在 30 分鐘後公佈

用法:
    python remind_before.py          -> 抓真實資料,符合條件會真的發送到 Discord
    python remind_before.py --test   -> 用假資料測試,不會真的打 Discord,只印出結果
"""

import os
import sys
import json
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

import requests
from dateutil import parser as date_parser

# ---------- 設定 ----------

FF_JSON_URL = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"

TARGET_COUNTRY = "USD"
TARGET_IMPACT = "High"

# 提前多少分鐘提醒
LEAD_MINUTES = 30

# 檢查視窗容許誤差(分鐘)。因為每 5 分鐘檢查一次,用窗口確保不會錯過「剛好 30 分鐘前」這個時間點
WINDOW_MINUTES = 5

# 記錄「已經提醒過」的檔案,執行完會 commit 回 repo
STATE_FILE = Path(__file__).parent / "sent_reminders.json"

LOCAL_TZ = timezone(timedelta(hours=8))

DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL", "")


# ---------- 核心邏輯 ----------

def fetch_calendar():
    headers = {"User-Agent": "Mozilla/5.0 (compatible; ff-discord-reminder/1.0)"}
    resp = requests.get(FF_JSON_URL, headers=headers, timeout=15)
    resp.raise_for_status()
    try:
        return resp.json()
    except ValueError:
        raise RuntimeError("抓取失敗,可能觸發了 Fair Economy 的請求限制(回傳非 JSON)。")


def build_sample_events():
    """測試用假資料:一則會落在 30 分鐘後的 USD High 新聞"""
    fake_time = (datetime.now(timezone.utc) + timedelta(minutes=LEAD_MINUTES)).isoformat()
    return [
        {"title": "CPI m/m", "country": "USD", "impact": "High",
         "date": fake_time, "forecast": "0.3%", "previous": "0.2%"},
        {"title": "Low Impact News", "country": "USD", "impact": "Low",
         "date": fake_time, "forecast": "", "previous": ""},
    ]


def load_sent_state():
    if not STATE_FILE.exists():
        return {}
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def save_sent_state(state):
    # 順手清掉 2 天前的舊紀錄,檔案不會一直長大
    cutoff = time.time() - 2 * 24 * 3600
    state = {k: v for k, v in state.items() if v > cutoff}
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def event_key(event):
    return f"{event['country']}|{event['title']}|{event['date']}"


def send_reminder(triggered_events):
    lines = []
    for event, minutes_until in triggered_events:
        t = date_parser.parse(event["date"]).astimezone(LOCAL_TZ).strftime("%H:%M")
        forecast = event.get("forecast") or "N/A"
        previous = event.get("previous") or "N/A"
        lines.append(
            f"**{event['title']}**\n"
            f"時間: {t} (GMT+8)  |  約 {minutes_until} 分鐘後\n"
            f"Forecast: {forecast}  |  Previous: {previous}"
        )

    embed = {
        "title": "🟠 30 分鐘後有重要新聞!",
        "description": "\n\n".join(lines),
        "color": 0xFF8C00,  # 橘色
    }

    resp = requests.post(DISCORD_WEBHOOK_URL, json={"embeds": [embed]}, timeout=10)
    resp.raise_for_status()


def run(test_mode=False):
    use_test_data = test_mode or os.environ.get("USE_TEST_DATA", "false").lower() == "true"

    if not test_mode and not DISCORD_WEBHOOK_URL:
        print("錯誤:找不到環境變數 DISCORD_WEBHOOK_URL,請先設定。", file=sys.stderr)
        sys.exit(1)

    events = build_sample_events() if use_test_data else fetch_calendar()

    sent_state = load_sent_state()
    now = datetime.now(timezone.utc)

    triggered = []

    for event in events:
        if event.get("country") != TARGET_COUNTRY:
            continue
        if event.get("impact") != TARGET_IMPACT:
            continue

        try:
            event_time = date_parser.parse(event["date"])
        except (ValueError, TypeError):
            continue

        minutes_until = (event_time - now).total_seconds() / 60

        if (LEAD_MINUTES - WINDOW_MINUTES) <= minutes_until <= (LEAD_MINUTES + WINDOW_MINUTES):
            key = event_key(event)
            if key in sent_state:
                continue  # 已經提醒過了
            triggered.append((event, round(minutes_until)))
            sent_state[key] = time.time()

    if triggered:
        if test_mode:
            print(f"[TEST] 會發送提醒,共 {len(triggered)} 則:")
            for e, m in triggered:
                print(f"  - {e['title']} ({m} 分鐘後)")
        else:
            send_reminder(triggered)
            print(f"已發送提醒,共 {len(triggered)} 則事件。")
        save_sent_state(sent_state)
    else:
        print(f"[{datetime.now(LOCAL_TZ).strftime('%Y-%m-%d %H:%M:%S')}] 沒有符合條件的事件需要提醒。")


if __name__ == "__main__":
    run(test_mode="--test" in sys.argv)
