#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
udf.name.py – v3.0-full  (2025-07-13)
─────────────────────────────────────────────────────────────────────────────
• 기본 카테고리 ‘벨라루스 뉴스’(slug=belarus-news) ID 자동 조회
• categories 필드 항상 포함   # ★
• meta 키 → source_url (언더스코어 제거)   # ★
• WP 메타 + /posts?search= 병행 중복 차단   # ★
• WebP → JPEG 변환 후 /media 업로드 (Pillow)   # ★
• print + logging DEBUG 둘 다 지원
"""

import os, sys, json, time, logging
from io import BytesIO
from urllib.parse import urljoin, urlparse, urlunparse
import requests
from requests.auth import HTTPBasicAuth
from bs4 import BeautifulSoup, NavigableString, Tag
from PIL import Image         # pip install pillow

# ─────────────────────────── 1. 환경 변수
WP_URL          = os.getenv("WP_URL", "https://belatri.info").rstrip("/")
WP_USERNAME     = os.getenv("WP_USERNAME")
WP_APP_PASSWORD = os.getenv("WP_APP_PASSWORD")
OPENAI_API_KEY  = os.getenv("OPENAI_API_KEY")
if not all([WP_USERNAME, WP_APP_PASSWORD, OPENAI_API_KEY]):
    sys.exit("❌  WP_USERNAME / WP_APP_PASSWORD / OPENAI_API_KEY 필요")

WP_POSTS_API = f"{WP_URL}/wp-json/wp/v2/posts"
WP_TAGS_API  = f"{WP_URL}/wp-json/wp/v2/tags"
WP_MEDIA_API = f"{WP_URL}/wp-json/wp/v2/media"
WP_CATS_API  = f"{WP_URL}/wp-json/wp/v2/categories"

UDF_BASE      = "https://udf.name/news/"
UA_HEADER     = {"User-Agent": "UDFCrawler/3.0-full (+https://belatri.info)"}
SEEN_FILE     = "seen_urls.json"
CATEGORY_SLUG = "belarus-news"           # WP 슬러그

# ─────────────────────────── 2. 카테고리 ID 조회
def get_category_id(slug: str) -> int:
    r = requests.get(WP_CATS_API, params={"slug": slug, "per_page": 1},
                     auth=HTTPBasicAuth(WP_USERNAME, WP_APP_PASSWORD), timeout=20)
    if r.status_code == 200 and r.json():
        return r.json()[0]["id"]
    # 없으면 자동 생성
    c = requests.post(WP_CATS_API,
                      json={"name": "벨라루스 뉴스", "slug": slug},
                      auth=HTTPBasicAuth(WP_USERNAME, WP_APP_PASSWORD), timeout=20)
    c.raise_for_status()
    return c.json()["id"]

CATEGORY_ID = get_category_id(CATEGORY_SLUG)
print(f"✅ 카테고리 ID → {CATEGORY_ID}")

# ─────────────────────────── 3. 유틸
def norm(u: str) -> str:
    p = urlparse(u)
    return urlunparse((p.scheme, p.netloc, p.path, "", "", ""))

def load_seen() -> set[str]:
    if os.path.exists(SEEN_FILE):
        with open(SEEN_FILE, encoding="utf-8") as f:
            return set(json.load(f))
    return set()

def save_seen(s: set[str]):
    with open(SEEN_FILE, "w", encoding="utf-8") as f:
        json.dump(list(s), f, ensure_ascii=False, indent=2)

# ─────────────────────────── 4. WordPress 기존 URL 수집 (meta.source_url)
def wp_meta_urls() -> set[str]:
    urls, page = set(), 1
    while True:
        r = requests.get(WP_POSTS_API, params={"per_page": 100, "page": page},
                         auth=HTTPBasicAuth(WP_USERNAME, WP_APP_PASSWORD), timeout=30)
        if r.status_code != 200 or not r.json():
            break
        for p in r.json():
            if (m := p.get("meta")) and m.get("source_url"):
                urls.add(norm(m["source_url"]))
        page += 1
    return urls

# ─────────────────────────── 5. 링크 수집
def fetch_links() -> list[str]:
    html = requests.get(UDF_BASE, headers=UA_HEADER, timeout=10).text
    soup = BeautifulSoup(html, "html.parser")
    return list({norm(urljoin(UDF_BASE, a["href"]))
                 for a in soup.select("div.article1 div.article_title_news a[href]")})

# ─────────────────────────── 6. 기사 파싱
def parse_article(url: str):
    r = requests.get(url, headers=UA_HEADER, timeout=10)
    if r.status_code != 200:
        print("⚠️ 본문 실패", url, r.status_code)
        return None
    soup = BeautifulSoup(r.text, "html.parser")
    title = soup.find("h1", class_="newtitle")
    body  = soup.find("div", id="zooming")
    if not (title and body):
        return None
    img = soup.find("img", class_="lazy") or soup.find("img")
    img_url = urljoin(url, img.get("data-src") or img.get("src")) if img else None
    return {"title": title.get_text(strip=True),
            "html": str(body),
            "image": img_url,
            "url": url}

# ─────────────────────────── 7. ChatGPT 리라이팅
def rewrite(article: dict) -> str:
    prompt = f"""
다음은 벨라루스 관련 외신 기사입니다. 아래 양식에 맞춰 한국 독자를 위한 블로그 게시글을 작성해주세요.

