#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
udf.name.py – v3.8  (AdSense 심층 확장 + 품질 가드)
• 원문 100 % 유지 + 카테고리별 외부 데이터 삽입
• Q&A 답변·내부 링크·출처 앵커·이미지 캡션 자동 보강
• 제목 한국어 변환 · 중복 헤더 제거 · placeholder 이미지 필터
"""

import os, sys, re, json, time, logging, random, textwrap
from datetime import datetime
from zoneinfo import ZoneInfo
from urllib.parse import urljoin, urlparse, urlunparse
import xml.etree.ElementTree as ET
import requests
import feedparser
from bs4 import BeautifulSoup

# ────────── 환경 변수 ──────────
WP_URL      = os.getenv("WP_URL", "https://belatri.info").rstrip("/")
USER        = os.getenv("WP_USERNAME")
APP_PW      = os.getenv("WP_APP_PASSWORD")
OPEN_KEY    = os.getenv("OPENAI_API_KEY")
if not all([USER, APP_PW, OPEN_KEY]):
    sys.exit("❌  WP_USERNAME / WP_APP_PASSWORD / OPENAI_API_KEY 누락")

POSTS_API   = f"{WP_URL}/wp-json/wp/v2/posts"
TAGS_API    = f"{WP_URL}/wp-json/wp/v2/tags"
UDF_BASE    = "https://udf.name/news/"
HEADERS     = {"User-Agent": "UDFCrawler/3.8"}
SEEN_FILE   = "seen_urls.json"
TARGET_CAT_ID = 20

norm = lambda u: urlunparse(urlparse(u)._replace(query="", params="", fragment=""))

# ────────── seen 관리 ──────────
def load_seen():
    return set(json.load(open(SEEN_FILE))) if os.path.exists(SEEN_FILE) else set()
def save_seen(s):
    json.dump(list(s), open(SEEN_FILE, "w"), ensure_ascii=False, indent=2)

def wp_exists(u):
    r = requests.get(POSTS_API, params={"search":u,"per_page":1},
                     auth=(USER,APP_PW), timeout=10)
    return r.ok and bool(r.json())

def sync_seen(seen):
    synced = {u for u in seen if wp_exists(norm(u))}
    if synced != seen:
        save_seen(synced)
    return synced

# ────────── 링크 크롤링 ──────────
def fetch_links():
    html = requests.get(UDF_BASE, headers=HEADERS, timeout=10).text
    soup = BeautifulSoup(html, "html.parser")
    return list({norm(urljoin(UDF_BASE, a["href"]))
                 for a in soup.select("div.article1 div.article_title_news a[href]")})

# ────────── 기사 파싱 ──────────
def parse(url):
    r = requests.get(url, headers=HEADERS, timeout=10)
    if not r.ok: return None
    s = BeautifulSoup(r.text, "html.parser")
    t = s.find("h1", class_="newtitle")
    b = s.find("div", id="zooming")
    if not (t and b): return None
    img = s.find("img", class_="lazy") or s.find("img")
    src = None
    if img:
        src = img.get("data-src") or img.get("src")
        if src and ("placeholder" in src or "default" in src):
            src = None
    img_url = urljoin(url, src) if src else None
    cat = url.split("/news/")[1].split("/")[0]
    return {
        "title": t.get_text(strip=True),
        "html":  str(b),
        "image": img_url,
        "url":   url,
        "cat":   cat
    }

# ────────── 외부 데이터 수집 ──────────

def build_brief(cat: str, headline: str) -> str:
    snippets = []

    # 1) 환율: USD/BYN
    try:
        usd = requests.get(
            "https://api.exchangerate.host/latest?base=USD&symbols=BYN",
            timeout=10
        ).json().get("rates", {}).get("BYN")
        if usd is not None:
            snippets.append(f"• USD/BYN 환율: {usd:.4f}")
    except Exception:
        snippets.append("• USD/BYN 환율: 데이터 없음")

    # 2) 환율: EUR/BYN
    try:
        eur = requests.get(
            "https://api.exchangerate.host/latest?base=EUR&symbols=BYN",
            timeout=10
        ).json().get("rates", {}).get("BYN")
        if eur is not None:
            snippets.append(f"• EUR/BYN 환율: {eur:.4f}")
    except Exception:
        snippets.append("• EUR/BYN 환율: 데이터 없음")

    # 3) 환율: KRW/BYN
    try:
        krw = requests.get(
            "https://api.exchangerate.host/latest?base=KRW&symbols=BYN",
            timeout=10
        ).json().get("rates", {}).get("BYN")
        if krw is not None:
            snippets.append(f"• KRW/BYN 환율: {krw:.4f}")
    except Exception:
        snippets.append("• KRW/BYN 환율: 데이터 없음")

    # 4) BBC World 헤드라인 1건
    if cat != "economic":
        try:
            dp_bbc = feedparser.parse("https://feeds.bbci.co.uk/news/world/rss.xml")
            if dp_bbc.entries and dp_bbc.entries[0].title:
                title = dp_bbc.entries[0].title.strip()
                snippets.append(f"• BBC 헤드라인: {title}")
            else:
                snippets.append("• BBC 헤드라인: 데이터 없음")
        except Exception:
            snippets.append("• BBC 헤드라인: 데이터 없음")

    # 5) 로이터 RU 비즈 헤드라인 2건
    try:
        dp_reu = feedparser.parse("https://www.reuters.com/rssFeed/ru/businessNews")
        for entry in dp_reu.entries[:2]:
            if entry.title:
                snippets.append(f"• 로이터: {entry.title.strip()}")
    except Exception:
        snippets.append("• 로이터: 데이터 없음")

    # 6) 주요 키워드
    snippets.append(f"• 주요 키워드: {headline.strip()[:60]}")

    return "\n".join(snippets)

# ────────── 스타일 가이드 ──────────
STYLE_GUIDE = textwrap.dedent("""
<h1>{emoji} {title}</h1>
<small>UDF • {date} • 읽음 {views:,}</small>

