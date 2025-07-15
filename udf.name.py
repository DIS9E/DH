#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
udf.name.py – v4.0.1-full  (뉴닉 톤 + AdSense 가이드 + RSS/환율 + 안정 패치)
"""

import os, sys, re, json, time, logging, html, random
from urllib.parse import urljoin, urlparse, urlunparse

import requests, feedparser          # ← requirements.txt 에 feedparser 추가
from bs4 import BeautifulSoup

# ────────── 환경 변수 ──────────
WP_URL   = os.getenv("WP_URL" , "https://belatri.info").rstrip("/")
USER     = os.getenv("WP_USERNAME")
APP_PW   = os.getenv("WP_APP_PASSWORD")
OPEN_KEY = os.getenv("OPENAI_API_KEY")
if not all([USER, APP_PW, OPEN_KEY]):
    sys.exit("❌  WP_USERNAME / WP_APP_PASSWORD / OPENAI_API_KEY 누락")

POSTS_API = f"{WP_URL}/wp-json/wp/v2/posts"
TAGS_API  = f"{WP_URL}/wp-json/wp/v2/tags"

UDF_BASE   = "https://udf.name/news/"
HEADERS    = {"User-Agent": "UDFCrawler/4.0.1-full"}
SEEN_FILE  = "seen_urls.json"
TARGET_CAT_ID = 20                      # ‘벨라루스 뉴스’ 카테고리(ID)

norm = lambda u: urlunparse(urlparse(u)._replace(query="", params="", fragment=""))

# ────────── seen 파일 ──────────
def load_seen() -> set[str]:
    return set(json.load(open(SEEN_FILE))) if os.path.exists(SEEN_FILE) else set()

def save_seen(s: set[str]): json.dump(list(s), open(SEEN_FILE, "w"), ensure_ascii=False, indent=2)

# ────────── WP 존재 여부 확인 ──────────
def wp_exists(url_norm: str) -> bool:
    r = requests.get(POSTS_API, params={"search": url_norm, "per_page": 1},
                     auth=(USER, APP_PW), timeout=10)
    return r.ok and bool(r.json())

def sync_seen(seen: set[str]) -> set[str]:
    synced = {u for u in seen if wp_exists(norm(u))}
    if synced != seen: save_seen(synced)
    return synced

# ────────── 링크 크롤링 ──────────
def fetch_links() -> list[str]:
    soup = BeautifulSoup(requests.get(UDF_BASE, headers=HEADERS, timeout=10).text,
                         "html.parser")
    return list({norm(urljoin(UDF_BASE, a["href"]))
                 for a in soup.select("div.article1 div.article_title_news a[href]")})

# ────────── 기사 파싱 ──────────
def parse(url: str):
    r = requests.get(url, headers=HEADERS, timeout=10)
    if not r.ok: return None
    s = BeautifulSoup(r.text, "html.parser")
    h1 = s.find("h1", class_="newtitle")
    body = s.find("div", id="zooming")
    if not (h1 and body): return None
    img = s.find("img", class_="lazy") or s.find("img")
    return {
        "title": h1.get_text(strip=True),
        "html": str(body),
        "image": urljoin(url, img.get("data-src") or img.get("src")) if img else None,
        "url": url
    }

# ────────── 외부 데이터 (환율·유가·RSS 헤드라인) ──────────
def nbrb_rate() -> str:
    try:
        j = requests.get("https://api.nbrb.by/exrates/rates/431", timeout=8).json()
        return f"NBRB USD/BYN {j['Cur_OfficialRate']:.4g} ({j['Date'][:10]})"
    except Exception:
        return "NBRB 환율 데이터 N/A"

def oil_price() -> str:
    try:
        # EIA DEMO_KEY 는 하루 2천 call 한계
        j = requests.get(
            "https://api.eia.gov/series/?api_key=DEMO_KEY&series_id=PET.RWTC.D",
            timeout=8).json()
        price = j["series"][0]["data"][0][1]
        return f"WTI {price} $/bbl"
    except Exception:
        return "WTI 가격 N/A"

RSS_SOURCES = {
    "biz": "https://feeds.bbci.co.uk/news/business/rss.xml",
    "world": "https://feeds.bbci.co.uk/news/world/rss.xml",
    "eu": "https://feeds.bbci.co.uk/news/world/europe/rss.xml",
}
def rss_headlines(max_items=3) -> list[str]:
    out = []
    for url in RSS_SOURCES.values():
        try:
            feed = feedparser.parse(url)
            for e in feed.entries[: max_items]:
                out.append(f"• {e.title}")
        except Exception: pass
    random.shuffle(out)
    return out[:max_items]

def build_brief() -> str:
    s = []
    s.append(f"• {nbrb_rate()}")
    s.append(f"• {oil_price()}")
    for h in rss_headlines():
        s.append(h)
    return "<br>".join(s)

# ────────── 스타일 가이드 ──────────
STYLE_GUIDE = f"""
• 아래 템플릿을 ‘그대로’ 유지하세요.
  <h1>📰 (이모지) 45자↓ 한국어 제목</h1>
  <h2>✍️ 편집자 주 — 핵심 2문장</h2>
  <h3>📊 최신 데이터</h3>
    {build_brief()}
    이어서 (총 550자 이상) …
  <h3>💬 전문가 전망</h3>
    (550자 이상, 시나리오·인용 포함) …
  <h3>❓ Q&A</h3>
    <ul><li><strong>Q1:</strong> …<br><strong>A:</strong> …</li> …</ul>
  <p>🏷️ 태그: 명사 3–6개</p>
  <p>출처: UDF.name 원문<br>by. 에디터 LEE🌳</p>

