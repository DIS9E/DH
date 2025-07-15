#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
udf.name.py – v3.9-debug2  (롱폼·체류시간 강화 + 핑백 차단 + 디버그)
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

UDF_BASE  = "https://udf.name/news/"
HEADERS   = {"User-Agent": "UDFCrawler/3.9-debug2"}
SEEN_FILE = "seen_urls.json"
TARGET_CAT_ID = 20
norm = lambda u: urlunparse(urlparse(u)._replace(query="", params="", fragment=""))

# ────────── seen ──────────
def load_seen(): return set(json.load(open(SEEN_FILE))) if os.path.exists(SEEN_FILE) else set()
def save_seen(s): json.dump(list(s), open(SEEN_FILE, "w"), ensure_ascii=False, indent=2)
def wp_exists(u): return requests.get(POSTS_API, params={"search":u,"per_page":1},
                                      auth=(USER,APP_PW),timeout=10).json()
def sync_seen(seen): 
    synced={u for u in seen if wp_exists(norm(u))}
    if synced!=seen: save_seen(synced)
    return synced

# ────────── 링크 크롤링 ──────────
def fetch_links():
    html=requests.get(UDF_BASE,headers=HEADERS,timeout=10).text
    soup=BeautifulSoup(html,"html.parser")
    return list({norm(urljoin(UDF_BASE,a["href"])) 
                 for a in soup.select("div.article1 div.article_title_news a[href]")})

# ────────── 파싱 ──────────
def parse(url):
    r=requests.get(url,headers=HEADERS,timeout=10)
    if not r.ok: return None
    s=BeautifulSoup(r.text,"html.parser")
    t=s.find("h1",class_="newtitle"); b=s.find("div",id="zooming")
    if not(t and b): return None
    img=s.find("img",class_="lazy") or s.find("img")
    src=None
    if img:
        src=img.get("data-src") or img.get("src")
        if src and ("placeholder" in src or "default" in src): src=None
    cat=url.split("/news/")[1].split("/")[0]
    return {"title":t.get_text(strip=True),"html":str(b),"image":urljoin(url,src) if src else None,
            "url":url,"cat":cat}

# ────────── 외부 브리프 ──────────
def build_brief(cat,headline):
    s=[]
    try:
        rss=requests.get("https://www.reuters.com/rssFeed/ru/businessNews",timeout=10).text
        s+=[f"• Reuters: {t}" for t in re.findall(r"<title>(.*?)</title>",rss)[1:3]]
    except: pass
    if cat=="economic":
        try:r=requests.get("https://www.nbrb.by/api/exrates/rates/usd?parammode=2",timeout=10).json()
        ;s.append(f"• NBRB <a href='https://www.nbrb.by'>USD/BLR</a> {r['Cur_OfficialRate']} ({r['Date'][:10]})")
        except: pass
    else:
        try:
            bbc=requests.get("https://feeds.bbci.co.uk/news/world/rss.xml",timeout=10).text
            s.append("• BBC: "+re.search(r"<title>(.*?)</title>",bbc).group(1))
        except: pass
        try:
            eia=requests.get("https://api.eia.gov/series/?api_key=DEMO_KEY&series_id=PET.RWTC.D",timeout=10).json()
            s.append(f"• <a href='https://www.eia.gov'>WTI</a> ${eia['series'][0]['data'][0][1]}")
        except: pass
    s.append(f"• 헤드라인 키워드: {headline[:60]}")
    return "\n".join(s)

# ────────── STYLE_GUIDE (요약) ──────────
STYLE_GUIDE="""<h1>📰 (이모지) 흥미로운 한국어 제목</h1>
<h2>✍️ 편집자 주 — 기사 핵심을 2문장</h2>
<h3>📊 최신 데이터</h3><p>(extra_context 숫자·링크, <strong>500자↑</strong>)</p>
<h3>💬 전문가 전망</h3><p>(시나리오·숫자·기관 인용, <strong>500자↑</strong>)</p>
<h3>❓ Q&A</h3><ul><li>Q1…?<br><strong>A.</strong> …</li><li>Q2…?<br><strong>A.</strong> …</li><li>Q3…?<br><strong>A.</strong> …</li></ul>
<h3>(본문 해설)</h3><p>원문 문장 모두 자연스럽게 재배치…</p>
<p>🏷️ 태그: 명사 3–6개</p>
<p>이 기사는 벨라루스 현지 보도를 재구성한 콘텐츠입니다.<br>by. 에디터 LEE🌳</p>"""

# ────────── GPT 헬퍼 ──────────
def chat(prompt,max_tok=1800,temp=0.5,model="gpt-4o"):
    h={"Authorization":f"Bearer {OPEN_KEY}","Content-Type":"application/json"}
    d={"model":model,"messages":[{"role":"user","content":prompt}],
       "temperature":temp,"max_tokens":max_tok}
    r=requests.post("https://api.openai.com/v1/chat/completions",
                    headers=h,json=d,timeout=120)
    r.raise_for_status(); return r.json()["choices"][0]["message"]["content"].strip()

