#!/usr/bin/env python3
"""Regenerate index.html for the Daily Brief PWA.

Free sources (no API keys):
- News: RSS feeds from major outlets
- Weather: api.weather.gov (US National Weather Service)

Designed to run daily under GitHub Actions.
"""
import datetime
import re
import sys
from html import escape
from zoneinfo import ZoneInfo

import feedparser
import requests
from bs4 import BeautifulSoup

USER_AGENT = "yamesmack-daily-brief (+https://github.com/YamesMacK/daily-brief)"

# (publisher label, RSS URL, max items to take from this feed)
WORLD_FEEDS = [
    ("NPR", "https://feeds.npr.org/1004/rss.xml", 3),
    ("BBC World", "http://feeds.bbci.co.uk/news/world/rss.xml", 2),
    ("NPR Top", "https://feeds.npr.org/1001/rss.xml", 2),
]
MARKETS_FEEDS = [
    ("CNBC Markets", "https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=15839069", 3),
    ("Yahoo Finance", "https://finance.yahoo.com/news/rss", 2),
    ("MarketWatch", "https://feeds.content.dowjones.io/public/rss/mw_topstories", 2),
]
CONSTRUCTION_FEEDS = [
    ("Construction Dive", "https://www.constructiondive.com/feeds/news/", 3),
    ("ENR", "https://www.enr.com/rss/articles", 2),
    ("NAHB", "https://nahbnow.com/feed/", 2),
]


def fetch_top(feeds, want):
    """Pull up to `count` items from each feed, return up to `want` items total."""
    items = []
    for name, url, count in feeds:
        try:
            d = feedparser.parse(url, agent=USER_AGENT)
            for entry in d.entries[:count]:
                title = (entry.get("title") or "").strip()
                link = (entry.get("link") or "").strip()
                if not (title and link):
                    continue
                summary = entry.get("summary") or entry.get("description") or ""
                summary = re.sub(r"<[^>]+>", " ", summary)
                summary = re.sub(r"\s+", " ", summary).strip()
                if len(summary) > 260:
                    cut = summary.rfind(". ", 0, 260)
                    summary = summary[: cut + 1] if cut > 100 else summary[:257].rstrip() + "..."
                if not summary:
                    summary = "(See full article.)"
                items.append({"title": title, "link": link, "summary": summary, "source": name})
        except Exception as e:
            print(f"WARN: feed {name} failed: {e}", file=sys.stderr)
    return items[:want]


def fetch_weather(lat, lon, label):
    """Return (temp_f, short_forecast) for the daytime period at this point, or (None, msg)."""
    headers = {"User-Agent": USER_AGENT, "Accept": "application/geo+json"}
    try:
        r = requests.get(f"https://api.weather.gov/points/{lat},{lon}", headers=headers, timeout=15)
        r.raise_for_status()
        forecast_url = r.json()["properties"]["forecast"]
        r2 = requests.get(forecast_url, headers=headers, timeout=15)
        r2.raise_for_status()
        periods = r2.json()["properties"]["periods"]
        day = next((p for p in periods if p.get("isDaytime")), periods[0])
        return day["temperature"], day["shortForecast"]
    except Exception as e:
        print(f"WARN: weather {label} failed: {e}", file=sys.stderr)
        return None, "Forecast unavailable"


def make_story(item):
    fragment = (
        '<article class="story">'
        f'<h3><a href="{escape(item["link"])}" target="_blank" rel="noopener">{escape(item["title"])}</a></h3>'
        f'<p>{escape(item["summary"])}</p>'
        f'<span class="src">{escape(item["source"])}</span>'
        "</article>"
    )
    return BeautifulSoup(fragment, "html.parser")


def main():
    now_ct = datetime.datetime.now(ZoneInfo("America/Chicago"))
    date_str = now_ct.strftime("%A, %B ") + str(now_ct.day) + now_ct.strftime(", %Y")
    iso = now_ct.strftime("%Y-%m-%dT%H:%M%z")
    iso = iso[:-2] + ":" + iso[-2:]
    hour12 = now_ct.strftime("%I").lstrip("0") or "12"
    ampm = "a.m." if now_ct.hour < 12 else "p.m."
    refresh_label = f"{hour12}:{now_ct.strftime('%M')} {ampm} CT"

    world = fetch_top(WORLD_FEEDS, 5)
    markets = fetch_top(MARKETS_FEEDS, 5)
    construction = fetch_top(CONSTRUCTION_FEEDS, 5)
    h_temp, h_cond = fetch_weather(29.7604, -95.3698, "Houston")
    d_temp, d_cond = fetch_weather(32.7767, -96.7970, "Dallas")

    bits = []
    if markets:
        bits.append(f"Markets: {markets[0]['title'].rstrip('.')}.")
    if world:
        bits.append(f"World: {world[0]['title'].rstrip('.')}.")
    if construction:
        bits.append(f"Construction: {construction[0]['title'].rstrip('.')}.")
    if h_temp and d_temp:
        bits.append(f"Texas today: Houston {h_temp}°F, Dallas {d_temp}°F.")
    brief_text = " ".join(bits) or "Daily brief refreshed."

    with open("index.html", "r", encoding="utf-8") as f:
        soup = BeautifulSoup(f.read(), "html.parser")

    if (el := soup.find("div", id="dateline")):
        el.clear()
        el.append(date_str)

    if (t := soup.find("time", id="refreshed-at")):
        t["datetime"] = iso
        t.clear()
        t.append(refresh_label)

    if (wx := soup.find("div", id="weather")):
        wx.clear()
        wx_html = (
            f'<div class="wx-card"><div class="city">Houston</div>'
            f'<div class="temp">{h_temp if h_temp is not None else "--"}°</div>'
            f'<div class="cond">{escape(h_cond)}</div></div>'
            f'<div class="wx-card"><div class="city">Dallas</div>'
            f'<div class="temp">{d_temp if d_temp is not None else "--"}°</div>'
            f'<div class="cond">{escape(d_cond)}</div></div>'
        )
        wx.append(BeautifulSoup(wx_html, "html.parser"))

    if (brief := soup.find("div", id="brief")):
        h2 = brief.find("h2")
        brief.clear()
        if h2:
            brief.append(h2)
        brief.append(brief_text)

    for sec_id, stories in (("world", world), ("markets", markets), ("construction", construction)):
        sec = soup.find("section", id=sec_id)
        if not sec:
            continue
        for art in sec.find_all("article", class_="story"):
            art.decompose()
        for s in stories:
            sec.append(make_story(s))

    with open("index.html", "w", encoding="utf-8") as f:
        f.write(str(soup))
    print(
        f"OK: {date_str} — "
        f"{len(world)} world / {len(markets)} markets / {len(construction)} construction; "
        f"Houston {h_temp}°, Dallas {d_temp}°"
    )


if __name__ == "__main__":
    main()
