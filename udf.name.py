#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
udf.name.py  v3.6  (2025-07-13)
• 헤드라이트 톤  • Yoast Snippet Title/Focus/Meta  • slug 한글→EN  • dup-safe  • auto-sync
"""

import os, re, json, time, logging, unicodedata
from urllib.parse import urljoin, urlparse, urlunparse, quote_plus
import requests
from bs4 import BeautifulSoup

# ─────── 환경 ----------------------------------------------------------
WP_URL  = os.getenv("WP_URL", "https://belatri.info").rstrip("/")
USER    = os.getenv("WP_USERNAME")
APP_PW  = os.getenv("WP_APP_PASSWORD")
OPENKEY = os.getenv("OPENAI_API_KEY")
POSTS = f"{WP_URL}/wp-json/wp/v2/posts"
TAGS  = f"{WP_URL}/wp-json/wp/v2/tags"
CAT_ID = 20        # ‘벨라루스 뉴스’
HEADERS = {"User-Agent": "UDFCrawler/3.6"}
UDF_BASE = "https://udf.name/news/"
SEEN_FILE = "seen_urls.json"
norm = lambda u: urlunparse(urlparse(u)._replace(query="", params="", fragment=""))

# ─────── seen 파일 ------------------------------------------------------
def load_seen():  # set[str]
    if os.path.exists(SEEN_FILE):
        with open(SEEN_FILE, encoding="utf-8") as f:
            return set(json.load(f))
    return set()

def save_seen(s):
    with open(SEEN_FILE, "w", encoding="utf-8") as f:
        json.dump(list(s), f, ensure_ascii=False, indent=2)

# ─────── WP 존재 여부 & 동기화 -----------------------------------------
def wp_exist(url_norm):
    r = requests.get(POSTS, params={"search": url_norm, "per_page": 1},
                     auth=(USER, APP_PW), timeout=10)
    return r.ok and bool(r.json())

def sync_seen(seen):
    kept = {u for u in seen if wp_exist(u)}
    if kept != seen:
        save_seen(kept)
    return kept

# ─────── 링크 수집 -------------------------------------------------------
def fetch_links():
    soup = BeautifulSoup(requests.get(UDF_BASE, headers=HEADERS, timeout=10).text, "html.parser")
    return list({norm(a["href"]) for a in soup.select("a[href^='https://udf.name/news/']") if a["href"].endswith(".html")})

# ─────── 기사 파싱 -------------------------------------------------------
def parse(url):
    html = requests.get(url, headers=HEADERS, timeout=10).text
    s = BeautifulSoup(html, "html.parser")
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

# ─────── Head-light 스타일 가이드 ---------------------------------------
STYLE_GUIDE = """
[헤드라이트 스타일 작성 규칙]

1. 마크다운 #, ##, ### 헤더를 절대 사용하지 말 것.
2. 구조와 문구는 아래 예시와 완전히 동일한 틀 유지(단, 내용은 기사에 맞게).
 ─────────────────────────────────────
제목(첫 줄)

헤드라이트
YYYY.MM.DD
•
읽음 추정치

[한 줄 편집자 주: 기사 핵심 요약, 2문장 이하]

이 주의 헤드라이트: XX 📰

화제성: ✦✦ (1~3개)   난이도: ✦✦ (1~3개)

이 글을 읽고 뉴니커가 답할 수 있는 질문 💬
• Q1
• Q2
• Q3

헤드라인 주요 뉴스 🗞️
[매체명] 기사 제목
[매체명] 기사 제목

본문(원문 90% 길이로 재작성, 번호·이모지 자유)

헤드라이트’s 코멘트 🔦✨: “한 문장 인사이트”
 ─────────────────────────────────────
3. 기사 정보 누락·요약 과도 금지(원문 90±10% 길이).
4. 친근한 존댓말, 질문·감탄 사용. 이모지는 필요할 때 자연스럽게.
"""

def rewrite(art):
    prompt = f"""{STYLE_GUIDE}

