#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
udf.name.py – v3.6
• GPT-4o 헤드라이트 톤 (80~110 % 길이)
• HTML <h1>/<h2>/<h3> 헤더 변환 & <strong> 강조
• Yoast SEO 3필드 자동
• 카테고리 20 고정, WP↔seen 동기화, dup-safe
• 미디어 업로드 없이 본문 img 삽입
"""

import os, sys, re, json, time, logging
from urllib.parse import urljoin, urlparse, urlunparse
import requests
from bs4 import BeautifulSoup

# ─────── 환경변수 & WP 엔드포인트
WP_URL = os.getenv("WP_URL", "https://belatri.info").rstrip("/")
USER   = os.getenv("WP_USERNAME")
APP_PW = os.getenv("WP_APP_PASSWORD")
OPENAI = os.getenv("OPENAI_API_KEY")
if not all([USER, APP_PW, OPENAI]):
    sys.exit("❌  WP_USERNAME / WP_APP_PASSWORD / OPENAI_API_KEY 누락")

POSTS = f"{WP_URL}/wp-json/wp/v2/posts"
TAGS  = f"{WP_URL}/wp-json/wp/v2/tags"

UDF_BASE   = "https://udf.name/news/"
HEADERS    = {"User-Agent": "UDFCrawler/3.6"}
SEEN_FILE  = "seen_urls.json"
CAT_ID     = 20            # ‘벨라루스 뉴스’

norm = lambda u: urlunparse(urlparse(u)._replace(query="", params="", fragment=""))

# ─────── seen 관리
def load_seen():
    if os.path.exists(SEEN_FILE):
        with open(SEEN_FILE, encoding="utf-8") as f:
            return set(json.load(f))
    return set()

def save_seen(s):
    with open(SEEN_FILE, "w", encoding="utf-8") as f:
        json.dump(list(s), f, ensure_ascii=False, indent=2)

def wp_exists(url_):
    r = requests.get(POSTS, params={"search": url_, "per_page": 1},
                     auth=(USER, APP_PW), timeout=10)
    return r.ok and bool(r.json())

def sync_seen(seen):
    synced = {u for u in seen if wp_exists(norm(u))}
    if len(synced) != len(seen):
        save_seen(synced)
    return synced

# ─────── 링크 수집
def fetch_links():
    soup = BeautifulSoup(requests.get(UDF_BASE, headers=HEADERS, timeout=10).text, "html.parser")
    return list({norm(urljoin(UDF_BASE, a["href"]))
                 for a in soup.select("div.article1 div.article_title_news a[href]")})

# ─────── 기사 파싱
def parse(url):
    r = requests.get(url, headers=HEADERS, timeout=10)
    if not r.ok: return None
    s = BeautifulSoup(r.text, "html.parser")
    h1 = s.find("h1", class_="newtitle")
    body = s.find("div", id="zooming")
    if not (h1 and body): return None
    img = s.find("img", class_="lazy") or s.find("img")
    img_url = urljoin(url, (img.get("data-src") or img.get("src"))) if img else None
    return {"title": h1.get_text(strip=True),
            "html": str(body),
            "image": img_url,
            "url": url}

# ─────── 스타일 & GPT
STYLE_GUIDE = """
**헤드라이트 블로그 리라이트 규칙 (v3.6)**  
1. 톤: 친근한 존댓말, 질문·감탄·이모지 적절히 삽입  
2. 길이: 원문 대비 최소 80 %, 최대 110 % (요약·생략 금지)  
3. 구조  
   <h1>📰 제목</h1>  
   <h2>✍️ 편집자 주</h2> – 2문장 핵심 요약  
   <h2>🗞️ 본문</h2>  
   <h3>‣ 소제목 1</h3> 본문 유지·재구성  
   <h3>‣ 소제목 2</h3> …  
   <h2>🔦 헤드라이트’s 코멘트</h2> 300자 내외 통찰  
   <p>🏷️ 태그: …(명사 3~6개)</p>  
