"""
Forex Factory (Fair Economy feed) -> Discord Webhook 每日摘要
每天執行一次,列出「當天」所有 USD + High Impact(紅色)新聞

用法:
    python daily_digest.py          -> 抓真實資料並發送到 Discord
    python daily_digest.py --test   -> 用假資料測試,不會真的打 Discord
"""

import os
import sys
import json
from datetime import datetime, timezone, timedelta

import requests
from dateutil import parser as date_parser

# ---------- 設定 ----------

FF_JSON_URL = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"

TARGET_COUNTRY = "USD"
TARGET_IMPACT = "High"

# 顯示 & 判斷「今天」用的時區(GMT+8)
LOCAL_TZ = timezone(timedelta(hours=8))

DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL", "")


# ---------- 核心邏輯 ----------

def fetch_calendar():
    headers = {"User-Agent": "Mozilla/5.0 (compatible; ff-discord-digest/1.0)"}
    resp = requests.get(FF_JSON_URL, headers=headers, timeout=15)
    resp.raise_for_status()
    try:
        return resp.json()
    except ValueError:
        raise RuntimeError("抓取失敗,可能觸發了 Fair Economy 的請求限制(回傳非 JSON)。")


def build_sample_events():
    """測試用假資料:今天早上、下午各一則 USD High,另外混一則會被過濾掉的"""
    today_local = datetime.now(LOCAL_TZ)
    morning = today_local.replace(hour=20, minute=30, second=0, microsecond=0)
    afternoon = today_local.replace(hour=22, minute=0, second=0, microsecond=0)
    return [
        {"title": "CPI m/m", "country": "USD", "impact": "High",
         "date": morning.isoformat(), "forecast": "0.3%", "previous": "0.2%"},
        {"title": "FOMC Statement", "country": "USD", "impact": "High",
         "date": afternoon.isoformat(), "forecast": "", "previous": ""},
        {"title": "German Factory Orders", "country": "EUR", "impact": "High",
         "date": morning.isoformat(), "forecast": "", "previous": ""},
        {"title": "Unemployment Claims", "country": "USD", "impact": "Low",
         "date": morning.isoformat(), "forecast": "", "previous": ""},
    ]


def send_digest(events_today):
    today_str = datetime.now(LOCAL_TZ).strftime("%Y-%m-%d (%A)")

    if not events_today:
        description = "今天沒有 USD 紅色(High Impact)新聞。"
        color = 0x2ECC71  # 綠色
    else:
        lines = []
        for e in events_today:
            t = date_parser.parse(e["date"]).astimezone(LOCAL_TZ).strftime("%H:%M")
            forecast = e.get("forecast") or "N/A"
            previous = e.get("previous") or "N/A"
            lines.append(f"**{t}** — {e['title']}\nForecast: {forecast}  |  Previous: {previous}")
        description = "\n\n".join(lines)
        color = 0xFF0000  # 紅色

    embed = {
        "title": f"🔴 今日 USD 高影響力新聞 — {today_str}",
        "description": description,
        "color": color,
    }

    payload = {"embeds": [embed]}
    resp = requests.post(DISCORD_WEBHOOK_URL, json=payload, timeout=10)
    resp.raise_for_status()


def run(test_mode=False):
    if not test_mode and not DISCORD_WEBHOOK_URL:
        print("錯誤:找不到環境變數 DISCORD_WEBHOOK_URL,請先設定。", file=sys.stderr)
        sys.exit(1)

    use_test_data = test_mode or os.environ.get("USE_TEST_DATA", "false").lower() == "true"
    events = build_sample_events() if use_test_data else fetch_calendar()

    today_local_date = datetime.now(LOCAL_TZ).date()

    events_today = []
    for event in events:
        if event.get("country") != TARGET_COUNTRY:
            continue
        if event.get("impact") != TARGET_IMPACT:
            continue
        try:
            event_date_local = date_parser.parse(event["date"]).astimezone(LOCAL_TZ).date()
        except (ValueError, TypeError):
            continue
        if event_date_local == today_local_date:
            events_today.append(event)

    events_today.sort(key=lambda e: date_parser.parse(e["date"]))

    if test_mode:
        print(f"[TEST] 今天符合條件的事件共 {len(events_today)} 則:")
        for e in events_today:
            print(f"  - {e['title']}")
    else:
        send_digest(events_today)
        print(f"已發送每日摘要,共 {len(events_today)} 則事件。")


if __name__ == "__main__":
    run(test_mode="--test" in sys.argv)
