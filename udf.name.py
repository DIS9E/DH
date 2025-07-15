#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
udf.name.py – v4.0.1  (AdSense·뉴닉 톤·외부데이터·자동 태그·관련 기사·디버그 포함)
"""

import os, sys, re, json, time, logging, random, html
from datetime import datetime
from urllib.parse import urljoin, urlparse, urlunparse

import requests, feedparser                # ← requirements.txt 에 feedparser 추가
from bs4 import BeautifulSoup

# ────────────────────────── 환경 변수 ──────────────────────────
WP_URL   = os.getenv("WP_URL", "https://belatri.info").rstrip("/")
USER     = os.getenv("WP_USERNAME")
APP_PW   = os.getenv("WP_APP_PASSWORD")
OPEN_KEY = os.getenv("OPENAI_API_KEY")
if not all([USER, APP_PW, OPEN_KEY]):
    sys.exit("❌  WP_USERNAME / WP_APP_PASSWORD / OPENAI_API_KEY 누락")

POSTS_API = f"{WP_URL}/wp-json/wp/v2/posts"
TAGS_API  = f"{WP_URL}/wp-json/wp/v2/tags"

UDF_BASE   = "https://udf.name/news/"
HEADERS    = {"User-Agent": "UDFCrawler/4.0.1"}
SEEN_FILE  = "seen_urls.json"
TARGET_CAT_ID = 20                         # ‘벨라루스 뉴스’

norm = lambda u: urlunparse(urlparse(u)._replace(query="", params="", fragment=""))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s │ %(levelname)s │ %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S")

# ────────────────────────── 유틸 ──────────────────────────
def load_seen() -> set[str]:
    if os.path.exists(SEEN_FILE):
        with open(SEEN_FILE, encoding="utf-8") as f:
            return set(json.load(f))
    return set()

def save_seen(s: set[str]):  json.dump(list(s), open(SEEN_FILE, "w"), ensure_ascii=False, indent=2)

def wp_exists(u):
    r = requests.get(POSTS_API, params={"search": u, "per_page": 1},
                     auth=(USER, APP_PW), timeout=10)
    return r.ok and bool(r.json())

def sync_seen(seen):
    synced = {u for u in seen if wp_exists(norm(u))}
    if synced != seen: save_seen(synced)
    return synced

# ────────────────────────── 링크 크롤러 ──────────────────────────
def fetch_links():
    soup = BeautifulSoup(requests.get(UDF_BASE, headers=HEADERS, timeout=10).text,
                         "html.parser")
    return list({norm(urljoin(UDF_BASE, a["href"]))
                 for a in soup.select("div.article1 div.article_title_news a[href]")})

# ────────────────────────── 기사 파서 ──────────────────────────
def parse(url):
    r = requests.get(url, headers=HEADERS, timeout=10)
    if not r.ok: return None
    s = BeautifulSoup(r.text, "html.parser")
    t = s.find("h1", class_="newtitle"); b = s.find("div", id="zooming")
    if not (t and b): return None
    img = s.find("img", class_="lazy") or s.find("img")
    return {"title": t.get_text(strip=True),
            "html": str(b),
            "image": urljoin(url, img.get("data-src") or img.get("src")) if img else None,
            "url": url}

# ────────────────────────── 외부 데이터 (환율·유가·헤드라인) ──────────────────────────
def get_usd_rate():
    try:
        js = requests.get("https://api.nbrb.by/exrates/rates/431", timeout=8).json()
        return f"{js['Cur_OfficialRate']:.4g} BYN (NBRB · {js['Date'][:10]})"
    except Exception:  return "데이터 없음"

def get_wti_price():
    try:
        # 무료 DEMO_KEY 는 24h 지연·404일 수 있음 → 실패 시 None
        js = requests.get("https://api.eia.gov/series/?api_key=DEMO_KEY&series_id=PET.RWTC.D",
                          timeout=8).json()
        v, d = js["series"][0]["data"][-1]
        return f"{float(v):.2f}$/bbl (WTI · {d})"
    except Exception:  return None

def get_rss_headlines(category):
    feeds = {
        "econ": ["https://feeds.bbci.co.uk/news/business/rss.xml",
                 "https://www.reuters.com/rssFeed/businessNews"],
        "world": ["https://feeds.bbci.co.uk/news/world/rss.xml"],
    }.get(category, [])
    items = []
    for url in feeds:
        try:
            fp = feedparser.parse(url)
            items += [ent.title for ent in fp.entries[:5]]
        except Exception:
            continue
    return random.sample(items, k=min(3, len(items)))

# ────────────────────────── 브리프(📊·💬) 생성 ──────────────────────────
def build_brief(cat):
    s = []
    usd = get_usd_rate(); s.append(f"• NBRB 환율 USD/BYN {usd}")
    wti = get_wti_price();  wti and s.append(f"• 국제유가 WTI {wti}")
    heads = get_rss_headlines(cat)
    for h in heads: s.append(f"• 헤드라인 ― {h}")
    return "<br>".join(s)

# ────────────────────────── STYLE_GUIDE ──────────────────────────
STYLE_GUIDE = """
• 구조
  <h1>📰 (이모지) 뉴닉 느낌의 한국어 제목</h1>
  <h2>✍️ 편집자 주 — 2문장 개요</h2>
  <h3>📊 최신 데이터</h3>
    외부 API·RSS 숫자 최소 4줄
  <h3>💬 전문가 전망</h3>
    최소 500자, 질문·감탄 포함
  <h3>❓ Q&A</h3>
    Q3개 + 각 답변 2문장↑
  <h3>💡 본문 해설</h3>
    원문 100% 보존·부가 해설
  <p>🏷️ 태그: 명사 3~6개</p>
  <p>출처: UDF.name 원문<br>Photo: UDF.name<br>by. 에디터 LEE🌳</p>

