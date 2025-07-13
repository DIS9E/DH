#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
udf.name.py – v3.6.1b  (제목 한국어·중복 헤더·코드블록·이모지 개선)
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
HEADERS    = {"User-Agent": "UDFCrawler/3.6.1b"}
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
    return {"title":t.get_text(strip=True),
            "html":str(b),
            "image":urljoin(url, img.get("data-src") or img.get("src")) if img else None,
            "url":url}

# ────────── 스타일 가이드 ──────────
STYLE_GUIDE = """
• 구조 (반드시 HTML 태그 사용)
  <h1>📰 (관련 이모지 1–3개) 흥미로운 한국어 제목</h1>
  <h2>✍️ 편집자 주 — 맥락 2문장</h2>
  <h3>(소제목)</h3>
    본문 …
  <h3>(다음 소제목)</h3>
    본문 …
  <p>🏷️ 태그: 명사 3~6개</p>
  <p>이 기사는 벨라루스 현지 보도 내용을 재구성한 콘텐츠입니다.<br>
     by. 에디터 LEE🌳</p>

• 코드블록, `소제목 1/2` 같은 템플릿 문구 금지.
• 제목은 전부 한국어·기사 분위기에 맞는 이모지(1–3개) 포함·45자 이내.
• 내용 요약·삭제 금지(원문 길이 100% 유지). 톤: 친근한 대화체·질문·감탄.
"""

# ── GPT 리라이팅 ──
def rewrite(article):
    prompt=f"{STYLE_GUIDE}\n\n◆ 원문:\n{article['html']}"
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
    if not CYRILLIC.search(src): return src  # 이미 한글이면 그대로
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

    # 1) 코드블록 울타리(``` 라인)와 📰 -라인, ‘소제목 1/2’ 플레이스홀더 제거
    import re
    lines = []
    for l in txt.splitlines():
        stripped = l.strip()
        if stripped.startswith("```"):             # 울타리 라인만 스킵, 내용은 유지
            continue
        if stripped.startswith("📰") or stripped.startswith("소제목"):
            continue
        lines.append(l)
    txt_clean = "\n".join(lines)

    # 2) HTML 파싱
    soup = BeautifulSoup(txt_clean, "html.parser")

    # 3) 포스트 제목 결정 → 러시아어라면 한국어+맞춤 이모지 변환
    h1_tag = soup.find("h1")
    orig_title = h1_tag.get_text(strip=True) if h1_tag else article["title"]
    context_txt = soup.get_text(" ", strip=True)
    title = korean_title(orig_title, context_txt)

    # 4) 본문에 남은 <h1> 제거(중복 방지)
    if h1_tag:
        h1_tag.decompose()

    body = hidden + img_tag + str(soup)

    payload = {
        "title": title,
        "content": body,
        "status": "publish",
        "categories": [TARGET_CAT_ID],
        "tags": tag_ids,
    }
    r = requests.post(POSTS_API, json=payload, auth=(USER, APP_PW), timeout=30)
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
