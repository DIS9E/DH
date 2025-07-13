#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
udf.name.py – v3.5-style (fix-4)
• WP↔seen 동기화 • no-media • dup-safe
• 헤드라이트 톤 + Yoast 3필드
• 헤더 강제 · 이미지 정확 · 태그 정규화 · 타임아웃 처리
"""

import os, sys, re, json, time, logging
from urllib.parse import urljoin, urlparse, urlunparse
import requests, openai
from bs4 import BeautifulSoup

# ─────── 환경
WP_URL   = os.getenv("WP_URL", "https://belatri.info").rstrip("/")
USER     = os.getenv("WP_USERNAME")
APP_PW   = os.getenv("WP_APP_PASSWORD")
OPEN_KEY = os.getenv("OPENAI_API_KEY")
openai.api_key = OPEN_KEY
if not all([USER, APP_PW, OPEN_KEY]):
    sys.exit("❌  WP_USERNAME / WP_APP_PASSWORD / OPENAI_API_KEY 누락")

POSTS = f"{WP_URL}/wp-json/wp/v2/posts"
TAGS  = f"{WP_URL}/wp-json/wp/v2/tags"

UDF_BASE   = "https://udf.name/news/"
HEADERS    = {"User-Agent": "UDFCrawler/3.5-fix4"}
SEEN_FILE  = "seen_urls.json"
TARGET_CAT_ID = 20            # ‘벨라루스 뉴스’ 고정 카테고리

norm = lambda u: urlunparse(urlparse(u)._replace(query="", params="", fragment=""))

# ─────── seen 파일
def load_seen():
    if os.path.exists(SEEN_FILE):
        with open(SEEN_FILE, encoding="utf-8") as f:
            return set(json.load(f))
    return set()

def save_seen(s):
    with open(SEEN_FILE, "w", encoding="utf-8") as f:
        json.dump(list(s), f, ensure_ascii=False, indent=2)

# ─────── WP 존재 확인
def wp_exists(url_norm):
    r = requests.get(POSTS, params={"search": url_norm, "per_page": 1},
                     auth=(USER, APP_PW), timeout=10)
    return r.ok and bool(r.json())

def sync_seen(seen):
    synced = {u for u in seen if wp_exists(norm(u))}
    if len(synced) != len(seen):
        save_seen(synced)
    return synced

# ─────── 링크 수집
def fetch_links():
    soup = BeautifulSoup(requests.get(UDF_BASE, headers=HEADERS, timeout=15).text,
                         "html.parser")
    return list({norm(urljoin(UDF_BASE, a["href"]))
                 for a in soup.select("div.article1 div.article_title_news a[href]")})

# ─────── 기사 파싱
def parse(url):
    try:
        r = requests.get(url, headers=HEADERS, timeout=25)
    except requests.exceptions.ReadTimeout:
        print("  ⚠️  타임아웃:", url)
        return None
    if not r.ok:
        return None
    s = BeautifulSoup(r.text, "html.parser")
    title = s.find("h1", class_="newtitle")
    body  = s.find("div", id="zooming")
    if not (title and body):
        return None
    # 본문 영역 안 첫 번째 이미지
    img_tag = body.select_one("img[src]")
    img_url = urljoin(url, img_tag["src"]) if img_tag else None
    return {"title": title.get_text(strip=True),
            "html": str(body),
            "image": img_url,
            "url": url}

# ─────── GPT 재작성
STYLE_GUIDE = """
• 톤: 친근한 존댓말, 질문·감탄 사용
• 구조
  📰 제목
  ✍️ 편집자 주 — 핵심 2문장
  🗞️ 본문
    ‣ 소제목1: …
    ‣ 소제목2: …
  🔦 헤드라이트's 코멘트 (300자 내외)
  🏷️ 태그: 명사 3~6개
• 마크다운 #, ##, ### 헤더 **반드시 포함**
• 사실 누락·요약 금지, 길이는 원문 대비 90±10 %
"""

def openai_chat(prompt):
    resp = openai.ChatCompletion.create(
        model="gpt-4o",
        messages=[{"role":"user","content":prompt}],
        temperature=0.2,
        max_tokens=2048
    )
    return resp.choices[0].message.content

def postprocess(text):
    fixed = []
    for line in text.splitlines():
        if line.startswith("###"):
            fixed.append("‣ " + line.lstrip("# ").strip())
        elif line.startswith("##"):
            fixed.append("✍️ " + line.lstrip("# ").strip())
        elif line.startswith("#"):
            fixed.append("📰 " + line.lstrip("# ").strip())
        else:
            fixed.append(line)
    return "\n".join(fixed)

def rewrite(a, retry=2):
    prompt = f"{STYLE_GUIDE}\n\n◆ 원문\n{a['html']}"
    for _ in range(retry+1):
        out = openai_chat(prompt)
        if any(h in out for h in ("###", "##", "#")):
            return postprocess(out)
    raise RuntimeError("헤더 없는 출력")

# ─────── 태그
STOP = {"벨라루스", "뉴스", "기사"}
def tag_names(txt):
    m = re.search(r"🏷️\s*태그[^:：]*[:：]\s*(.+)", txt)
    if not m:
        return []
    out = []
    for t in re.split(r"[,\s]+", m.group(1)):
        t = re.sub(r"[^가-힣a-zA-Z0-9]", "", t)  # 불용문자 제거
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

# ─────── 발행
def publish(a, txt, tag_ids):
    hidden = f'<a href="{a["url"]}" style="display:none">src</a>\n'
    img_tag = f'<p><img src="{a["image"]}" alt=""></p>\n' if a["image"] else ""
    body = hidden + img_tag + txt

    title_line = next((l for l in txt.splitlines() if l.startswith("📰")), a["title"])
    title = title_line.lstrip("📰").strip()
    focus = (tag_ids and tag_ids[0]) or ""
    meta  = re.search(r"✍️\s*편집자 주[^\n]*\n(.+)", txt)
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

# ─────── 메인
def main():
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s │ %(levelname)s │ %(message)s",
                        datefmt="%Y-%m-%d %H:%M:%S")
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
