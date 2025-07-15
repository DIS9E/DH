#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
udf.name.py – v4.1.0  (헤드라이트·AdSense 대응)
• WP↔seen 동기화  • 이미지 삽입 • 자동 태그 • 외부 데이터 주입 • 길이 Guard
"""

import os, sys, re, json, time, logging, random, textwrap
from datetime import datetime
from zoneinfo import ZoneInfo
from urllib.parse import urljoin, urlparse, urlunparse

import requests
from bs4 import BeautifulSoup

# ────────── 환경 변수 ──────────
WP_URL   = os.getenv("WP_URL", "https://belatri.info").rstrip("/")
USER     = os.getenv("WP_USERNAME")
APP_PW   = os.getenv("WP_APP_PASSWORD")
OPEN_KEY = os.getenv("OPENAI_API_KEY")
if not all([USER, APP_PW, OPEN_KEY]):
    sys.exit("❌  WP_USERNAME / WP_APP_PASSWORD / OPENAI_API_KEY 누락")

POSTS_API = f"{WP_URL}/wp-json/wp/v2/posts"
TAGS_API  = f"{WP_URL}/wp-json/wp/v2/tags"

UDF_BASE  = "https://udf.name/news/"
HEADERS   = {"User-Agent": "UDFCrawler/4.1.0"}
SEEN_FILE = "seen_urls.json"
TARGET_CAT_ID = 20

norm = lambda u: urlunparse(urlparse(u)._replace(query="", params="", fragment=""))

# ── Helper: 메타라인 ─────────────────────────────────────────────
def build_meta():
    today = datetime.now(tz=ZoneInfo("Asia/Seoul")).strftime("%Y.%m.%d")
    reads = f"{random.randint(7_000, 12_000):,}"
    return f"<p class='meta'>헤드라이트 • {today} • 읽음 {reads}</p>"

# ── seen 파일 ────────────────────────────────────────────────────
def load_seen():  # set[str]
    return set(json.load(open(SEEN_FILE))) if os.path.exists(SEEN_FILE) else set()

def save_seen(s: set[str]):
    json.dump(list(s), open(SEEN_FILE, "w"), ensure_ascii=False, indent=2)

# ── WP 중복 검사 ────────────────────────────────────────────────
def wp_exists(u_norm):
    r = requests.get(POSTS_API, params={"search": u_norm, "per_page": 1},
                     auth=(USER, APP_PW), timeout=10)
    return r.ok and bool(r.json())

def sync_seen(seen):
    synced = {u for u in seen if wp_exists(norm(u))}
    if synced != seen:
        save_seen(synced)
    return synced

# ── 링크 크롤러 ──────────────────────────────────────────────────
def fetch_links():
    soup = BeautifulSoup(requests.get(UDF_BASE, headers=HEADERS, timeout=10).text,
                         "html.parser")
    return list({norm(urljoin(UDF_BASE, a["href"]))
                 for a in soup.select("div.article1 div.article_title_news a[href]")})

# ── 기사 파싱 ────────────────────────────────────────────────────
def parse(url):
    r = requests.get(url, headers=HEADERS, timeout=10)
    if not r.ok: return None
    s = BeautifulSoup(r.text, "html.parser")
    title_tag = s.find("h1", class_="newtitle")
    body_tag  = s.find("div", id="zooming")
    if not (title_tag and body_tag): return None
    img = s.find("img", class_="lazy") or s.find("img")
    return {
        "title": title_tag.get_text(strip=True),
        "html":  str(body_tag),
        "image": urljoin(url, img.get("data-src") or img.get("src")) if img else None,
        "url":   url
    }

# ── STYLE_GUIDE (⟪META⟫, ⟪RAW_HTML⟫ 플레이스홀더 사용) ────────
STYLE_GUIDE = textwrap.dedent("""
<h1>(이모지 1–3개) 흥미로운 한국어 제목</h1>

<h2>✍️ 편집자 주 — 기사 핵심 2문장</h2>
<h3>📊 최신 데이터</h3><p><ul>
  <li>환율·유가·헤드라인 등 최소 4~6줄</li>
</ul></p>
<h3>💬 전문가 전망</h3><p>근거·숫자 포함 분석 2문단(500자↑)</p>
<h3>❓ Q&A</h3>
<ul><li><strong>Q1.</strong> …?<br><strong>A.</strong> …</li>
<li><strong>Q2.</strong> …?<br><strong>A.</strong> …</li>
<li><strong>Q3.</strong> …?<br><strong>A.</strong> …</li></ul>
<h3>(본문 해설)</h3><p>원문 100 % 재배치</p>
<p>🏷️ 태그: 명사 3–6개</p>
<p>출처: UDF.name 원문<br>Photo: UDF.name<br>
by. 에디터 LEE🌳<br><em>* 생성형 AI의 도움으로 작성.</em></p>

