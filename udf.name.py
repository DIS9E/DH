#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
udf.name.py – v3.6.2  (한국어 제목 변환 패치)
• WP↔seen 동기화  • 이미지 삽입 • 중복 방지 • 자동 태그 • 헤드라이트 톤
• 러시아어 제목을 한국어 카피라이터 스타일+이모지로 자동 변환
"""

import os, sys, re, json, time, logging
from urllib.parse import urljoin, urlparse, urlunparse
import requests
from bs4 import BeautifulSoup
from requests.exceptions import RequestException

# ────────── 환경 변수 ──────────
WP_URL   = os.getenv("WP_URL", "https://belatri.info").rstrip("/")
USER     = os.getenv("WP_USERNAME")
APP_PW   = os.getenv("WP_APP_PASSWORD")
OPEN_KEY = os.getenv("OPENAI_API_KEY")           # ← 반드시 설정
if not all([USER, APP_PW, OPEN_KEY]):
    sys.exit("❌  WP_USERNAME / WP_APP_PASSWORD / OPENAI_API_KEY 누락")

POSTS_API = f"{WP_URL}/wp-json/wp/v2/posts"
TAGS_API  = f"{WP_URL}/wp-json/wp/v2/tags"

UDF_BASE   = "https://udf.name/news/"
HEADERS    = {"User-Agent": "UDFCrawler/3.6.2"}
SEEN_FILE  = "seen_urls.json"
TARGET_CAT_ID = 20                      # ‘벨라루스 뉴스’ 카테고리(ID)

norm = lambda u: urlunparse(urlparse(u)._replace(query="", params="", fragment=""))

# ────────── seen 파일 ──────────
def load_seen() -> set[str]:
    if os.path.exists(SEEN_FILE):
        with open(SEEN_FILE, encoding="utf-8") as f:
            return set(json.load(f))
    return set()

def save_seen(s: set[str]):
    with open(SEEN_FILE, "w", encoding="utf-8") as f:
        json.dump(list(s), f, ensure_ascii=False, indent=2)

# ────────── WP 존재 여부 확인 & 동기화 ──────────
def wp_exists(url_norm: str) -> bool:
    r = requests.get(POSTS_API,
                     params={"search": url_norm, "per_page": 1},
                     auth=(USER, APP_PW), timeout=10)
    return r.ok and bool(r.json())

def sync_seen(seen: set[str]) -> set[str]:
    synced = {u for u in seen if wp_exists(norm(u))}
    if len(synced) != len(seen):
        save_seen(synced)
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

# ────────── 작성 가이드 & 프롬프트 ──────────
STYLE_GUIDE = """
• 구조 (반드시 HTML 태그 사용)
  <h1>📰 🎯 흥미로운 제목 😮</h1>
  <h2>✍️ 편집자 주 — 원문 맥락 2문장</h2>
  <h3>소제목 1</h3>
    본문 …
  <h3>소제목 2</h3>
    본문 …
  <p>🏷️ 태그: 명사 3~6개</p>
  <p>이 기사는 벨라루스 현지 보도 내용을 재구성한 콘텐츠입니다.<br>
     by. 에디터 LEE🌳</p>

• ⚠️ **절대 요약·삭제 금지** — 원문 길이를 100 % 그대로 유지하세요.
• 제목은 **전부 한국어**로, 카피라이터처럼 눈길을 끌되 관련 이모지 1–3개를 자연스럽게 넣으세요. 🇰🇷  <─※ 러시아어·영어 금지!
• 톤: 친근한 대화체, 질문·감탄 섞기.
"""

# ── GPT 호출 (본문 리라이팅) ──
def rewrite(article: dict) -> str:
    prompt = f"""{STYLE_GUIDE}

아래 원문을 규칙에 맞춰 재작성하세요.

