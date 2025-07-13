#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
udf.name.py – v3.5-style
• WP↔seen 자동 동기화 • no-media • dup-safe • Yoast 3필드 • 헤드라이트 톤
"""

import os, sys, re, json, time, logging
from urllib.parse import urljoin, urlparse, urlunparse
import requests
from bs4 import BeautifulSoup

# ─────── 환경
WP_URL   = os.getenv("WP_URL", "https://belatri.info").rstrip("/")
USER     = os.getenv("WP_USERNAME")
APP_PW   = os.getenv("WP_APP_PASSWORD")
OPEN_KEY = os.getenv("OPENAI_API_KEY")
if not all([USER, APP_PW, OPEN_KEY]):
    sys.exit("❌  WP_USERNAME / WP_APP_PASSWORD / OPENAI_API_KEY 누락")

POSTS = f"{WP_URL}/wp-json/wp/v2/posts"
TAGS  = f"{WP_URL}/wp-json/wp/v2/tags"

UDF_BASE   = "https://udf.name/news/"
HEADERS    = {"User-Agent": "UDFCrawler/3.5-style"}
SEEN_FILE  = "seen_urls.json"
TARGET_CAT_ID = 20            # ‘벨라루스 뉴스’ 고정 카테고리

norm = lambda u: urlunparse(urlparse(u)._replace(query="", params="", fragment=""))

# ─────── seen 파일 로드·저장
def load_seen() -> set[str]:
    if os.path.exists(SEEN_FILE):
        with open(SEEN_FILE, encoding="utf-8") as f:
            return set(json.load(f))
    return set()

def save_seen(s: set[str]):
    with open(SEEN_FILE, "w", encoding="utf-8") as f:
        json.dump(list(s), f, ensure_ascii=False, indent=2)

# ─────── WP에 글이 남아 있는지 검사
def wp_exists(url_norm: str) -> bool:
    r = requests.get(POSTS, params={"search": url_norm, "per_page": 1},
                     auth=(USER, APP_PW), timeout=10)
    return r.ok and bool(r.json())

# ─────── **동기화**: WP에 없는 URL은 seen에서 제거
def sync_seen(seen: set[str]) -> set[str]:
    synced = {u for u in seen if wp_exists(norm(u))}
    if len(synced) != len(seen):
        save_seen(synced)
    return synced

# ─────── 기사 링크 수집
def fetch_links():
    soup = BeautifulSoup(requests.get(UDF_BASE, headers=HEADERS, timeout=10).text, "html.parser")
    return list({norm(urljoin(UDF_BASE, a["href"]))
                 for a in soup.select("div.article1 div.article_title_news a[href]")})

# ─────── 기사 파싱
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

# ─────── 스타일 가이드 & GPT 프롬프트
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
• 마크다운 #, ##, ### 사용 금지
• 사실 누락·요약 금지, 길이는 원문 대비 90±10 %
"""

def rewrite(a):
    prompt = f"""{STYLE_GUIDE}

아래 원문을 규칙에 맞춰 재작성하세요.

◆ 원문
{a['html']}
"""
    out = requests.post("https://api.openai.com/v1/chat/completions",
        headers={"Authorization": f"Bearer {OPEN_KEY}",
                 "Content-Type": "application/json"},
        json={"model":"gpt-4o",
              "messages":[{"role":"user","content":prompt}],
              "temperature":0.4}, timeout=90)
    out.raise_for_status()
    text = out.json()["choices"][0]["message"]["content"]

    # 헤더 기호 제거 + 이모지 치환
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

# ─────── 태그
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
    print("  ↳ 게시", r.status_code, r.json().get("id"))
    r.raise_for_status()

# ─────── 메인
def main():
    logging.basicConfig(level=logging.WARNING)
    seen = sync_seen(load_seen())          # ★ WP와 동기화
    links = fetch_links()

    todo = [u for u in links if norm(u) not in seen and not wp_exists(norm(u))]
    print(f"📰 새 기사 {len(todo)} / 총 {len(links)}")

    for url in todo:
        print("===", url)
        art = parse(url)
        if not art:
            continue
        try:
            txt = rewrite(art)
        except Exception as e:
            print("  GPT 오류:", e)
            continue

        tag_ids = [tid for n in tag_names(txt) if (tid := tag_id(n))]
        try:
            publish(art, txt, tag_ids)
            seen.add(norm(url)); save_seen(seen)
        except Exception as e:
            print("  업로드 실패:", e)
        time.sleep(2)

if __name__ == "__main__":
    main()
