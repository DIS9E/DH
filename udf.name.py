#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
udf.name.py  –  v4.0.0-d  (2025-07-16)

· 뉴닉 스타일 · AdSense 품질 요건 충족
· 태그 백업 + 빈 배열 가드 (IndexError 해결)
· related_links(): WP 0개/오류 JSON 안전 처리
· 버전 로깅 + 락파일 중복 실행 방지
"""

__version__ = "4.0.0-d"

import os, sys, re, json, time, logging, random, requests
from urllib.parse import urljoin, urlparse, urlunparse
from bs4 import BeautifulSoup

# ─────────────── 0. 환경 변수 ───────────────
WP_URL  = os.getenv("WP_URL", "https://belatri.info").rstrip("/")
USER    = os.getenv("WP_USERNAME")
APP_PW  = os.getenv("WP_APP_PASSWORD")
OPEN_KEY= os.getenv("OPENAI_API_KEY")
if not all([USER, APP_PW, OPEN_KEY]):
    sys.exit("❌  WP_USERNAME / WP_APP_PASSWORD / OPENAI_API_KEY 누락")

POSTS_API = f"{WP_URL}/wp-json/wp/v2/posts"
TAGS_API  = f"{WP_URL}/wp-json/wp/v2/tags"

UDF_BASE   = "https://udf.name/news/"
HEADERS    = {"User-Agent": "UDFCrawler/4.0.0-d"}
TARGET_CAT_ID = 20
SEEN_FILE  = "seen_urls.json"
LOCK       = "/tmp/udf_crawler.lock"

norm = lambda u: urlunparse(urlparse(u)._replace(query="", params="", fragment=""))

# ─────────────── 1. 락파일 ───────────────
if os.path.exists(LOCK):
    print("⚠️  이미 실행 중, 종료"); sys.exit(0)
open(LOCK, "w").close()

# ─────────────── 2. seen & WP util ───────────────
def load_seen():
    return set(json.load(open(SEEN_FILE))) if os.path.exists(SEEN_FILE) else set()
def save_seen(s):
    json.dump(list(s), open(SEEN_FILE, "w"), ensure_ascii=False, indent=2)
def wp_exists(u):
    return bool(requests.get(POSTS_API,
        params={"search":u,"per_page":1},
        auth=(USER,APP_PW), timeout=10).json())

# ─────────────── 3. 크롤·파싱 ───────────────
def fetch_links():
    soup = BeautifulSoup(requests.get(UDF_BASE, headers=HEADERS,
                    timeout=10).text, "html.parser")
    return list({norm(urljoin(UDF_BASE, a["href"]))
        for a in soup.select("div.article1 div.article_title_news a[href]")})

def parse(url):
    s = BeautifulSoup(requests.get(url, headers=HEADERS, timeout=10).text,
                      "html.parser")
    h=s.find("h1",class_="newtitle"); b=s.find("div",id="zooming")
    if not (h and b): return None
    img=s.find("img",class_="lazy") or s.find("img")
    src=(img.get("data-src") or img.get("src")) if img else None
    cat=url.split("/news/")[1].split("/")[0]
    return {"title":h.get_text(strip=True),
            "html":str(b),
            "image":urljoin(url,src) if src else None,
            "url":url, "cat":cat}

# ─────────────── 4. 외부 데이터(환율·유가·RSS) ───────────────
def nbrb_rate():
    try:
        j=requests.get("https://api.nbrb.by/exrates/rates/431",timeout=6).json()
        return f"• NBRB USD/BYN {j['Cur_OfficialRate']:.2f} (출처: NBRB)"
    except Exception: return ""

def oil_price():
    try:
        j=requests.get("https://api.eia.gov/series/?api_key=DEMO_KEY&series_id=PET.RWTC.D",
                       timeout=6).json()
        p=j["series"][0]["data"][0][1]
        return f"• WTI 유가 {p}$/bbl (출처: EIA)"
    except Exception: return ""

RSS = {
 "economic":[
   "https://feeds.bbci.co.uk/news/business/rss.xml"],
 "politic":[
   "https://feeds.bbci.co.uk/news/world/rss.xml"],
 "sport":[
   "https://www.espn.com/espn/rss/news"]
}

def headlines(cat,n=2):
    for feed in RSS.get(cat,[]):
        try:
            items=BeautifulSoup(requests.get(feed,timeout=6).text,"xml")\
                   .find_all("item",limit=n)
            if items:
                host=urlparse(feed).hostname
                return [f"• {i.title.get_text(strip=True)} (출처: {host})"
                        for i in items]
        except Exception: pass
    return []

def brief(cat):
    data=[nbrb_rate(),oil_price()]+headlines(cat)
    return "\n".join(d for d in data if d)[:400]

# ─────────────── 5. GPT 래퍼 ───────────────
def chat(user,max_tok=1800,temp=0.45,model="gpt-4o"):
    hdr={"Authorization":f"Bearer {OPEN_KEY}","Content-Type":"application/json"}
    payload={"model":model,"messages":[{"role":"system","content":
        "당신은 한국어 뉴닉 기자. 친근한 존댓말·질문·감탄·이모지 사용."},
        {"role":"user","content":user}],
        "temperature":temp,"max_tokens":max_tok}
    r=requests.post("https://api.openai.com/v1/chat/completions",
        headers=hdr,json=payload,timeout=120); r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"].strip()

STYLE = """
<h1>(이모지 1–3개) 흥미로운 한국어 제목</h1>
<small>뉴닉 • {date} • 읽음 {views:,}</small>
<h2>✍️ 편집자 주 — 기사 핵심 2문장</h2>
<h3>📊 최신 데이터</h3><p>(extra_context)</p>
<h3>💬 전문가 전망</h3><p>(500자↑)</p>
<h3>❓ Q&A</h3>
<ul><li><strong>Q1.</strong> …?<br><strong>A.</strong> …</li>
<li><strong>Q2.</strong> …?<br><strong>A.</strong> …</li>
<li><strong>Q3.</strong> …?<br><strong>A.</strong> …</li></ul>
<h3>(본문 해설)</h3><p>원문 100 % 재배치</p>
<p>🏷️ 태그: 명사 3–6개</p>
<p>출처: UDF.name 원문<br>Photo: UDF.name<br>
by. 에디터 LEE🌳<br><em>* 생성형 AI의 도움으로 작성.</em></p>
"""

def rewrite(art):
    prompt=STYLE.format(date=time.strftime("%Y.%m.%d"),
                        views=random.randrange(8500,12000))
    prompt+=f"\n\n◆ extra_context:\n{brief(art['cat'])}\n\n◆ 원문:\n{art['html']}"
    txt=chat(prompt,max_tok=2300)
    txt=re.sub(r"<h1>.*?</h1>","",txt,flags=re.S)  # GPT h1 제거
    return txt

# ─────────────── 6. 태그 ───────────────
STOP={"벨라루스","뉴스","기사"}
TAG_RGX=re.compile(r"🏷️[^:：]{0,20}[:：]\s*(.+)", re.S)
def tag_names(txt):
    m=TAG_RGX.search(txt);  out=[]
    if m:
        clean=re.sub(r"<[^>]+>"," ",m.group(1))
        for t in re.split(r"[,\s]+",clean):
            t=t.strip("–-#•")
            if 1<len(t)<=20 and t not in STOP and t not in out:
                out.append(t)
    return out[:6]

def tag_id(name):
    q=requests.get(TAGS_API, params={"search":name,"per_page":1},
                   auth=(USER,APP_PW), timeout=10).json()
    if q: return q[0]["id"]
    c=requests.post(TAGS_API,json={"name":name},
                    auth=(USER,APP_PW), timeout=10)
    return c.json()["id"] if c.status_code==201 else None

# ─────────────── 7. 본문 확장 & 플레이스홀 제거 ───────────────
PLACE_RGX=re.compile(r"(기사 핵심.*?2문장|extra_context.+?strong>|문단을.*?확장.*?|어떤 주제에.*알려주세요)!?",re.I)
def ensure_long(html,title):
    soup=BeautifulSoup(html,"html.parser")
    for t in soup.find_all(string=True):
        if title.strip()==t.strip(): t.extract()
    for blk in soup.find_all(["p","ul"]):
        if len(blk.get_text())<500:
            try:
                exp=chat(f"<문단>{blk.get_text()}</문단>\n\n500자↑ 확장.",max_tok=500,
                         model="gpt-4o-mini")
                blk.clear(); blk.append(BeautifulSoup(exp,"html.parser"))
            except Exception: pass
    return PLACE_RGX.sub("",str(soup))

# ─────────────── 8. 내부 링크 ───────────────
def related_links(tag_ids, exclude_id=0, limit=3):
    if not tag_ids: return ""
    res=requests.get(POSTS_API,
        params={"tags":tag_ids[0],"per_page":limit,"exclude":exclude_id,
                "status":"publish"},
        auth=(USER,APP_PW), timeout=10).json()
    if not isinstance(res,list) or not res: return ""
    lis=[f'<li><a href="{p["link"]}">{p["title"]["rendered"]}</a></li>'
         for p in res]
    return "<h3>📚 관련 기사 더 보기</h3><ul>"+ "".join(lis)+"</ul>"

# ─────────────── 9. 러시아어 제목 → 한국어 ───────────────
CYRILLIC=re.compile(r"[А-Яа-яЁё]")
def ko_title(src,ctx):
    if not CYRILLIC.search(src): return src
    return chat(f"러시아어 제목 «{src}» 를 45자↓ 카피+이모지 한국어로.\n문맥:{ctx[:200]}",
                max_tok=60,temp=0.9,model="gpt-4o-mini")

# ─────────────── 10. 게시 ───────────────
def publish(art,raw,safe_tags):
    title=ko_title(art["title"],raw)
    body=ensure_long(raw,title)
    soup=BeautifulSoup(body,"html.parser")
    soup.insert(0,BeautifulSoup(f"<h1>{title}</h1>","html.parser"))
    names=list(dict.fromkeys(tag_names(str(soup))+safe_tags))
    tag_ids=[tid for n in names if (tid:=tag_id(n))]
    if not soup.find(string=re.compile("by\\. 에디터")):
        footer=('<p>출처: <a href="{u}">UDF.name 원문</a><br>Photo: UDF.name<br>'
                'by. 에디터 LEE🌳<br><em>* 생성형 AI의 도움으로 작성.</em></p>').format(u=art["url"])
        soup.append(BeautifulSoup(footer,"html.parser"))
    soup.append(BeautifulSoup(related_links(tag_ids), "html.parser"))

    hidden=f"<a href='{art['url']}' style='display:none'>src</a>\n"
    img= (f"<p><img src='{art['image']}' alt=''><br>Photo: UDF.name</p>\n"
          if art["image"] else "")
    payload={"title":title,"content":hidden+img+str(soup),
             "status":"publish","categories":[TARGET_CAT_ID],
             "tags":tag_ids,"ping_status":"closed"}
    r=requests.post(POSTS_API,json=payload,
                    auth=(USER,APP_PW), timeout=30); r.raise_for_status()
    logging.info("  ↳ 게시 id=%s", r.json().get("id"))

# ─────────────── 11. main ───────────────
def main():
    logging.basicConfig(level=logging.DEBUG,
        format="%(asctime)s │ %(levelname)s │ %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S")
    logging.info("🚀 버전 %s 실행", __version__)
    seen=load_seen()
    links=fetch_links()
    todo=[u for u in links if norm(u) not in seen and not wp_exists(norm(u))]
    logging.info("📰 새 기사 %d / 총 %d", len(todo), len(links))
    for url in todo:
        logging.info("▶ %s", url)
        art=parse(url); time.sleep(1)
        if not art: continue
        try:
            raw=rewrite(art); safe=tag_names(raw)
            publish(art,raw,safe); seen.add(norm(url)); save_seen(seen)
        except Exception as e:
            logging.warning("업로드 실패: %s", e)
        time.sleep(1.5)

if __name__=="__main__":
    try: main()
    finally:
        if os.path.exists(LOCK): os.remove(LOCK)
