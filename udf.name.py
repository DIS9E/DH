#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
udf.name.py – v3.9-stable c  (2025-07-15)
• 이모지 고정/플레이스홀더/제목 중복 제거
• 섹션 500자↑ 확장 안정화 + 헤드라이트 톤
• 출처 링크 + by. 에디터 LEE🌳 자동 삽입
• 워드프레스 핑백 차단 + DEBUG 로그
"""

import os, sys, re, json, time, logging
from urllib.parse import urljoin, urlparse, urlunparse
import requests
from bs4 import BeautifulSoup

# ────── 환경 변수 ──────
WP_URL   = os.getenv("WP_URL", "https://belatri.info").rstrip("/")
USER     = os.getenv("WP_USERNAME")
APP_PW   = os.getenv("WP_APP_PASSWORD")
OPEN_KEY = os.getenv("OPENAI_API_KEY")
if not all([USER, APP_PW, OPEN_KEY]):
    sys.exit("❌ WP_USERNAME / WP_APP_PASSWORD / OPENAI_API_KEY 누락")

POSTS_API = f"{WP_URL}/wp-json/wp/v2/posts"
TAGS_API  = f"{WP_URL}/wp-json/wp/v2/tags"
UDF_BASE  = "https://udf.name/news/"
HEADERS   = {"User-Agent": "UDFCrawler/3.9-stable-c"}
SEEN_FILE = "seen_urls.json"
TARGET_CAT_ID = 20
norm = lambda u: urlunparse(urlparse(u)._replace(query="", params="", fragment=""))

# ────── seen ──────
def load_seen():
    return set(json.load(open(SEEN_FILE))) if os.path.exists(SEEN_FILE) else set()
def save_seen(s):
    json.dump(list(s), open(SEEN_FILE, "w"), ensure_ascii=False, indent=2)
def wp_exists(u_norm):
    return bool(requests.get(POSTS_API,
        params={"search": u_norm, "per_page": 1},
        auth=(USER, APP_PW), timeout=10).json())
def sync_seen(seen):
    kept = {u for u in seen if wp_exists(norm(u))}
    if kept != seen: save_seen(kept)
    return kept

# ────── 크롤 & 파싱 ──────
def fetch_links():
    html = requests.get(UDF_BASE, headers=HEADERS, timeout=10).text
    soup = BeautifulSoup(html, "html.parser")
    return list({norm(urljoin(UDF_BASE, a["href"]))
        for a in soup.select("div.article1 div.article_title_news a[href]")})

def parse(url):
    r = requests.get(url, headers=HEADERS, timeout=10); r.raise_for_status()
    s = BeautifulSoup(r.text, "html.parser")
    h = s.find("h1", class_="newtitle")
    b = s.find("div", id="zooming")
    if not (h and b): return None
    img = s.find("img", class_="lazy") or s.find("img")
    src = (img.get("data-src") or img.get("src")) if img else None
    if src and any(x in src for x in ("placeholder", "default")):
        src = None
    cat = url.split("/news/")[1].split("/")[0]
    return dict(title=h.get_text(strip=True), html=str(b),
                image=urljoin(url, src) if src else None,
                url=url, cat=cat)

# ────── GPT 헬퍼 ──────
def chat(sys_p, user_p, max_tok=1800, temp=0.5, model="gpt-4o"):
    h = {"Authorization": f"Bearer {OPEN_KEY}",
         "Content-Type":  "application/json"}
    msgs = [{"role": "system", "content": sys_p},
            {"role": "user",   "content": user_p}]
    r = requests.post("https://api.openai.com/v1/chat/completions",
        headers=h, json={"model": model, "messages": msgs,
                         "temperature": temp, "max_tokens": max_tok},
        timeout=120)
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"].strip()

SYS = ("당신은 ‘헤드라이트’ 뉴스레터 스타일의 한국어 기자입니다. "
       "친근한 존댓말·질문·감탄을 적절히 섞어 쓰되, 같은 이모지를 "
       "기사마다 반복하지 마세요.")

STYLE_GUIDE = """
<h1>(이모지 1–3개) 흥미로운 한국어 제목</h1>
<h2>✍️ 편집자 주 — 기사 핵심을 2문장</h2>
<h3>📊 최신 데이터</h3>
<p>(extra_context 숫자·링크, <strong>500자 이상</strong>)</p>
<h3>💬 전문가 전망</h3>
<p>(시나리오·숫자·기관 인용, <strong>500자 이상</strong>)</p>
<h3>❓ Q&A</h3>
<ul><li>Q1…?<br><strong>A.</strong> …</li>
<li>Q2…?<br><strong>A.</strong> …</li>
<li>Q3…?<br><strong>A.</strong> …</li></ul>
<h3>(본문 해설)</h3>
<p>원문 문장 모두 자연스럽게 재배치…</p>
<p>🏷️ 태그: 명사 3–6개</p>
<p>출처: UDF.name 원문<br>by. 에디터 LEE🌳</p>
"""

PLACE_RGX = re.compile(r"(기사 핵심.*?2문장|흥미로운 한국어 제목:|extra_context.+?strong>|"
                       r"문단을.+?확장.*?|어떤 주제에.*알려주세요)!?", re.I)

def rewrite(art):
    prompt = f"{STYLE_GUIDE}\n\n◆ 원문:\n{art['html']}\n\n" \
             f"◆ extra_context:\n• 헤드라인 키워드: {art['title'][:60]}"
    txt = chat(SYS, prompt)
    txt = re.sub(r"<h1>.*?</h1>", "", txt, flags=re.S)  # GPT h1 제거
    logging.debug("GPT raw >>> %s …", txt[:300].replace('\n', ' '))
    return txt

# ────── 확장·정리 ──────
def ensure_long(html, title):
    soup = BeautifulSoup(html, "html.parser")
    for t in soup.find_all(string=True):
        if title.strip() == t.strip():
            t.extract()
    for blk in soup.find_all(["p", "ul"]):
        if len(blk.get_text()) < 500:
            try:
                expanded = chat(
                    SYS,
                    f"<문단>{blk.get_text()}</문단>\n\n위 문단을 "
                    "근거·숫자·전망 포함 500자 이상으로 확장.",
                    max_tok=400, temp=0.7, model="gpt-4o-mini")
                blk.clear()
                blk.append(BeautifulSoup(expanded, "html.parser"))
            except Exception as e:
                logging.debug("확장 실패: %s", e)
    html = PLACE_RGX.sub("", str(soup))
    return re.sub(r"\s{2,}", " ", html)

# ────── 태그 & 제목 ──────
CYRILLIC = re.compile(r"[А-Яа-яЁё]")
def korean_title(src, ctx):
    if not CYRILLIC.search(src):
        return src
    return chat(
        SYS,
        f"다음 러시아어 제목을 45자↓ 한국어 카피라이터 스타일 "
        f"+ 이모지 1–3개로:\n«{src}»\n문맥:{ctx[:200]}",
        max_tok=60, temp=0.9, model="gpt-4o-mini")

STOP = {"벨라루스", "뉴스", "기사"}
def tag_names(txt):
    m = re.search(r"🏷️.*[:：]\s*(.+)", txt)
    out = []
    if m:
        for t in re.split(r"[,\s]+", m.group(1)):
            t = t.strip("–-#•")
            if 1 < len(t) <= 20 and t not in STOP and t not in out:
                out.append(t)
    return out[:6]

def tag_id(name):
    q = requests.get(TAGS_API, params={"search": name, "per_page": 1},
                     auth=(USER, APP_PW), timeout=10).json()
    if q: return q[0]["id"]
    c = requests.post(TAGS_API, json={"name": name},
                      auth=(USER, APP_PW), timeout=10)
    return c.json()["id"] if c.status_code == 201 else None

# ────── 게시 ──────
def publish(art, txt, tag_ids):
    soup = BeautifulSoup(txt, "html.parser")
    kor_title = korean_title(art["title"], soup.get_text(" ", strip=True))
    body = ensure_long(str(soup), kor_title)
    soup = BeautifulSoup(body, "html.parser")

    h1 = soup.new_tag("h1"); h1.string = kor_title
    soup.insert(0, h1)

    if not soup.find(string=re.compile("by\\. 에디터")):
        footer = (f'<p>출처: <a href="{art["url"]}">UDF.name 원문</a>'
                  "<br>by. 에디터 LEE🌳</p>")
        soup.append(BeautifulSoup(footer, "html.parser"))

    hidden = f"<a href='{art['url']}' style='display:none'>src</a>\n"
    img    = f"<p><img src='{art['image']}' alt=''></p>\n" if art["image"] else ""

    payload = {"title": kor_title, "content": hidden + img + str(soup),
               "status": "publish", "categories": [TARGET_CAT_ID],
               "tags": tag_ids, "ping_status": "closed"}
    r = requests.post(POSTS_API, json=payload,
                      auth=(USER, APP_PW), timeout=30); r.raise_for_status()
    logging.info("↳ 게시 %s %s", r.status_code, r.json().get("id"))

# ────── main ──────
def main():
    logging.basicConfig(level=logging.DEBUG,
        format="%(asctime)s │ %(levelname)s │ %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S")
    seen = sync_seen(load_seen())
    links = fetch_links()
    todo = [u for u in links if norm(u) not in seen and not wp_exists(norm(u))]
    logging.info("📰 새 기사 %d / 총 %d", len(todo), len(links))

    for url in todo:
        logging.info("▶ %s", url)
        art = parse(url); time.sleep(1)
        if not art: continue
        try:
            txt = rewrite(art)
        except Exception as e:
            logging.warning("GPT 오류: %s", e); continue

        tag_ids = [tid for n in tag_names(txt) if (tid := tag_id(n))]
        try:
            publish(art, txt, tag_ids)
            seen.add(norm(url)); save_seen(seen)
        except Exception as e:
            logging.warning("업로드 실패: %s", e)
        time.sleep(1.5)

if __name__ == "__main__":
    main()
