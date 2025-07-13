#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
UDF.name → WordPress 자동 포스팅 v3.3
(이미지 본문 삽입, Yoast·태그·문체 개선)
"""

# ───────────── 기본 모듈
import os, re, json, random, logging, unicodedata
from datetime import datetime
from urllib.parse import urlparse
from typing import List, Dict, Optional

import requests
from bs4 import BeautifulSoup, NavigableString, Tag
from requests.auth import HTTPBasicAuth

# ───────────── 환경
WP_USERNAME     = os.getenv("WP_USERNAME")
WP_APP_PASSWORD = os.getenv("WP_APP_PASSWORD")
WP_API_URL      = "https://belatri.info/wp-json/wp/v2/posts"
TAG_API_URL     = "https://belatri.info/wp-json/wp/v2/tags"
OPENAI_API_KEY  = os.getenv("OPENAI_API_KEY")

UDF_BASE_URL = "https://udf.name/news/"
HEADERS      = {"User-Agent":"Mozilla/5.0 (UDF-crawler)"}
SEEN_FILE    = "seen_urls.json"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s │ %(levelname)s │ %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
log = logging.getLogger("udf")

# ───────────── 유틸
HANJA_R = re.compile(r"[\u3400-\u4DBF\u4E00-\u9FFF]+")
RUEN_R  = re.compile(r"[A-Za-zА-Яа-яЁё]")

def normalize_url(u:str)->str:
    p=urlparse(u); return f"{p.scheme}://{p.netloc}{p.path}"

def load_seen_urls()->set:
    if os.path.exists(SEEN_FILE):
        with open(SEEN_FILE,"r",encoding="utf-8") as f: return set(json.load(f))
    return set()

def save_seen_urls(s:set):
    with open(SEEN_FILE,"w",encoding="utf-8") as f:
        json.dump(sorted(list(s)),f,ensure_ascii=False,indent=2)

# ───────────── WP 중복 체크
def get_existing_source_urls(max_pages=40)->set:
    page,found=1,set()
    while page<=max_pages:
        r=requests.get(WP_API_URL,
            params={"per_page":100,"page":page,"_fields":"id,meta"},
            auth=(WP_USERNAME,WP_APP_PASSWORD))
        if r.status_code!=200 or not r.json(): break
        for p in r.json():
            u=p.get("meta",{}).get("_source_url"); 
            if u: found.add(normalize_url(u))
        page+=1
    log.info("WP _source_url %d건",len(found))
    return found

# ───────────── 링크 수집
def get_article_links()->List[str]:
    r=requests.get(UDF_BASE_URL,headers=HEADERS,timeout=15); r.raise_for_status()
    soup=BeautifulSoup(r.text,"html.parser")
    links=set()
    for a in soup.find_all("a",href=True):
        h=a["href"]
        if h.startswith("https://udf.name/news/") and h.endswith(".html"):
            links.add(normalize_url(h))
    return list(links)

# ───────────── 기사 파싱
def extract_article(url:str)->Optional[Dict]:
    try:
        r=requests.get(url,headers=HEADERS,timeout=15); r.raise_for_status()
    except Exception as e:
        log.warning("요청 실패 %s | %s",url,e); return None
    s=BeautifulSoup(r.text,"html.parser")
    title  = s.find("h1",class_="newtitle")
    author = s.find("div",class_="author")
    img    = s.find("img",class_="lazy")
    body   = s.find("div",id="zooming")

    # 본문
    lines=[]
    if body:
        for el in body.descendants:
            if isinstance(el,NavigableString):
                t=el.strip()
                if t: lines.append(t)
            elif isinstance(el,Tag) and el.name in ("p","br"): lines.append("\n")
    content="\n".join(l for l in lines if l.strip())
    content=re.sub(r"dle_leech_(begin|end)","",content).strip()

    return {
        "title":  title.get_text(strip=True) if title else "",
        "author": author.get_text(strip=True) if author else "",
        "image" : "https://udf.name"+img["data-src"] if img else "",
        "url":    url,
        "content":content
    }

# ───────────── GPT 프롬프트
PROMPT = """
너는 20–40대 한국 독자를 위한 벨라루스 전문 에디터야.

[목표]
• **직역 금지** / 정보 누락 최소화 — 원문 흐름 대부분 살리기
• 국내 독자가 클릭할 만한 **카피형 제목** (25~35자, 이모지 1개)
• `h1/h2/h3/p` HTML 태그로 레이아웃
• 한자·러시아어·중복 기호 제거
• 중간에 <img src="{image_url}"> 한 줄 삽입
• “뉴니커” 같은 브랜드 단어 쓰지 말 것
• 마무리엔 `by. 에디터 LEE🌳`

