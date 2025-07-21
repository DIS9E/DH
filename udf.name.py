#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
udf.name.py – v1.1 
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
from requests.exceptions import RequestException

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
    try:
        resp = requests.get(UDF_BASE, headers=HEADERS, timeout=15)  # 타임아웃 15초로 연장
        resp.raise_for_status()
        html = resp.text
    except RequestException as e:
        logging.warning("링크 크롤링 실패: %s", e)
        return []  # 실패 시 빈 리스트 반환

    soup = BeautifulSoup(html, "html.parser")
    return list({
        norm(urljoin(UDF_BASE, a["href"]))
        for a in soup.select("div.article1 div.article_title_news a[href]")
    })

# ────────── 기사 파싱 ──────────
def parse(url):
    try:
        r = requests.get(url, headers=HEADERS, timeout=10)
        r.raise_for_status()
    except RequestException as e:
        logging.warning("파싱 실패(%s): %s", url, e)
        return None

    s = BeautifulSoup(r.text, "html.parser")
    t = s.find("h1", class_="newtitle")
    b = s.find("div", id="zooming")
    if not (t and b):
        return None

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

    # 1) BYN 기준으로 각 통화 한 번에 불러오기
    try:
        resp = requests.get(
            "https://api.exchangerate.host/latest",
            params={"base": "BYN", "symbols": "USD,EUR,KRW"},
            timeout=10
        )
        resp.raise_for_status()
        rates = resp.json().get("rates", {})

        usd = rates.get("USD")
        eur = rates.get("EUR")
        krw = rates.get("KRW")

        if usd is not None:
            snippets.append(f" 🇺🇸 1달러 = {1/usd:.4f} BYN")
        if eur is not None:
            snippets.append(f" 🇪🇺 1유로 = {1/eur:.4f} BYN")
        if krw is not None:
            snippets.append(f" 🇰🇷 1,000원 = {1000/krw:.4f} BYN")
    except Exception:
        # 환율 수집 실패 시, 아무 항목도 추가하지 않습니다.
        pass

    # 2) BBC World 헤드라인 1건
    if cat != "economic":
        try:
            dp = feedparser.parse("https://feeds.bbci.co.uk/news/world/rss.xml")
            title = dp.entries[0].title.strip()
            snippets.append(f" 🇬🇧 BBC 헤드라인: {title}")
        except Exception:
            snippets.append(" 🇬🇧 BBC 헤드라인: 데이터 없음")

    # 3) 주요 키워드
    snippets.append(f" 🌐 주요 키워드: {headline.strip()[:60]}")

    # <li> 태그로 감싸서 반환
    return "\n".join(f"<li>{s}</li>" for s in snippets)

# ────────── 스타일 가이드 ──────────
STYLE_GUIDE = textwrap.dedent("""
<h1>{title}</h1>
<small>UDF • {date} • 읽음 {views:,}</small>

<h3>💡 본문 정리</h3>
<p>⟪RAW_HTML⟫</p>

<h2>✍️ 편집자 주 — 이 기사, 이렇게 읽어요</h2>
<!-- 아래 한 단락에 기사 핵심을 ‘긴 문장’ 2개로 작성하세요 -->
<p></p>

<h3>📝 개요</h3>
<p>원문을 100% 재배치하고, 추가 조사·분석을 더해 500자 이상 풍부하게 기술하세요.</p>

[gpt_latest_data]

<h3>💬 전문가 전망</h3>
<p>첫 번째 단락: 구체적 근거·숫자 포함 4문장 이상</p>
<p>두 번째 단락: 시나리오·전망 포함 4문장 이상</p>

[gpt_related_qna]

<p>🏷️ 태그: {tags}</p>
<p>출처: UDF.name 원문<br>
   Photo: UDF.name<br>
   by. LEE🌳<br>
   <em>* 생성형 AI의 도움으로 작성.</em></p>

<p class="related"></p>
""").strip()

