#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
udf.name.py – v3.9  (롱폼·체류시간 강화판)
• 원문 100 % 유지 + 카테고리별 외부 데이터 삽입
• 섹션별 500자↑ 자동 확장·제목 중복 제거·이미지 캡션
• 예상 글 길이 1,200–1,800자 → 체류 1–2 분 확보
"""

import os, sys, re, json, time, logging
from urllib.parse import urljoin, urlparse, urlunparse
import requests
from bs4 import BeautifulSoup

# ────────── 환경 변수 ──────────
WP_URL = os.getenv("WP_URL", "https://belatri.info").rstrip("/")
USER = os.getenv("WP_USERNAME")
APP_PW = os.getenv("WP_APP_PASSWORD")
OPEN_KEY = os.getenv("OPENAI_API_KEY")
if not all([USER, APP_PW, OPEN_KEY]):
    sys.exit("❌  WP_USERNAME / WP_APP_PASSWORD / OPENAI_API_KEY 누락")

POSTS_API = f"{WP_URL}/wp-json/wp/v2/posts"
TAGS_API  = f"{WP_URL}/wp-json/wp/v2/tags"

UDF_BASE = "https://udf.name/news/"
HEADERS  = {"User-Agent": "UDFCrawler/3.9"}
SEEN_FILE = "seen_urls.json"
TARGET_CAT_ID = 20

norm = lambda u: urlunparse(urlparse(u)._replace(query="", params="", fragment=""))

# ────────── seen ──────────
def load_seen():
    return set(json.load(open(SEEN_FILE))) if os.path.exists(SEEN_FILE) else set()

def save_seen(s):
    json.dump(list(s), open(SEEN_FILE, "w"), ensure_ascii=False, indent=2)

def wp_exists(u_norm: str) -> bool:
    r = requests.get(POSTS_API, params={"search": u_norm, "per_page": 1},
                     auth=(USER, APP_PW), timeout=10)
    return r.ok and bool(r.json())

def sync_seen(seen):
    synced = {u for u in seen if wp_exists(norm(u))}
    if synced != seen:
        save_seen(synced)
    return synced

# ────────── 링크 크롤링 ──────────
def fetch_links():
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
    title_tag = s.find("h1", class_="newtitle")
    body_tag  = s.find("div", id="zooming")
    if not (title_tag and body_tag):
        return None

    img = s.find("img", class_="lazy") or s.find("img")
    src = None
    if img:
        src = img.get("data-src") or img.get("src")
        if src and ("placeholder" in src or "default" in src):
            src = None

    cat = url.split("/news/")[1].split("/")[0]  # economic, society, politic, war, …

    return {
        "title":  title_tag.get_text(strip=True),
        "html":   str(body_tag),
        "image":  urljoin(url, src) if src else None,
        "url":    url,
        "cat":    cat
    }

# ────────── 외부 브리프 ──────────
def build_brief(cat: str, headline: str) -> str:
    snippets = []
    try:
        rss = requests.get("https://www.reuters.com/rssFeed/ru/businessNews", timeout=10).text
        titles = re.findall(r"<title>(.*?)</title>", rss)[1:3]
        snippets += [f"• Reuters: {t}" for t in titles]
    except: pass

    if cat == "economic":
        try:
            r = requests.get("https://www.nbrb.by/api/exrates/rates/usd?parammode=2", timeout=10).json()
            snippets.append(f"• NBRB <a href='https://www.nbrb.by'>USD/BLR</a> {r['Cur_OfficialRate']} ({r['Date'][:10]})")
        except: pass
    else:
        try:
            bbc = requests.get("https://feeds.bbci.co.uk/news/world/rss.xml", timeout=10).text
            title = re.search(r"<title>(.*?)</title>", bbc).group(1)
            snippets.append(f"• BBC: {title}")
        except: pass
        try:
            eia = requests.get("https://api.eia.gov/series/?api_key=DEMO_KEY&series_id=PET.RWTC.D", timeout=10).json()
            price = eia["series"][0]["data"][0][1]
            snippets.append(f"• <a href='https://www.eia.gov'>WTI</a> ${price}")
        except: pass

    snippets.append(f"• 헤드라인 키워드: {headline[:60]}")
    return "\n".join(snippets)

# ────────── STYLE_GUIDE ──────────
STYLE_GUIDE = """
<h1>📰 (이모지) 흥미로운 한국어 제목</h1>
<h2>✍️ 편집자 주 — 기사 핵심을 2문장</h2>

<h3>📊 최신 데이터</h3>
<p>(extra_context 숫자·링크 이용, <strong>500자 이상</strong>)</p>

<h3>💬 전문가 전망</h3>
<p>(시나리오·숫자·기관 인용 포함, <strong>500자 이상</strong>)</p>

<h3>❓ Q&A</h3>
<ul>
  <li>Q1…?<br><strong>A.</strong> (2문장↑)</li>
  <li>Q2…?<br><strong>A.</strong> (2문장↑)</li>
  <li>Q3…?<br><strong>A.</strong> (2문장↑)</li>
</ul>

