#!/usr/bin/env python3
"""
Fortnightly drift sweep for the China SMR Tracker.

    1. Pull headlines from Google News RSS, in Chinese and English.
       Free, no API key, no scraping.
    2. Hand those headlines to Claude together with the current state of
       data/reactors.yml and ask one question: what here contradicts,
       updates or is missing from the file?
    3. Write the answer to build/digest.md, build/digest.html and
       build/issue.md for the workflow to email and file as an issue.

The sweep never edits data/reactors.yml. It flags; a person verifies against
the primary source and makes the commit. That distinction is the difference
between a tracker people cite and a feed nobody trusts.

Run locally:
    ANTHROPIC_API_KEY=... python3 scripts/news_sweep.py
"""

import os
import sys
import time
import xml.etree.ElementTree as ET
from datetime import date, timedelta
from urllib.parse import quote_plus

import anthropic
import markdown
import requests
import yaml

DATA_FILE = "data/reactors.yml"
OUT_DIR = "build"
MODEL = "claude-sonnet-5-5"
LOOKBACK_DAYS = 21

# (query, locale). "zh" searches the Chinese-language edition, which is where
# construction news appears first; "en" catches international coverage and the
# designations that Chinese outlets do not report.
QUERIES = [
    ("玲龙一号 OR ACP100 进展", "zh"),
    ("小型模块化反应堆 OR 小型堆 开工 OR 并网 OR 投产", "zh"),
    ("石岛湾 高温气冷堆", "zh"),
    ("高温气冷堆 瑞金 OR 商运 OR 核准", "zh"),
    ("海上浮动核电站 OR 海洋核动力平台", "zh"),
    ("国家核安全局 小堆 建造许可证", "zh"),
    ("CAP200 OR 国家电投 小型堆", "zh"),
    ("核电 小堆 核准 国务院常务会议", "zh"),
    ("China small modular reactor", "en"),
    ("Linglong One ACP100", "en"),
    ("HTR-PM China high temperature gas cooled", "en"),
    ("China floating nuclear power plant", "en"),
]

RSS = ("https://news.google.com/rss/search?q={q}+when:{days}d"
       "&hl={hl}&gl={gl}&ceid={ceid}")

LOCALES = {
    "zh": {"hl": "zh-CN", "gl": "CN", "ceid": "CN:zh-Hans"},
    "en": {"hl": "en-US", "gl": "US", "ceid": "US:en"},
}

PROMPT = """You are the research assistant for an open-source tracker of small \
modular reactor projects in mainland China. The tracker's current state is below, \
followed by news headlines from the last {days} days.

Your job is to find drift: anything in the headlines that contradicts, updates or \
is missing from the tracker. You are not writing a news summary and you are not \
editing the data.

Current tracker state:
{state}

Headlines:
{headlines}

Write a short briefing in Markdown with exactly these sections:

## Status changes
Projects whose recorded status now looks wrong (for example, recorded as Under \
Construction but reported as grid-connected). For each, name the entry id, the \
recorded status, what the headline implies, and the headline's source.

## New projects
Reactor projects that appear in the headlines but have no entry. Only include \
projects that are in scope: electricity-generating, 300 MWe or less per module, \
in mainland China. Say explicitly if a project is near the scope boundary.

## Figures to check
Output, cost, schedule or ownership numbers that differ from the file.

## Nothing to do
Headlines that look relevant but do not change anything, in one line each.

Rules. Be specific: always cite the headline you are relying on. Never assert a \
date or a megawatt figure that is not in a headline. If a headline is vague, say \
it is vague rather than resolving it. If a section has nothing in it, write \
"Nothing this cycle." Keep the whole briefing under 800 words. Remember that \
everything you flag will be checked against a primary source before anyone edits \
the file, so flag generously but never state a flag as fact."""


