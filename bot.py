import os, json, time, html, re
import feedparser, requests

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
    """Перевод. Возвращает None, если не получилось."""
    if not text:
        return ""
    if src == dst:
        return text
    for _ in range(3):
        try:
            r = requests.get(
                "https://translate.googleapis.com/translate_a/single",
                params={"client": "gtx", "sl": src, "tl": dst, "dt": "t", "q": text},
                timeout=20,
            )
            if r.ok:
                out = "".join(p[0] for p in r.json()[0] if p and p[0])
                if out:
                    return out
            print("google status", r.status_code)
        except Exception as e:
            print("google error:", e)
        time.sleep(2)
    try:  # запасной бесплатный переводчик
        r = requests.get(
            "https://api.mymemory.translated.net/get",
            params={"q": text[:480], "langpair": f"{src}|{dst}"},
            timeout=20,
        )
        out = r.json().get("responseData", {}).get("translatedText")
        if out and "MYMEMORY WARNING" not in out:
            return out
    except Exception as e:
        print("mymemory error:", e)
    return None


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
            ok_tr = 0
            for code, flag in LANGS:
                t = tr(title, lang, code)
                if t is None:
                    continue
                s2 = tr(summ, lang, code) if summ else ""
                if code != lang:
                    ok_tr += 1
                parts.append(
                    f"{flag} <b>{html.escape(t)}</b>"
                    + (f"\n{html.escape(s2 or '')}" if s2 else "")
                )
            if ok_tr == 0:
                print("translation failed, skip:", title)
                continue
            parts.append(f'🔗 <a href="{html.escape(e.get("link", ""))}">{html.escape(name)}</a>')
            if send("\n\n".join(parts)):
                sent.append(uid)
                seen.add(uid)
            time.sleep(4)
    json.dump(sent[-3000:], open(STATE, "w", encoding="utf-8"))


main()
