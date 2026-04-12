"""
netflix.py
──────────────────────────────────────────────────────
Netflix 공식 Tudum 페이지에서 한국 Top 10 TV + Top 10 영화를
Playwright(헤드리스 브라우저)로 파싱하여 합산 Top 20 생성.

저장 위치:
  history/
    index.json          ← 주차 목록 ["2026-W14", ...]
    2026-W14.json       ← 해당 주 Top 20 데이터
"""

import json
import os
import re
import sys
from datetime import date, datetime, timezone

# ── 설정 ──────────────────────────────────────────────
HISTORY_DIR = "history"

today      = date.today()
year, week, _ = today.isocalendar()
WEEK_KEY   = f"{year}-W{week:02d}"          # ex) "2026-W15"
OUTPUT_FILE = os.path.join(HISTORY_DIR, f"{WEEK_KEY}.json")
INDEX_FILE  = os.path.join(HISTORY_DIR, "index.json")

TV_URL    = "https://www.netflix.com/tudum/top10/south-korea/tv"
MOVIE_URL = "https://www.netflix.com/tudum/top10/south-korea"

# ── Playwright 스크래핑 ────────────────────────────────

def scrape_tudum(url: str, content_type: str) -> list[dict]:
    """
    Playwright로 Netflix Tudum 페이지 렌더링 후 순위 파싱.
    반환: [{"rank": 1, "title": "...", "type": "TV"|"Movie", "week_range": "..."}, ...]
    """
    from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

    results = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(
            locale="ko-KR",
            user_agent=(
                "Mozilla/5.0 (X11; Linux x86_64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
        )
        page = ctx.new_page()

        print(f"  접속 중: {url}")
        page.goto(url, wait_until="networkidle", timeout=60000)

        # 순위 컨테이너가 로드될 때까지 대기
        # Tudum 페이지: ol 또는 [data-testid] 속성이 있는 리스트
        try:
            page.wait_for_selector("table, ol, [class*='RankList'], [class*='rank']", timeout=20000)
        except PWTimeout:
            print("  ⚠ 셀렉터 타임아웃 — 현재 DOM으로 파싱 시도")

        html = page.content()
        browser.close()

    # ── HTML 파싱 ──────────────────────────────────────
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "lxml")

    # 날짜 범위 추출 (예: "3/23/26 - 3/29/26")
    week_range = ""
    for el in soup.find_all(string=re.compile(r"\d+/\d+/\d+\s*-\s*\d+/\d+/\d+")):
        m = re.search(r"(\d+/\d+/\d+)\s*-\s*(\d+/\d+/\d+)", el)
        if m:
            week_range = f"{m.group(1)} - {m.group(2)}"
            break

    # 순위 항목 파싱 전략 1: <table> 기반
    rows = soup.select("table tbody tr, table tr")
    rank = 1
    for row in rows:
        cells = row.find_all(["td", "th"])
        if len(cells) < 2:
            continue
        # 첫 셀이 숫자(순위)이거나 제목 셀 탐색
        title = ""
        for cell in cells:
            text = cell.get_text(strip=True)
            if text and not text.isdigit() and len(text) > 1:
                title = text
                break
        if title:
            results.append({
                "rank":       rank,
                "title":      title,
                "type":       content_type,
                "week_range": week_range,
            })
            rank += 1
            if rank > 10:
                break

    # 전략 2: 순위 번호 + 제목 패턴 탐색 (table 실패 시)
    if not results:
        # 숫자로 시작하는 span/div + 인접 제목
        rank_els = soup.find_all(
            lambda t: t.name in ("span", "div", "p", "td") and
                      t.get_text(strip=True).isdigit() and
                      1 <= int(t.get_text(strip=True)) <= 10
        )
        seen_ranks = set()
        for el in rank_els:
            r = int(el.get_text(strip=True))
            if r in seen_ranks:
                continue
            seen_ranks.add(r)
            # 인접 형제 또는 부모에서 제목 탐색
            parent = el.parent
            title  = ""
            for sib in parent.find_all(["span", "div", "a", "h3", "p"]):
                t = sib.get_text(strip=True)
                if t and not t.isdigit() and t != el.get_text(strip=True) and len(t) > 2:
                    title = t
                    break
            if title:
                results.append({
                    "rank":       r,
                    "title":      title,
                    "type":       content_type,
                    "week_range": week_range,
                })
        results.sort(key=lambda x: x["rank"])

    # 전략 3: <li> 기반 리스트
    if not results:
        items = soup.select("ol li, ul li")
        rank  = 1
        for li in items:
            text = li.get_text(separator=" ", strip=True)
            # 숫자로 시작하면 제거
            text = re.sub(r"^\d+\s*", "", text).strip()
            if text and len(text) > 2:
                results.append({
                    "rank":       rank,
                    "title":      text[:80],
                    "type":       content_type,
                    "week_range": week_range,
                })
                rank += 1
                if rank > 10:
                    break

    print(f"  → {content_type} {len(results)}개 파싱 완료 (주간: {week_range or 'N/A'})")
    return results


def collect_ranking() -> list[dict]:
    """TV Top10 + Movie Top10 → 합산 Top20"""
    print("[1/2] TV 순위 수집")
    tv     = scrape_tudum(TV_URL,    "TV")

    print("[2/2] 영화 순위 수집")
    movies = scrape_tudum(MOVIE_URL, "Movie")

    # TV는 1~10위, 영화는 11~20위로 통합 순위 생성
    combined = []
    for i, item in enumerate(tv[:10], start=1):
        combined.append({**item, "rank": i, "section_rank": item["rank"]})
    for i, item in enumerate(movies[:10], start=11):
        combined.append({**item, "rank": i, "section_rank": item["rank"]})

    return combined


def save_data(ranking: list[dict]) -> None:
    os.makedirs(HISTORY_DIR, exist_ok=True)

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(ranking, f, ensure_ascii=False, indent=2)
    print(f"  저장: {OUTPUT_FILE}")

    # index.json 업데이트
    if os.path.exists(INDEX_FILE):
        with open(INDEX_FILE, "r", encoding="utf-8") as f:
            index: list[str] = json.load(f)
    else:
        index = []

    if WEEK_KEY not in index:
        index.append(WEEK_KEY)
        index.sort()

    with open(INDEX_FILE, "w", encoding="utf-8") as f:
        json.dump(index, f, ensure_ascii=False, indent=2)
    print(f"  인덱스 업데이트: {INDEX_FILE} ({len(index)}개 주차)")


def print_ranking(ranking: list[dict]) -> None:
    week_range = ranking[0].get("week_range", "") if ranking else ""
    print(f"\n{'='*55}")
    print(f"  Netflix 한국 Top 20  ({WEEK_KEY}  {week_range})")
    print(f"{'='*55}")
    for item in ranking:
        star = "★" if item["rank"] <= 3 else " "
        sec  = f"[{item['type']} #{item.get('section_rank', item['rank'])}]"
        print(f"  {star} {item['rank']:2d}위  {item['title']:<35} {sec}")
    print(f"{'='*55}\n")


if __name__ == "__main__":
    print(f"\n[Netflix Korea Tracker] {WEEK_KEY} 실행 시작")
    ranking = collect_ranking()

    if not ranking:
        print("⚠ 데이터 없음 — 종료")
        sys.exit(1)

    print_ranking(ranking)
    save_data(ranking)
    print("완료.\n")
