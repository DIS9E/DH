#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
udf.name.py – v3.8  (AdSense 심층 확장 + 품질 가드)
• 원문 100 % 유지 + 카테고리별 외부 데이터 삽입
• Q&A 답변·내부 링크·출처 앵커·이미지 캡션 자동 보강
• 제목 한국어 변환 · 중복 헤더 제거 · placeholder 이미지 필터
"""

import os, sys, re, json, time, logging
from urllib.parse import urljoin, urlparse, urlunparse
import requests
from bs4 import BeautifulSoup
import textwrap

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
HEADERS    = {"User-Agent": "UDFCrawler/3.8"}
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
        if src and ("placeholder" in src or "default" in src):
            src = None
    img_url=urljoin(url, src) if src else None
    cat = url.split("/news/")[1].split("/")[0]  # economic, society, politic, war, world…
    return {"title":t.get_text(strip=True),
            "html":  str(b),
            "image": img_url,
            "url":   url,
            "cat":   cat}

# ────────── 카테고리별 외부 브리프 ──────────
def build_brief(cat: str, headline: str) -> str:
    snippets=[]
    # 로이터 RU 비즈 헤드라인 2건 (공통)
    try:
        rss=requests.get("https://www.reuters.com/rssFeed/ru/businessNews",timeout=10).text
        titles=re.findall(r"<title>(.*?)</title>",rss)[1:3]
        for t in titles:
            snippets.append(f"• 로이터: {t}")
    except: pass

    if cat=="economic":
        # NBRB 환율
        try:
            r=requests.get("https://www.nbrb.by/api/exrates/rates/usd?parammode=2",timeout=10).json()
            snippets.append(f"• NBRB <a href='https://www.nbrb.by'>USD/BLR</a>: {r['Cur_OfficialRate']} (발표 {r['Date'][:10]})")
        except: pass
    else:
        # BBC World 헤드라인 1건
        try:
            bbc=requests.get("https://feeds.bbci.co.uk/news/world/rss.xml",timeout=10).text
            t=re.search(r"<title>(.*?)</title>",bbc).group(1)
            snippets.append(f"• BBC: {t}")
        except: pass
        # WTI 유가
        try:
            eia=requests.get("https://api.eia.gov/series/?api_key=DEMO_KEY&series_id=PET.RWTC.D",timeout=10).json()
            price=eia["series"][0]["data"][0][1]
            snippets.append(f"• <a href='https://www.eia.gov'>WTI 유가</a>: ${price}")
        except: pass
        # USD/EUR & USD/JPY
        try:
            dxy=requests.get("https://api.exchangerate.host/latest?base=USD&symbols=EUR,JPY",timeout=10).json()
            eur, jpy=dxy["rates"]["EUR"], dxy["rates"]["JPY"]
            snippets.append(f"• USD/EUR {eur:.3f}, USD/JPY {jpy:.1f}")
        except: pass

    snippets.append(f"• 헤드라인 키워드: {headline[:60]}")
    return "\n".join(snippets)

# ────────── 스타일 가이드 ──────────

STYLE_GUIDE = textwrap.dedent("""
<h1>(이모지 1-3개) 흥미로운 한국어 제목</h1>

<h3>💡 본문 정리</h3>
<p>⟪RAW_HTML⟫</p>

<h2>✍️ 편집자 주 — 기사 핵심 2문장으로</h2>
<p>…여기에 핵심 두 문장을 적어주세요.</p>

<h3>(첫 번째 소제목)</h3>
<p>…</p>

<h3>(두 번째 소제목)</h3>
<p>…</p>

<h3>📊 최신 데이터</h3>
<ul>
  <li>헤드라인 및 관련정보 4~6줄</li>
</ul>

<h3>💬 전문가 전망</h3>
<p>근거·숫자 포함 분석 2문단(500자↑)</p>

