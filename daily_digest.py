"""
Forex Factory (Fair Economy feed) -> Discord Webhook 24小時摘要
每天早上8點執行一次,列出「接下來 24 小時內」的 USD + High Impact(紅色)新聞

用法:
    python daily_digest.py             -> 抓真實資料並發送到 Discord(正式使用)
    python daily_digest.py --test      -> 假資料(有新聞),終端機預覽,不發送
    python daily_digest.py --test-empty -> 假資料(無新聞),終端機預覽,不發送
    python daily_digest.py --send-test      -> 假資料(有新聞),真的發送到 Discord
    python daily_digest.py --send-test-empty -> 假資料(無新聞),真的發送到 Discord
    python daily_digest.py --preview   -> 抓真實資料,終端機預覽,不發送
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

WINDOW_HOURS = 24  # 每次看「接下來幾小時」內的新聞

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
    """測試用假資料:模擬同一天兩個時段(其中一個時段有2則新聞)+ 跨天一則,示範分組格式"""
    today_2030 = base_now.replace(hour=20, minute=30, second=0, microsecond=0)
    today_2200 = base_now.replace(hour=22, minute=0, second=0, microsecond=0)
    tomorrow_0200 = (base_now + timedelta(days=1)).replace(hour=2, minute=0, second=0, microsecond=0)
    return [
        {"title": "Core CPI m/m", "country": "USD", "impact": "High", "date": today_2030.isoformat()},
        {"title": "Core CPI y/y", "country": "USD", "impact": "High", "date": today_2030.isoformat()},
        {"title": "Fed Chairman Warsh Testifies", "country": "USD", "impact": "High", "date": today_2200.isoformat()},
        {"title": "NFP", "country": "USD", "impact": "High", "date": tomorrow_0200.isoformat()},
    ]


def build_event_sections(events):
    """
    把事件依「日期」再依「時間」分組,同時間的多則新聞只顯示一次時間,
    後面的用對齊的橫線列出。回傳組好的 description 字串(不含標題)。
    """
    date_groups = []  # [{'header': str, 'time_blocks': [[line, line, ...], ...]}, ...]
    current_date = None
    current_time = None

    for e in events:
        et = date_parser.parse(e["date"]).astimezone(LOCAL_TZ)
        date_key = et.date()
        time_str = et.strftime("%H:%M")

        if date_key != current_date:
            current_date = date_key
            current_time = None
            date_groups.append({
                "header": f"**{et.strftime('%Y-%m-%d')}｜{weekday_cn(et)}**",
                "time_blocks": [],
            })

        if time_str != current_time:
            current_time = time_str
            date_groups[-1]["time_blocks"].append([f"{time_str} - {e['title']}"])
        else:
            padding = "\u00A0" * 10  # 不換行空格,對齊「HH:MM 」的寬度(反覆微調中)
            # 用 \- 跳脫橫線,避免 Discord 把「空格+-」誤判成條列清單符號
            date_groups[-1]["time_blocks"][-1].append(f"{padding}\\- {e['title']}")

    group_strs = []
    for g in date_groups:
        time_block_strs = ["\n".join(tb) for tb in g["time_blocks"]]
        group_strs.append(g["header"] + "\n" + "\n\n".join(time_block_strs))

    return "\n\n".join(group_strs)


def build_message(events, now_local):
    """組出 Discord 訊息的 embed,回傳 payload(共用給正式發送跟預覽用)。每日摘要不 @everyone。"""
    if not events:
        date_str = now_local.strftime("%Y-%m-%d")
        description = f"**{date_str}｜{weekday_cn(now_local)}**\n計劃你的交易,交易你的計劃。✌️"
        title = "⚪ 接下來24小時無 USD 高影響新聞"
        color = 0xFFFFFF  # 白色
    else:
        description = build_event_sections(events)
        title = "🔴 接下來24小時USD 高影響新聞"
        color = 0xFF0000  # 紅色

    embed = {"title": title, "description": description, "color": color}
    return {"embeds": [embed]}


def send_digest(events, now_local):
    payload = build_message(events, now_local)
    resp = requests.post(DISCORD_WEBHOOK_URL, json=payload, timeout=10)
    resp.raise_for_status()


def print_preview(events, now_local):
    """終端機印出這則訊息實際會長怎樣,方便手動測試檢查格式"""
    payload = build_message(events, now_local)
    embed = payload["embeds"][0]
    print("========== Discord 訊息預覽 ==========")
    print(f"[{embed['title']}]")
    print(embed["description"])
    print(f"(顏色: #{embed['color']:06X})")
    print("=======================================")


def run(mode="live"):
    """
    mode:
      "live"        -> 正式發送到 Discord(真實資料)
      "test"        -> 假資料(有新聞),終端機預覽,不發送
      "test_empty"  -> 假資料(無新聞),終端機預覽,不發送
      "send_test"       -> 假資料(有新聞),真的發送到 Discord
      "send_test_empty" -> 假資料(無新聞),真的發送到 Discord
      "preview"     -> 真實資料,終端機預覽,不發送
    """
    needs_webhook = mode in ("live", "send_test", "send_test_empty")
    if needs_webhook and not DISCORD_WEBHOOK_URL:
        print("錯誤:找不到環境變數 DISCORD_WEBHOOK_URL,請先設定。", file=sys.stderr)
        sys.exit(1)

    if mode in ("test", "send_test"):
        now_local = datetime.now(LOCAL_TZ).replace(hour=8, minute=0, second=0, microsecond=0)
        matched = build_sample_events(now_local)
        if mode == "send_test":
            send_digest(matched, now_local)
            print("已發送測試訊息(有新聞情境)。")
        else:
            print_preview(matched, now_local)
        return

    if mode in ("test_empty", "send_test_empty"):
        now_local = datetime.now(LOCAL_TZ)
        if mode == "send_test_empty":
            send_digest([], now_local)
            print("已發送測試訊息(無新聞情境)。")
        else:
            print_preview([], now_local)
        return

    now_local = datetime.now(LOCAL_TZ)

    if mode == "live" and now_local.weekday() >= 5:  # 5=星期六, 6=星期日
        print(f"今天是{weekday_cn(now_local)}(週末),跳過發送,不打擾大家。")
        return

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
        print_preview(matched, now_local)
    else:
        send_digest(matched, now_local)
        print(f"已發送摘要,共 {len(matched)} 則事件。")


if __name__ == "__main__":
    if "--send-test-empty" in sys.argv:
        run(mode="send_test_empty")
    elif "--send-test" in sys.argv:
        run(mode="send_test")
    elif "--test-empty" in sys.argv:
        run(mode="test_empty")
    elif "--test" in sys.argv:
        run(mode="test")
    elif "--preview" in sys.argv:
        run(mode="preview")
    else:
        run(mode="live")
