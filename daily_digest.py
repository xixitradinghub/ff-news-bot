"""
Forex Factory (Fair Economy feed) -> Discord Webhook 12小時摘要
一天執行兩次(早上8點、晚上8點),各自列出「接下來 12 小時內」的 USD + High Impact(紅色)新聞

用法:
    python daily_digest.py                -> 抓真實資料並發送到 Discord(正式使用)
    python daily_digest.py --test-morning -> 模擬「早上8點」的樣子,終端機預覽,不發送
    python daily_digest.py --test-evening -> 模擬「晚上8點」的樣子,終端機預覽,不發送
    python daily_digest.py --test-empty   -> 模擬「無新聞」的樣子,終端機預覽,不發送
    python daily_digest.py --preview      -> 抓真實資料,終端機預覽,不發送
"""

import os
import sys
from datetime import datetime, timezone, timedelta

import requests
from dateutil import parser as date_parser

# ---------- 設定 ----------

FF_JSON_URL = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"

TARGET_COUNTRY = "USD"
TARGET_IMPACT = "High"

WINDOW_HOURS = 12  # 每次看「接下來幾小時」內的新聞

LOCAL_TZ = timezone(timedelta(hours=8))

DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL", "")

WEEKDAY_CN = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"]


def weekday_cn(dt):
    return WEEKDAY_CN[dt.weekday()]


# ---------- 核心邏輯 ----------

def fetch_calendar():
    headers = {"User-Agent": "Mozilla/5.0 (compatible; ff-discord-digest/1.0)"}
    resp = requests.get(FF_JSON_URL, headers=headers, timeout=15)
    resp.raise_for_status()
    try:
        return resp.json()
    except ValueError:
        raise RuntimeError("抓取失敗,可能觸發了 Fair Economy 的請求限制(回傳非 JSON)。")


def build_sample_events(base_now):
    """測試用假資料:相對於指定的模擬時間點,產生一則等下、一則跨天的新聞"""
    soon = base_now + timedelta(hours=2)
    later_crossing = base_now + timedelta(hours=8)
    return [
        {"title": "ISM Services PMI", "country": "USD", "impact": "High",
         "date": soon.isoformat(), "forecast": "N/A", "previous": "N/A"},
        {"title": "FOMC Statement", "country": "USD", "impact": "High",
         "date": later_crossing.isoformat(), "forecast": "N/A", "previous": "N/A"},
    ]


def format_with_ampm(dt):
    """依照範例格式:數字維持24小時制,後面加 AM/PM 標籤(小時<12標AM,否則標PM)"""
    tag = "AM" if dt.hour < 12 else "PM"
    return f"{dt.strftime('%H:%M')} {tag}"


def build_message(events, now_local, window_end):
    """組出 Discord 訊息的 content + embed,回傳 payload(共用給正式發送跟預覽用)"""
    coverage_line = (
        f"⏰ 即將到來的 12 小時新聞速報 "
        f"({format_with_ampm(now_local)} - {format_with_ampm(window_end)})"
    )

    if not events:
        date_str = now_local.strftime("%Y-%m-%d")
        description = (
            f"{coverage_line}\n\n"
            f"{date_str}｜{weekday_cn(now_local)}\n計劃你的交易,交易你的計劃。✌️"
        )
        title = "🟢 今日無 USD 高影響新聞"
        color = 0x00CED1  # 青色
    else:
        lines = [coverage_line, ""]
        current_date = None
        for e in events:
            et = date_parser.parse(e["date"]).astimezone(LOCAL_TZ)
            if et.date() != current_date:
                current_date = et.date()
                if len(lines) > 2:
                    lines.append("")  # 換日期前多空一行
                lines.append(f"{et.strftime('%Y-%m-%d')}｜{weekday_cn(et)}")
            forecast = e.get("forecast") or "N/A"
            previous = e.get("previous") or "N/A"
            lines.append(f"{et.strftime('%H:%M')} — {e['title']}\nForecast: {forecast} | Previous: {previous}")
            lines.append("")  # 每則事件之間多空一行,方便閱讀
        description = "\n".join(lines).rstrip()
        title = "🔴 USD 高影響新聞"
        color = 0xFF0000  # 紅色

    embed = {"title": title, "description": description, "color": color}
    payload = {
        "content": "@everyone",
        "allowed_mentions": {"parse": ["everyone"]},
        "embeds": [embed],
    }
    return payload


