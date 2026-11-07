import os, json, time, html, re
import feedparser, requests
from deep_translator import GoogleTranslator

TOKEN = os.environ["BOT_TOKEN"]
CHANNEL = os.environ["CHANNEL"]  # например @mynewschannel

# ===== НАСТРОЙКИ =====
PER_REGION = 2      # сколько новостей из каждого региона за один запуск
SUMMARY_LEN = 250   # длина краткого описания
# Включить/выключить регион: True / False
REGIONS = {
    "🇺🇸 Америка": {"on": True, "feeds": [
        ("BBC", "https://feeds.bbci.co.uk/news/world/us_and_canada/rss.xml", "en"),
        ("NPR", "https://feeds.npr.org/1001/rss.xml", "en"),
    ]},
    "🇪🇺 Европа": {"on": True, "feeds": [
        ("BBC", "https://feeds.bbci.co.uk/news/world/europe/rss.xml", "en"),
        ("DW", "https://rss.dw.com/xml/rss-en-all", "en"),
    ]},
    "🌏 Азия": {"on": True, "feeds": [
        ("BBC", "https://feeds.bbci.co.uk/news/world/asia/rss.xml", "en"),
        ("The Diplomat", "https://thediplomat.com/feed/", "en"),
    ]},
    "🇦🇲 Армения": {"on": True, "feeds": [
        ("Azatutyun", "https://www.azatutyun.am/api/zkjprl-vomx-tpej_yq", "en"),
        ("CivilNet", "https://www.civilnet.am/en/feed/", "en"),
    ]},
    "🇷🇺 Россия": {"on": True, "feeds": [
        ("Meduza", "https://meduza.io/rss/en/all", "en"),
        ("Moscow Times", "https://www.themoscowtimes.com/rss/news", "en"),
    ]},
}
# =====================

LANGS = [("en", "🇬🇧"), ("ru", "🇷🇺"), ("hy", "🇦🇲")]
STATE = "sent.json"


def load_state():
    try:
        return json.load(open(STATE, encoding="utf-8"))
    except Exception:
        return []


def clean(text):
    text = re.sub(r"<[^>]+>", " ", text or "")
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def tr(text, src, dst):
    if not text or src == dst:
        return text
    try:
        return GoogleTranslator(source=src, target=dst).translate(text) or text
    except Exception as e:
        print("translate error:", e)
        return text


def send(text):
    for _ in range(3):
        r = requests.post(
            f"https://api.telegram.org/bot{TOKEN}/sendMessage",
            json={"chat_id": CHANNEL, "text": text, "parse_mode": "HTML"},
            timeout=30,
        )
        if r.status_code == 429:
            time.sleep(r.json().get("parameters", {}).get("retry_after", 5) + 1)
            continue
        if not r.ok:
            print("telegram error:", r.text)
        return r.ok
    return False


def main():
    sent = load_state()
    seen = set(sent)
    for region, cfg in REGIONS.items():
        if not cfg["on"]:
            continue
        items = []
        for name, url, lang in cfg["feeds"]:
            try:
                feed = feedparser.parse(url, agent="Mozilla/5.0")
            except Exception as e:
                print("feed error:", url, e)
                continue
            for e in feed.entries[:15]:
                uid = e.get("id") or e.get("link")
                if not uid or uid in seen:
                    continue
                ts = e.get("published_parsed") or e.get("updated_parsed")
                items.append((time.mktime(ts) if ts else 0, uid, name, lang, e))
        items.sort(key=lambda x: x[0], reverse=True)
        for _, uid, name, lang, e in items[:PER_REGION]:
            title = clean(e.get("title"))
            summ = clean(e.get("summary"))[:SUMMARY_LEN]
            parts = [f"<b>{html.escape(region)}</b>"]
            for code, flag in LANGS:
                t = html.escape(tr(title, lang, code))
                s = html.escape(tr(summ, lang, code)) if summ else ""
                parts.append(f"{flag} <b>{t}</b>" + (f"\n{s}" if s else ""))
            parts.append(f'🔗 <a href="{html.escape(e.get("link", ""))}">{html.escape(name)}</a>')
            if send("\n\n".join(parts)):
                sent.append(uid)
                seen.add(uid)
            time.sleep(4)
    json.dump(sent[-3000:], open(STATE, "w", encoding="utf-8"))


main()
