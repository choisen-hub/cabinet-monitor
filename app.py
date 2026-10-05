import json
import logging
import re
import time
from datetime import datetime
from pathlib import Path

import requests
from apscheduler.schedulers.background import BackgroundScheduler
from bs4 import BeautifulSoup
from flask import Flask, jsonify, render_template, request
from flask_cors import CORS

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

app = Flask(__name__)
CORS(app)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8",
}

DATA_FILE = Path(__file__).parent / "ministers_cache.json"
SNAPSHOTS_FILE = Path(__file__).parent / "snapshots.json"

# ──────────────────────────────────────────────────────────
# Scrapers
# ──────────────────────────────────────────────────────────

def scrape_korea_net() -> list[dict]:
    url = "https://www.korea.net/Government/Administration/Cabinet"
    try:
        resp = requests.get(url, headers=HEADERS, timeout=15, allow_redirects=True)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "lxml")
        ministers = []
        for card in soup.select(".minister-list li, .cabinet-list li, .person-list li, li.person"):
            name_el = card.select_one(".name, .minister-name, strong, h3, h4")
            title_el = card.select_one(".title, .position, .post, p, span")
            img_el = card.select_one("img")
            if not name_el:
                continue
            ministers.append({
                "name": name_el.get_text(strip=True),
                "title": title_el.get_text(strip=True) if title_el else "",
                "photo": img_el["src"] if img_el and img_el.get("src") else "",
                "appointed": "",
                "source": "korea.net",
            })
        if ministers:
            log.info("korea.net: %d ministers scraped", len(ministers))
            return ministers
    except Exception as exc:
        log.warning("korea.net scrape failed: %s", exc)
    return []


def scrape_opm() -> list[dict]:
    url = "https://www.opm.go.kr/opm/office/group01.do"
    try:
        resp = requests.get(url, headers=HEADERS, timeout=15)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "lxml")
        ministers = []
        for card in soup.select(".org_person, .member_info, .minister_wrap, .person_box"):
            name_el = card.select_one(".name, strong, h3, h4, .person_name")
            title_el = card.select_one(".position, .title, .dept_name, p")
            img_el = card.select_one("img")
            if not name_el:
                continue
            ministers.append({
                "name": name_el.get_text(strip=True),
                "title": title_el.get_text(strip=True) if title_el else "",
                "photo": img_el["src"] if img_el and img_el.get("src") else "",
                "appointed": "",
                "source": "opm.go.kr",
            })
        if ministers:
            log.info("opm.go.kr: %d ministers scraped", len(ministers))
            return ministers
    except Exception as exc:
        log.warning("opm.go.kr scrape failed: %s", exc)
    return []


def scrape_wikipedia() -> list[dict]:
    """Wikipedia 이재명 정부 페이지에서 국무위원 목록 수집.
    테이블 구조: 각 행에 장관 2명, 셀 순서 [직위, 이름, 사진, 기간, 직위, 이름, 사진, 기간]
    """
    url = "https://ko.wikipedia.org/wiki/%EC%9D%B4%EC%9E%AC%EB%AA%85_%EC%A0%95%EB%B6%80"
    try:
        resp = requests.get(url, headers=HEADERS, timeout=15)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "lxml")

        tables = soup.select("table.wikitable")
        if not tables:
            return []

        ministers = []
        table = tables[0]
        for row in table.select("tr")[1:]:
            cells = row.find_all(["th", "td"])
            texts = [re.sub(r"\[\w+\]", "", c.get_text(strip=True)) for c in cells]
            for offset in (0, 4):
                if len(texts) > offset + 1:
                    title = texts[offset].strip()
                    name = texts[offset + 1].strip()
                    appointed = texts[offset + 3].strip() if len(texts) > offset + 3 else ""
                    if title and name:
                        ministers.append({
                            "name": name,
                            "title": title,
                            "photo": "",
                            "appointed": appointed,
                            "source": "위키피디아",
                        })

        if ministers:
            log.info("wikipedia: %d ministers scraped", len(ministers))
            return ministers
    except Exception as exc:
        log.warning("wikipedia scrape failed: %s", exc)
    return []


# ──────────────────────────────────────────────────────────
# Cache helpers
# ──────────────────────────────────────────────────────────

def load_cache() -> dict:
    if DATA_FILE.exists():
        with open(DATA_FILE, encoding="utf-8") as f:
            return json.load(f)
    return {"ministers": [], "last_updated": None, "history": []}


def save_cache(data: dict):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def load_snapshots() -> list[dict]:
    if SNAPSHOTS_FILE.exists():
        with open(SNAPSHOTS_FILE, encoding="utf-8") as f:
            return json.load(f)
    return []


def save_snapshot(ministers: list[dict], timestamp: str):
    snapshots = load_snapshots()
    snapshots.append({"timestamp": timestamp, "ministers": ministers})
    snapshots = snapshots[-52:]  # keep up to ~1 year of weekly snapshots
    with open(SNAPSHOTS_FILE, "w", encoding="utf-8") as f:
        json.dump(snapshots, f, ensure_ascii=False, indent=2)