[예시 뼈대]
<h1>제목 📰</h1>
<blockquote>한 줄 편집자 주</blockquote>

<h2>포인트 요약 ✍️</h2>
<ul><li>…</li><li>…</li></ul>

<h2>현지 상황 🔍</h2>
<h3>소제목</h3><p>본문</p>

<h2>시사점 💡</h2><p>…</p>

<em>by. 에디터 LEE🌳</em>

────────────────
아래 원문을 재구성해:
{article_body}
"""

def rewrite(article:dict)->str:
    p=PROMPT.format(article_body=article["content"][:6000],
                    image_url=article["image"])
    r=requests.post("https://api.openai.com/v1/chat/completions",
        headers={"Authorization":f"Bearer {OPENAI_API_KEY}",
                 "Content-Type":"application/json"},
        json={"model":"gpt-4o","messages":[{"role":"user","content":p}],
              "temperature":0.3},timeout=90)
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"]

# ───────────── 제목·SEO
def strip_hanja(t:str)->str: return HANJA_R.sub("",t)

EMOJIS=["🚨","🌍","🇧🇾","✈️","🤔","💡"]

def catchy_title(raw:str,fallback_kw:str)->str:
    t=strip_hanja(raw)
    if RUEN_R.search(t) or len(t)<15: t=""
    if t: return t
    return f"{fallback_kw[:12]}… {random.choice(EMOJIS)}"

def focus_kw(txt:str)->str:
    kws=[w for w in re.findall(r"[가-힣]{2,6}",txt) if len(w)>=2]
    return kws[0] if kws else "벨라루스"

def slugify(t:str)->str:
    s=re.sub(r"[^\w\s-]","",unicodedata.normalize("NFKD",t))
    return re.sub(r"\s+","-",s).lower()[:90]

def meta_desc(html:str)->str:
    return re.sub(r"\s+"," ",re.sub(r"<[^>]+>","",html))[:150]

# ───────────── 태그
BASE_TAGS=["벨라루스","뉴스"]

def ensure_tags(kw:str)->List[int]:
    ids=[]
    for name in BASE_TAGS+[kw]:
        tid=requests.get(TAG_API_URL,params={"search":name}).json()
        tid=tid[0]["id"] if tid else requests.post(
            TAG_API_URL,auth=(WP_USERNAME,WP_APP_PASSWORD),
            json={"name":name}).json().get("id")
        if tid: ids.append(tid)
    return ids

# ───────────── 포스팅
def wp_post(title,content,slug,kw,meta,source,tags)->bool:
    data={
        "title":title,"content":content,"status":"publish","slug":slug,
        "tags":tags,
        "meta":{
            "_source_url":source,
            "_yoast_wpseo_focuskw":kw,
            "_yoast_wpseo_metadesc":meta,
            "_yoast_wpseo_title":title
        }
    }
    r=requests.post(WP_API_URL,json=data,
        auth=HTTPBasicAuth(WP_USERNAME,WP_APP_PASSWORD),
        headers=HEADERS,timeout=40)
    log.info("  ↳ 게시 %s %s",r.status_code,r.json().get("id"))
    return r.status_code==201

# ───────────── main
if __name__=="__main__":
    log.info("🔍 Start")
    seen=load_seen_urls()
    existing=get_existing_source_urls()
    links=get_article_links()

    targets=[u for u in links
             if normalize_url(u) not in seen and normalize_url(u) not in existing]
    log.info("업로드 %d / 총 %d",len(targets),len(links))

    ok=0
    for url in targets:
        log.info("▶ %s",url)
        art=extract_article(url);  # noqa
        if not art or not art["content"]: continue
        html=rewrite(art)

        h1=re.search(r"<h1[^>]*>(.+?)</h1>",html,re.S)
        gtitle=h1.group(1).strip() if h1 else ""
        kw=focus_kw(gtitle or art["title"] or "벨라루스")
        title=catchy_title(gtitle,kw)
        slug =slugify(title)
        meta =meta_desc(html)
        tags =ensure_tags(kw)

        if wp_post(title,html,slug,kw,meta,normalize_url(url),tags):
            ok+=1; seen.add(normalize_url(url)); save_seen_urls(seen)
    log.info("🎉 완료 %d / %d",ok,len(targets))