[원문 HTML]
{art['html']}
"""
    r = requests.post("https://api.openai.com/v1/chat/completions",
        headers={"Authorization": f"Bearer {OPENKEY}",
                 "Content-Type":"application/json"},
        json={"model":"gpt-4o","messages":[{"role":"user","content":prompt}],
              "temperature":0.4}, timeout=90)
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"]

# ─────── 태그 ------------------------------------------------------------
STOP = {"벨라루스","뉴스","기사"}
def pick_tags(txt):
    m = re.search(r"헤드라이트’[^\n]*?:\s*(.+)", txt)
    pool = re.findall(r"[가-힣]{2,20}", txt) if not m else re.split(r"[,\s]+", m.group(1))
    out = []
    for w in pool:
        if w not in STOP and w not in out and 1<len(w)<=20:
            out.append(w)
        if len(out)==6:
            break
    return out[:3]   # 3개만

def tag_id(name):
    s = requests.get(TAGS, params={"search":name,"per_page":1},
                     auth=(USER,APP_PW), timeout=10)
    if s.ok and s.json():
        return s.json()[0]["id"]
    c = requests.post(TAGS, json={"name":name},
                      auth=(USER,APP_PW), timeout=10)
    return c.json().get("id") if c.status_code==201 else None

# ─────── slugify(한글→로마자 간이) --------------------------------------
def slugify(txt):
    txt = unicodedata.normalize('NFKD', txt)
    txt = ''.join(c for c in txt if not unicodedata.combining(c))
    txt = re.sub(r"[^\w\s-]", "", txt).strip().lower()
    return re.sub(r"[\s_-]+", "-", txt)[:80] or quote_plus(txt)

# ─────── 발행 ------------------------------------------------------------
def publish(art, body, tag_ids):
    title = art["title"].strip()
    slug  = slugify(title)
    # 편집자 주 줄(헤드라이트 다음 줄) meta description
    m = re.search(r"\n\n(.+?)\n\n이 주의 헤드라이트", body, flags=re.S)
    meta = (m.group(1).strip() if m else "")[:155]

    meta_fields = {
        "yoast_wpseo_title": f"{title} | 벨라뉴스",
        "yoast_wpseo_focuskw": tag_ids and tag_ids[0] or "",
        "yoast_wpseo_metadesc": meta
    }

    hidden_src = f'<a href="{art["url"]}" style="display:none">src</a>\n'
    img_tag = f'<p><img src="{art["image"]}" alt=""></p>\n' if art["image"] else ""
    content = hidden_src + img_tag + body

    payload = {
        "title": title,
        "slug": slug,
        "content": content,
        "status": "publish",
        "categories": [CAT_ID],
        "tags": tag_ids,
        "meta": meta_fields
    }
    r = requests.post(POSTS, json=payload, auth=(USER,APP_PW), timeout=30)
    print("  ↳ 게시", r.status_code, r.json().get("id"))
    r.raise_for_status()

# ─────── 메인 ------------------------------------------------------------
def main():
    logging.basicConfig(level=logging.WARNING)
    seen = sync_seen(load_seen())
    links = fetch_links()
    todo = [u for u in links if norm(u) not in seen and not wp_exist(norm(u))]
    print(f"📰 새 기사 {len(todo)} / 총 {len(links)}")

    for url in todo:
        print("===", url)
        art = parse(url)
        if not art: continue
        try:
            body = rewrite(art)
        except Exception as e:
            print("  GPT 오류:", e); continue

        tag_ids = [tid for t in pick_tags(body) if (tid:=tag_id(t))]
        try:
            publish(art, body, tag_ids)
            seen.add(norm(url)); save_seen(seen)
        except Exception as e:
            print("  업로드 실패:", e)
        time.sleep(1.5)

if __name__ == "__main__":
    main()
