#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
udf.name.py – v3.7  (1-기사 ‘심층 확장’ + AdSense 창작성 보강판)
• 원문 100 % 유지 + 추가 브리프(실시간 데이터·해외 헤드라인) 자동 삽입
• 제목 한국어 변환 · 중복 헤더 제거 · 코드블록 정리 · placeholder 이미지 필터
"""

import os, sys, re, json, time, logging
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

UDF_BASE   = "https://udf.name/news/"
HEADERS    = {"User-Agent": "UDFCrawler/3.7"}
SEEN_FILE  = "seen_urls.json"
TARGET_CAT_ID = 20

norm = lambda u: urlunparse(urlparse(u)._replace(query="", params="", fragment=""))

# ────────── seen ──────────
def load_seen():  return set(json.load(open(SEEN_FILE))) if os.path.exists(SEEN_FILE) else set()
def save_seen(s): json.dump(list(s), open(SEEN_FILE, "w"), ensure_ascii=False, indent=2)

def wp_exists(u):
    r = requests.get(POSTS_API, params={"search":u,"per_page":1}, auth=(USER,APP_PW), timeout=10)
    return r.ok and bool(r.json())

def sync_seen(seen):
    synced={u for u in seen if wp_exists(norm(u))}
    if synced!=seen: save_seen(synced)
    return synced

# ────────── 링크 크롤링 ──────────
def fetch_links():
    html=requests.get(UDF_BASE, headers=HEADERS, timeout=10).text
    soup=BeautifulSoup(html,"html.parser")
    return list({norm(urljoin(UDF_BASE, a["href"]))
                 for a in soup.select("div.article1 div.article_title_news a[href]")})

# ────────── 기사 파싱 ──────────
def parse(url):
    r=requests.get(url, headers=HEADERS, timeout=10)
    if not r.ok: return None
    s=BeautifulSoup(r.text,"html.parser")
    t=s.find("h1",class_="newtitle"); b=s.find("div",id="zooming")
    if not (t and b): return None
    img=s.find("img",class_="lazy") or s.find("img")
    src = None
    if img:
        src = img.get("data-src") or img.get("src")
        # placeholder 필터
        if src and ("placeholder" in src or "default" in src):
            src = None
    img_url=urljoin(url, src) if src else None
    return {"title":t.get_text(strip=True),
            "html":str(b),
            "image":img_url,
            "url":url}

# ────────── 추가 브리프 생성 ──────────
def build_brief() -> str:
    snippets = []
    # (1) NBRB 공식 USD/BLR 환율
    try:
        api = "https://www.nbrb.by/api/exrates/rates/usd?parammode=2"
        r = requests.get(api, timeout=10).json()
        snippets.append(f"• NBRB 공식 USD/BLR 환율 : {r['Cur_OfficialRate']} (발표 {r['Date'][:10]})")
    except Exception as e:
        logging.debug("NBRB fetch 실패: %s", e)
    # (2) 로이터 러시아판 최신 헤드라인 2건
    try:
        rss = requests.get("https://www.reuters.com/rssFeed/ru/businessNews", timeout=10).text
        titles = re.findall(r"<title>(.*?)</title>", rss)[1:3]   # 첫 건은 채널 제목
        for t in titles:
            snippets.append(f"• 로이터: {t}")
    except Exception as e:
        logging.debug("로이터 RSS 실패: %s", e)
    return "\n".join(snippets)

# ────────── 스타일 가이드 ──────────
STYLE_GUIDE = """
🗒️ 작성 규칙  ───────────────────────────────────────
• 반드시 HTML 태그만 사용(코드블록·백틱 X)
• **원문 문장을 하나도 빼지 말고** 어순·어휘만 자연스럽게 바꿀 것
• 톤: ‘헤드라이트’ 뉴스레터처럼 친근한 대화체 + 질문·감탄
• 제목은 45자↓ 한국어 · 기사 분위기에 맞는 이모지 1–3개
───────────────────────────────────────────────

<h1>📰 (이모지) 흥미로운 한국어 제목</h1>

<h2>✍️ 편집자 주 — 기사 핵심을 2문장으로</h2>

<h3>📊 최신 데이터 & 전문가 전망</h3>
<p>(아래 extra_context 내용을 표·리스트·문장으로 재구성)</p>

<h3>이 글을 읽고 답할 수 있는 질문 💬</h3>
<ul>
  <li>Q1…?</li>
  <li>Q2…?</li>
  <li>Q3…?</li>
</ul>

<h3>(첫 번째 소제목)</h3>
<p>독자에게 말을 건네듯, 핵심 정보를 쉽고 간결하게…</p>

<h3>(두 번째 소제목)</h3>
<p>이어지는 설명…</p>

<p>🏷️ 태그: 명사 3–6개</p>
<p>이 기사는 벨라루스 현지 보도를 재구성한 콘텐츠입니다.<br>
   by. 에디터 LEE🌳</p>
