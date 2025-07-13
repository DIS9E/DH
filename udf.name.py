#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
udf.name.py – v2.2-debug-full
  • 중복 검사: WP meta('_source_url') 스캔 + seen.json
  • 이미지 401 확인용 디버그 로그
  • ChatGPT 리라이팅 프롬프트 전체 포함
"""
import os, sys, json, time, logging
from urllib.parse import urljoin, urlparse, urlunparse
import requests
from bs4 import BeautifulSoup
from requests.auth import HTTPBasicAuth

# ────────────────────────── 환경
WP_URL         = os.getenv("WP_URL", "https://belatri.info").rstrip("/")
WP_USERNAME    = os.getenv("WP_USERNAME")
WP_APP_PASSWORD= os.getenv("WP_APP_PASSWORD")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
CATEGORY_ID    = 136

if not all([WP_USERNAME, WP_APP_PASSWORD, OPENAI_API_KEY]):
    sys.exit("❌ WP_USERNAME / WP_APP_PASSWORD / OPENAI_API_KEY 필요")

WP_POSTS_API = f"{WP_URL}/wp-json/wp/v2/posts"
WP_TAGS_API  = f"{WP_URL}/wp-json/wp/v2/tags"
WP_MEDIA_API = f"{WP_URL}/wp-json/wp/v2/media"

UDF_BASE      = "https://udf.name/news/"
UA_HEADER     = {"User-Agent": "UDFCrawler/2.2-debug-full (+https://belatri.info)"}
SEEN_FILE     = "seen_urls.json"

# ────────────────────────── 유틸
def normalize(u: str) -> str:
    p = urlparse(u)
    return urlunparse((p.scheme, p.netloc, p.path, "", "", ""))

def load_seen() -> set[str]:
    try:
        with open(SEEN_FILE, encoding="utf-8") as f:
            return set(json.load(f))
    except FileNotFoundError:
        return set()

def save_seen(s: set[str]):
    with open(SEEN_FILE, "w", encoding="utf-8") as f:
        json.dump(list(s), f, ensure_ascii=False, indent=2)

# ────────────────────────── WP 기존 source_url
def wp_source_urls() -> set[str]:
    urls, page = set(), 1
    print("📥 WP에서 _source_url 수집 중 …")
    while True:
        r = requests.get(
            WP_POSTS_API,
            params={"per_page": 100, "page": page},
            auth=HTTPBasicAuth(WP_USERNAME, WP_APP_PASSWORD),
            timeout=30,
        )
        if r.status_code != 200 or not r.json():
            break
        batch = sum(
            1
            for p in r.json()
            if (m := p.get("meta")) and m.get("_source_url") and not urls.add(normalize(m["_source_url"]))
        )
        print(f"  • page {page} : {batch}건 추가, 누적 {len(urls)}")
        page += 1
    print(f"✅ WP 저장 소스 URL {len(urls)}건\n")
    return urls

# ────────────────────────── 기사 링크
def article_links() -> list[str]:
    html = requests.get(UDF_BASE, headers=UA_HEADER, timeout=10).text
    soup = BeautifulSoup(html, "html.parser")
    links = {
        normalize(urljoin(UDF_BASE, a["href"]))
        for a in soup.select("div.article1 div.article_title_news a[href]")
    }
    print(f"🔗 메인 페이지 링크 {len(links)}개 수집\n")
    return list(links)

# ────────────────────────── 파싱
def parse_article(url: str):
    r = requests.get(url, headers=UA_HEADER, timeout=10)
    if r.status_code != 200:
        print(f"⚠️ 요청 실패 {url} | {r.status_code}")
        return None
    s = BeautifulSoup(r.text, "html.parser")
    title = s.find("h1", class_="newtitle")
    body = s.find("div", id="zooming")
    if not (title and body):
        print(f"⚠️ 본문/제목 누락 {url}")
        return None
    img = s.find("img", class_="lazy") or s.find("img")
    img_url = urljoin(url, img.get("data-src") or img.get("src")) if img else None
    return {
        "title": title.get_text(strip=True),
        "html": str(body),
        "image": img_url,
        "url": url,
    }

# ────────────────────────── ✏️ ChatGPT 리라이팅
def rewrite_with_chatgpt(article: dict) -> str:
    prompt = f"""
다음은 벨라루스 관련 외신 기사입니다. 아래 양식에 맞춰 한국 독자를 위한 블로그 게시글을 작성해주세요.

🎯 작성 조건:
- 기사 내용을 바탕으로 **요약하거나 해석하지 말고**, **문체와 구조만 바꿔서 재작성**해주세요.
- **기사의 정보는 그대로 유지**하고, **한국어로 자연스럽고 가독성 높게** 작성해주세요.
- **제목(H1), 부제(H2), 내용 문단(H3)** 등으로 구분해 블로그에 최적화된 구조로 작성해주세요.
- 마지막에 "이 기사는 벨라루스 현지 보도 내용을 재구성한 콘텐츠입니다." 문구를 포함해주세요.

