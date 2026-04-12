"""
netflix.py
──────────────────────────────────────────────────────
Netflix 공식 Tudum 페이지에서 한국 Top 10 TV + Top 10 영화를
Playwright(헤드리스 브라우저)로 파싱하여 합산 Top 20 생성.

Tudum 페이지 실제 HTML 구조:
  <ul>
    <li>
      <img alt="작품 제목">
      ...
      #1 in Shows  (또는 #1 in Films)
    </li>
    ...
  </ul>

저장 위치:
  history/
    index.json       ← 주차 목록 ["2026-W14", ...]
    2026-W14.json    ← 해당 주 Top 20 데이터
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
WEEK_KEY   = f"{year}-W{week:02d}"
OUTPUT_FILE = os.path.join(HISTORY_DIR, f"{WEEK_KEY}.json")
INDEX_FILE  = os.path.join(HISTORY_DIR, "index.json")

TV_URL    = "https://www.netflix.com/tudum/top10/south-korea/tv"
MOVIE_URL = "https://www.netflix.com/tudum/top10/south-korea"


# ── Playwright 스크래핑 ────────────────────────────────

def scrape_tudum(url: str, content_type: str) -> list[dict]:
    """
    Playwright로 Netflix Tudum 페이지 렌더링 후 순위 파싱.

    실제 HTML 구조:
      <ul>
        <li>
          <img alt="작품제목: Season 1">
          ...텍스트..."#1 in Shows"...
        </li>
      </ul>

    전략:
      1. <img alt="..."> 에서 제목 추출
      2. 같은 <li> 안의 "#N in Shows/Films" 텍스트로 순위 확인
    """
    from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout
    from bs4 import BeautifulSoup

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

        # 순위 항목이 나타날 때까지 대기
        try:
            page.wait_for_selector("li img[alt]", timeout=20000)
        except PWTimeout:
            print("  ⚠ img[alt] 셀렉터 타임아웃 — 현재 DOM으로 파싱 시도")

        html = page.content()
        browser.close()

    soup = BeautifulSoup(html, "lxml")

    # ── 날짜 범위 추출 ──────────────────────────────────
    week_range = ""
    for el in soup.find_all(string=re.compile(r"\d+/\d+/\d+\s*-\s*\d+/\d+/\d+")):
        m = re.search(r"(\d+/\d+/\d+)\s*-\s*(\d+/\d+/\d+)", str(el))
        if m:
            week_range = f"{m.group(1)} - {m.group(2)}"
            break

    # ── 핵심 파싱: <li> 단위로 순위+제목 추출 ──────────
    results = []

    # Tudum 구조: <ul> > <li> 각각이 하나의 순위 항목
    # li 안에 img[alt]="제목" 과 "#N in Shows" 텍스트가 함께 존재
    rank_pattern = re.compile(r"#(\d+)\s+in\s+(Shows|Films|Movies)", re.IGNORECASE)

    for li in soup.find_all("li"):
        li_text = li.get_text(separator=" ", strip=True)

        # "#N in Shows/Films" 패턴 검색
        m = rank_pattern.search(li_text)
        if not m:
            continue

        rank = int(m.group(1))
        if rank > 10:
            continue

        # 제목: li 안의 img[alt] 에서 추출
        img = li.find("img", alt=True)
        if not img:
            continue

        raw_title = img["alt"].strip()
        # ": Season N", ": Limited Series" 등 suffix 제거
        title = re.sub(r":\s*(Season\s*\d+|Limited Series|Part\s*\d+|Volume\s*\d+)$",
                       "", raw_title, flags=re.IGNORECASE).strip()

        if not title or title.lower() in ("", "ranking"):
            continue

        results.append({
            "rank":         rank,
            "section_rank": rank,
            "title":        title,
            "full_title":   raw_title,
            "type":         content_type,
            "week_range":   week_range,
        })

    # 중복 제거 (같은 순위가 두 번 나올 경우 첫 번째 유지)
    seen = set()
    unique = []
    for item in sorted(results, key=lambda x: x["rank"]):
        if item["rank"] not in seen:
            seen.add(item["rank"])
            unique.append(item)

    print(f"  → {content_type} {len(unique)}개 파싱 완료 (주간: {week_range or 'N/A'})")
    if unique:
        for item in unique:
            print(f"       #{item['rank']}  {item['title']}")

    return unique


def collect_ranking() -> list[dict]:
    """TV Top10 + Movie Top10 → 합산 Top20"""
    print("[1/2] TV 순위 수집")
    tv = scrape_tudum(TV_URL, "TV")

    print("[2/2] 영화 순위 수집")
    movies = scrape_tudum(MOVIE_URL, "Movie")

    # TV 1~10위, 영화 11~20위로 통합
    combined = []
    for item in tv[:10]:
        combined.append({**item, "rank": item["section_rank"]})
    for item in movies[:10]:
        combined.append({**item, "rank": item["section_rank"] + 10})

    return combined


def save_data(ranking: list[dict]) -> None:
    os.makedirs(HISTORY_DIR, exist_ok=True)

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(ranking, f, ensure_ascii=False, indent=2)
    print(f"\n  저장: {OUTPUT_FILE}")

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
    print(f"\n{'='*58}")
    print(f"  Netflix 한국 Top 20  ({WEEK_KEY}  {week_range})")
    print(f"{'='*58}")
    for item in ranking:
        star = "★" if item["rank"] <= 3 else " "
        sec  = f"[{item['type']} #{item['section_rank']}위]"
        print(f"  {star} {item['rank']:2d}위  {item['title']:<35} {sec}")
    print(f"{'='*58}\n")


if __name__ == "__main__":
    print(f"\n[Netflix Korea Tracker] {WEEK_KEY} 실행 시작")
    ranking = collect_ranking()

    if not ranking:
        print("⚠ 데이터 없음 — 종료")
        sys.exit(1)

    print_ranking(ranking)
    save_data(ranking)
    print("완료.\n")
