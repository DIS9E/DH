#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
udf.name.py  –  UDF.name → ChatGPT → WordPress 자동 업로드 파이프라인
 - 중복 포스트 방지: WP /posts?search= 로 서버-측 검사
 - 이미지 업로드 401/404 해결: Basic Auth + multipart + 404 graceful skip
 - 최신 HTML 셀렉터: div.article1 div.article_title_news a
 - '벨라루스 뉴스' 카테고리(ID 136) 자동 지정
"""
import os, sys, json, time, logging, re
from datetime import datetime
from urllib.parse import urljoin, urlparse, urlunparse
import requests
from bs4 import BeautifulSoup, NavigableString, Tag
from requests.auth import HTTPBasicAuth

# ──────────────────────────────────────────────────────────────────────────────
# 🔧 환경 변수
WP_URL         = os.getenv("WP_URL", "https://belatri.info").rstrip("/")
WP_USERNAME    = os.getenv("WP_USERNAME")
WP_APP_PASSWORD= os.getenv("WP_APP_PASSWORD")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
CATEGORY_ID    = 136                       # '벨라루스 뉴스' 카테고리

if not all([WP_USERNAME, WP_APP_PASSWORD, OPENAI_API_KEY]):
    sys.exit("❌  WP_USERNAME / WP_APP_PASSWORD / OPENAI_API_KEY 가 필요합니다.")

WP_API_URL    = f"{WP_URL}/wp-json/wp/v2/posts"
TAG_API_URL   = f"{WP_URL}/wp-json/wp/v2/tags"
MEDIA_API_URL = f"{WP_URL}/wp-json/wp/v2/media"

UDF_BASE_URL  = "https://udf.name/news/"
HEADERS_HTML  = {"User-Agent": "UDFCrawler/1.0 (+https://belatri.info)"}
SEEN_FILE     = "seen_urls.json"

# ──────────────────────────────────────────────────────────────────────────────
# 🛠️ 유틸
def normalize_url(u: str) -> str:
    """쿼리스트링 제거(중복 방지)"""
    p = urlparse(u)
    return urlunparse((p.scheme, p.netloc, p.path, "", "", ""))

def load_seen_urls() -> set[str]:
    if os.path.exists(SEEN_FILE):
        with open(SEEN_FILE, encoding="utf-8") as f:
            return set(json.load(f))
    return set()

def save_seen_urls(urls: set[str]) -> None:
    with open(SEEN_FILE, "w", encoding="utf-8") as f:
        json.dump(list(urls), f, ensure_ascii=False, indent=2)

# ──────────────────────────────────────────────────────────────────────────────
# 🌐 세션 (WP 인증 포함)
session = requests.Session()
session.auth = (WP_USERNAME, WP_APP_PASSWORD)
session.headers.update({"User-Agent": "UDFCrawler/1.0 (+https://belatri.info)"})

# ──────────────────────────────────────────────────────────────────────────────
# 📑 기사 링크 수집
def fetch_article_links() -> list[str]:
    res = requests.get(UDF_BASE_URL, headers=HEADERS_HTML, timeout=10)
    res.raise_for_status()
    soup = BeautifulSoup(res.text, "html.parser")
    anchors = soup.select("div.article1 div.article_title_news a[href]")
    links = [normalize_url(urljoin(UDF_BASE_URL, a["href"])) for a in anchors]
    return list(dict.fromkeys(links))

# ──────────────────────────────────────────────────────────────────────────────
# 📰 기사 파싱
def extract_article(url: str) -> dict | None:
    res = requests.get(url, headers=HEADERS_HTML, timeout=10)
    if res.status_code != 200:
        logging.error("⌧ 요청 실패 %s | %s", url, res.status_code); return None
    soup = BeautifulSoup(res.text, "html.parser")
    title  = soup.find("h1", class_="newtitle")
    author = soup.find("div", class_="author")
    body   = soup.find("div", id="zooming")
    if not (title and body):
        logging.warning("본문 누락: %s", url); return None

    # 대표 이미지 (lazy-load 지원)
    img_tag = soup.find("img", class_="lazy") or soup.find("img")
    img_url = None
    if img_tag:
        img_url = img_tag.get("data-src") or img_tag.get("src")
        if img_url:
            img_url = urljoin(url, img_url)

    # 본문(HTML) 그대로
    content_html = str(body)

    return {
        "title": title.get_text(strip=True),
        "author": author.get_text(strip=True) if author else "",
        "image_url": img_url,
        "source_url": url,
        "content_html": content_html
    }

# ──────────────────────────────────────────────────────────────────────────────
# 🔄 중복 검사
def already_posted(source_url: str) -> bool:
    q = {"search": source_url, "per_page": 1}
    r = session.get(WP_API_URL, params=q, timeout=10)
    return r.status_code == 200 and bool(r.json())

# ──────────────────────────────────────────────────────────────────────────────
# 🖼️ 이미지 업로드
def upload_media(image_url: str | None) -> int | None:
    if not image_url:
        return None
    img_resp = requests.get(image_url, headers=HEADERS_HTML, timeout=10, stream=True)
    if img_resp.status_code == 404:
        logging.warning("🚫 이미지 404: %s", image_url); return None
    img_resp.raise_for_status()

    filename = os.path.basename(urlparse(image_url).path) or "featured.jpg"
    files = {"file": (filename, img_resp.content, img_resp.headers.get("Content-Type", "image/jpeg"))}
    up = session.post(MEDIA_API_URL, files=files, timeout=30)
    if up.status_code == 201:
        media_id = up.json()["id"]
        logging.info("📸 이미지 업로드 성공 ID %s", media_id)
        return media_id
    logging.error("이미지 업로드 실패 %s | %s", up.status_code, up.text[:120])
    return None

# ──────────────────────────────────────────────────────────────────────────────
# ✏️ ChatGPT 리라이팅
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
- 원문 링크: {article['source_url']}

---

📰 기사 원문:
{article['content_html']}
"""
    headers = {"Authorization": f"Bearer {OPENAI_API_KEY}", "Content-Type": "application/json"}
    payload = {"model": "gpt-4o", "messages": [{"role": "user", "content": prompt}], "temperature": 0.3}
    r = requests.post("https://api.openai.com/v1/chat/completions", headers=headers, json=payload, timeout=60)
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"]