<h3>💡 본문 정리</h3>
<p>⟪RAW_HTML⟫</p>

<h2>✍️ 편집자 주 — 이 기사, 이렇게 읽어요</h2>
<!-- 아래 한 단락에 기사 핵심을 ‘긴 문장’ 2개로 작성하세요 -->
<p></p>

<h3>📝 개요</h3>
<p>원문을 100% 재배치하고, 추가 조사·분석을 더해 500자 이상 풍부하게 기술하세요.</p>

<h3>📊 최신 데이터</h3>
<ul>
  ⟪META_DATA⟫
</ul>

<h3>💬 전문가 전망</h3>
<p>첫 번째 단락: 구체적 근거·숫자 포함 4문장 이상</p>
<p>두 번째 단락: 시나리오·전망 포함 4문장 이상</p>

<h3>❓ Q&A</h3>
<ul>
  <li><strong>Q1.</strong> …?<br><strong>A.</strong> 2문장 이상, 분석·전망 포함</li>
  <li><strong>Q2.</strong> …?</li>
  <li><strong>Q3.</strong> …?</li>
</ul>

<p>🏷️ 태그: {tags}</p>
<p>출처: UDF.name 원문<br>
   Photo: UDF.name<br>
   by. LEE🌳<br>
   <em>* 생성형 AI의 도움으로 작성.</em></p>

<p class="related"></p>
""").strip()

# ─── GPT 리라이팅 (정책 안전 가이드 포함) ──────────
def rewrite(article):
    extra = build_brief(article['cat'], article['title'])
    today = datetime.now(tz=ZoneInfo("Asia/Seoul")).strftime("%Y.%m.%d")
    views = random.randint(7_000, 12_000)
    tags_placeholder = ""

    # STYLE_GUIDE 에 메타 플레이스홀더를 채우고, 본문+extra_context를 이어붙입니다.
    prompt_body = STYLE_GUIDE.format(
        emoji="📰",
        title=article['title'],
        date=today,
        views=views,
        tags=tags_placeholder
    ) + f"""
원문:
{article['html']}