# ─── GPT 리라이팅 (정책 안전 + 메타데이터 삽입) ──────────
def rewrite(article):
    extra            = build_brief(article['cat'], article['title'])
    today            = datetime.now(tz=ZoneInfo("Asia/Seoul")).strftime("%Y.%m.%d")
    views            = random.randint(7_000, 12_000)
    tags_placeholder = ""

    # 1) META_DATA 리스트 항목 생성
    meta_items = "\n".join(f"<li>{line}</li>" for line in extra.split("\n"))

    # 2) STYLE_GUIDE의 플레이스홀더({emoji},{title} 등)만 먼저 채워서 'filled'에 담기
    filled = STYLE_GUIDE.format(
        emoji="📰",
        title=article["title"],
        date=today,
        views=views,
        tags=tags_placeholder
    )

    # 3) RAW_HTML·META_DATA 플레이스홀더 치환 및 원문/extra_context 덧붙이기
    prompt_body = (
        filled
        .replace("⟪RAW_HTML⟫", article["html"])
        .replace("⟪META_DATA⟫", meta_items)
        + f"""

원문:
{article["html"]}

extra_context:
{extra}
"""
    )

    # ─── GPT 호출 준비 ──────────
    messages = [
        {
            "role": "system",
            "content": (
                "당신은 ‘헤드라이트’ 뉴스레터의 톤과 문체를 100% 따라야 합니다.\n"
                "– 친근한 대화체로, 문장마다 ‘~요’, ‘~죠’, ‘~네요?’ 같은 종결어미를 꼭 넣고, “?”와 “!”를 섞어 질문과 감탄을 자연스럽게 사용하세요.\n"
                "– 묵직한 설명문체 대신, 독자에게 말을 건네듯 생동감 있게 써야 합니다.\n"
                "– 무례하거나 부적절한 표현은 절대 쓰지 마세요.\n"
                "– 정책에 민감한 단어나 부적절한 표현도 포함하지 마세요.\n\n"
                "**📊 최신 데이터 섹션은 숏코드로 대체합니다.**\n"
                "**❓ Q&A 섹션은 숏코드로 대체합니다.**\n"
                "`[gpt_related_qna]`\n\n"
                "**※ 반드시 STYLE_GUIDE 순서대로 아래 헤더 블록을 모두 포함해야 합니다.**\n"
                "    - `<h1>…</h1>`\n"
                "    - `<small>…</small>`\n"
                "    - `<h3>💡 본문 정리</h3>`\n"
                "    - `<h2>✍️ 편집자 주 …</h2>`\n"
                "    - `<h3>📝 개요</h3>`\n"
                "    - `<h3>📊 최신 데이터</h3>` + `<ul>…</ul>`\n"
                "    - `<h3>💬 전문가 전망</h3>`\n"
                "    - `[gpt_related_qna]`\n"
                "    - `<p>🏷️ 태그: …</p>`\n"
                "    - `<p>출처: …</p>`\n"
                "    - `<p class=\"related\"></p>`"
            )
        },
        {
            "role": "user",
            "content": prompt_body
        }
    ]

    headers = {
        "Authorization": f"Bearer {OPEN_KEY}",
        "Content-Type":  "application/json"
    }

    data = {
        "model":       "gpt-4o",
        "messages":    messages,
        "temperature": 0.4,
        "max_tokens":  1800
    }

    # 4) 첫 요청
    r = requests.post(
        "https://api.openai.com/v1/chat/completions",
        headers=headers,
        json=data,
        timeout=90
    )
    r.raise_for_status()
    txt = r.json()["choices"][0]["message"]["content"].strip().replace("**", "")

    # 5) 길이 보강
    if len(txt) < 1500:
        logging.info("  ↺ 길이 보강 재-요청")
        data["temperature"] = 0.6
        r2 = requests.post(
            "https://api.openai.com/v1/chat/completions",
            headers=headers,
            json=data,
            timeout=90
        )
        r2.raise_for_status()
        txt = r2.json()["choices"][0]["message"]["content"].strip().replace("**", "")

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