def send_digest(events, now_local, window_end):
    payload = build_message(events, now_local, window_end)
    resp = requests.post(DISCORD_WEBHOOK_URL, json=payload, timeout=10)
    resp.raise_for_status()


def print_preview(events, now_local, window_end):
    """終端機印出這則訊息實際會長怎樣,方便手動測試檢查格式"""
    payload = build_message(events, now_local, window_end)
    embed = payload["embeds"][0]
    print("========== Discord 訊息預覽 ==========")
    print(payload["content"])
    print(f"[{embed['title']}]")
    print(embed["description"])
    print("=======================================")


def run(mode="live"):
    """
    mode:
      "live"               -> 正式發送到 Discord(真實資料,依實際觸發時間)
      "test_morning"       -> 假資料,模擬早上8點,終端機預覽,不發送
      "test_evening"       -> 假資料,模擬晚上8點,終端機預覽,不發送
      "test_empty"         -> 假資料(無新聞),終端機預覽,不發送
      "send_test_morning"  -> 假資料,模擬早上8點,真的發送到 Discord(方便網頁上測試)
      "send_test_evening"  -> 假資料,模擬晚上8點,真的發送到 Discord
      "send_test_empty"    -> 假資料(無新聞),真的發送到 Discord
      "preview"            -> 真實資料,依實際觸發時間,終端機預覽,不發送
    """
    needs_webhook = mode in ("live", "send_test_morning", "send_test_evening", "send_test_empty")
    if needs_webhook and not DISCORD_WEBHOOK_URL:
        print("錯誤:找不到環境變數 DISCORD_WEBHOOK_URL,請先設定。", file=sys.stderr)
        sys.exit(1)

    if mode in ("test_morning", "send_test_morning"):
        now_local = datetime.now(LOCAL_TZ).replace(hour=8, minute=0, second=0, microsecond=0)
        window_end = now_local + timedelta(hours=WINDOW_HOURS)
        matched = build_sample_events(now_local)
        if mode == "send_test_morning":
            send_digest(matched, now_local, window_end)
            print("已發送早上情境測試訊息。")
        else:
            print_preview(matched, now_local, window_end)
        return

    if mode in ("test_evening", "send_test_evening"):
        now_local = datetime.now(LOCAL_TZ).replace(hour=20, minute=0, second=0, microsecond=0)
        window_end = now_local + timedelta(hours=WINDOW_HOURS)
        matched = build_sample_events(now_local)
        if mode == "send_test_evening":
            send_digest(matched, now_local, window_end)
            print("已發送晚上情境測試訊息。")
        else:
            print_preview(matched, now_local, window_end)
        return

    if mode in ("test_empty", "send_test_empty"):
        now_local = datetime.now(LOCAL_TZ)
        window_end = now_local + timedelta(hours=WINDOW_HOURS)
        if mode == "send_test_empty":
            send_digest([], now_local, window_end)
            print("已發送無新聞情境測試訊息。")
        else:
            print_preview([], now_local, window_end)
        return

    now_local = datetime.now(LOCAL_TZ)
    window_end = now_local + timedelta(hours=WINDOW_HOURS)

    events = fetch_calendar()

    matched = []
    for event in events:
        if event.get("country") != TARGET_COUNTRY:
            continue
        if event.get("impact") != TARGET_IMPACT:
            continue
        try:
            event_time_local = date_parser.parse(event["date"]).astimezone(LOCAL_TZ)
        except (ValueError, TypeError):
            continue
        # 未來 N 小時內都算,不卡日曆日期,避免美東時間換算後
        # 落在 GMT+8 凌晨、日期已經跳到明天的新聞被漏掉
        if now_local <= event_time_local <= window_end:
            matched.append(event)

    matched.sort(key=lambda e: date_parser.parse(e["date"]))

    if mode == "preview":
        print_preview(matched, now_local, window_end)
    else:
        send_digest(matched, now_local, window_end)
        print(f"已發送摘要,共 {len(matched)} 則事件。")


if __name__ == "__main__":
    if "--send-test-morning" in sys.argv:
        run(mode="send_test_morning")
    elif "--send-test-evening" in sys.argv:
        run(mode="send_test_evening")
    elif "--send-test-empty" in sys.argv:
        run(mode="send_test_empty")
    elif "--test-morning" in sys.argv:
        run(mode="test_morning")
    elif "--test-evening" in sys.argv:
        run(mode="test_evening")
    elif "--test-empty" in sys.argv:
        run(mode="test_empty")
    elif "--preview" in sys.argv:
        run(mode="preview")
    else:
        run(mode="live")