<h3>❓ Q&A</h3>
<ul>
  <li><strong>Q1.</strong> …?<br><strong>A.</strong> …</li>
  <li><strong>Q2.</strong> …?<br><strong>A.</strong> …</li>
  <li><strong>Q3.</strong> …?<br><strong>A.</strong> …</li>
</ul>

<p>🏷️ 태그: 명사 3–6개</p>
<p>출처: UDF.name 원문<br>Photo: UDF.name<br>
   by. 에디터 LEE🌳<br><em>* 생성형 AI의 도움으로 작성.</em></p>

<p class="related">📚 관련 기사 더 보기</p>
""").strip()

# ── GPT 리라이팅 ──
def rewrite(article):
    extra=build_brief(article['cat'], article['title'])
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

# ────────── Q&A 깊이 보장 ──────────
def ensure_depth(html: str) -> str:
    soup=BeautifulSoup(html,"html.parser")
    modified=False
    for li in soup.find_all("li"):
        txt=li.get_text()
        if "<strong>A." not in txt:
            continue
        sentences=len(re.findall(r"[.!?]", txt))
        if sentences<2:
            # GPT mini 호출로 확장
            prompt=(f"아래 답변을 근거·숫자·전망 포함 3문장 이상으로 확장:\n{txt}")
            headers={"Authorization":f"Bearer {OPEN_KEY}","Content-Type":"application/json"}
            data={"model":"gpt-4o-mini","messages":[{"role":"user","content":prompt}],
                  "temperature":0.7,"max_tokens":100}
            try:
                r=requests.post("https://api.openai.com/v1/chat/completions",
                                headers=headers,json=data,timeout=20)
                r.raise_for_status()
                li.string = r.json()["choices"][0]["message"]["content"].strip()
                modified=True
            except: pass
    return str(soup) if modified else html

# ────────── 게시 ──────────
def publish(article: dict, txt: str, tag_ids: list[int]):
    # 0) 길이·답변 보강
    txt = ensure_depth(txt)

    hidden  = f'<a href="{article["url"]}" style="display:none">src</a>\n'
    img_tag = f'<p><img src="{article["image"]}" alt=""></p>\n' if article["image"] else ""

    # 1) 울타리·📰·소제목 템플릿 제거
    lines=[l for l in txt.splitlines()
           if not (l.strip().startswith("```") or l.strip().startswith("📰") or l.strip().startswith("소제목"))]
    soup=BeautifulSoup("\n".join(lines),"html.parser")

    # 2) 제목 변환 + <h1> 재삽입
    h1=soup.find("h1")
    orig=h1.get_text(strip=True) if h1 else article["title"]
    title=korean_title(orig, soup.get_text(" ",strip=True))
    if h1: h1.decompose()
    new_h1=soup.new_tag("h1"); new_h1.string=title; soup.insert(0,new_h1)

    # 3) 이미지 캡션
    if img_tag:
        img=soup.find("img")
        if img and not img.find_next_sibling("em"):
            caption=soup.new_tag("em"); caption.string="Photo: UDF.name"
            img.insert_after(caption)

    # 4) 내부 링크 (첫 번째 태그 기준)
    if tag_ids:
        try:
            r=requests.get(POSTS_API, params={"search": tag_ids[0], "per_page": 1})
            if r.ok and r.json():
                link=r.json()[0]["link"]
                more=soup.new_tag("p")
                a=soup.new_tag("a", href=link); a.string="📚 관련 기사 더 보기"
                more.append(a); soup.append(more)
        except: pass

    body = hidden + img_tag + str(soup)

    payload={"title":title,"content":body,"status":"publish",
             "categories":[TARGET_CAT_ID],"tags":tag_ids}
    r=requests.post(POSTS_API,json=payload,auth=(USER,APP_PW),timeout=30)
    logging.info("  ↳ 게시 %s %s", r.status_code, r.json().get("id"))
    r.raise_for_status()

# ────────── main ──────────
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