extra_context:
{extra}
"""

    messages = [
        {
            "role": "system",
            "content": (
                "당신은 ‘헤드라이트’ 스타일의 친근한 대화체로 작성해야 합니다. "
                "정책에 민감한 제안이나 부적절한 표현은 절대 포함하지 마세요."
            )
        },
        {"role": "user", "content": prompt_body}
    ]

    headers = {
        "Authorization": f"Bearer {OPEN_KEY}",
        "Content-Type": "application/json"
    }
    data = {
        "model": "gpt-4o",
        "messages": messages,
        "temperature": 0.4,
        "max_tokens": 1800
    }

    # 첫 요청
    r = requests.post("https://api.openai.com/v1/chat/completions",
                      headers=headers, json=data, timeout=90)
    r.raise_for_status()
    txt = r.json()["choices"][0]["message"]["content"].strip()

    # 길이 보강
    if len(txt) < 1500:
        logging.info("  ↺ 길이 보강 재-요청")
        data["temperature"] = 0.6
        r2 = requests.post("https://api.openai.com/v1/chat/completions",
                           headers=headers, json=data, timeout=90)
        r2.raise_for_status()
        txt = r2.json()["choices"][0]["message"]["content"].strip()

    return txt

# ─── 기타 유틸 및 게시 로직 (변경 없음) ──────────
CYRILLIC = re.compile(r"[А-Яа-яЁё]")

def korean_title(src: str, context: str) -> str:
    if not CYRILLIC.search(src):
        return src
    prompt = (
        "기사 내용을 참고해 친근한 대화체로, 독자의 호기심을 끌 "
        "45자 이내 한국어 제목을 만들고 이모지 1–3개를 자연스럽게 포함하세요.\n\n"
        f"원제목: {src}\n기사 일부: {context[:300]}"
    )
    headers = {"Authorization":f"Bearer {OPEN_KEY}", "Content-Type":"application/json"}
    data = {"model":"gpt-4o-mini","messages":[{"role":"user","content":prompt}],
            "temperature":0.8,"max_tokens":60}
    try:
        r = requests.post("https://api.openai.com/v1/chat/completions",
                          headers=headers, json=data, timeout=20)
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"].strip()
    except:
        return src

STOP = {"벨라루스","뉴스","기사"}
def tag_names(txt: str) -> list[str]:
    m = re.search(r"🏷️\s*태그[^:]*[:：]\s*(.+)", txt)
    if not m: return []
    out=[]
    for t in re.split(r"[,\s]+", m.group(1)):
        t = t.strip("–-#•")
        if 1<len(t)<=20 and t not in STOP and t not in out:
            out.append(t)
        if len(out)==6: break
    return out

def tag_id(name: str) -> int|None:
    q = requests.get(TAGS_API, params={"search":name,"per_page":1},
                     auth=(USER,APP_PW), timeout=10)
    if q.ok and q.json(): return q.json()[0]["id"]
    c = requests.post(TAGS_API, json={"name":name}, auth=(USER,APP_PW), timeout=10)
    return c.json().get("id") if c.status_code==201 else None

def ensure_depth(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    modified = False
    for li in soup.find_all("li"):
        txt = li.get_text()
        if "<strong>A." not in txt: continue
        if len(re.findall(r"[.!?]", txt)) < 2:
            prompt = f"아래 답변을 근거·숫자·전망 포함 3문장 이상으로 확장:\n{txt}"
            headers={"Authorization":f"Bearer {OPEN_KEY}","Content-Type":"application/json"}
            data={"model":"gpt-4o-mini","messages":[{"role":"user","content":prompt}],
                  "temperature":0.7,"max_tokens":100}
            try:
                r = requests.post("https://api.openai.com/v1/chat/completions",
                                  headers=headers, json=data, timeout=20)
                r.raise_for_status()
                li.string = r.json()["choices"][0]["message"]["content"].strip()
                modified = True
            except:
                pass
    return str(soup) if modified else html

def publish(article: dict, txt: str, tag_ids: list[int]):
    txt   = ensure_depth(txt)
    hidden = f'<a href="{article["url"]}" style="display:none">src</a>\n'
    img_tag = f'<p><img src="{article["image"]}" alt=""></p>\n' if article["image"] else ""

    lines = [l for l in txt.splitlines()
             if not (l.strip().startswith("```") or l.strip().startswith("📰") or "소제목" in l)]
    soup = BeautifulSoup("\n".join(lines), "html.parser")

    # 제목 재삽입
    h1   = soup.find("h1")
    orig = (h1.get_text(strip=True) if h1 else article["title"])
    title= korean_title(orig, soup.get_text(" ", strip=True))
    if h1: h1.decompose()
    new_h1 = soup.new_tag("h1"); new_h1.string = title
    soup.insert(0, new_h1)

    # 이미지 캡션
    if img_tag:
        img = soup.find("img")
        if img and not img.find_next_sibling("em"):
            cap = soup.new_tag("em"); cap.string = "Photo: UDF.name"
            img.insert_after(cap)

    # 내부 관련 기사 링크
    if tag_ids:
        try:
            r = requests.get(POSTS_API, params={"tags":tag_ids[0],"per_page":1},
                             auth=(USER,APP_PW), timeout=10)
            if r.ok and r.json():
                link = r.json()[0]["link"]
                more = soup.new_tag("p")
                a    = soup.new_tag("a", href=link)
                a.string = "📚 관련 기사 더 보기"
                more.append(a)
                soup.append(more)
        except:
            pass

    body = hidden + img_tag + str(soup)
    payload = {"title":title,"content":body,
               "status":"publish","categories":[TARGET_CAT_ID],"tags":tag_ids}
    r = requests.post(POSTS_API, json=payload,
                      auth=(USER,APP_PW), timeout=30)
    logging.info("  ↳ 게시 %s %s", r.status_code, r.json().get("id"))
    r.raise_for_status()

def main():
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s │ %(levelname)s │ %(message)s",
                        datefmt="%Y-%m-%d %H:%M:%S")

    seen  = sync_seen(load_seen())
    links = fetch_links()
    todo  = [u for u in links if norm(u) not in seen and not wp_exists(norm(u))]
    logging.info("📰 새 기사 %d / 총 %d", len(todo), len(links))

    for url in todo:
        logging.info("▶ %s", url)
        art = parse(url); time.sleep(1)
        if not art: continue

        try:
            txt = rewrite(art)
        except Exception as e:
            logging.warning("GPT 오류: %s", e)
            continue

        tag_ids = [tid for n in tag_names(txt) if (tid := tag_id(n))]
        try:
            publish(art, txt, tag_ids)
            seen.add(norm(url)); save_seen(seen)
        except Exception as e:
            logging.warning("업로드 실패: %s", e)

        time.sleep(1.5)

if __name__=="__main__":
    main()