<p class="related">📚 관련 기사 더 보기</p>
""").strip()

# ── OpenAI 리라이터 ────────────────────────────────────────────
def rewrite(article):
    prompt = STYLE_GUIDE.replace("⟪META⟫", build_meta())\
                        .replace("⟪RAW_HTML⟫", article["html"])
    headers={"Authorization":f"Bearer {OPEN_KEY}",
             "Content-Type":"application/json"}
    data = {
        "model": "gpt-4o",
        "messages":[{"role":"user", "content": prompt}],
        "temperature":0.4,
        "max_tokens": 2300
    }
    r = requests.post("https://api.openai.com/v1/chat/completions",
                      headers=headers, json=data, timeout=90)
    r.raise_for_status()
    txt = r.json()["choices"][0]["message"]["content"].strip()

    # 길이 guard: 1 500자 미만이면 한 번 더 요청
    if len(txt) < 1500:
        logging.info("  ↺ 길이 보강 재-요청")
        data["temperature"] = 0.6
        r2 = requests.post("https://api.openai.com/v1/chat/completions",
                           headers=headers, json=data, timeout=90)
        r2.raise_for_status()
        txt = r2.json()["choices"][0]["message"]["content"].strip()
    return txt

# ── 태그 유틸 ───────────────────────────────────────────────────
STOP = {"벨라루스", "뉴스", "기사"}
def tag_names(txt):
    m = re.search(r"🏷️\s*태그[^:：]*[:：]\s*(.+)", txt)
    if not m: return []
    out=[]
    for t in re.split(r"[,\s]+", m.group(1)):
        t=t.strip("–-#•")
        if 1<len(t)<=20 and t not in STOP and t not in out:
            out.append(t)
        if len(out)==6: break
    return out

def tag_id(name):
    q = requests.get(TAGS_API, params={"search":name,"per_page":1},
                     auth=(USER,APP_PW), timeout=10)
    if q.ok and q.json(): return q.json()[0]["id"]
    r = requests.post(TAGS_API, json={"name":name},
                      auth=(USER,APP_PW), timeout=10)
    return r.json()["id"] if r.status_code==201 else None

# ── 게시 (제목 중복 H1 제거 & 관련 링크) ─────────────────────────
def publish(article, txt, tag_ids):
    soup = BeautifulSoup(txt, "html.parser")

    h1 = soup.find("h1")
    title = (h1.get_text(" ", strip=True) if h1 else article["title"]).lstrip("📰").strip()
    if h1: h1.decompose()

    # 관련 기사(동일 태그 최신 3) – 태그 없으면 건너뜀
    related_html = ""
    if tag_ids:
        r = requests.get(POSTS_API,
                         params={"tags": ",".join(map(str,tag_ids)),
                                 "per_page": 3, "exclude":0, "status":"publish"},
                         auth=(USER,APP_PW), timeout=10)
        if r.ok and r.json():
            lst = [f"<li><a href='{p['link']}'>{p['title']['rendered']}</a></li>"
                   for p in r.json()]
            related_html = "<ul>" + "".join(lst) + "</ul>"
    if related_html:
        soup.find("p", class_="related").append(BeautifulSoup(related_html,"html.parser"))

    hidden = f'<a href="{article["url"]}" style="display:none">src</a>\n'
    img_tag = f'<p><img src="{article["image"]}" alt=""></p>\n' if article["image"] else ""
    body = hidden + img_tag + str(soup)

    payload = {
        "title": title,
        "content": body,
        "status": "publish",
        "categories": [TARGET_CAT_ID],
        "tags": tag_ids
    }
    r = requests.post(POSTS_API, json=payload, auth=(USER,APP_PW), timeout=30)
    if r.status_code == 201:
        logging.info("  ↳ 게시 201 %s", r.json()["id"])
    else:
        logging.warning("  ↳ 업로드 실패 %s %s", r.status_code, r.text)
    r.raise_for_status()

# ── main ─────────────────────────────────────────────────────────
def main():
    logging.basicConfig(level=logging.INFO,
        format="%(asctime)s │ %(levelname)s │ %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S")
    logging.info("🚀 버전 4.1.0 실행")

    seen = sync_seen(load_seen())
    links = fetch_links()

    todo = [u for u in links if norm(u) not in seen and not wp_exists(norm(u))]
    logging.info("📰 새 기사 %d / 총 %d", len(todo), len(links))

    for url in todo:
        logging.info("▶ %s", url)
        art = parse(url)
        if not art: continue

        try:
            txt = rewrite(art)
        except Exception as e:
            logging.warning("GPT 오류: %s", e); continue

        tag_ids=[tid for n in tag_names(txt) if (tid:=tag_id(n))]
        try:
            publish(art, txt, tag_ids)
            seen.add(norm(url)); save_seen(seen)
        except Exception as e:
            logging.warning("업로드 실패: %s", e)

        time.sleep(1.2)

if __name__ == "__main__":
    main()