4. 마크다운 # 기호 사용 금지 (반드시 HTML <h1>/<h2>/<h3>)  
5. 굵게 강조할 키워드에 <strong>…</strong> 사용  
6. 원문 링크·날짜·불필요한 러시아어 그대로 남기지 말 것  
7. 제목은 ‘독자가 클릭하고 싶을’ 한국어 새 제목 (직역 X)  
"""

GPT_URL = "https://api.openai.com/v1/chat/completions"
GPT_HDR = {"Authorization": f"Bearer {OPENAI}", "Content-Type": "application/json"}

def rewrite(article):
    prompt = f"{STYLE_GUIDE}\n\n◆ 원문 HTML\n{article['html']}"
    def ask():
        r = requests.post(GPT_URL,
            headers=GPT_HDR,
            json={"model":"gpt-4o",
                  "messages":[{"role":"user","content":prompt}],
                  "temperature":0.4,
                  "top_p":0.95}, timeout=120)
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"].strip()

    text = ask()
    if len(text) < 2000:                 # 너무 짧으면 1회 재시도
        text = ask()

    return text

# ─────── 태그
STOP = {"벨라루스", "뉴스", "기사"}
def tag_names(txt):
    m = re.search(r"🏷️\s*태그[^:：]*[:：]\s*(.+)", txt)
    if not m: return []
    out = []
    for t in re.split(r"[,\s]+", m.group(1)):
        t = t.strip("–-#•")
        if 1 < len(t) <= 20 and t not in STOP and t not in out:
            out.append(t)
        if len(out) == 6: break
    return out

def tag_id(name):
    r = requests.get(TAGS, params={"search": name, "per_page":1},
                     auth=(USER, APP_PW), timeout=10)
    if r.ok and r.json():
        return r.json()[0]["id"]
    c = requests.post(TAGS, json={"name": name},
                      auth=(USER, APP_PW), timeout=10)
    return c.json().get("id") if c.status_code == 201 else None

# ─────── 발행
def publish(a, txt, tag_ids):
    # 본문: 숨은 src 링크 + 외부 이미지 + GPT 결과
    hidden = f'<a href="{a["url"]}" style="display:none">src</a>\n'
    img_tag = f'<p><img src="{a["image"]}" alt=""></p>\n' if a["image"] else ""
    content = hidden + img_tag + txt

    # 제목 (첫 <h1>)
    m = re.search(r"<h1[^>]*>(.+?)</h1>", txt)
    title = m.group(1).strip() if m else a["title"]

    # Yoast
    focus_kw = (tag_ids and tag_ids[0]) or ""
    meta = ""
    m2 = re.search(r"✍️\s*편집자 주.*?\n(.+)", txt)
    if m2: meta = re.sub(r"<[^>]+>", "", m2.group(1)).strip()[:140]

    payload = {
        "title": title,
        "content": content,
        "status": "publish",
        "categories": [CAT_ID],
        "tags": tag_ids,
        "meta": {
            "yoast_wpseo_title": title,
            "yoast_wpseo_focuskw": focus_kw,
            "yoast_wpseo_metadesc": meta
        }
    }
    r = requests.post(POSTS, json=payload, auth=(USER, APP_PW), timeout=30)
    print("  ↳ 게시", r.status_code, r.json().get("id"))
    r.raise_for_status()

# ─────── 메인
def main():
    logging.basicConfig(level=logging.WARNING)
    seen = sync_seen(load_seen())
    links = fetch_links()

    todo = [u for u in links if norm(u) not in seen and not wp_exists(norm(u))]
    print(f"📰 새 기사 {len(todo)} / 총 {len(links)}")

    for url in todo:
        print("===", url)
        art = parse(url)
        if not art: continue
        try:
            txt = rewrite(art)
        except Exception as e:
            print("  GPT 오류:", e); continue

        tag_ids = [tid for n in tag_names(txt) if (tid := tag_id(n))]
        try:
            publish(art, txt, tag_ids)
            seen.add(norm(url)); save_seen(seen)
        except Exception as e:
            print("  업로드 실패:", e)
        time.sleep(2)

if __name__ == "__main__":
    main()
