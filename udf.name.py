#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
udf.name.py – v3.6.1-tag
• 3.6(헤드라이트 톤·이모지·H1/H2/H3 유지)에
  → GPT가 추천 태그 한 줄을 함께 돌려주고
  → 태그 자동 생성·등록·연결 까지만 추가
"""

import os, sys, re, json, time, logging
from urllib.parse import urljoin, urlparse, urlunparse
import requests, openai   # ← requirements.txt 에 openai, requests 두 줄만 있으면 됩니다
from bs4 import BeautifulSoup

# ─────── 환경 변수
WP_URL   = os.getenv("WP_URL", "https://belatri.info").rstrip("/")
USER     = os.getenv("WP_USERNAME")
APP_PW   = os.getenv("WP_APP_PASSWORD")
OPEN_KEY = os.getenv("OPENAI_API_KEY")
if not all([USER, APP_PW, OPEN_KEY]):
    sys.exit("❌  WP_USERNAME / WP_APP_PASSWORD / OPENAI_API_KEY 누락")

POSTS = f"{WP_URL}/wp-json/wp/v2/posts"
TAGS  = f"{WP_URL}/wp-json/wp/v2/tags"
HEADERS = {"User-Agent": "UDFCrawler/3.6.1-tag"}
UDF_BASE = "https://udf.name/news/"
SEEN_FILE = "seen_urls.json"
TARGET_CAT_ID = 20                 # ‘벨라루스 뉴스’ 고정

norm = lambda u: urlunparse(urlparse(u)._replace(query="", params="", fragment=""))

# ────────── seen  관리 ──────────
def load_seen() -> set[str]:
    if os.path.exists(SEEN_FILE):
        with open(SEEN_FILE, encoding="utf-8") as f:
            return set(json.load(f))
    return set()

def save_seen(s: set[str]):
    with open(SEEN_FILE, "w", encoding="utf-8") as f:
        json.dump(list(s), f, ensure_ascii=False, indent=2)

def wp_exists(u_norm: str) -> bool:
    r = requests.get(POSTS, params={"search": u_norm, "per_page": 1},
                     auth=(USER, APP_PW), timeout=10)
    return r.ok and bool(r.json())

def sync_seen(seen: set[str]) -> set[str]:
    synced = {u for u in seen if wp_exists(norm(u))}
    if len(synced) != len(seen):
        save_seen(synced)
    return synced

# ────────── 링크 · 파싱 ──────────
def fetch_links():
    soup = BeautifulSoup(requests.get(UDF_BASE, headers=HEADERS, timeout=10).text, "html.parser")
    return list({norm(urljoin(UDF_BASE, a["href"]))
                 for a in soup.select("div.article1 div.article_title_news a[href]")})

def parse(url):
    r = requests.get(url, headers=HEADERS, timeout=10)
    if not r.ok:
        return None
    s = BeautifulSoup(r.text, "html.parser")
    title = s.find("h1", class_="newtitle")
    body  = s.find("div", id="zooming")
    if not (title and body):
        return None
    img = s.find("img", class_="lazy") or s.find("img")
    img_url = urljoin(url, img.get("data-src") or img.get("src")) if img else None
    return {"title": title.get_text(strip=True),
            "html": str(body),
            "image": img_url,
            "url": url}

# ────────── GPT 프롬프트 ──────────
STYLE_GUIDE = """
• 존댓말 + 헤드라이트 톤, 질문/감탄 포함
• 구조:
  #📰 제목
  ##✍️ 편집자 주 (2문장)
  ###🗞️ 본문
    ‣ 소제목1
    ‣ 소제목2
  🔦 헤드라이트's 코멘트 (200~300자)
  🏷️ 태그: 핵심명사 3~6개 (콤마 구분, 1~3단어짜리, 불용어 제외)
• 사실 요약·누락 금지, 분량 90±10%
• 마크다운 #,##,### 반드시 포함(H1~H3)
• 한자·러시아어·영어 고유명사 외 외국어 금지
"""

def rewrite(a):
    openai.api_key = OPEN_KEY
    prompt = f"""{STYLE_GUIDE}

◆ 원문:
{a['html']}
"""
    rsp = openai.ChatCompletion.create(
        model="gpt-4o",
        messages=[{"role":"user","content":prompt}],
        temperature=0.4,
        max_tokens=1800,
    )
    return rsp.choices[0].message.content.strip()

# ────────── 태그 처리(3.5식) ──────────
STOP = {"벨라루스", "뉴스", "기사"}

def tag_names(txt):
    m = re.search(r"🏷️\s*태그[^:：]*[:：]\s*(.+)", txt)
    if not m:
        return []
    out = []
    for t in re.split(r"[,\s]+", m.group(1)):
        t = t.strip("–-#")
        if 1 < len(t) <= 20 and t not in STOP and t not in out:
            out.append(t)
        if len(out) == 6:
            break
    return out

def tag_id(name):
    q = requests.get(TAGS, params={"search": name, "per_page": 1},
                     auth=(USER, APP_PW), timeout=10)
    if q.ok and q.json():
        return q.json()[0]["id"]
    c = requests.post(TAGS, json={"name": name},
                      auth=(USER, APP_PW), timeout=10)
    return c.json().get("id") if c.status_code == 201 else None

# ────────── 발행 ──────────
def publish(a, txt, tag_ids):
    hidden = f'<a href="{a["url"]}" style="display:none">src</a>\n'
    img_tag = f'<p><img src="{a["image"]}" alt=""></p>\n' if a["image"] else ""
    body = hidden + img_tag + txt

    title_line = next((l for l in txt.splitlines() if l.lstrip().startswith("#📰")), a["title"])
    title = title_line.replace("#", "").replace("📰", "").strip()
    focus = (tag_ids and tag_ids[0]) or ""
    meta  = re.search(r"##✍️[^\n]*\n(.+)", txt)
    meta  = (meta.group(1).strip()[:140]) if meta else ""

    payload = {
        "title": title,
        "content": body,
        "status": "publish",
        "categories": [TARGET_CAT_ID],
        "tags": tag_ids,
        "meta": {
            "yoast_wpseo_title": title,
            "yoast_wpseo_focuskw": focus,
            "yoast_wpseo_metadesc": meta
        }
    }
    r = requests.post(POSTS, json=payload, auth=(USER, APP_PW), timeout=30)
    logging.info("  ↳ 게시 %s %s", r.status_code, r.json().get("id"))
    r.raise_for_status()

# ────────── 메인 루프 ──────────
def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s │ %(levelname)s │ %(message)s")
    seen = sync_seen(load_seen())
    links = fetch_links()
    todo = [u for u in links if norm(u) not in seen and not wp_exists(norm(u))]
    logging.info("📰 새 기사 %d / 총 %d", len(todo), len(links))

    for url in todo:
        logging.info("▶ %s", url)
        art = parse(url)
        if not art:
            continue
        try:
            txt = rewrite(art)
        except Exception as e:
            logging.warning("  GPT 오류: %s", e)
            continue

        tag_ids = [tid for n in tag_names(txt) if (tid := tag_id(n))]
        try:
            publish(art, txt, tag_ids)
            seen.add(norm(url)); save_seen(seen)
        except Exception as e:
            logging.error("  업로드 실패: %s", e)
        time.sleep(2)

if __name__ == "__main__":
    main()
