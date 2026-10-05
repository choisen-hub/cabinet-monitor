"""
3년치 주간 스냅샷 백필 스크립트

두 Wikipedia 페이지에서 역대 국무위원 임기 데이터를 수집해
3년 전부터 현재까지 매주 1회 스냅샷을 생성합니다.
  - 윤석열 정부: https://ko.wikipedia.org/wiki/윤석열_정부
  - 이재명 정부: https://ko.wikipedia.org/wiki/이재명_정부
"""

import json
import re
import sys
from datetime import date, timedelta
from pathlib import Path
from typing import Optional, Tuple

import requests
from bs4 import BeautifulSoup

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    )
}

SNAPSHOTS_FILE = Path(__file__).parent / "snapshots.json"

# 포함할 직책 (국무위원 범위)
INCLUDE_TITLES = {
    "국무총리", "경제부총리겸기획재정부 장관", "경제부총리겸재정경제부 장관",
    "사회부총리겸교육부 장관", "과학기술부총리겸과학기술정보통신부 장관",
    "교육부 장관", "과학기술정보통신부 장관", "외교부 장관", "통일부 장관",
    "법무부 장관", "국방부 장관", "행정안전부 장관", "문화체육관광부 장관",
    "농림축산식품부 장관", "산업통상자원부 장관", "산업통상부 장관",
    "보건복지부 장관", "환경부 장관", "기후에너지환경부 장관",
    "고용노동부 장관", "여성가족부 장관", "성평등가족부 장관",
    "국토교통부 장관", "해양수산부 장관", "중소벤처기업부 장관",
    "국가보훈부 장관", "국가보훈처장", "기획예산처 장관",
}

# 제외할 직책 (장관급이지만 국무위원 아닌 직책)
EXCLUDE_TITLES = {
    "대통령", "국가정보원장", "대통령비서실장", "대통령비서실 정책실장",
    "국가안보실장", "국무조정실장", "검찰총장", "방송통신위원회 위원장",
    "공정거래위원회 위원장", "금융위원회 위원장", "국민권익위원회 위원장",
}


# ── 날짜 파싱 ──────────────────────────────────────────────

MONTH_KR = {
    "1월": 1, "2월": 2, "3월": 3, "4월": 4, "5월": 5, "6월": 6,
    "7월": 7, "8월": 8, "9월": 9, "10월": 10, "11월": 11, "12월": 12,
}

def parse_date(text: str) -> Optional[date]:
    """
    '2022년 5월 10일' → date(2022, 5, 10)
    Returns None if unparseable.
    """
    text = text.strip()
    m = re.search(r"(\d{4})년\s*(\d{1,2})월\s*(\d{1,2})일", text)
    if m:
        try:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            pass
    return None


def parse_tenure(tenure_text: str) -> Tuple[Optional[date], Optional[date]]:
    """
    '2022년 5월 10일~2023년 12월 28일' → (start, end)
    '2025년 7월 3일~'                  → (start, None)  # 현재 재임 중
    """
    tenure_text = tenure_text.replace(" ", "")
    # Split on ~ or -
    parts = re.split(r"[~\-–]", tenure_text, maxsplit=1)
    start = parse_date(parts[0]) if parts else None
    end = None
    if len(parts) > 1 and parts[1]:
        end = parse_date(parts[1])
    return start, end


# ── HTML 테이블 → 2D 그리드 ────────────────────────────────

def table_to_grid(table_el) -> list[list[str]]:
    """rowspan/colspan을 처리해 2D 텍스트 그리드로 변환."""
    grid: list[list[str | None]] = []
    span_map: dict[tuple[int, int], str] = {}  # (row, col) → text

    rows = table_el.find_all("tr")
    for ri, row in enumerate(rows):
        cells = row.find_all(["th", "td"])
        # ensure row exists
        while len(grid) <= ri:
            grid.append([])

        ci = 0
        for cell in cells:
            # skip columns already filled by previous rowspan
            while span_map.get((ri, ci)) is not None:
                grid[ri].append(span_map[(ri, ci)])
                ci += 1

            text = re.sub(r"\[\w+\]", "", cell.get_text(strip=True))
            rowspan = int(cell.get("rowspan", 1))
            colspan = int(cell.get("colspan", 1))

            for dr in range(rowspan):
                for dc in range(colspan):
                    if dr == 0 and dc == 0:
                        continue
                    span_map[(ri + dr, ci + dc)] = text

            grid[ri].append(text)
            ci += colspan

        # flush remaining spans for this row
        while span_map.get((ri, ci)) is not None:
            grid[ri].append(span_map[(ri, ci)])
            ci += 1

    return grid