<h3>(본문 해설)</h3>
<p>원문 문장 모두 자연스럽게 재배치…</p>

<p>🏷️ 태그: 명사 3–6개</p>
<p>이 기사는 벨라루스 현지 보도를 재구성한 콘텐츠입니다.<br>by. 에디터 LEE🌳</p>
"""

# ────────── GPT 호출 헬퍼 ──────────
def chat(prompt: str, max_tok=1800, temp=0.5, model="gpt-4o") -> str:
    h = {"Authorization": f"Bearer {OPEN_KEY}", "Content-Type": "application/json"}
    d = {"model": model,
         "messages": [{"role": "user", "content": prompt}],
         "temperature": temp,
         "max_tokens": max_tok}
    r = requests.post("https://api.openai.com/v1/chat/completions",
                      headers=h, json=d, timeout=120)
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"].strip()

# ────────── 리라이팅 ──────────
def rewrite(article: dict) -> str:
    extra = build_brief(article['cat'], article['title'])
    prompt = f"""{STYLE_GUIDE}

◆ 원문:
{article['html']}

◆ extra_context:
{extra}
"""
    return chat(prompt)

# ────────── 제목 변환 ──────────
CYRILLIC = re.compile(r"[А-Яа-яЁё]")
def korean_title(src: str, context: str) -> str:
    if not CYRILLIC.search(src):
        return src
    prompt = ("다음 제목을 한국어 카피라이터 스타일(45자↓, 이모지 1–3개)로:\n"
              f"«{src}»\n문맥:{context[:200]}")
    return chat(prompt, max_tok=60, temp=0.9, model="gpt-4o-mini")

# ────────── 태그 ──────────
STOP = {"벨라루스", "뉴스", "기사"}
def tag_names(txt: str):
    m = re.search(r"🏷️.*[:：]\s*(.+)", txt)
    out = []
    if not m:
        return out
    for t in re.split(r"[,\s]+", m.group(1)):
        t = t.strip("–-#•")
        if 1 < len(t) <= 20 and t not in STOP and t not in out:
            out.append(t)
    return out[:6]

def tag_id(name: str):
    q = requests.get(TAGS_API, params={"search": name, "per_page": 1},
                     auth=(USER, APP_PW), timeout=10)
    if q.ok and q.json():
        return q.json()[0]["id"]
    c = requests.post(TAGS_API, json={"name": name},
                      auth=(USER, APP_PW), timeout=10)
    return c.json()["id"] if c.status_code == 201 else None

# ────────── 길이·헤더 가드 ──────────
def ensure_longform(html: str, title: str) -> str:
    soup = BeautifulSoup(html, "html.parser")

    # 제목 중복 텍스트 제거
    for tag in soup.find_all(string=True):
        if title.strip() == tag.strip():
            tag.extract()

    # 각 섹션 500자 미만이면 확장
    for blk in soup.find_all(["p", "ul"]):
        if len(blk.get_text()) < 500:
            prompt = (f"아래 문단을 근거·숫자·전망 포함 500자 이상으로 확장:\n{blk}")
            try:
                expanded = chat(prompt, max_tok=200, temp=0.7, model="gpt-4o-mini")
                blk.clear()
                blk.append(BeautifulSoup(expanded, "html.parser"))
            except: pass

    return str(soup)

# ────────── 게시 ──────────
def publish(article: dict, txt: str, tag_ids: list[int]):
    txt = ensure_longform(txt, article["title"])

    hidden  = f'<a href="{article["url"]}" style="display:none">src</a>\n'
    img_tag = f'<p><img src="{article["image"]}" alt=""></p>\n' if article["image"] else ""

    soup = BeautifulSoup(txt, "html.parser")

    h1 = soup.find("h1")
    orig_title = h1.get_text(strip=True) if h1 else article["title"]
    title = korean_title(orig_title, soup.get_text(" ", strip=True))
    if h1:
        h1.decompose()
    new_h1 = soup.new_tag("h1")
    new_h1.string = title
    soup.insert(0, new_h1)

    # 이미지 캡션
    if img_tag:
        img = soup.find("img")
        if img and not img.find_next_sibling("em"):
            cap = soup.new_tag("em")
            cap.string = "Photo: UDF.name"
            img.insert_after(cap)

    body = hidden + img_tag + str(soup)

    payload = {
        "title": title,
        "content": body,
        "status": "publish",
        "categories": [TARGET_CAT_ID],
        "tags": tag_ids
    }
    r = requests.post(POSTS_API, json=payload,
                      auth=(USER, APP_PW), timeout=30)
    logging.info("↳ 게시 %s %s", r.status_code, r.json().get("id"))
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
        time.sleep(1)
        if not art:
            continue

        try:
            txt = rewrite(art)
        except Exception as e:
            logging.warning("GPT 오류: %s", e)
            continue

        tag_ids = [tid for n in tag_names(txt) if (tid := tag_id(n))]
        try:
            publish(art, txt, tag_ids)
            seen.add(norm(url))
            save_seen(seen)
        except Exception as e:
            logging.warning("업로드 실패: %s", e)

        time.sleep(1.5)

if __name__ == "__main__":
    main()