• 요약·삭제 금지 — 원문 문장 유지 + 부가 설명으로 ‘새 텍스트 40%↑’
• 제목은 45자↓, 이모지 1~3개, 러시아어·영어 금지
"""

# ────────────────────────── GPT 리라이팅 ──────────────────────────
CYRILLIC = re.compile(r"[А-Яа-яЁё]")

def korean_title(src:str, context:str)->str:
    if not CYRILLIC.search(src): return src  # 이미 한글
    prompt=( "다음 기사 내용에 어울리는 카피라이팅 한국어 제목을 45자 이내로 작성하고, "
             "관련 이모지 1–3개를 자연스럽게 포함하세요.\n\n"
             f"원제목: {src}\n기사 일부: {context[:300]}" )
    data={"model":"gpt-4o-mini","messages":[{"role":"user","content":prompt}],
          "temperature":0.8,"max_tokens":60}
    try:
        r=requests.post("https://api.openai.com/v1/chat/completions",
                        headers={"Authorization":f"Bearer {OPEN_KEY}","Content-Type":"application/json"},
                        json=data,timeout=20)
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"].strip()
    except Exception:
        return src

def rewrite(article, brief_html):
    prompt = f"{STYLE_GUIDE}\n\n◆ 원문:\n{article['html']}\n\n◆ 외부데이터 HTML:\n{brief_html}"
    data={"model":"gpt-4o","messages":[{"role":"user","content":prompt}],
          "temperature":0.55,"max_tokens":2200}
    r=requests.post("https://api.openai.com/v1/chat/completions",
                    headers={"Authorization":f"Bearer {OPEN_KEY}",
                             "Content-Type":"application/json"},
                    json=data,timeout=120)
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"].strip()

# ────────────────────────── 태그 ──────────────────────────
STOP = {"벨라루스","뉴스","기사"}
def extract_tags(txt):
    m = re.search(r"🏷️\s*태그[^:：]*[:：]\s*(.+)", txt)
    if not m: return []
    out=[]
    for t in re.split(r"[,\s]+", m.group(1)):
        t=t.strip("–-#•")
        if 1<len(t)<=20 and t not in STOP and t not in out:
            out.append(t)
        if len(out)==6: break
    return out

def ensure_tag(name):
    q=requests.get(TAGS_API, params={"search":name,"per_page":1},
                   auth=(USER,APP_PW),timeout=10)
    if q.ok and q.json(): return q.json()[0]["id"]
    c=requests.post(TAGS_API, json={"name":name},
                    auth=(USER,APP_PW),timeout=10)
    return c.json()["id"] if c.status_code==201 else None

# ────────────────────────── 관련 기사 링크 ──────────────────────────
def related_posts(tag_ids):
    if not tag_ids: return ""
    r=requests.get(POSTS_API, params={"tags":",".join(map(str,tag_ids)),
                                      "per_page":3,"exclude":0,"status":"publish"},
                   auth=(USER,APP_PW),timeout=10)
    if not (r.ok and r.json()): return ""
    li = '\n'.join(f"<li><a href='{p['link']}'>{html.escape(p['title']['rendered'])}</a></li>"
                   for p in r.json())
    return f"<h3>📚 관련 기사 더 보기</h3><ul>{li}</ul>"

# ────────────────────────── 게시 ──────────────────────────
def publish(article, gpt_html, tag_ids):
    hidden  = f'<a href="{article["url"]}" style="display:none">src</a>\n'
    img_tag = f'<p><img src="{article["image"]}" alt=""></p>\n' if article["image"] else ""

    soup = BeautifulSoup(gpt_html, "html.parser")
    h1 = soup.find("h1")
    title_txt = korean_title(h1.get_text(" ",strip=True) if h1 else article["title"],
                             soup.get_text(" ",strip=True))
    if h1: h1.decompose()                   # 본문에 H1 제거

    body = hidden + img_tag + str(soup) + related_posts(tag_ids)

    payload = {"title": title_txt, "content": body, "status":"publish",
               "categories":[TARGET_CAT_ID], "tags": tag_ids}
    r=requests.post(POSTS_API, json=payload, auth=(USER,APP_PW), timeout=30)
    r.raise_for_status()
    logging.info("  ↳ 게시 %s %s", r.status_code, r.json().get("id"))

# ────────────────────────── main ──────────────────────────
def main():
    logging.info("🚀 버전 4.0.1 실행")
    seen = sync_seen(load_seen())
    links = fetch_links()
    todo = [u for u in links if norm(u) not in seen and not wp_exists(norm(u))]
    logging.info("📰 새 기사 %d / 총 %d", len(todo), len(links))

    for url in todo:
        logging.info("▶ %s", url)
        art = parse(url); time.sleep(1)
        if not art: continue

        brief = build_brief("econ" if "/economic/" in url else "world")
        try:
            txt = rewrite(art, brief)
        except Exception as e:
            logging.warning("GPT 오류: %s", e); continue

        tag_ids=[ensure_tag(n) for n in extract_tags(txt)]
        tag_ids = [t for t in tag_ids if t]

        try:
            publish(art, txt, tag_ids)
            seen.add(norm(url)); save_seen(seen)
        except Exception as e:
            logging.warning("업로드 실패: %s", e)

        time.sleep(2)

if __name__ == "__main__":
    main()
