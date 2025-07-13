#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
UDF.name → WordPress 자동 포스팅 스크립트
(1일 1회 Render CronJob)
────────────────────────────────────────────
■ 개선 요약
1. **중복 방지 3-단계** (seen.json · WP 메타 `_source_url` · 최근 삭제 허용)
2. **대표 이미지 업로드 옵션화** (image_id 필요 없으면 None)
3. **제목 카피라이팅 강화 + 한자 제거**
4. **Yoast SEO 필드 자동 채우기**
5. **직역 금지 프롬프트 / 러시아어 검출 보정**
6. **로깅 가독성 개선**
"""

# ──────────────────────────────────────────
# 기본 라이브러리
import os, re, json, random, logging, unicodedata
from datetime import datetime
from urllib.parse import urlparse
from typing import List, Dict, Optional

# 서드파티
import requests
from bs4 import BeautifulSoup, NavigableString, Tag
from requests.auth import HTTPBasicAuth

# ──────────────────────────────────────────
# 환경 변수
WP_USERNAME     = os.getenv("WP_USERNAME")
WP_APP_PASSWORD = os.getenv("WP_APP_PASSWORD")
WP_API_URL      = "https://belatri.info/wp-json/wp/v2/posts"
TAG_API_URL     = "https://belatri.info/wp-json/wp/v2/tags"
OPENAI_API_KEY  = os.getenv("OPENAI_API_KEY")
UDF_BASE_URL    = "https://udf.name/news/"

HEADERS = {"User-Agent":"Mozilla/5.0 (UDF-crawler)"}
SEEN_FILE = "seen_urls.json"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s │ %(levelname)s │ %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
log = logging.getLogger("udf")

# ──────────────────────────────────────────
# 유틸
def normalize_url(url: str) -> str:
    p = urlparse(url)
    return f"{p.scheme}://{p.netloc}{p.path}"

def load_seen_urls() -> set:
    if os.path.exists(SEEN_FILE):
        with open(SEEN_FILE, "r", encoding="utf-8") as f:
            return set(json.load(f))
    return set()

def save_seen_urls(urls: set):
    with open(SEEN_FILE, "w", encoding="utf-8") as f:
        json.dump(sorted(list(urls)), f, ensure_ascii=False, indent=2)

# ──────────────────────────────────────────
# WordPress 쪽 중복 검사
def get_existing_source_urls(pages:int=50) -> set:
    page, existing = 1, set()
    while page <= pages:
        r = requests.get(
            WP_API_URL,
            params={"per_page":100,"page":page,"_fields":"meta"},
            auth=(WP_USERNAME, WP_APP_PASSWORD)
        )
        if r.status_code != 200 or not r.json():
            break
        for post in r.json():
            src = post.get("meta",{}).get("_source_url")
            if src:
                existing.add(normalize_url(src))
        page+=1
    log.info("WP 저장 _source_url %d건", len(existing))
    return existing

# ──────────────────────────────────────────
# 기사 링크 수집
def get_article_links()->List[str]:
    r = requests.get(UDF_BASE_URL, headers=HEADERS, timeout=15)
    r.raise_for_status()
    soup = BeautifulSoup(r.text,"html.parser")
    links=set()
    for a in soup.find_all("a",href=True):
        href=a["href"]
        if href.startswith("https://udf.name/news/") and href.endswith(".html"):
            links.add(normalize_url(href))
    return list(links)

# ──────────────────────────────────────────
# 본문·메타 추출
def extract_article(url:str)->Optional[Dict]:
    try:
        r=requests.get(url,headers=HEADERS,timeout=15)
        r.raise_for_status()
    except Exception as e:
        log.warning("요청 실패 %s | %s", url,e); return None

    soup = BeautifulSoup(r.text,"html.parser")
    title  = soup.find("h1", class_="newtitle")
    author = soup.find("div", class_="author")
    content_block = soup.find("div", id="zooming")

    # 본문 텍스트
    lines=[]
    if content_block:
        for el in content_block.descendants:
            if isinstance(el,NavigableString):
                t=el.strip()
                if t: lines.append(t)
            elif isinstance(el,Tag) and el.name in ("p","br"): lines.append("\n")
    content="\n".join(l for l in lines if l.strip())
    content=re.sub(r"dle_leech_(begin|end)","",content).strip()

    return {
        "title": title.get_text(strip=True) if title else "",
        "author": author.get_text(strip=True) if author else "",
        "url":   url,
        "content": content
    }

# ──────────────────────────────────────────
# GPT 리라이팅
PROMPT_BASE = """
너는 20–40대 한국인을 위한 벨라루스 뉴스 칼럼니스트야.

✍️ [제목 규칙]
• 러시아어·직역 NO, **국내 독자가 클릭할 25~35자 카피**  
• 숫자·질문·대조 표현 활용, 끝에 관련 이모지 1개 붙이기  
• 한자 사용 금지

✍️ [본문·레이아웃]
<글 형식 예시>
<h1>제목 📰</h1>
<blockquote>한 줄 편집자 주 (1문장)</blockquote>

<h2>포인트 요약 ✍️</h2>
<ul>
<li>핵심 1</li><li>핵심 2</li></ul>

<h2>현지 상황 🔍</h2>
<h3>소제목</h3>
<p>…</p>

<h2>시사점 💡</h2>
<p>…</p>

<em>by. 에디터 LEE🌳</em>

────────────────
러시아어 원문 ↓
{article_body}
────────────────