# ─── 게시 전 헤더 변환/필터링 & 게시 로직 ──────────
def publish(article: dict, txt: str, tag_ids: list[int]):
    # 1) Q&A 깊이 보강 유지
    txt = ensure_depth(txt)

    # 2) 원본 URL 숨김 + 대표 이미지 태그
    hidden  = f'<a href="{article["url"]}" style="display:none">src</a>\n'
    img_tag = f'<p><img src="{article["image"]}" alt=""></p>\n' if article["image"] else ""

    # 3) Markdown 헤더(#, ##, ###)를 HTML <h1>-<h3>로 변환하고
    #    코드블록, 기존 📰 헤더, '소제목' 주석은 제거
    lines = []
    for line in txt.splitlines():
        s = line.lstrip()

        # (가) 제거할 패턴
        if s.startswith("```") or s.startswith("📰") or "소제목" in s:
            continue

        # (나) Markdown 헤더 → HTML 헤더
        m = re.match(r'^(#{1,6})\s*(.*)$', s)
        if m:
            level   = min(len(m.group(1)), 3)       # 최대 h3
            content = m.group(2).strip()
            lines.append(f"<h{level}>{content}</h{level}>")
            continue

        # (다) 일반 문장
        lines.append(line)

    # 4) BeautifulSoup으로 다시 파싱
    soup = BeautifulSoup("\n".join(lines), "html.parser")

    # 5) 제목 재삽입 (korean_title 변환 포함)
    h1   = soup.find("h1")
    orig = h1.get_text(strip=True) if h1 else article["title"]
    title= korean_title(orig, soup.get_text(" ", strip=True))
    if h1:
        h1.decompose()
    new_h1 = soup.new_tag("h1")
    new_h1.string = title
    soup.insert(0, new_h1)

    # 6) 이미지 캡션
    if img_tag:
        img = soup.find("img")
        if img and not img.find_next_sibling("em"):
            cap = soup.new_tag("em")
            cap.string = "Photo: UDF.name"
            img.insert_after(cap)

    # 7) 내부 관련 기사 링크 삽입
    if tag_ids:
        try:
            r = requests.get(
                POSTS_API,
                params={"tags": tag_ids[0], "per_page": 1},
                auth=(USER, APP_PW),
                timeout=10
            )
            if r.ok and r.json():
                link = r.json()[0]["link"]
                more = soup.new_tag("p")
                a    = soup.new_tag("a", href=link)
                a.string = "📚 관련 기사 더 보기"
                more.append(a)
                soup.append(more)
        except:
            pass

    # 8) 최종 게시 (한 번만 호출)
    body = hidden + img_tag + str(soup)
    payload = {
        "title":      title,
        "content":    body,
        "status":     "publish",
        "categories": [TARGET_CAT_ID],
        "tags":       tag_ids
    }
    r = requests.post(POSTS_API, json=payload, auth=(USER, APP_PW), timeout=30)
    logging.info("  ↳ 게시 %s %s", r.status_code, r.json().get("id"))
    r.raise_for_status()
def main():
    logging.basicConfig(
        level=logging.INFO,
        stream=sys.stdout,                        # ← STDERR 대신 STDOUT으로
        format="%(asctime)s │ %(levelname)s │ %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )

    seen  = sync_seen(load_seen())
    links = fetch_links()
    todo  = [u for u in links if norm(u) not in seen and not wp_exists(norm(u))]
    logging.info("📰 새 기사 %d / 총 %d", len(todo), len(links))

    for url in todo:
        logging.info("▶ %s", url)
        art = parse(url)
        time.sleep(1)
        if not art:
            continue

        try:
            txt = rewrite(art)
        except Exception as e:
            logging.warning("GPT 오류: %s", e)
            continue

        tag_ids = [tid for n in tag_names(txt) if (tid := tag_id(n))]
        try:
            publish(art, txt, tag_ids)
            seen.add(norm(url))
            save_seen(seen)
        except Exception as e:
            logging.warning("업로드 실패: %s", e)

        time.sleep(1.5)

if __name__ == "__main__":
    main()