# ────────── 리라이팅 ──────────
def rewrite(art):
    extra=build_brief(art['cat'],art['title'])
    prompt=f"{STYLE_GUIDE}\n\n◆ 원문:\n{art['html']}\n\n◆ extra_context:\n{extra}"
    txt=chat(prompt); logging.debug("GPT raw >>> %s …",txt[:300].replace('\n',' '))
    return txt

# ────────── 제목 변환 ──────────
CYRILLIC=re.compile(r"[А-Яа-яЁё]")
def korean_title(src,ctx):
    if not CYRILLIC.search(src): return src
    return chat(f"다음 제목을 한국어 카피라이터 스타일(45자↓, 이모지 1–3개)로:\n«{src}»\n문맥:{ctx[:200]}",
                max_tok=60,temp=0.9,model="gpt-4o-mini")

# ────────── 태그 ──────────
STOP={"벨라루스","뉴스","기사"}
def tag_names(txt):
    m=re.search(r"🏷️.*[:：]\s*(.+)",txt); out=[]
    if m:
        for t in re.split(r"[,\s]+",m.group(1)):
            t=t.strip("–-#•"); 
            if 1<len(t)<=20 and t not in STOP and t not in out: out.append(t)
    return out[:6]
def tag_id(name):
    q=requests.get(TAGS_API,params={"search":name,"per_page":1},
                   auth=(USER,APP_PW),timeout=10).json()
    if q: return q[0]["id"]
    c=requests.post(TAGS_API,json={"name":name},
                    auth=(USER,APP_PW),timeout=10)
    return c.json()["id"] if c.status_code==201 else None

# ────────── 길이·헤더 가드 ──────────
def ensure_long(html,title):
    soup=BeautifulSoup(html,"html.parser")
    for t in soup.find_all(string=True):
        if title.strip() in t.strip(): t.extract()
    for blk in soup.find_all(["p","ul"]):
        if len(blk.get_text())<500:
            try:
                blk.clear()
                blk.append(BeautifulSoup(
                    chat(f"문단을 근거·숫자·전망 포함 500자↑ 확장:\n{blk}",
                         max_tok=200,temp=0.7,model="gpt-4o-mini"),"html.parser"))
            except: pass
    return str(soup)

# ────────── 게시 ──────────
def publish(art,txt,tags):
    logging.debug("before guard len=%d",len(txt))
    txt=ensure_long(txt,art["title"])
    logging.debug("after guard len=%d",len(txt))

    hidden=f'<a href="{art["url"]}" style="display:none">src</a>\n'
    img_tag=f'<p><img src="{art["image"]}" alt=""></p>\n' if art["image"] else ""
    soup=BeautifulSoup(txt,"html.parser")

    h1=soup.find("h1"); orig=h1.get_text(strip=True) if h1 else art["title"]
    title=korean_title(orig,soup.get_text())
    if h1:h1.decompose()
    new_h1=soup.new_tag("h1"); new_h1.string=title; soup.insert(0,new_h1)
    logging.debug("after header has_h1=%s",bool(soup.find("h1")))

    if img_tag:
        img=soup.find("img"); cap=soup.new_tag("em"); cap.string="Photo: UDF.name"
        img.insert_after(cap)

    body=hidden+img_tag+str(soup)
    payload={"title":title,"content":body,"status":"publish",
             "categories":[TARGET_CAT_ID],"tags":tags,"ping_status":"closed"}  # 🔒 핑백 차단
    r=requests.post(POSTS_API,json=payload,auth=(USER,APP_PW),timeout=30)
    logging.info("↳ 게시 %s %s",r.status_code,r.json().get("id"));
    r.raise_for_status()

# ────────── main ──────────
def main():
    logging.basicConfig(level=logging.DEBUG,
        format="%(asctime)s │ %(levelname)s │ %(message)s",datefmt="%Y-%m-%d %H:%M:%S")
    seen=sync_seen(load_seen()); links=fetch_links()
    todo=[u for u in links if norm(u) not in seen and not wp_exists(norm(u))]
    logging.info("📰 새 기사 %d / 총 %d",len(todo),len(links))
    for url in todo:
        logging.info("▶ %s",url); art=parse(url); time.sleep(1)
        if not art: continue
        try: txt=rewrite(art)
        except Exception as e: logging.warning("GPT 오류:%s",e); continue
        tag_ids=[tid for n in tag_names(txt) if (tid:=tag_id(n))]
        try: publish(art,txt,tag_ids); seen.add(norm(url)); save_seen(seen)
        except Exception as e: logging.warning("업로드 실패:%s",e)
        time.sleep(1.5)

if __name__=="__main__": main()