⚠️ 지시
• ‘##’, ‘###’ 같은 Markdown 대신 html 태그 사용  
• 이모지를 적절히 활용  
• 요약·해석은 자유롭게, **정보 왜곡은 금지**
• 한자(漢字) 절대 사용 금지
"""

def rewrite_with_chatgpt(article:dict)->str:
    prompt = PROMPT_BASE.format(article_body=article["content"][:2500])
    headers = {
        "Authorization": f"Bearer {OPENAI_API_KEY}",
        "Content-Type":  "application/json"
    }
    payload = {
        "model":"gpt-4o",
        "messages":[{"role":"user","content":prompt}],
        "temperature":0.4
    }
    r=requests.post("https://api.openai.com/v1/chat/completions",
                    headers=headers,json=payload,timeout=60)
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"]

# ──────────────────────────────────────────
# 한자 제거·제목 보정
HANJA_R = re.compile(r"[\u3400-\u4DBF\u4E00-\u9FFF]+")
RUEN_R  = re.compile(r"[A-Za-zА-Яа-яЁё]")

TEMPLATES = [
    "○○, 진짜 노림수는? {e}",
    "벨라루스 ●● 파장 {e}",
    "왜 지금 ○○? {e}",
    "현지서 터진 ●● {e}"
]
EMOJIS = ["🚨","🌍","💡","🤔","🇧🇾","📰","✈️","⚡"]

def strip_hanja(txt:str)->str:              # 한자 제거
    return HANJA_R.sub("", txt)

def quick_ko_title(src:str)->str:           # fallback
    t = strip_hanja(src)
    t = RUEN_R.sub("", t)                   # 러·영 삭제
    t = re.sub(r"\s+"," ",t).strip()
    return (t[:30] or "벨라루스 현지 소식") + " 📰"

def ensure_catchy(title:str, kw:str)->str:
    title = strip_hanja(title or "")
    if RUEN_R.search(title) or len(title)<15 or title.endswith("."):
        title=""
    if title: return title
    tpl=random.choice(TEMPLATES)
    return tpl.replace("○○",kw[:10]).replace("●●",kw[:8]).format(e=random.choice(EMOJIS))

# ──────────────────────────────────────────
# SEO 유틸
def pick_focus_kw(text:str)->str:           # 간단 키프레이즈 추출
    words=[w for w in re.findall(r"[가-힣]{2,}", text) if len(w)<=6]
    return words[0] if words else "벨라루스"

def build_slug(title:str)->str:
    s = re.sub(r"[^\w\s]", "", unicodedata.normalize("NFKD", title))
    s = s.replace(" ","-").lower()
    return s[:90]

def make_metadesc(html:str)->str:
    txt=re.sub(r"<[^>]+>","",html)
    return re.sub(r"\s+"," ",txt)[:150]

# ──────────────────────────────────────────
# 태그 처리
def create_or_get_tag_id(name:str)->Optional[int]:
    r=requests.get(TAG_API_URL, params={"search":name})
    if r.status_code==200 and r.json():
        return r.json()[0]["id"]
    r=requests.post(TAG_API_URL,
        auth=(WP_USERNAME,WP_APP_PASSWORD),
        json={"name":name})
    return r.json().get("id") if r.status_code==201 else None

# ──────────────────────────────────────────
# 포스팅
def post_to_wordpress(*, title:str, content:str, tags:List[int],
                      slug:str, focus_kw:str, meta_desc:str, source_url:str)->bool:

    data = {
        "title":   title,
        "content": content,
        "status":  "publish",
        "slug":    slug,
        "tags":    tags,
        "meta": {
            "_source_url": source_url,
            "yoast_wpseo_focuskw": focus_kw,
            "yoast_wpseo_metadesc": meta_desc,
            "yoast_wpseo_title":    title
        }
    }
    r=requests.post(
        WP_API_URL, json=data, headers=HEADERS,
        auth=HTTPBasicAuth(WP_USERNAME, WP_APP_PASSWORD), timeout=30
    )
    log.info("  ↳ 게시 %s %s", r.status_code, r.json().get("id"))
    return r.status_code==201

# ──────────────────────────────────────────
# 메인
if __name__ == "__main__":
    log.info("🔍 UDF 크롤링 시작")
    seen = load_seen_urls()
    existing = get_existing_source_urls()
    links = get_article_links()
    log.info("🔗 메인 페이지 링크 %d개 수집", len(links))

    # 삭제된 포스트는 재업로드 허용
    targets = [u for u in links
               if normalize_url(u) not in seen and normalize_url(u) not in existing]

    log.info("⚡ 업로드 대상 %d개", len(targets))
    success=0

    for url in targets:
        log.info("===== 처리 시작: %s =====", url)
        art=extract_article(url)
        if not art or not art["content"]: continue

        html = rewrite_with_chatgpt(art)

        # 제목·SEO
        h1_match = re.search(r"<h1[^>]*>(.+?)</h1>", html, flags=re.S)
        gpt_title = h1_match.group(1).strip() if h1_match else ""
        focus_kw  = pick_focus_kw(gpt_title or art["title"])
        final_title = ensure_catchy(gpt_title, focus_kw)
        slug      = build_slug(final_title)
        meta_desc = make_metadesc(html)

        # 태그 (벨라루스 뉴스 카테고리 ID=20 포함)
        tag_ids = [20]
        kw_tag  = create_or_get_tag_id(focus_kw)
        if kw_tag: tag_ids.append(kw_tag)

        ok = post_to_wordpress(
            title=final_title,
            content=html,
            tags=tag_ids,
            slug=slug,
            focus_kw=focus_kw,
            meta_desc=meta_desc,
            source_url=normalize_url(url)
        )
        if ok:
            success+=1
            seen.add(normalize_url(url))
            save_seen_urls(seen)
        log.info("===== 처리 끝: %s =====\n", url)

    log.info("🎉 최종 성공 %d / %d", success, len(targets))
