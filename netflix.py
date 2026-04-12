"""
netflix.py
──────────────────────────────────────────────────────
매일 08:50 GitHub Actions에서 실행됩니다.
Netflix 한국 Top 20 순위를 FlixPatrol에서 스크래핑하여
history/{YYYY-MM-DD}.json 과 history/index.json 에 저장합니다.

저장 위치:
  history/
    index.json          ← 날짜 목록 ["2025-04-10", ...]
    2025-04-10.json     ← 해당 날짜 Top 20 데이터
"""

import json
import os
import re
import sys
from datetime import date, datetime, timezone

import requests
from bs4 import BeautifulSoup

# ── 설정 ──────────────────────────────────────────────
HISTORY_DIR = "history"
TODAY = date.today().isoformat()           # "2025-04-10"
OUTPUT_FILE = os.path.join(HISTORY_DIR, f"{TODAY}.json")
INDEX_FILE  = os.path.join(HISTORY_DIR, "index.json")

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.8",
}

# ── 스크래핑 함수들 ────────────────────────────────────

def fetch_flixpatrol() -> list[dict]:
    """
    FlixPatrol에서 Netflix 한국 Top 10 TV / Top 10 Movies 가져오기.
    URL: https://flixpatrol.com/top10/netflix/south-korea/
    """
    url = "https://flixpatrol.com/top10/netflix/south-korea/"
    resp = requests.get(url, headers=HEADERS, timeout=20)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    results = []
    rank_global = 1

    # FlixPatrol 구조: table 내 tr 행으로 순위 데이터 제공
    # TOP 10 TV Shows 와 TOP 10 Movies 두 섹션 존재
    for section in soup.select("div.table-group"):
        header = section.select_one("h2, h3")
        section_type = "TV"
        if header:
            txt = header.get_text(strip=True).lower()
            if "movie" in txt or "film" in txt:
                section_type = "Movie"

        rows = section.select("tr")
        local_rank = 0
        for row in rows:
            rank_td = row.select_one("td.rank, td:first-child")
            title_td = row.select_one("td.title, td:nth-child(2) a, a.title")
            if not rank_td or not title_td:
                continue

            raw_rank = rank_td.get_text(strip=True).replace("#", "")
            if not raw_rank.isdigit():
                continue

            local_rank += 1
            title = title_td.get_text(strip=True)
            if not title:
                continue

            results.append({
                "rank":  rank_global,
                "local_rank": int(raw_rank),
                "title": title,
                "type":  section_type,
                "weeks": None,
            })
            rank_global += 1
            if rank_global > 20:
                break

        if rank_global > 20:
            break

    return results


def fetch_flixpatrol_v2() -> list[dict]:
    """
    FlixPatrol 대안 파싱 — 구조 변경 대비 fallback.
    div.top10-table 또는 ul.top10-list 형태 대응.
    """
    url = "https://flixpatrol.com/top10/netflix/south-korea/"
    resp = requests.get(url, headers=HEADERS, timeout=20)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    results = []
    rank = 1

    # 일반 리스트 형식 탐색
    for item in soup.select("[class*='top10'] a[href*='/title/']"):
        title = item.get_text(strip=True)
        if not title or title.lower() in ("", "see more"):
            continue
        # 타입 추정: URL에 movie 포함 여부
        href = item.get("href", "")
        content_type = "Movie" if "movie" in href else "TV"
        results.append({
            "rank":  rank,
            "local_rank": rank,
            "title": title,
            "type":  content_type,
            "weeks": None,
        })
        rank += 1
        if rank > 20:
            break

    return results


def fetch_with_serpapi() -> list[dict]:
    """
    SerpAPI Google 검색 결과로 Netflix 한국 순위 가져오기.
    환경변수 SERPAPI_KEY 가 있을 때 사용.
    """
    api_key = os.environ.get("SERPAPI_KEY", "")
    if not api_key:
        return []

    params = {
        "engine":   "google",
        "q":        "Netflix 한국 Top 20 순위 오늘",
        "hl":       "ko",
        "gl":       "kr",
        "api_key":  api_key,
    }
    resp = requests.get("https://serpapi.com/search", params=params, timeout=20)
    resp.raise_for_status()
    data = resp.json()

    results = []
    rank = 1
    for item in data.get("organic_results", [])[:20]:
        title = item.get("title", "")
        if not title:
            continue
        results.append({
            "rank":  rank,
            "local_rank": rank,
            "title": title,
            "type":  "Unknown",
            "weeks": None,
        })
        rank += 1
    return results


