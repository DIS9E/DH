#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
udf.name.py – v1.1.1  (📊 동적 메타데이터 패치)
• 원문 100 % 유지 + 기사별 ‘최신 데이터’ 5줄 자동 생성
• Q&A·내부 링크·출처 앵커·이미지 캡션 자동 보강
• 제목 한국어 변환 · 중복 헤더 제거 · placeholder 이미지 필터
"""

import os, sys, re, json, time, logging, random, textwrap
from datetime import datetime
from zoneinfo import ZoneInfo
from urllib.parse import urljoin, urlparse, urlunparse
import requests, feedparser
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
    try:
        resp = requests.get(UDF_BASE, headers=HEADERS, timeout=15)
        resp.raise_for_status()
        html = resp.text
    except RequestException as e:
        logging.warning("링크 크롤링 실패: %s", e)
        return []
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
def dynamic_bullets(title: str, html: str) -> str:
    """
    기사 주제와 직결된 ‘📊 최신 데이터’ 5줄 반환
      • [이모지] 설명: 숫자/기간/비율 (출처: …, 연도)
      • 숫자만 나열 X → 한 문장 맥락 필수
      • 기사와 무관한 항목·출처 불명 항목은 작성 금지
    """
    sys_prompt = (
        "너는 데이터 저널리스트야. 아래 기사 제목과 본문을 참고해 "
        "해당 주제와 직접 관련된 ‘추가 데이터’ 5줄을 작성해. 형식은:\n"
        "• [이모지] 간결한 설명: 숫자·기간/비율 (출처: 기관·언론, 연도)\n\n"
        "규칙:\n"
        "1) 각 줄 45자 이내.\n"
        "2) 숫자·기간·비율 필수, 단순 건수 나열 금지.\n"
        "3) 서로 다른 출처 사용 권장, 출처 불명 시 그 줄 생략.\n"
        "4) 최대 5줄, 부족하면 가능한 만큼만.\n"
        "5) 기사와 무관한 데이터 넣지 말 것."
    )
    user_prompt = f"<제목>\n{title}\n\n<본문 일부>\n{html[:3500]}"
    headers = {"Authorization": f"Bearer {OPEN_KEY}", "Content-Type": "application/json"}
    data = {
        "model": "gpt-4o-mini",
        "messages": [
            {"role": "system", "content": sys_prompt},
            {"role": "user",   "content": user_prompt}
        ],
        "temperature": 0.35,
        "max_tokens": 320
    }
    try:
        r = requests.post("https://api.openai.com/v1/chat/completions",
                          headers=headers, json=data, timeout=60)
        r.raise_for_status()
        lines = [ln.lstrip("• ").strip() for ln in
                 r.json()["choices"][0]["message"]["content"].splitlines()
                 if ln.strip()]
        return "\n".join(f"<li>{ln}</li>" for ln in lines[:5]) or "<li>데이터 부족</li>"
    except Exception as e:
        logging.warning("📊 데이터 생성 실패: %s", e)
        return "<li>데이터 부족</li>"
        
def build_brief(cat_unused: str, headline: str, raw_html: str | None = None) -> str:
    """
    rewrite() 호출 호환용 래퍼. cat 인자는 더 이상 사용하지 않음.
    """
    return dynamic_bullets(headline, raw_html or "")   # ← 함수 종료

# ────────── 출력 검증 ──────────
REQ_HEADERS = [
    "<h1>", "<small>", "💡 본문 정리", "✍️ 편집자 주", "📝 개요",
    "📊 최신 데이터", "💬 전문가 전망", "[gpt_related_qna]", "🏷️ 태그", "출처:"
]

def validate_blocks(txt: str) -> bool:
    ok = sum(h in txt for h in REQ_HEADERS)
    return ok >= 8          # 10개 → 8개 이상이면 통과
    
# ────────── 스타일 가이드 ──────────
STYLE_GUIDE = textwrap.dedent("""
<h1>{title}</h1>
<small>UDF • {date} • 읽음 {views:,}</small>

<h3>💡 본문 정리</h3>
<p>⟪RAW_HTML⟫</p>