# ── Wikipedia 스크래퍼 ─────────────────────────────────────

def scrape_gov_page(url: str, gov_name: str) -> list[dict]:
    """
    Returns list of records:
      { title, name, start: date, end: date|None, source }
    """
    print(f"  Fetching {url} ...")
    resp = requests.get(url, headers=HEADERS, timeout=20)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "lxml")

    tables = soup.find_all("table", class_="wikitable")
    if not tables:
        print(f"  [warn] no wikitable found on {url}")
        return []

    records = []

    # 이재명 정부 특수 처리: 첫 번째 테이블이 국무위원 목록
    # (각 행에 장관 2명, 4셀씩: 직위/이름/사진/기간)
    if "이재명" in gov_name:
        table = tables[0]
        for row in table.find_all("tr")[1:]:
            cells = row.find_all(["th", "td"])
            texts = [re.sub(r"\[\w+\]", "", c.get_text(strip=True)) for c in cells]
            for offset in (0, 4):
                if len(texts) > offset + 1:
                    title = texts[offset].strip()
                    name = texts[offset + 1].strip()
                    tenure = texts[offset + 3].strip() if len(texts) > offset + 3 else ""
                    if not title or not name:
                        continue
                    start, end = parse_tenure(tenure)
                    records.append({
                        "title": title, "name": name,
                        "start": start, "end": end, "source": gov_name,
                    })
        return records

    # 윤석열 정부: 국무위원 표 (Table 0) — rowspan 처리
    table = tables[0]
    grid = table_to_grid(table)

    current_title = ""
    for row in grid:
        if not row:
            continue
        # 헤더 행 건너뛰기
        if row[0] in ("직책", "국무위원", "기타 장관급 중앙행정기관장"):
            continue

        # 3컬럼: [직책, 성명, 임기] or [성명, 임기] (직책 rowspan 연속)
        if len(row) >= 3:
            title_raw, name, tenure = row[0], row[1], row[2]
        elif len(row) == 2:
            title_raw, name, tenure = current_title, row[0], row[1]
        else:
            continue

        # 직책이 비어있으면 이전 직책 재사용
        if title_raw.strip():
            current_title = title_raw.strip()

        name = name.strip()
        tenure = tenure.strip()
        if not name or not current_title:
            continue

        start, end = parse_tenure(tenure)
        records.append({
            "title": current_title, "name": name,
            "start": start, "end": end, "source": gov_name,
        })

    return records


def filter_ministers(records: list[dict]) -> list[dict]:
    """국무위원만 남기고 나머지 제거. INCLUDE/EXCLUDE 목록 기반."""
    result = []
    for r in records:
        t = r["title"]
        # 명시 제외
        if t in EXCLUDE_TITLES:
            continue
        # 명시 포함이거나 "장관"이 들어가면 포함
        if t in INCLUDE_TITLES or "장관" in t or "국무총리" in t:
            result.append(r)
    return result


# ── 스냅샷 생성 ────────────────────────────────────────────

def cabinet_on(records: list[dict], target: date) -> list[dict]:
    """주어진 날짜에 재임 중인 국무위원 목록 반환."""
    seen_titles: dict[str, dict] = {}
    for r in records:
        start = r["start"]
        end = r["end"]
        if start is None:
            continue
        if start > target:
            continue
        if end is not None and end < target:
            continue
        # 같은 직책에 여러 명이면 가장 최근 임명자 우선
        title = r["title"]
        if title not in seen_titles or (start > (seen_titles[title]["_start"] or date.min)):
            seen_titles[title] = {
                "title": title,
                "name": r["name"],
                "appointed": start.strftime("%Y년 %-m월 %-d일~"),
                "photo": "",
                "source": r["source"],
                "_start": start,
            }

    result = list(seen_titles.values())
    # Remove internal _start key
    for m in result:
        m.pop("_start", None)
    return result