• 원문 문장 ✖️삭제 ✖️요약 (가독성 위해 문단·어순 재배치 OK)
• 코드블록·백틱·“소제목 1” 같은 표시 금지.
• 전체 길이 최소 1 400자. 40 %는 새로 생성된 텍스트.
"""

# ────────── GPT 리라이팅 ──────────
def rewrite(article):
    prompt = f"{STYLE_GUIDE}\n\n◆ 원문:\n{article['html']}"
    headers = {"Authorization": f"Bearer {OPEN_KEY}", "Content-Type": "application/json"}
    data = {"model": "gpt-4o",
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.6,
            "max_tokens": 2600}
    r = requests.post("https://api.openai.com/v1/chat/completions",
                      headers=headers, json=data, timeout=150)
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"].strip()

# ────────── 태그 추출 & WP 태그 생성 ──────────
STOP = {"벨라루스", "뉴스", "기사"}
def tag_names(txt: str) -> list[str]:
    m = re.search(r"🏷️\s*태그[^:：]*[:：]\s*(.+)", txt)
    if not m: return []
    out = []
    for t in re.split(r"[,\s]+", m.group(1)):
        t = t.strip("–-#•")
        if 1 < len(t) <= 20 and t not in STOP and t not in out:
            out.append(t)
        if len(out) == 6: break
    return out

def tag_id(name: str):
    q = requests.get(TAGS_API, params={"search": name, "per_page": 1},
                     auth=(USER, APP_PW), timeout=10)
    if q.ok and q.json(): return q.json()[0]["id"]
    c = requests.post(TAGS_API, json={"name": name},
                      auth=(USER, APP_PW), timeout=10)
    return c.json()["id"] if c.status_code == 201 else None

# ────────── 내부 관련 기사 링크 ──────────
def related_links(tag_ids, exclude_id=0, limit=3):
    if not tag_ids: return ""
    res = requests.get(
        POSTS_API,
        params={"tags": tag_ids[0], "per_page": limit,
                "exclude": exclude_id, "status": "publish"},
        auth=(USER, APP_PW), timeout=10).json()
    if not isinstance(res, list) or not res: return ""
    lis = [f'<li><a href="{p["link"]}">{html.escape(p["title"]["rendered"])}</a></li>'
           for p in res]
    return "<h3>📚 관련 기사 더 보기</h3><ul>" + "".join(lis) + "</ul>"

# ────────── 게시 ──────────
def publish(article, txt, tag_ids):
    hidden  = f'<a href="{article["url"]}" style="display:none">src</a>\n'
    cap     = '<p><em>Photo: UDF.name</em></p>\n' if article["image"] else ""
    img_tag = f'<p><img src="{article["image"]}" alt=""></p>\n' if article["image"] else ""

    soup = BeautifulSoup(txt, "html.parser")
    h1 = soup.find("h1")
    title = h1.get_text(strip=True) if h1 else article["title"]
    if h1: h1.decompose()

    if not soup.find(string=lambda t: isinstance(t, str) and "출처:" in t):
        soup.append(BeautifulSoup(
            '<p>출처: UDF.name 원문<br>by. 에디터 LEE🌳</p>', "html.parser"))

    body = hidden + cap + img_tag + str(soup) + related_links(tag_ids)

    payload = {"title": title, "content": body, "status": "publish",
               "categories": [TARGET_CAT_ID], "tags": tag_ids}
    r = requests.post(POSTS_API, json=payload, auth=(USER, APP_PW), timeout=30)
    logging.info("  ↳ 게시 %s %s", r.status_code, r.json().get("id"))
    r.raise_for_status()

# ────────── main ──────────
def main():
    logging.basicConfig(level=logging.INFO,
        format="%(asctime)s │ %(levelname)s │ %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S")
    logging.info("🚀 버전 4.0.1-full 실행")

    seen = sync_seen(load_seen())
    links = fetch_links()
    todo = [u for u in links if norm(u) not in seen and not wp_exists(norm(u))]
    logging.info("📰 새 기사 %d / 총 %d", len(todo), len(links))

    for url in todo:
        logging.info("▶ %s", url)
        art = parse(url); time.sleep(1)
        if not art: continue

        try:
            txt = rewrite(art)
        except Exception as e:
            logging.warning("GPT 오류: %s", e); continue

        tag_ids = [tid for n in tag_names(txt) if (tid := tag_id(n))]
        try:
            publish(art, txt, tag_ids)
            seen.add(norm(url)); save_seen(seen)
        except Exception as e:
            logging.warning("업로드 실패: %s", e)

        time.sleep(1.5)

if __name__ == "__main__":
    main()