🎯 작성 조건:
- 기사 내용을 요약하거나 해석하지 말고, **문체·구조만 변경**해주세요.
- 제목(H1), 부제(H2), 내용 문단(H3) 구조 포함.
- 마지막에 "이 기사는 벨라루스 현지 보도 내용을 재구성한 콘텐츠입니다." 문장 추가.

🧾 출력 형식:
# [📰 제목]
> 한 줄 요약
## ✍️ 편집자 주
- 1~2문장 코멘트
## 📌 핵심 내용
### H3 요약 1
### H3 요약 2
## 🗞️ 원문 재작성
### [소제목 H3]
- 문단
## 🌍 시사점
- 영향
## 🔗 출처
- 원문 링크: {article['url']}

📰 기사 원문:
{article['html']}
"""
    res = requests.post(
        "https://api.openai.com/v1/chat/completions",
        headers={"Authorization": f"Bearer {OPENAI_API_KEY}",
                 "Content-Type": "application/json"},
        json={"model": "gpt-4o",
              "messages": [{"role": "user", "content": prompt}],
              "temperature": 0.3},
        timeout=90)
    res.raise_for_status()
    return res.json()["choices"][0]["message"]["content"]

# ─────────────────────────── 8. 태그 생성 (기본 '벨라루스')
def tag_id(name: str) -> int|None:
    r = requests.get(WP_TAGS_API, params={"search": name, "per_page": 1},
                     auth=HTTPBasicAuth(WP_USERNAME, WP_APP_PASSWORD), timeout=10)
    if r.status_code == 200 and r.json():
        return r.json()[0]["id"]
    c = requests.post(WP_TAGS_API, json={"name": name},
                      auth=HTTPBasicAuth(WP_USERNAME, WP_APP_PASSWORD), timeout=10)
    return c.json().get("id") if c.status_code == 201 else None

TAG_BELARUS = tag_id("벨라루스") or 0

# ─────────────────────────── 9. 썸네일 업로드 (WebP→JPEG 변환)
def upload_media(img_url: str | None) -> int | None:
    if not img_url:
        print("  ↳ 썸네일 없음")
        return None
    f = requests.get(img_url, headers=UA_HEADER, timeout=10)
    if f.status_code == 404:
        print("  ↳ 404 이미지")
        return None
    f.raise_for_status()

    filename = os.path.basename(urlparse(img_url).path)
    if filename.lower().endswith(".webp"):
        img = Image.open(BytesIO(f.content)).convert("RGB")
        buf = BytesIO(); img.save(buf, format="JPEG", quality=90)
        file_bytes, mime = buf.getvalue(), "image/jpeg"
        filename = filename.rsplit(".", 1)[0] + ".jpg"
    else:
        file_bytes, mime = f.content, f.headers.get("Content-Type", "image/jpeg")

    up = requests.post(WP_MEDIA_API,
                       auth=HTTPBasicAuth(WP_USERNAME, WP_APP_PASSWORD),
                       headers={"Content-Disposition": f'attachment; filename="{filename}"'},
                       files={"file": (filename, file_bytes, mime)}, timeout=30)
    print("  ↳ 썸네일 응답", up.status_code)
    if up.status_code == 201:
        return up.json()["id"]
    print("  ↳ 썸네일 실패", up.text[:160])
    return None

# ─────────────────────────── 10. 중복 검사 함수
def is_duplicate(url_norm: str, wp_set: set[str]) -> bool:
    if url_norm in wp_set:
        return True
    s = requests.get(WP_POSTS_API, params={"search": url_norm, "per_page": 1},
                     auth=HTTPBasicAuth(WP_USERNAME, WP_APP_PASSWORD), timeout=10)
    return s.status_code == 200 and bool(s.json())

# ─────────────────────────── 11. 포스트 발행
def publish(article, content, media_id):
    title_line = next((l for l in content.splitlines() if l.startswith("# ")),
                      article["title"])
    title = title_line.lstrip("# ").strip()
    payload = {
        "title": title,
        "content": content,
        "status": "publish",
        "categories": [CATEGORY_ID],         # ★ 반드시 포함
        "tags": [TAG_BELARUS] if TAG_BELARUS else [],
        "meta": {"source_url": article["url"]}   # ★ 언더스코어 제거
    }
    if media_id:
        payload["featured_media"] = media_id
    r = requests.post(WP_POSTS_API, json=payload,
                      auth=HTTPBasicAuth(WP_USERNAME, WP_APP_PASSWORD), timeout=30)
    print("  ↳ 게시 응답", r.status_code)
    r.raise_for_status()
    print("  ↳ 📝 ID", r.json()["id"])

# ─────────────────────────── 12. 메인
def main():
    logging.basicConfig(level=logging.WARNING)
    seen = load_seen()
    wp_set = wp_meta_urls()
    links = fetch_links()

    todo = [u for u in links if not is_duplicate(norm(u), wp_set) and norm(u) not in seen]
    print(f"총 {len(links)}개 링크 → 새 기사 {len(todo)}개\n")

    for url in todo:
        print("=== 처리:", url)
        art = parse_article(url)
        if not art:
            continue
        try:
            content = rewrite(art)
        except Exception as e:
            print("  ↳ GPT 오류", e)
            continue
        media_id = upload_media(art["image"])
        try:
            publish(art, content, media_id)
            seen.add(norm(url)); save_seen(seen)
        except Exception as e:
            print("  ↳ 업로드 실패", e)
        time.sleep(2)

if __name__ == "__main__":
    main()