def generate_weekly_snapshots(records: list[dict], start_date: date, end_date: date) -> list[dict]:
    snapshots = []
    current = start_date
    while current <= end_date:
        ministers = cabinet_on(records, current)
        if ministers:
            snapshots.append({
                "timestamp": current.strftime("%Y-%m-%d 00:00:00"),
                "ministers": ministers,
            })
        current += timedelta(weeks=1)
    return snapshots


# ── Main ──────────────────────────────────────────────────

def main():
    print("=== 역대 국무위원 데이터 수집 ===")

    # 기존 스냅샷 로드 (실시간 갱신된 것 보존)
    existing = []
    if SNAPSHOTS_FILE.exists():
        with open(SNAPSHOTS_FILE, encoding="utf-8") as f:
            existing = json.load(f)
    existing_ts = {s["timestamp"] for s in existing}
    print(f"기존 스냅샷: {len(existing)}개")

    # 두 정부 데이터 수집
    all_records = []
    try:
        yoon = scrape_gov_page(
            "https://ko.wikipedia.org/wiki/%EC%9C%A4%EC%84%9D%EC%97%B4_%EC%A0%95%EB%B6%80",
            "윤석열 정부"
        )
        yoon = filter_ministers(yoon)
        print(f"  윤석열 정부 국무위원 레코드: {len(yoon)}개")
        all_records.extend(yoon)
    except Exception as e:
        print(f"  [error] 윤석열 정부: {e}")

    try:
        lee = scrape_gov_page(
            "https://ko.wikipedia.org/wiki/%EC%9D%B4%EC%9E%AC%EB%AA%85_%EC%A0%95%EB%B6%80",
            "이재명 정부"
        )
        lee = filter_ministers(lee)
        print(f"  이재명 정부 국무위원 레코드: {len(lee)}개")
        all_records.extend(lee)
    except Exception as e:
        print(f"  [error] 이재명 정부: {e}")

    if not all_records:
        print("데이터 없음. 종료.")
        sys.exit(1)

    # 날짜 범위: 3년 전 ~ 오늘
    today = date.today()
    three_years_ago = today.replace(year=today.year - 3)
    # 가장 가까운 일요일로 맞추기
    three_years_ago -= timedelta(days=three_years_ago.weekday())

    print(f"\n=== 주간 스냅샷 생성: {three_years_ago} ~ {today} ===")
    new_snapshots = generate_weekly_snapshots(all_records, three_years_ago, today)
    print(f"생성된 스냅샷: {len(new_snapshots)}개")

    # 기존 스냅샷과 병합 (중복 제거, 시간순 정렬)
    merged = {s["timestamp"]: s for s in new_snapshots}
    for s in existing:
        # 실시간 갱신 스냅샷은 보존 (타임스탬프에 시분초 있음)
        if "00:00:00" not in s["timestamp"]:
            merged[s["timestamp"]] = s

    final = sorted(merged.values(), key=lambda s: s["timestamp"])

    with open(SNAPSHOTS_FILE, "w", encoding="utf-8") as f:
        json.dump(final, f, ensure_ascii=False, indent=2)

    print(f"\n저장 완료: {SNAPSHOTS_FILE}")
    print(f"총 스냅샷: {len(final)}개")

    # 샘플 출력
    print("\n--- 샘플 스냅샷 ---")
    for snap in [final[0], final[len(final)//2], final[-1]]:
        print(f"\n[{snap['timestamp']}] 국무위원 {len(snap['ministers'])}명")
        for m in snap["ministers"][:3]:
            print(f"  {m['title']}: {m['name']} ({m['appointed']})")
        print("  ...")


if __name__ == "__main__":
    main()