◆ 원문:
{article['html']}
"""
    headers = {
        "Authorization": f"Bearer {OPEN_KEY}",
        "Content-Type": "application/json"
    }
    data = {
        "model": "gpt-4o",
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.4,
        "max_tokens": 1800
    }
    r = requests.post("https://api.openai.com/v1/chat/completions",
                      headers=headers, json=data, timeout=90)
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"].strip()

# ────────── 러시아어 제목 → 한국어 변환 ──────────
CYRILLIC = re.compile(r"[А-Яа-яЁё]")

def korean_title(src: str) -> str:
    """
    키릴 문자가 포함된 제목을 한국어 카피라이터 스타일(이모지 포함)로 변환.
    이미 한글이면 그대로 반환.
    """
    if not CYRILLIC.search(src):
        return src  # 변환 불필요

    prompt = (
        "다음 제목을 한국어 카피라이터 스타일로 45자 이내로 재창작해 주세요. "
        "관련 이모지 1–3개를 자연스럽게 넣어 주세요.\n\n"
        f"«{src}»"
    )
    headers = {"Authorization": f"Bearer {OPEN_KEY}", "Content-Type": "application/json"}
    data = {
        "model": "gpt-4o-mini",
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.8,
        "max_tokens": 60,
    }
    try:
        r = requests.post("https://api.openai.com/v1/chat/completions",
                          headers=headers, json=data, timeout=20)
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"].strip()
    except Exception as e:
        logging.warning("제목 변환 실패, 원본 사용: %s", e)
        return src

# ────────── 태그 추출 & WP 태그 생성 ──────────
STOP = {"벨라루스", "뉴스", "기사"}
def tag_names(txt: str) -> list[str]:
    m = re.search(r"🏷️\s*태그[^:：]*[:：]\s*(.+)", txt)
    if not m:
        return []
    out = []
    for t in re.split(r"[,\s]+", m.group(1)):
        t = t.strip("–-#•")
        if 1 < len(t) <= 20 and t not in STOP and t not in out:
            out.append(t)
        if len(out) == 6:
            break
    return out

def tag_id(name: str):
    q = requests.get(TAGS_API, params={"search": name, "per_page": 1},
                     auth=(USER, APP_PW), timeout=10)
    if q.ok and q.json():
        return q.json()[0]["id"]
    c = requests.post(TAGS_API, json={"name": name},
                      auth=(USER, APP_PW), timeout=10)
    if c.status_code == 201:
        return c.json()["id"]
    return None

# ────────── 게시 ──────────
def publish(article: dict, txt: str, tag_ids: list[int]):
    hidden = f'<a href="{article["url"]}" style="display:none">src</a>\n'
    img_tag = f'<p><img src="{article["image"]}" alt=""></p>\n' if article["image"] else ""

    # ――― 제목 추출 & 한국어 변환 ―――
    soup       = BeautifulSoup(txt, "html.parser")
    h1_tag     = soup.find("h1")
    orig_title = h1_tag.get_text(strip=True) if h1_tag else article["title"]
    title      = korean_title(orig_title)

    if h1_tag:
        h1_tag.string = title
    else:
        # 본문에 <h1>이 없으면 맨 앞에 삽입
        new_h1 = soup.new_tag("h1")
        new_h1.string = title
        soup.insert(0, new_h1)

    txt = str(soup)
    body = hidden + img_tag + txt

    payload = {
        "title": title,
        "content": body,
        "status": "publish",
        "categories": [TARGET_CAT_ID],
        "tags": tag_ids
    }
    r = requests.post(POSTS_API, json=payload, auth=(USER, APP_PW), timeout=30)
    logging.info("  ↳ 게시 %s %s", r.status_code, r.json().get("id"))
    r.raise_for_status()

# ────────── main ──────────
def main():
    logging.basicConfig(
        level=logging.INFO,
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
            logging.warning("GPT 오류: %s", e)
            continue

        tag_ids = [tid for name in tag_names(txt) if (tid := tag_id(name))]
        try:
            publish(art, txt, tag_ids)
            seen.add(norm(url)); save_seen(seen)
        except Exception as e:
            logging.warning("업로드 실패: %s", e)

        time.sleep(2)

if __name__ == "__main__":
    main()
