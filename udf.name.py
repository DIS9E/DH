#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v4-adsense-nyunik.py   (2025-07-16)
——————————————————————————————————————————
• 뉴닉(News Letter) 스타일 + AdSense 품질요건 완전 대응
• 원문 100 % + 외부 API(환율·유가·RSS 헤드라인) + GPT 전망
• 📊 4–6줄 실시간 숫자/출처 링크 • Q&A 답변 2문장↑ 분석
• 내부 관련 글 2–3개 자동 링크 • ping_status=closed
• 제목·편집자주/데이터/전망 4단 구조 고정
——————————————————————————————————————————
"""

import os, sys, re, json, time, logging, random
from urllib.parse import urljoin, urlparse, urlunparse
import requests
from bs4 import BeautifulSoup

# ────────────────────────── 0. 환경 변수 ──────────────────────────
WP_URL = os.getenv("WP_URL", "https://belatri.info").rstrip("/")
USER, APP_PW, OPEN_KEY = map(os.getenv,
    ["WP_USERNAME", "WP_APP_PASSWORD", "OPENAI_API_KEY"])
if not all([USER, APP_PW, OPEN_KEY]):
    sys.exit("❌ WP_USERNAME / WP_APP_PASSWORD / OPENAI_API_KEY 누락")

POSTS_API = f"{WP_URL}/wp-json/wp/v2/posts"
TAGS_API  = f"{WP_URL}/wp-json/wp/v2/tags"
UDF_BASE  = "https://udf.name/news/"
HEADERS   = {"User-Agent": "UDFCrawler/4-adsense-nyunik"}
SEEN_FILE = "seen_urls.json"
TARGET_CAT_ID = 20
LOCK      = "/tmp/udf_crawler.lock"
norm = lambda u: urlunparse(urlparse(u)._replace(query="", params="", fragment=""))

# ────────────────────────── 1. 실행 중복 방지 ──────────────────────────
if os.path.exists(LOCK):
    print("Another instance running → exit"); sys.exit(0)
open(LOCK, "w").close()

# ────────────────────────── 2. seen & WP util ──────────────────────────
def load_seen():
    return set(json.load(open(SEEN_FILE))) if os.path.exists(SEEN_FILE) else set()
def save_seen(s):
    json.dump(list(s), open(SEEN_FILE, "w"),
              ensure_ascii=False, indent=2)
def wp_exists(u_norm):
    return bool(requests.get(POSTS_API,
        params={"search": u_norm, "per_page": 1},
        auth=(USER, APP_PW), timeout=10).json())
def sync_seen(seen):
    kept = {u for u in seen if wp_exists(norm(u))}
    if kept != seen: save_seen(kept)
    return kept

# ────────────────────────── 3. 링크 크롤링 & 파싱 ──────────────────────────
def fetch_links():
    soup = BeautifulSoup(requests.get(UDF_BASE, headers=HEADERS,
                    timeout=10).text, "html.parser")
    return list({norm(urljoin(UDF_BASE, a["href"]))
        for a in soup.select("div.article1 div.article_title_news a[href]")})

def parse(url):
    r = requests.get(url, headers=HEADERS, timeout=10); r.raise_for_status()
    s = BeautifulSoup(r.text, "html.parser")
    h = s.find("h1", class_="newtitle"); b = s.find("div", id="zooming")
    if not (h and b): return None
    img = s.find("img", class_="lazy") or s.find("img")
    src = (img.get("data-src") or img.get("src")) if img else None
    if src and any(x in src for x in ("placeholder", "default")): src = None
    return dict(title=h.get_text(strip=True), html=str(b),
                image=urljoin(url, src) if src else None, url=url)

# ────────────────────────── 4. 외부 데이터 (E-E-A-T) ──────────────────────────
RSS_FEEDS = {
    "economic": [
        "https://feeds.bbci.co.uk/news/business/rss.xml",
        "https://www.rbc.ru/v10/ajax/channel.jsp?channel=biz&limit=10"
    ],
    "sport": [
        "https://www.espn.com/espn/rss/news",
        "https://sports.yahoo.com/rss/"
    ],
    "politic": [
        "https://feeds.bbci.co.uk/news/world/rss.xml",
        "https://www.rferl.org/rss"
    ]
}

def pick_headlines(cat, n=2):
    for feed in RSS_FEEDS.get(cat, []):
        try:
            xml = requests.get(feed, timeout=6).text
            items = BeautifulSoup(xml, "xml").find_all("item", limit=n)
            if items: 
                return [f"• {i.title.get_text().strip()} (출처: {urlparse(feed).hostname})"
                        for i in items]
        except Exception: pass
    return []

def nbrb_rate():
    try:
        r = requests.get("https://api.nbrb.by/exrates/rates/431",
                         timeout=6).json()
        return f"• NBRB 공식환율 USD/BYN {r['Cur_OfficialRate']:.2f} (출처: NBRB)"
    except Exception: return ""

def oil_price():
    try:
        r = requests.get("https://api.eia.gov/series/?api_key=DEMO_KEY&series_id=PET.RWTC.D",
                         timeout=6).json()
        price = r["series"][0]["data"][0][1]
        return f"• WTI 유가 {price}$/bbl (출처: EIA)"
    except Exception: return ""

def build_brief(cat):
    data = [nbrb_rate(), oil_price()] + pick_headlines(cat)
    return "\n".join([d for d in data if d])[:400]

# ────────────────────────── 5. GPT 래퍼 ──────────────────────────
def chat(sys_p, user_p, max_tok=1800, temp=0.45, model="gpt-4o"):
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

SYS = ("당신은 ‘뉴닉’ 뉴스레터 스타일의 한국어 기자입니다. "
       "친근한 존댓말·질문·감탄·이모지를 사용하되, 구조는 "
       "제목→개요→데이터→전망→Q&A→해설→태그→footer 순서를 "
       "반드시 지킵니다. 같은 이모지는 기사마다 반복하지 않습니다.")

STYLE_GUIDE = """
<h1>(이모지 1–3개) 흥미로운 한국어 제목</h1>
<small>뉴닉 • {date} • 읽음 {views:,}</small>