# ──────────────────────────────────────────────────────────────────────────────
# 🏷️ 태그
def create_or_get_tag_id(tag_name: str) -> int | None:
    q = session.get(TAG_API_URL, params={"search": tag_name, "per_page": 1}, timeout=10)
    if q.status_code == 200 and q.json():
        return q.json()[0]["id"]
    c = session.post(TAG_API_URL, json={"name": tag_name}, timeout=10)
    if c.status_code == 201:
        return c.json()["id"]
    return None

def extract_tags_from_output(output: str) -> list[str]:
    """'# 태그:' 같은 라인을 찾아 단어 추출 (원하는 양식대로 수정 가능)"""
    lines = [l.strip() for l in output.splitlines() if l.strip()]
    tag_section = [l for l in lines if l.lower().startswith("🏷") or "태그" in l]
    if not tag_section:
        return []
    # 라인 끝에 쉼표/공백 구분
    raw = re.sub(r"^.*?:", "", tag_section[0])
    return [t.strip("–- ,#") for t in raw.split() if t.strip()]

# ──────────────────────────────────────────────────────────────────────────────
# 📝 포스트 업로드
def publish_post(title: str, content: str, tag_ids: list[int], media_id: int | None, source_url: str):
    payload = {
        "title": title,
        "content": content,
        "status": "publish",
        "categories": [CATEGORY_ID],
        "tags": tag_ids,
        "meta": {"_source_url": source_url}
    }
    if media_id:
        payload["featured_media"] = media_id
    r = session.post(WP_API_URL, json=payload, timeout=30)
    r.raise_for_status()
    logging.info("📝 게시 성공 (ID %s)", r.json()["id"])

# ──────────────────────────────────────────────────────────────────────────────
def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")

    seen_urls = load_seen_urls()
    article_links = fetch_article_links()
    targets = [u for u in article_links if normalize_url(u) not in seen_urls and not already_posted(u)]
    logging.info("📰 새 기사 %d건", len(targets))

    for url in targets:
        art = extract_article(url)
        if art is None:
            continue

        try:
            rewritten = rewrite_with_chatgpt(art)
        except Exception as e:
            logging.error("ChatGPT 실패: %s", e); continue

        # 제목 추출
        title_line = next((l for l in rewritten.splitlines() if l.startswith("# ")), art["title"])
        title_clean = title_line.replace("# ", "").strip()

        # 태그
        tag_names = extract_tags_from_output(rewritten)
        tag_ids = [tid for tag in tag_names if (tid := create_or_get_tag_id(tag))]

        # 이미지
        media_id = upload_media(art["image_url"])

        # 업로드
        try:
            publish_post(title_clean, rewritten, tag_ids, media_id, art["source_url"])
            seen_urls.add(normalize_url(url))
            save_seen_urls(seen_urls)
            time.sleep(3)           # 서버 부하 완화
        except Exception as e:
            logging.error("게시 실패: %s", e)

    logging.info("✅ 전체 작업 완료")

# ──────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    main()
