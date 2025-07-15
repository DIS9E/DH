#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
udf.name.py – v4.0.0-f  (feedparser optional import + 빈 리스트 가드)
"""

__version__ = "4.0.0-f"

import os, sys, re, json, time, logging
from urllib.parse import urljoin, urlparse, urlunparse
import requests, bs4

from bs4 import BeautifulSoup

# ────────── 옵션 라이브러리 (BBC RSS) ──────────
try:
    import feedparser                    # 있으면 사용
except ModuleNotFoundError:
    feedparser = None                    # 없어도 실행 계속

# ────────── 환경 변수 ──────────
WP_URL = os.getenv("WP_URL", "https://belatri.info").rstrip("/")
USER   = os.getenv("WP_USERNAME")
APP_PW = os.getenv("WP_APP_PASSWORD")
OPENAI = os.getenv("OPENAI_API_KEY")
if not all([USER, APP_PW, OPENAI]):
    sys.exit("❌  WP_USERNAME / WP_APP_PASSWORD / OPENAI_API_KEY 누락")

POSTS_API = f"{WP_URL}/wp-json/wp/v2/posts"
TAGS_API  = f"{WP_URL}/wp-json/wp/v2/tags"

UDF_BASE  = "https://udf.name/news/"
HEADERS   = {"User-Agent": "UDFCrawler/4.0.0-f"}
SEEN_FILE = "seen_urls.json"
TARGET_CAT_ID = 20
norm = lambda u: urlunparse(urlparse(u)._replace(query="", params="", fragment=""))

# ────────── seen 관리 ──────────
def load_seen():  return set(json.load(open(SEEN_FILE))) if os.path.exists(SEEN_FILE) else set()
def save_seen(s): json.dump(list(s), open(SEEN_FILE, "w"), ensure_ascii=False, indent=2)

def wp_exists(u):
    r = requests.get(POSTS_API, params={"search": u, "per_page": 1},
                     auth=(USER, APP_PW), timeout=10)
    return r.ok and bool(r.json())

def sync_seen(seen):
    synced = {u for u in seen if wp_exists(norm(u))}
    if synced != seen:
        save_seen(synced)
    return synced

# ────────── 링크 크롤링 ──────────
def fetch_links():
    soup = BeautifulSoup(requests.get(UDF_BASE, headers=HEADERS, timeout=10).text,
                         "html.parser")
    return list({norm(urljoin(UDF_BASE, a["href"]))
                 for a in soup.select("div.article1 div.article_title_news a[href]")})

# ────────── 기사 파싱 ──────────
def parse(url):
    r = requests.get(url, headers=HEADERS, timeout=10)
    if not r.ok: return None
    s  = BeautifulSoup(r.text, "html.parser")
    t  = s.find("h1", class_="newtitle")
    b  = s.find("div", id="zooming")
    if not (t and b): return None
    img = s.find("img", class_="lazy") or s.find("img")
    return {"title": t.get_text(strip=True),
            "html": str(b),
            "image": urljoin(url, img.get("data-src") or img.get("src")) if img else None,
            "url": url}

# ────────── 외부 데이터 (환율·유가·RSS) ──────────
def build_brief():
    s = []
    # ① USD/BLR
    try:
        r = requests.get("https://api.nbrb.by/exrates/rates/431", timeout=6).json()
        s.append(f"• NBRB USD/BLR {r['Cur_OfficialRate']} ({r['Date'][:10]})")
    except Exception:
        pass
    # ② 국제 유가
    try:
        r = requests.get(
            "https://api.eia.gov/series/?api_key=DEMO_KEY&series_id=PET.RWTC.D",
            timeout=6).json()["series"][0]["data"][0]
        s.append(f"• WTI 원유 ${r[1]} (EIA {r[0]})")
    except Exception:
        pass
    # ③ BBC RSS (옵션)
    if feedparser:
        try:
            feed = feedparser.parse("https://feeds.bbci.co.uk/news/world/rss.xml")
            for ent in feed.entries[:2]:
                s.append(f"• BBC: <a href='{ent.link}'>{ent.title}</a>")
        except Exception:
            pass
    return "<br>".join(s)

# ────────── GPT 호출 래퍼 ──────────
GPT_URL = "https://api.openai.com/v1/chat/completions"
def gpt_chat(messages, model="gpt-4o-mini", temperature=0.7, max_tokens=1024):
    r = requests.post(GPT_URL,
        headers={"Authorization": f"Bearer {OPENAI}", "Content-Type": "application/json"},
        json={"model": model, "messages": messages,
              "temperature": temperature, "max_tokens": max_tokens},
        timeout=90)
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"].strip()

# ────────── 제목 한국화 ──────────
CYRILLIC = re.compile(r"[А-Яа-яЁё]")
def korean_title(src, context):
    if not CYRILLIC.search(src):
        return src
    prompt = ("기사 내용을 참고해 독자의 호기심을 끌면서도 맥락에 어울리는 "
              "한국어 제목(45자↓)을 작성하고, 관련 이모지 1–3개를 자연스럽게 넣으세요.\n\n"
              f"원제목: {src}\n기사 일부: {context[:360]}")
    return gpt_chat([{"role": "user", "content": prompt}], temperature=0.9, max_tokens=60)

# ────────── 스타일 가이드 & 리라이팅 ──────────
STYLE_GUIDE = """
• HTML 태그만 사용, 코드블록 금지
• <h1> → <h2> → <h3> 구조 유지 (📊 · 💬 · ❓)
• 원문 100 % 유지 + 추가 해설·데이터
• 제목 45자↓ 한국어 + 이모지
• Q&A 답변 2문장↑, 숫자·전망 포함
"""
def rewrite(article, brief):
    up = f"{STYLE_GUIDE}\n\n◆ 외부 데이터:\n{brief}\n\n◆ 원문:\n{article['html']}"
    return gpt_chat([{"role": "user", "content": up}], model="gpt-4o")

# ────────── 태그 처리 ──────────
STOP = {"벨라루스", "뉴스", "기사"}
def tag_names(txt):
    m = re.search(r"🏷️\s*태그[^:：]*[:：]\s*(.+)", txt)
    if not m: return []
    out=[]
    for t in re.split(r"[,\s]+", m.group(1)):
        t=t.strip("–-#•")
        if 1<len(t)<=20 and t not in STOP and t not in out:
            out.append(t)
        if len(out)==6: break
    return out

def tag_id(name):
    q = requests.get(TAGS_API, params={"search": name, "per_page": 1},
                     auth=(USER, APP_PW), timeout=10)
    if q.ok and q.json():
        return q.json()[0]["id"]
    c = requests.post(TAGS_API, json={"name": name},
                      auth=(USER, APP_PW), timeout=10)
    return c.json()["id"] if c.status_code==201 else None

# ────────── 관련 글 링크 ──────────
def related_links(tag_ids, exclude_id=0, limit=3):
    if not tag_ids: return ""
    res = requests.get(POSTS_API,
        params={"tags": tag_ids[0], "per_page": limit,
                "exclude": exclude_id, "status": "publish"},
        auth=(USER, APP_PW), timeout=10).json()
    if not isinstance(res, list) or not res:   # 빈 리스트 가드
        return ""
    lis = [f'<li><a href="{p["link"]}">{p["title"]["rendered"]}</a></li>' for p in res]
    return f"<h3>📚 관련 기사 더 보기</h3><ul>{''.join(lis)}</ul>"

# ────────── 게시 ──────────
def publish(article, txt, tag_ids):
    hidden  = f'<a href="{article["url"]}" style="display:none">src</a>\n'
    img_tag = (f'<p><img src="{article["image"]}" alt="Photo: UDF.name"></p>\n'
               if article["image"] else "")
    # 코드블록·플레이스홀더 제거
    lines=[]
    for l in txt.splitlines():
        s=l.strip()
        if s.startswith("```") or "(본문 해설)" in s or "기사 핵심" in s:
            continue
        lines.append(l)
    txt_clean="\n".join(lines)
    soup=BeautifulSoup(txt_clean,"html.parser")
    h1  = soup.find("h1")
    orig= h1.get_text(strip=True) if h1 else article["title"]
    title = korean_title(orig, soup.get_text(" ", strip=True))
    if h1: h1.decompose()

    body = hidden + img_tag + str(soup) + related_links(tag_ids)
    payload = {
        "title": title,
        "content": body,
        "status": "publish",
        "categories": [TARGET_CAT_ID],
        "tags": tag_ids,
    }
    r = requests.post(POSTS_API, json=payload, auth=(USER, APP_PW), timeout=30)
    r.raise_for_status()
    logging.info("  ↳ 게시 %s %s", r.status_code, r.json().get("id"))

# ────────── main ──────────
def main():
    logging.basicConfig(level=logging.INFO,
        format="%(asctime)s │ %(levelname)s │ %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
    logging.info("🚀 버전 %s 실행", __version__)

    seen  = sync_seen(load_seen())
    links = fetch_links()
    todo  = [u for u in links if norm(u) not in seen and not wp_exists(norm(u))]
    logging.info("📰 새 기사 %d / 총 %d", len(todo), len(links))

    brief = build_brief()

    for url in todo:
        logging.info("▶ %s", url)
        art = parse(url); time.sleep(1)
        if not art: continue

        try:
            txt = rewrite(art, brief)
        except Exception as e:
            logging.warning("GPT 오류: %s", e); continue

        tag_ids=[tid for n in tag_names(txt) if (tid:=tag_id(n))]
        try:
            publish(art, txt, tag_ids)
            seen.add(norm(url)); save_seen(seen)
        except Exception as e:
            logging.warning("업로드 실패: %s", e)

        time.sleep(1.2)

if __name__ == "__main__":
    main()