def detect_changes(old: list[dict], new: list[dict]) -> list[dict]:
    old_map = {m["title"]: m["name"] for m in old}
    new_map = {m["title"]: m["name"] for m in new}
    changes = []
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    for title, name in new_map.items():
        if title not in old_map:
            changes.append({"type": "신규", "title": title, "name": name, "timestamp": ts})
        elif old_map[title] != name:
            changes.append({
                "type": "교체",
                "title": title,
                "name": name,
                "prev_name": old_map[title],
                "timestamp": ts,
            })

    for title in old_map:
        if title not in new_map:
            changes.append({
                "type": "해임",
                "title": title,
                "name": old_map[title],
                "timestamp": ts,
            })

    return changes


# ──────────────────────────────────────────────────────────
# Main fetch logic
# ──────────────────────────────────────────────────────────

def fetch_ministers() -> list[dict]:
    for scraper in [scrape_korea_net, scrape_opm, scrape_wikipedia]:
        result = scraper()
        if len(result) >= 5:
            return result
    log.warning("All scrapers returned insufficient data")
    return []


def refresh_data():
    log.info("Refreshing minister data...")
    cache = load_cache()
    new_ministers = fetch_ministers()

    if not new_ministers:
        log.warning("No data fetched; keeping existing cache")
        return

    changes = detect_changes(cache.get("ministers", []), new_ministers)
    history = cache.get("history", [])
    if changes:
        log.info("%d change(s) detected", len(changes))
        history = changes + history

    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cache["ministers"] = new_ministers
    cache["last_updated"] = ts
    cache["history"] = history[:100]
    save_cache(cache)
    save_snapshot(new_ministers, ts)
    log.info("Cache updated with %d ministers", len(new_ministers))


# ──────────────────────────────────────────────────────────
# Routes
# ──────────────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/ministers")
def api_ministers():
    cache = load_cache()
    return jsonify(cache)


@app.route("/api/snapshots")
def api_snapshots():
    snapshots = load_snapshots()
    # Return just metadata (timestamps + count), not full minister lists
    meta = [{"index": i, "timestamp": s["timestamp"], "count": len(s["ministers"])}
            for i, s in enumerate(snapshots)]
    return jsonify({"snapshots": meta})


@app.route("/api/snapshot/<int:idx>")
def api_snapshot(idx: int):
    snapshots = load_snapshots()
    if idx < 0 or idx >= len(snapshots):
        return jsonify({"error": "not found"}), 404
    return jsonify(snapshots[idx])


@app.route("/api/profile")
def api_profile():
    """Fetch a brief Wikipedia summary for a minister by name."""
    name = request.args.get("name", "").strip()
    if not name:
        return jsonify({"error": "name required"}), 400

    # Clean spaces in name (e.g. "조 현" → "조현" for search)
    search_name = name.replace(" ", "")
    wiki_api = "https://ko.wikipedia.org/api/rest_v1/page/summary/" + requests.utils.quote(search_name)
    try:
        resp = requests.get(wiki_api, headers=HEADERS, timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            return jsonify({
                "name": name,
                "summary": data.get("extract", ""),
                "thumbnail": data.get("thumbnail", {}).get("source", ""),
                "wiki_url": data.get("content_urls", {}).get("mobile", {}).get("page", ""),
            })
    except Exception as exc:
        log.warning("Wikipedia profile fetch failed for %s: %s", name, exc)

    # Fallback: try with original name including spaces
    if search_name != name:
        wiki_api2 = "https://ko.wikipedia.org/api/rest_v1/page/summary/" + requests.utils.quote(name)
        try:
            resp2 = requests.get(wiki_api2, headers=HEADERS, timeout=10)
            if resp2.status_code == 200:
                data2 = resp2.json()
                return jsonify({
                    "name": name,
                    "summary": data2.get("extract", ""),
                    "thumbnail": data2.get("thumbnail", {}).get("source", ""),
                    "wiki_url": data2.get("content_urls", {}).get("mobile", {}).get("page", ""),
                })
        except Exception:
            pass

    return jsonify({"name": name, "summary": "", "thumbnail": "", "wiki_url": ""})


@app.route("/api/refresh", methods=["POST"])
def api_refresh():
    start = time.time()
    refresh_data()
    elapsed = round(time.time() - start, 2)
    cache = load_cache()
    return jsonify({
        "status": "ok",
        "elapsed": elapsed,
        "count": len(cache.get("ministers", [])),
        "last_updated": cache.get("last_updated"),
    })


# ──────────────────────────────────────────────────────────
# Scheduler + startup
# ──────────────────────────────────────────────────────────

scheduler = BackgroundScheduler()
scheduler.add_job(refresh_data, "interval", weeks=1, id="auto_refresh")
scheduler.start()

if __name__ == "__main__":
    if not DATA_FILE.exists() or load_cache().get("ministers") == []:
        refresh_data()
    app.run(debug=True, port=8080, use_reloader=False)
