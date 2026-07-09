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


def build_sample_speech_event():
    """測試用假資料:一則落在 30 分鐘後的 USD High 演講類新聞,用來驗證 Speech 警語"""
    fake_time = (datetime.now(timezone.utc) + timedelta(minutes=LEAD_MINUTES)).isoformat()
    return [
        {"title": "Fed Chair Powell Speaks", "country": "USD", "impact": "High",
         "date": fake_time, "forecast": "N/A", "previous": "N/A"},
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


# 用來判斷是否為「演講類」新聞的關鍵字(ForexFactory 標題常見用字)
SPEECH_KEYWORDS = ["speech", "speaks", "testimony", "press conference", "q&a"]

SPEECH_WARNING = (
    "⚠️ 演講類新聞通常沒有固定結束時間。\n"
    "在做任何交易決策前,先查看官方直播,確認演講是否已經結束。"
)


def is_speech(title):
    t = title.lower()
    return any(keyword in t for keyword in SPEECH_KEYWORDS)


def build_message(triggered_events):
    lines = []
    has_speech = False
    for event, minutes_until in triggered_events:
        t = date_parser.parse(event["date"]).astimezone(LOCAL_TZ).strftime("%H:%M")
        forecast = event.get("forecast") or "N/A"
        previous = event.get("previous") or "N/A"
        lines.append(f"{t} - {event['title']}\nForecast: {forecast} | Previous: {previous}")
        if is_speech(event["title"]):
            has_speech = True

    if has_speech:
        lines.append(SPEECH_WARNING)

    embed = {
        "title": "🟠 30 分鐘後有 USD 高影響新聞",
        "description": "\n\n".join(lines),
        "color": 0xFF8C00,  # 橘色
    }
    return {
        "content": "@everyone",
        "allowed_mentions": {"parse": ["everyone"]},
        "embeds": [embed],
    }


def send_reminder(triggered_events):
    payload = build_message(triggered_events)
    resp = requests.post(DISCORD_WEBHOOK_URL, json=payload, timeout=10)
    resp.raise_for_status()


def print_preview(triggered_events):
    """終端機印出這則訊息實際會長怎樣,方便手動測試檢查格式"""
    payload = build_message(triggered_events)
    embed = payload["embeds"][0]
    print("========== Discord 訊息預覽 ==========")
    print(payload["content"])
    print(f"[{embed['title']}]")
    print(embed["description"])
    print("=======================================")


def run(mode="live"):
    """
    mode:
      "live"          -> 正式發送到 Discord(真實資料)
      "test"          -> 假資料(一般新聞)+ 終端機預覽,不發送,不記錄 dedupe
      "test_speech"   -> 假資料(演講類新聞)+ 終端機預覽,不發送,不記錄 dedupe
      "send_test"          -> 假資料(一般新聞)+ 真的發送到 Discord
      "send_test_speech"   -> 假資料(演講類新聞)+ 真的發送到 Discord
      "preview"       -> 真實資料 + 終端機預覽,不發送,不記錄 dedupe
    """
    needs_webhook = mode in ("live", "send_test", "send_test_speech")
    if needs_webhook and not DISCORD_WEBHOOK_URL:
        print("錯誤:找不到環境變數 DISCORD_WEBHOOK_URL,請先設定。", file=sys.stderr)
        sys.exit(1)

    if mode in ("test_speech", "send_test_speech"):
        fake_events = build_sample_speech_event()
        triggered = [(e, LEAD_MINUTES) for e in fake_events]
        if mode == "send_test_speech":
            send_reminder(triggered)
            print("已發送 Speech 情境測試訊息。")
        else:
            print_preview(triggered)
        return

    use_test_data = mode in ("test", "send_test") or os.environ.get("USE_TEST_DATA", "false").lower() == "true"

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
            if mode == "live" and key in sent_state:
                continue  # 已經提醒過了(預覽/測試模式不受 dedupe 限制,方便隨時查看格式)
            triggered.append((event, round(minutes_until)))
            if mode == "live":
                sent_state[key] = time.time()

    if mode in ("test", "preview"):
        if triggered:
            print_preview(triggered)
        else:
            print("目前沒有落在 30 分鐘提醒視窗內的事件(用 --test 可以看假資料格式預覽)。")
        return

    if mode == "send_test":
        send_reminder(triggered)
        print("已發送一般情境測試訊息。")
        return

    if triggered:
        send_reminder(triggered)
        print(f"已發送提醒,共 {len(triggered)} 則事件。")
        save_sent_state(sent_state)
    else:
        print(f"[{datetime.now(LOCAL_TZ).strftime('%Y-%m-%d %H:%M:%S')}] 沒有符合條件的事件需要提醒。")


if __name__ == "__main__":
    if "--send-test-speech" in sys.argv:
        run(mode="send_test_speech")
    elif "--test-speech" in sys.argv:
        run(mode="test_speech")
    elif "--send-test" in sys.argv:
        run(mode="send_test")
    elif "--test" in sys.argv:
        run(mode="test")
    elif "--preview" in sys.argv:
        run(mode="preview")
    else:
        run(mode="live")