"""

# ── GPT 리라이팅 ──
def rewrite(article):
    extra = build_brief()
    prompt=f"""{STYLE_GUIDE}

◆ 원문:
{article['html']}

◆ extra_context:
{extra}
"""
    headers={"Authorization":f"Bearer {OPEN_KEY}","Content-Type":"application/json"}
    data={"model":"gpt-4o","messages":[{"role":"user","content":prompt}],
          "temperature":0.4,"max_tokens":1800}
    r=requests.post("https://api.openai.com/v1/chat/completions",
                    headers=headers,json=data,timeout=90)
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"].strip()

# ── 러시아어 제목 ➜ 한국어 + 맞춤 이모지 ──
CYRILLIC = re.compile(r"[А-Яа-яЁё]")

def korean_title(src:str, context:str)->str:
    if not CYRILLIC.search(src): return src
    prompt=("기사 내용을 참고해 독자의 호기심을 끌면서도 맥락에 어울리는 "
            "한국어 카피라이터 제목을 45자 이내로 작성하고, "
            "관련 이모지 1–3개를 자연스럽게 포함하세요.\n\n"
            f"원제목: {src}\n기사 일부: {context[:300]}")
    headers={"Authorization":f"Bearer {OPEN_KEY}","Content-Type":"application/json"}
    data={"model":"gpt-4o-mini","messages":[{"role":"user","content":prompt}],
          "temperature":0.85,"max_tokens":60}
    try:
        r=requests.post("https://api.openai.com/v1/chat/completions",
                        headers=headers,json=data,timeout=20)
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"].strip()
    except Exception as e:
        logging.warning("제목 변환 실패, 원본 사용: %s", e)
        return src

# ── 태그 ──
STOP={"벨라루스","뉴스","기사"}
def tag_names(txt):
    m=re.search(r"🏷️\s*태그[^:：]*[:：]\s*(.+)",txt)
    if not m: return []
    out=[]
    for t in re.split(r"[,\s]+",m.group(1)):
        t=t.strip("–-#•")
        if 1<len(t)<=20 and t not in STOP and t not in out:
            out.append(t)
        if len(out)==6: break
    return out

def tag_id(name):
    q=requests.get(TAGS_API, params={"search":name,"per_page":1},
                   auth=(USER,APP_PW),timeout=10)
    if q.ok and q.json(): return q.json()[0]["id"]
    c=requests.post(TAGS_API, json={"name":name}, auth=(USER,APP_PW), timeout=10)
    return c.json()["id"] if c.status_code==201 else None

# ────────── 게시 ──────────
def publish(article: dict, txt: str, tag_ids: list[int]):
    hidden  = f'<a href="{article["url"]}" style="display:none">src</a>\n'
    img_tag = f'<p><img src="{article["image"]}" alt=""></p>\n' if article["image"] else ""

    # 1) 울타리·📰·소제목 템플릿 제거
    lines=[l for l in txt.splitlines()
           if not (l.strip().startswith("```") or l.strip().startswith("📰") or l.strip().startswith("소제목"))]
    soup=BeautifulSoup("\n".join(lines),"html.parser")

    # 2) 제목 변환 + 중복 h1 제거
    h1=soup.find("h1")
    orig=h1.get_text(strip=True) if h1 else article["title"]
    title=korean_title(orig, soup.get_text(" ",strip=True))
    if h1: h1.decompose()

    body = hidden + img_tag + str(soup)
    payload={"title":title,"content":body,"status":"publish",
             "categories":[TARGET_CAT_ID],"tags":tag_ids}
    r=requests.post(POSTS_API,json=payload,auth=(USER,APP_PW),timeout=30)
    logging.info("  ↳ 게시 %s %s", r.status_code, r.json().get("id"))
    r.raise_for_status()

# ── main ──
def main():
    logging.basicConfig(level=logging.INFO,
        format="%(asctime)s │ %(levelname)s │ %(message)s", datefmt="%Y-%m-%d %H:%M:%S")

    seen=sync_seen(load_seen())
    links=fetch_links()
    todo=[u for u in links if norm(u) not in seen and not wp_exists(norm(u))]
    logging.info("📰 새 기사 %d / 총 %d", len(todo), len(links))

    for url in todo:
        logging.info("▶ %s", url)
        art=parse(url); time.sleep(1)
        if not art: continue

        try:
            txt=rewrite(art)
        except Exception as e:
            logging.warning("GPT 오류: %s", e); continue

        tag_ids=[tid for n in tag_names(txt) if (tid:=tag_id(n))]
        try:
            publish(art, txt, tag_ids)
            seen.add(norm(url)); save_seen(seen)
        except Exception as e:
            logging.warning("업로드 실패: %s", e)

        time.sleep(1.5)

if __name__=="__main__":
    main()