<h2>✍️ 편집자 주 — 이 기사, 이렇게 읽어요</h2>
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

[gpt_related_qna]

<p>🏷️ 태그: {tags}</p>
<p>출처: UDF.name 원문<br>
   Photo: UDF.name<br>
   by. LEE🌳<br>
   <em>* 생성형 AI의 도움으로 작성.</em></p>

<p class="related"></p>
""").strip()

# ─── GPT 리라이팅 ──────────
def rewrite(article):
    extra  = build_brief(article['cat'], article['title'], article['html'])
    today  = datetime.now(tz=ZoneInfo("Asia/Seoul")).strftime("%Y.%m.%d")
    views  = random.randint(7_000, 12_000)

    filled = (
        STYLE_GUIDE.format(
            emoji="📰", title=article["title"], date=today, views=views, tags=""
        )
        .replace("⟪RAW_HTML⟫", article["html"])
        .replace("⟪META_DATA⟫", extra)
    )

    base_system = (
        "당신은 ‘헤드라이트’ 뉴스레터 편집봇입니다.\n"
        "◆ STYLE_GUIDE 순서·태그를 1px도 바꾸면 안 됩니다.\n"
        "◆ <h1> 제목 중복 출력 금지 (이미 포함돼 있음).\n"
        "◆ 📊 최신 데이터는 그대로 두고 수정/삭제/재정렬 금지.\n"
        "◆ Q&A는 `[gpt_related_qna]` 그대로 남겨야 합니다.\n"
        "◆ 남은 영역에 친근한 대화체로 600–800자 보강.\n"
        "◆ 무례·정책 민감 표현 금지.\n"
        "◆ 누락이 잦은 블록 힌트: `<p>🏷️ 태그:`, `<p>출처:`, `[gpt_related_qna]` — 반드시 포함하세요."
    )

    def gpt_call(temp: float) -> str:
        headers = {"Authorization": f"Bearer {OPEN_KEY}", "Content-Type": "application/json"}
        data = {
            "model": "gpt-4o",
            "messages": [
                {"role": "system", "content": base_system},
                {"role": "user",   "content": filled}
            ],
            "temperature": temp,
            "max_tokens": 1800
        }
        r = requests.post("https://api.openai.com/v1/chat/completions",
                          headers=headers, json=data, timeout=90)
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"].strip().replace("**", "")

    # ① 1차 생성
    txt = gpt_call(0.35)

    # ② 구조 검증 → 재시도 1회
    if not validate_blocks(txt):
        logging.info("  ↺ 구조 누락 → 재요청")
        txt = gpt_call(0.25)

    # ③ 여전히 누락이면 최소 골격 패치
    if not validate_blocks(txt):
        logging.warning("  ⚠️ 최종 구조 미준수 → 패치 모드")
        if "[gpt_related_qna]" not in txt:
            txt += "\n[gpt_related_qna]"
        if "🏷️ 태그:" not in txt:
            txt += "\n<p>🏷️ 태그: </p>"
        if "출처:" not in txt:
            txt += "\n<p>출처: UDF.name 원문</p>"

    return txt

# ─── 기타 유틸·게시 로직 (변경 없음) ──────────
CYRILLIC = re.compile(r"[А-Яа-яЁё]")

def korean_title(src: str, context: str) -> str:
    if not CYRILLIC.search(src):
        return src
    prompt = (
        "기사 내용을 참고해 친근한 대화체로, 독자의 호기심을 끌 "
        "45자 이내 한국어 제목을 만들고 이모지 1–3개를 자연스럽게 포함하세요.\n\n"
        f"원제목: {src}\n기사 일부: {context[:300]}"
    )
    headers = {"Authorization": f"Bearer {OPEN_KEY}", "Content-Type": "application/json"}
    data = {"model": "gpt-4o-mini", "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.8, "max_tokens": 60}
    try:
        r = requests.post("https://api.openai.com/v1/chat/completions",
                          headers=headers, json=data, timeout=20)
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"].strip()
    except:
        return src

STOP = {"벨라루스", "뉴스", "기사"}

def tag_names(txt: str) -> list[str]:
    m = re.search(r"🏷️\s*태그[^:]*[:：]\s*(.+)", txt)
    if not m:
        return []
    out = []
    for t in re.split(r"[,\s]+", m.group(1)):
        t = t.strip("–-#•")
        if 1 < len(t) <= 20 and t not in STOP and t not in out:
            out.append(t)
        if len(out) == 6:
            break
    return out

def tag_id(name: str) -> int | None:
    q = requests.get(TAGS_API, params={"search": name, "per_page": 1},
                     auth=(USER, APP_PW), timeout=10)
    if q.ok and q.json():
        return q.json()[0]["id"]
    c = requests.post(TAGS_API, json={"name": name},
                      auth=(USER, APP_PW), timeout=10)
    return c.json().get("id") if c.status_code == 201 else None

def ensure_depth(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    modified = False
    for li in soup.find_all("li"):
        txt = li.get_text()
        if "<strong>A." not in txt:
            continue
        if len(re.findall(r"[.!?]", txt)) < 2:
            prompt = f"아래 답변을 근거·숫자·전망 포함 3문장 이상으로 확장:\n{txt}"
            headers = {"Authorization": f"Bearer {OPEN_KEY}", "Content-Type": "application/json"}
            data = {"model": "gpt-4o-mini", "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.7, "max_tokens": 100}
            try:
                r = requests.post("https://api.openai.com/v1/chat/completions",
                                  headers=headers, json=data, timeout=20)
                r.raise_for_status()
                li.string = r.json()["choices"][0]["message"]["content"].strip()
                modified = True
            except:
                pass
    return str(soup) if modified else html

# ─── 게시 로직 (변경 없음) ──────────
def publish(article: dict, txt: str, tag_ids: list[int]):
    txt = ensure_depth(txt)
    hidden = f'<a href="{article["url"]}" style="display:none">src</a>\n'
    img_tag = f'<p><img src="{article["image"]}" alt=""></p>\n' if article["image"] else ""

    lines = []
    for line in txt.splitlines():
        s = line.lstrip()
        if s.startswith("```") or s.startswith("📰") or "소제목" in s:
            continue
        m = re.match(r"^(#{1,6})\s*(.*)$", s)
        if m:
            level = min(len(m.group(1)), 3)
            content = m.group(2).strip()
            lines.append(f"<h{level}>{content}</h{level}>")
            continue
        lines.append(line)

    soup = BeautifulSoup("\n".join(lines), "html.parser")
    h1 = soup.find("h1")
    orig = h1.get_text(strip=True) if h1 else article["title"]
    title = korean_title(orig, soup.get_text(" ", strip=True))
    if h1:
        h1.decompose()
    new_h1 = soup.new_tag("h1")
    new_h1.string = title
    soup.insert(0, new_h1)

    if img_tag:
        img = soup.find("img")
        if img and not img.find_next_sibling("em"):
            cap = soup.new_tag("em")
            cap.string = "Photo: UDF.name"
            img.insert_after(cap)

    if tag_ids:
        try:
            r = requests.get(POSTS_API,
                             params={"tags": tag_ids[0], "per_page": 1},
                             auth=(USER, APP_PW), timeout=10)
            if r.ok and r.json():
                link = r.json()[0]["link"]
                more = soup.new_tag("p")
                a = soup.new_tag("a", href=link)
                a.string = "📚 관련 기사 더 보기"
                more.append(a)
                soup.append(more)
        except:
            pass

    body = hidden + img_tag + str(soup)
    payload = {
        "title": title,
        "content": body,
        "status": "publish",
        "categories": [TARGET_CAT_ID],
        "tags": tag_ids
    }
    r = requests.post(POSTS_API, json=payload, auth=(USER, APP_PW), timeout=30)
    logging.info("  ↳ 게시 %s %s", r.status_code, r.json().get("id"))
    r.raise_for_status()

# ─── 메인 ──────────
def main():
    logging.basicConfig(
        level=logging.INFO,
        stream=sys.stdout,
        format="%(asctime)s │ %(levelname)s │ %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )

    seen = sync_seen(load_seen())
    links = fetch_links()
    todo = [u for u in links if norm(u) not in seen and not wp_exists(norm(u))]
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