🧾 출력 형식:

# [📰 제목]
> 블로그 게시글의 핵심을 반영한 명확하고 간결한 제목

## ✍️ 편집자 주
- 전체 기사 맥락을 1~2문장으로 요약한 편집자 코멘트

## 📌 핵심 내용
### H3 요약 1
### H3 요약 2

## 🗞️ 원문 재작성
### [소제목 H3 - 주제1]
- 기사 내용 그대로 문장 구조만 변경
### [소제목 H3 - 주제2]
- 이어지는 내용 계속 서술

## 🌍 시사점
- 한국 혹은 세계에 미칠 영향 정리

## 🔗 출처
- 원문 링크: {article['url']}

---

📰 기사 원문:
{article['html']}
"""
    r = requests.post(
        "https://api.openai.com/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {OPENAI_API_KEY}",
            "Content-Type": "application/json",
        },
        json={
            "model": "gpt-4o",
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.3,
        },
        timeout=90,
    )
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"]

# ────────────────────────── 태그
def tag_id(name: str) -> int | None:
    q = requests.get(
        WP_TAGS_API,
        params={"search": name, "per_page": 1},
        auth=HTTPBasicAuth(WP_USERNAME, WP_APP_PASSWORD),
        timeout=10,
    )
    if q.status_code == 200 and q.json():
        return q.json()[0]["id"]
    c = requests.post(
        WP_TAGS_API,
        json={"name": name},
        auth=HTTPBasicAuth(WP_USERNAME, WP_APP_PASSWORD),
        timeout=10,
    )
    return c.json().get("id") if c.status_code == 201 else None

# ────────────────────────── 이미지 업로드
def upload(img_url: str | None) -> int | None:
    if not img_url:
        print("  ↳ 대표 이미지 없음")
        return None
    print(f"  ↳ 이미지 다운로드 {img_url}")
    f = requests.get(img_url, headers=UA_HEADER, timeout=10)
    if f.status_code == 404:
        print("  ↳ 🚫 404, 건너뜀")
        return None
    f.raise_for_status()
    filename = os.path.basename(urlparse(img_url).path) or "featured.jpg"
    headers = {
        "Content-Disposition": f'attachment; filename="{filename}"',
        "Content-Type": f"{f.headers.get('Content-Type', 'image/jpeg')}",
    }
    up = requests.post(
        WP_MEDIA_API,
        auth=HTTPBasicAuth(WP_USERNAME, WP_APP_PASSWORD),
        headers=headers,
        files={"file": (filename, f.content, headers["Content-Type"])},
        timeout=30,
    )
    print(f"  ↳ 업로드 응답 {up.status_code}")
    if up.status_code == 201:
        print("  ↳ ✔️ 이미지 ID", up.json()["id"])
        return up.json()["id"]
    print("  ↳ ❌ 업로드 실패", up.text[:160])
    return None

# ────────────────────────── 포스트
def publish(title, content, tags, mid, src):
    data = {
        "title": title,
        "content": content,
        "status": "publish",
        "categories": [CATEGORY_ID],
        "tags": tags,
        "meta": {"_source_url": src},
    }
    if mid:
        data["featured_media"] = mid
    p = requests.post(
        WP_POSTS_API,
        json=data,
        auth=HTTPBasicAuth(WP_USERNAME, WP_APP_PASSWORD),
        timeout=30,
    )
    print("  ↳ 게시 응답", p.status_code)
    p.raise_for_status()
    print("  ↳ 📝 게시 성공 ID", p.json()["id"])

# ────────────────────────── 메인
def main():
    logging.basicConfig(level=logging.WARNING)

    seen = load_seen()
    wp_urls = wp_source_urls()
    links = article_links()

    print("⚡ 중복 체크 …")
    targets = []
    for url in links:
        key = normalize(url)
        print(f" • {url}\n   ↳ seen.json={key in seen}, WP={key in wp_urls}")
        if key not in seen and key not in wp_urls:
            targets.append(url)
    print(f"✅ 업로드 대상 {len(targets)}개\n")

    success = 0
    for url in targets:
        print(f"===== 처리 시작: {url} =====")
        art = parse_article(url)
        if not art:
            continue

        try:
            content = rewrite_with_chatgpt(art)
        except Exception as e:
            print("❌ GPT 오류", e)
            continue

        title = next(
            (l for l in content.splitlines() if l.startswith("# ")), art["title"]
        ).lstrip("# ").strip()
        t_ids = [tid for t in ("벨라루스",) if (tid := tag_id(t))]
        mid = upload(art["image"])

        try:
            publish(title, content, t_ids, mid, art["url"])
            success += 1
            seen.add(normalize(url))
            save_seen(seen)
        except Exception as e:
            print("❌ 게시 실패", e)

        print(f"===== 처리 끝: {url} =====\n")
        time.sleep(2)

    print(f"🎉 최종 성공 {success} / {len(targets)}")

if __name__ == "__main__":
    main()