def fetch(query, locale):
    cfg = LOCALES[locale]
    url = RSS.format(q=quote_plus(query), days=LOOKBACK_DAYS, **cfg)
    try:
        resp = requests.get(url, timeout=25,
                            headers={"User-Agent": "china-smr-tracker/1.0"})
        resp.raise_for_status()
        root = ET.fromstring(resp.content)
    except Exception as exc:                      # noqa: BLE001
        print(f"  query failed ({query}): {exc}", file=sys.stderr)
        return []
    items = []
    for item in list(root.iter("item"))[:12]:
        title = (item.findtext("title") or "").strip()
        pub = (item.findtext("pubDate") or "").strip()
        source = item.find("{*}source")
        publisher = source.text if source is not None else ""
        if title:
            items.append(f"- [{locale}] {title} ({publisher}; {pub[:16]})")
    return items


def tracker_state():
    with open(DATA_FILE, encoding="utf-8") as fh:
        reactors = yaml.safe_load(fh).get("reactors") or []
    lines = []
    for r in reactors:
        out = r.get("output") or {}
        dates = r.get("dates") or {}
        lines.append(
            f"- {r['id']}: {r.get('name_en')} ({r.get('name_zh','')}), "
            f"{r.get('design')}, {out.get('module_mwe')} MWe/module x "
            f"{out.get('modules')}, status {r.get('status')}, "
            f"construction start {dates.get('construction_start')}, "
            f"grid {dates.get('grid_connection')}, "
            f"commercial operation {dates.get('commercial_operation')}"
        )
    return "\n".join(lines)


def main():
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        print("ANTHROPIC_API_KEY is not set.", file=sys.stderr)
        return 1

    headlines = []
    for query, locale in QUERIES:
        print(f"  searching: {query}")
        headlines.extend(fetch(query, locale))
        time.sleep(1.2)                    # be polite to the RSS endpoint

    headlines = list(dict.fromkeys(headlines))      # dedupe, keep order
    print(f"  {len(headlines)} headlines collected")

    if not headlines:
        body = "## Nothing to do\n\nNo headlines returned this cycle. If this \
repeats, the RSS queries have probably broken."
    else:
        client = anthropic.Anthropic(api_key=key)
        response = client.messages.create(
            model=MODEL,
            max_tokens=4000,
            messages=[{"role": "user", "content": PROMPT.format(
                days=LOOKBACK_DAYS,
                state=tracker_state(),
                headlines="\n".join(headlines),
            )}],
        )
        body = "".join(b.text for b in response.content if b.type == "text")
        if response.stop_reason == "max_tokens":
            print("  WARNING: response was truncated.", file=sys.stderr)

    today = date.today().isoformat()
    since = (date.today() - timedelta(days=LOOKBACK_DAYS)).isoformat()
    subject = f"SMR tracker sweep {today}"
    header = (f"# {subject}\n\n*{len(headlines)} headlines, {since} to {today}. "
              "Nothing below is confirmed. Check the primary source before "
              "editing `data/reactors.yml`.*\n\n")

    os.makedirs(OUT_DIR, exist_ok=True)
    with open(f"{OUT_DIR}/digest.md", "w", encoding="utf-8") as fh:
        fh.write(header + body)
    with open(f"{OUT_DIR}/issue.md", "w", encoding="utf-8") as fh:
        fh.write(header + body)
    with open(f"{OUT_DIR}/digest.html", "w", encoding="utf-8") as fh:
        fh.write("<meta charset='utf-8'>"
                 "<div style=\"font:16px/1.55 -apple-system,system-ui,sans-serif;"
                 "max-width:40rem;margin:2rem auto;color:#19211E\">"
                 + markdown.markdown(header + body) + "</div>")
    with open(f"{OUT_DIR}/subject.txt", "w", encoding="utf-8") as fh:
        fh.write(subject)

    print(f"  wrote {OUT_DIR}/digest.md, digest.html, issue.md")
    return 0


if __name__ == "__main__":
    sys.exit(main())
