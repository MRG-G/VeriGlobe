import os, json, time, html, re
from urllib.parse import urljoin
import feedparser, requests

TOKEN = os.environ["BOT_TOKEN"]
CHANNEL = os.environ["CHANNEL"]  # например @mynewschannel

# ===== НАСТРОЙКИ =====
SUMMARY_LEN = 250
# Регион: on = True/False, per_source = сколько новостей брать с КАЖДОГО сайта за запуск
# Источник: (название, ссылка, язык, тип)
#   тип "rss"  - обычная RSS-лента
#   тип "html" - сайт без RSS: бот сам берёт ссылки на статьи со страницы
#                (шаблон ссылки на статью указан в поле pattern)
REGIONS = {
    "🇦🇲 Армения": {"on": True, "per_source": 3, "feeds": [
        ("Shamshyan", "https://shamshyan.com/hy", "hy", "html",
         r"/hy/article/\d{4}/\d{2}/\d{2}/\d+"),
        ("Yerkir", "https://yerkir.am/hy", "hy", "html",
         r"/hy/article/\d{4}/\d{2}/\d{2}/\d+"),
        ("Azatutyun", "https://www.azatutyun.am/api/zkjprl-vomx-tpej_yq", "en", "rss"),
        ("CivilNet", "https://www.civilnet.am/en/feed/", "en", "rss"),
        ("1in.am", "https://1in.am/feed", "hy", "rss"),
        ("A1+", "https://www.a1plus.am/en/rss", "en", "rss"),
        ("Hetq", "https://hetq.am/en/rss", "en", "rss"),
        ("News.am", "https://news.am/eng/rss/", "en", "rss"),
        ("Armenian Weekly", "https://armenianweekly.com/feed", "en", "rss"),
    ]},
    "🇺🇸 Америка": {"on": True, "per_source": 1, "feeds": [
        ("BBC", "https://feeds.bbci.co.uk/news/world/us_and_canada/rss.xml", "en", "rss"),
        ("NPR", "https://feeds.npr.org/1001/rss.xml", "en", "rss"),
    ]},
    "🇪🇺 Европа": {"on": True, "per_source": 1, "feeds": [
        ("BBC", "https://feeds.bbci.co.uk/news/world/europe/rss.xml", "en", "rss"),
        ("DW", "https://rss.dw.com/xml/rss-en-all", "en", "rss"),
    ]},
    "🌏 Азия": {"on": True, "per_source": 1, "feeds": [
        ("BBC", "https://feeds.bbci.co.uk/news/world/asia/rss.xml", "en", "rss"),
        ("The Diplomat", "https://thediplomat.com/feed/", "en", "rss"),
    ]},
    "🇷🇺 Россия": {"on": True, "per_source": 1, "feeds": [
        ("Meduza", "https://meduza.io/rss/en/all", "en", "rss"),
        ("Moscow Times", "https://www.themoscowtimes.com/rss/news", "en", "rss"),
    ]},
}
# =====================

LANGS = [("en", "🇬🇧"), ("ru", "🇷🇺"), ("hy", "🇦🇲")]
STATE = "sent.json"
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
      "Accept-Language": "hy,en;q=0.8"}


def load_state():
    try:
        return json.load(open(STATE, encoding="utf-8"))
    except Exception:
        return []


def clean(text):
    text = re.sub(r"<[^>]+>", " ", text or "")
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def get(url):
    try:
        r = requests.get(url, headers=UA, timeout=25)
        if r.ok:
            return r.text
        print("HTTP", r.status_code, url)
    except Exception as e:
        print("fetch error:", url, e)
    return ""


def meta(page, prop):
    for pat in (
        rf'<meta[^>]+(?:property|name)=["\']{prop}["\'][^>]+content=["\']([^"\']*)',
        rf'<meta[^>]+content=["\']([^"\']*)["\'][^>]+(?:property|name)=["\']{prop}["\']',
    ):
        m = re.search(pat, page, re.I)
        if m and m.group(1).strip():
            return clean(m.group(1))
    return ""


def from_rss(url, limit=15):
    out = []
    try:
        feed = feedparser.parse(url, agent=UA["User-Agent"])
    except Exception as e:
        print("feed error:", url, e)
        return out
    if not feed.entries:
        print("empty feed:", url)
    for e in feed.entries[:limit]:
        uid = e.get("id") or e.get("link")
        if not uid:
            continue
        ts = e.get("published_parsed") or e.get("updated_parsed")
        out.append({
            "uid": uid, "ts": time.mktime(ts) if ts else 0,
            "title": clean(e.get("title")),
            "summary": clean(e.get("summary")),
            "link": e.get("link", uid), "page": None,
        })
    out.sort(key=lambda x: x["ts"], reverse=True)
    return out


def from_html(url, pattern, limit=15):
    page = get(url)
    seen, links = set(), []
    for m in re.findall(pattern, page):
        full = urljoin(url, m)
        if full not in seen:
            seen.add(full)
            links.append(full)
    # новее = больше номер в конце ссылки
    links.sort(key=lambda l: int(re.search(r"(\d+)$", l).group(1)), reverse=True)
    if not links:
        print("no links found:", url)
    return [{"uid": l, "ts": 0, "title": None, "summary": None, "link": l, "page": True}
            for l in links[:limit]]


def fill_from_page(item):
    """Для сайтов без RSS: заходим в статью и берём заголовок и описание."""
    page = get(item["link"])
    title = meta(page, "og:title")
    if not title or title.startswith("http"):
        m = re.search(r"<title[^>]*>(.*?)</title>", page, re.S | re.I)
        title = clean(m.group(1)) if m else ""
    item["title"] = title
    item["summary"] = meta(page, "og:description") or meta(page, "description")
    if item["summary"].startswith("http"):
        item["summary"] = ""
    return bool(title)


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
        for feed in cfg["feeds"]:
            name, url, lang, kind = feed[:4]
            items = from_rss(url) if kind == "rss" else from_html(url, feed[4])
            fresh = [i for i in items if i["uid"] not in seen][: cfg["per_source"]]
            for it in reversed(fresh):  # старые сначала, чтобы лента шла по порядку
                if it["page"] and not fill_from_page(it):
                    print("no title, skip:", it["link"])
                    continue
                title = it["title"]
                summ = (it["summary"] or "")[:SUMMARY_LEN]
                if summ.strip() == title.strip():
                    summ = ""
                parts = [f"<b>{html.escape(region)}</b> · {html.escape(name)}"]
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
                parts.append(f'🔗 <a href="{html.escape(it["link"])}">{html.escape(name)}</a>')
                if send("\n\n".join(parts)):
                    sent.append(it["uid"])
                    seen.add(it["uid"])
                time.sleep(3)
    json.dump(sent[-5000:], open(STATE, "w", encoding="utf-8"))


main()