<h2>✍️ 편집자 주 — 기사 핵심을 2문장</h2>

<h3>📊 최신 데이터</h3>
<p>(아래 extra_context 숫자·링크 활용, 4–6줄•각 줄 60자±10)</p>

<h3>💬 전문가 전망</h3>
<p>(시나리오·근거·숫자 포함 500자↑)</p>

<h3>❓ Q&A</h3>
<ul>
  <li><strong>Q1.</strong> …?<br><strong>A.</strong> (2문장↑ 분석)</li>
  <li><strong>Q2.</strong> …?<br><strong>A.</strong> …</li>
  <li><strong>Q3.</strong> …?<br><strong>A.</strong> …</li>
</ul>

<h3>(본문 해설)</h3>
<p>원문 문장 100 % 재배치·의역 없이 유지, 대화체·질문·감탄 포함.</p>

<p>🏷️ 태그: 명사 3–6개</p>
<p>출처: UDF.name 원문<br>
Photo: UDF.name<br>
by. 에디터 LEE🌳<br>
<em>* 생성형 AI의 도움으로 작성한 아티클입니다.</em></p>
"""

def rewrite(art, cat):
    prompt = STYLE_GUIDE.format(date=time.strftime("%Y.%m.%d"),
                                views=random.randrange(7800, 12000))
    prompt += f"\n\n◆ 원문:\n{art['html']}\n\n"
    prompt += f"◆ extra_context:\n{build_brief(cat)}"
    txt = chat(SYS, prompt, max_tok=2300)
    txt = re.sub(r"<h1>.*?</h1>", "", txt, flags=re.S)  # GPT h1 제거
    return txt

# ─────────────── 6. 500자 미만 문단 확장 + 플레이스홀더 제거 ───────────────
PLACE_RGX = re.compile(
    r"(기사 핵심.*?2문장|흥미로운 한국어 제목:|extra_context.+?strong>|"
    r"문단을.+?확장.*?|어떤 주제에.*알려주세요)!?", re.I)

def ensure_long(html, title):
    soup = BeautifulSoup(html, "html.parser")
    for t in soup.find_all(string=True):
        if title.strip() == t.strip(): t.extract()
    for blk in soup.find_all(["p", "ul"]):
        if len(blk.get_text()) < 500:
            try:
                expanded = chat(
                    SYS,
                    f"<문단>{blk.get_text()}</문단>\n\n위 문단을 "
                    "근거·숫자·전망 포함 500자 이상으로 확장.",
                    max_tok=500, model="gpt-4o-mini")
                blk.clear()
                blk.append(BeautifulSoup(expanded, "html.parser"))
            except Exception as e:
                logging.debug("확장 실패 %s", e)
    html = PLACE_RGX.sub("", str(soup))
    return re.sub(r"\s{2,}", " ", html)

# ────────────────────────── 7. 내부 관련 글 삽입 ──────────────────────────
def related_links(tag_ids, exclude_id=None, limit=3):
    if not tag_ids: return ""
    t_id = tag_ids[0]  # 첫 태그 기준
    posts = requests.get(
        POSTS_API, params={"tags": t_id, "per_page": limit,
                           "exclude": exclude_id or 0, "status": "publish"},
        auth=(USER, APP_PW), timeout=10).json()
    if not posts: return ""
    lis = [f'<li><a href="{p["link"]}">{p["title"]["rendered"]}</a></li>'
           for p in posts]
    return "<h3>📚 관련 기사 더 보기</h3><ul>" + "".join(lis) + "</ul>"

# ────────────────────────── 8. 태그 & 제목 변환 ──────────────────────────
CYRILLIC = re.compile(r"[А-Яа-яЁё]")
def korean_title(src, ctx):
    if not CYRILLIC.search(src): return src
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

# ────────────────────────── 9. 게시 ──────────────────────────
def publish(art, txt, tag_ids):
    soup = BeautifulSoup(txt, "html.parser")
    kor_title = korean_title(art["title"], soup.get_text(" ", strip=True))
    body = ensure_long(str(soup), kor_title)
    soup = BeautifulSoup(body, "html.parser")

    # 새 h1 삽입
    h1 = soup.new_tag("h1"); h1.string = kor_title
    soup.insert(0, h1)

    # footer 보강
    if not soup.find(string=re.compile("by\\. 에디터")):
        footer = (f'<p>출처: <a href="{art["url"]}">UDF.name 원문</a><br>'
                  'Photo: UDF.name<br>by. 에디터 LEE🌳<br>'
                  '<em>* 생성형 AI의 도움으로 작성한 아티클입니다.</em></p>')
        soup.append(BeautifulSoup(footer, "html.parser"))

    # 관련 글 링크 삽입
    soup.append(BeautifulSoup(related_links(tag_ids), "html.parser"))

    # 숨김 src
    hidden = f"<a href='{art['url']}' style='display:none'>src</a>\n"
    img    = (f"<p><img src='{art['image']}' alt=''><br>"
              f"<em>Photo: UDF.name</em></p>\n") if art["image"] else ""

    payload = {"title": kor_title, "content": hidden + img + str(soup),
               "status": "publish", "categories": [TARGET_CAT_ID],
               "tags": tag_ids, "ping_status": "closed"}
    r = requests.post(POSTS_API, json=payload,
                      auth=(USER, APP_PW), timeout=30); r.raise_for_status()
    logging.info("↳ 게시 %s %s", r.status_code, r.json().get("id"))
    return r.json().get("id")

# ────────────────────────── 10. main ──────────────────────────
def main():
    logging.basicConfig(level=logging.DEBUG,
        format="%(asctime)s │ %(levelname)s │ %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S")
    seen = sync_seen(load_seen())
    links = fetch_links()
    todo  = [u for u in links if norm(u) not in seen and not wp_exists(norm(u))]
    logging.info("📰 새 기사 %d / 총 %d", len(todo), len(links))

    for url in todo:
        logging.info("▶ %s", url)
        art = parse(url); time.sleep(1)
        if not art: continue
        cat = url.split("/news/")[1].split("/")[0]
        try:
            txt = rewrite(art, cat)
        except Exception as e:
            logging.warning("GPT 오류: %s", e); continue

        tags = [tid for n in tag_names(txt) if (tid := tag_id(n))]
        try:
            new_id = publish(art, txt, tags)
            seen.add(norm(url)); save_seen(seen)
        except Exception as e:
            logging.warning("업로드 실패: %s", e)
        time.sleep(1.5)

if __name__ == "__main__":
    try:
        main()
    finally:
        if os.path.exists(LOCK):
            os.remove(LOCK)