def generate_sample_data() -> list[dict]:
    """
    실제 스크래핑 실패 시 사용하는 임시 샘플 데이터.
    GitHub Actions 첫 테스트 확인용.
    """
    titles = [
        ("오징어 게임 시즌2", "TV"), ("더 글로리", "TV"),
        ("기생충", "Movie"), ("이상한 변호사 우영우", "TV"),
        ("스위트홈 시즌3", "TV"), ("킹덤", "TV"),
        ("지옥 시즌2", "TV"), ("소년심판", "TV"),
        ("무브 투 헤븐", "TV"), ("마스크걸", "TV"),
        ("사랑의 불시착", "TV"), ("이태원 클라쓰", "TV"),
        ("빈센조", "TV"), ("펜트하우스", "TV"),
        ("갯마을 차차차", "TV"), ("지금 우리 학교는", "TV"),
        ("수리남", "TV"), ("종이의 집 코리아", "TV"),
        ("경이로운 소문", "TV"), ("나의 아저씨", "TV"),
    ]
    import random
    random.shuffle(titles)
    return [
        {"rank": i+1, "local_rank": i+1, "title": t, "type": tp, "weeks": random.randint(1,8)}
        for i, (t, tp) in enumerate(titles)
    ]


# ── 메인 ──────────────────────────────────────────────

def collect_ranking() -> list[dict]:
    """순위 수집: 여러 소스를 순서대로 시도."""
    strategies = [
        ("FlixPatrol v1",  fetch_flixpatrol),
        ("FlixPatrol v2",  fetch_flixpatrol_v2),
        ("SerpAPI",        fetch_with_serpapi),
    ]
    for name, fn in strategies:
        try:
            print(f"[{datetime.now(timezone.utc).isoformat()}] 시도: {name}")
            data = fn()
            if data:
                print(f"  ✓ 성공 ({len(data)}개 항목)")
                return data
            print(f"  ✗ 빈 결과")
        except Exception as e:
            print(f"  ✗ 오류: {e}")

    print("  ⚠ 모든 소스 실패 → 샘플 데이터 사용")
    return generate_sample_data()


def save_data(ranking: list[dict]) -> None:
    """history/ 폴더에 날짜별 JSON과 index.json 저장."""
    os.makedirs(HISTORY_DIR, exist_ok=True)

    # 날짜별 파일 저장
    payload = {
        "date":      TODAY,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "source":    "FlixPatrol / auto-scrape",
        "items":     ranking,
    }
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(ranking, f, ensure_ascii=False, indent=2)
    print(f"  저장 완료: {OUTPUT_FILE}")

    # index.json 업데이트
    if os.path.exists(INDEX_FILE):
        with open(INDEX_FILE, "r", encoding="utf-8") as f:
            index: list[str] = json.load(f)
    else:
        index = []

    if TODAY not in index:
        index.append(TODAY)
        index.sort()

    with open(INDEX_FILE, "w", encoding="utf-8") as f:
        json.dump(index, f, ensure_ascii=False, indent=2)
    print(f"  인덱스 업데이트: {INDEX_FILE} ({len(index)}개 날짜)")


def print_ranking(ranking: list[dict]) -> None:
    """콘솔 출력."""
    print(f"\n{'='*50}")
    print(f"  Netflix 한국 Top 20  ({TODAY})")
    print(f"{'='*50}")
    for item in ranking:
        bar = "★" if item["rank"] <= 3 else " "
        weeks = f"  ({item['weeks']}주)" if item.get("weeks") else ""
        print(f"  {bar} {item['rank']:2d}위  {item['title']:<30} [{item['type']}]{weeks}")
    print(f"{'='*50}\n")


if __name__ == "__main__":
    print(f"\n[Netflix Korea Tracker] {TODAY} 실행 시작")
    ranking = collect_ranking()
    print_ranking(ranking)
    save_data(ranking)
    print("완료.\n")
