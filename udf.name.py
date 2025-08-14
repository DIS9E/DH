#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
udf.name.py – v1.2
• 원문 100 % 유지 + 카테고리별 외부 데이터 삽입
• Q&A 답변·내부 링크·출처 앵커·이미지 캡션 자동 보강
• 제목 한국어 변환 · 중복 헤더 제거 · placeholder 이미지 필터
"""

import os, sys, re, json, time, logging, random, textwrap
from yoast_meta import generate_meta, push_meta
from datetime import datetime
from zoneinfo import ZoneInfo
from urllib.parse import urljoin, urlparse, urlunparse
import xml.etree.ElementTree as ET
import requests
import feedparser
from bs4 import BeautifulSoup
from requests.exceptions import RequestException


# ────────── 벨라루스 관련성 검사 ──────────
BELARUS_KEYWORDS = [
    # 국가·수도·도시
    "belarus", "беларус", "벨라루스",
    "минск", "мiнск", "міnsk",
    "брест", "гродно", "витебск", "могилев", "гомель",
    # 인물
    "лукашенко", "lukashenko", "루카셴코"
]

def is_belarus_related(text: str) -> bool:
    low = text.lower()
    return any(k in low for k in BELARUS_KEYWORDS)
    
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
        logging.debug("  🔴 구조 불일치 스킵: %s", url)
        return None

    # ── 1) ‘함께 읽어보세요’·관련기사 블록 제거 ─────────
    for marker in b.find_all(string=re.compile(
        r"(Читайте также|Чытайце таксама|함께 읽어보세요)", flags=re.I)):
        parent = marker.parent
        for nxt in list(parent.find_all_next()):
            nxt.decompose()
        parent.decompose()
    # ────────────────────────────────────────────────

    # ── 2) 벨라루스 관련 기사 필터 ─────────────────────
    raw_txt = t.get_text(" ", strip=True) + " " + b.get_text(" ", strip=True)
    if not is_belarus_related(raw_txt):
        logging.debug("  🔴 벨라루스 불포함 스킵: %s", url)
        return None
    # ────────────────────────────────────────────────

    # ─── 3) 대표 이미지 추출 (lazyload / srcset / og:image 대응) ───
    def pick_image(block):
        """<div id="zooming"> 안에서 첫 실제 이미지 URL 반환"""
        img = (block.find("img", attrs={"data-src": True}) or
               block.find("img", attrs={"data-lazy-src": True}) or
               block.find("img", attrs={"data-original": True}) or
               block.find("img"))
        if img:
            # data-* → src 순서로 검사
            for attr in ("data-src", "data-lazy-src", "data-original", "src"):
                src = img.get(attr)
                if src:
                    break
            else:
                src = None

            # srcset만 있을 때
            if not src and img.has_attr("srcset"):
                src = img["srcset"].split()[0]

            # 스킴리스·상대경로 보정
            if src and src.startswith("//"):
                src = "https:" + src
            elif src and src.startswith("/"):
                src = urljoin(url, src)

            # placeholder·logo 필터
            if src and re.search(r"(placeholder|logo|default)\.(svg|png|gif)", src, re.I):
                src = None
            if src:
                return src

        # ② 백업: <meta property="og:image">
        og = s.find("meta", property="og:image")
        return og["content"] if og and og.get("content") else None

    img_url = pick_image(b)
    if not img_url:
        logging.debug("  ⚠️  대표 이미지 없음: %s", url)
    # ─────────────────────────────────────────────────────────

    cat = url.split("/news/")[1].split("/")[0]
    return {
        "title": t.get_text(strip=True),
        "html":  str(b),
        "image": img_url,
        "url":   url,
        "cat":   cat
    }


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
[adsense_inarticle]

<h3>💬 전문가 전망</h3>
<p>첫 번째 단락: 구체적 근거·숫자 포함 4문장 이상</p>
<p>두 번째 단락: 시나리오·전망 포함 4문장 이상</p>

[gpt_related_qna]
[adsense_inarticle]

<p>🏷️ 태그: {tags}</p>
<p>출처: UDF.name 원문<br>
   Photo: UDF.name<br>
   by. LEE🌳<br>
   <em>* 생성형 AI의 도움으로 작성.</em></p>

<p class="related"></p>
""").strip()

# ─── GPT 리라이팅 (정책 안전 + 메타데이터 삽입) ──────────
def rewrite(article):
    # extra_context는 더 이상 사용하지 않습니다
    today            = datetime.now(tz=ZoneInfo("Asia/Seoul")).strftime("%Y.%m.%d")
    views            = random.randint(7_000, 12_000)
    tags_placeholder = ""

    # STYLE_GUIDE의 플레이스홀더만 채워서 'filled'에 담기
    filled = STYLE_GUIDE.format(
        emoji="📰",
        title=article["title"],
        date=today,
        views=views,
        tags=tags_placeholder
    )

    # RAW_HTML만 치환하고, extra_context 제거
    prompt_body = (
        filled
        .replace("⟪RAW_HTML⟫", article["html"])
        + f"""

원문:
{article["html"]}
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
                "`[gpt_latest_data]`\n\n"
                "**❓ Q&A 섹션은 숏코드로 대체합니다.**\n"
                "`[gpt_related_qna]`\n\n"
                "**※ 반드시 STYLE_GUIDE 순서대로 아래 헤더 블록을 모두 포함해야 합니다.**\n"
                "    - `<h1>…</h1>`\n"
                "    - `<small>…</small>`\n"
                "    - `<h3>💡 본문 정리</h3>`\n"
                "    - `<h2>✍️ 편집자 주 …</h2>`\n"
                "    - `<h3>📝 개요</h3>`\n"
                "    - `[gpt_latest_data]`\n"   
                "    - `[adsense_inarticle]`\n"   
                "    - `<h3>💬 전문가 전망</h3>`\n"
                "    - `[gpt_related_qna]`\n"
                "    - `[adsense_inarticle]`\n"   
                "    - `<p>🏷️ 태그: …</p>`\n"
                "    - `<p>출처: …</p>`\n"
                "    - `<p class=\\\"related\\\"></p>`\n\n"
                "[태그 생성 규칙 — 반드시 지켜야 함]\n"
                "1) 출력 형식: <p>🏷️ 태그: 태그1,태그2,태그3,태그4,태그5,태그6</p>\n"
                "   (쉼표 뒤 공백 금지, 정확히 6개)\n"
                "2) 단어 규칙: 2–12자, 허용문자=한글·영문·하이픈만,\n"
                "   따옴표·숫자·이모지 및 '의'·'적'·'적인' 꼬리 금지\n"
                "3) 구성 규칙: 인물 1개 + 지명 1개 + 사건·주제 4개 (기사 핵심 명사)\n"
            ),
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
    """
    모든 제목을 '주체, 대상 + 강한 행동!' + 이모지(1~2개) 형태로 강제 변환
    - 길이: 20~36자
    - 완곡/설명형(준비 중/논의/계획/가능성/에서/서) 금지
    - 실패 시 휴리스틱 폴백으로 동일 스타일 보장
    """
    snippet = context[:900]

    system = (
        "너는 한국 뉴스 헤드라인 전문 편집자다. 아래 규칙을 100% 준수해라.\n"
        "1) 형태: ‘주체, 상대/대상 + 강한 행동!’ (콤마 도치형, 문장 끝은 반드시 !)\n"
        "2) 길이: 20~36자.\n"
        "3) 금지: '준비 중', '논의', '계획', '가능성', '에서/서' 등 설명형·완곡어.\n"
        "4) 인물명은 가능하면 간단형(예: '유리 젠코비치'→'젠코비치').\n"
        "5) 이모지 1–2개 필수(법⚖️, 충돌💥, 경고⚠️, 경찰🛡️, 경제📉/📈 등 문맥 맞춤).\n"
        "6) 낚시 금지. 단, 힘 있는 동사(도전/격돌/정면승부/압박/파열 등) 사용.\n"
        "7) 고유명사는 통용 한국어 표기로 간결하게.\n"
        "출력은 헤드라인 1줄만."
    )

    examples = (
        "예시 변환:\n"
        "• 원문: 'Yury Zenkovich prepares a lawsuit in the US against security staff'\n"
        "  결과: '젠코비치, 보안 요원 상대로 법정 도전!⚖️💥'\n"
        "• 원문: 'Opposition figure files urgent motion over airport scuffle'\n"
        "  결과: '야권 인사, 공항 충돌 두고 긴급 신청!💥⚖️'\n"
    )

    prompt = (
        f"{examples}\n"
        f"원제목: {src}\n"
        f"기사 일부(요약 참고용): {snippet}\n"
        "규칙대로 한국어 헤드라인 1개만 출력."
    )

    headers = {"Authorization": f"Bearer {OPEN_KEY}", "Content-Type": "application/json"}
    data = {
        "model": "gpt-4o-mini",
        "messages": [{"role": "system", "content": system},
                     {"role": "user", "content": prompt}],
        "temperature": 0.7,
        "max_tokens": 60
    }

    title = ""
    try:
        r = requests.post("https://api.openai.com/v1/chat/completions",
                          headers=headers, json=data, timeout=20)
        r.raise_for_status()
        title = r.json()["choices"][0]["message"]["content"].strip()
    except Exception:
        title = ""

    # ── 폴백: API 실패/부적절 출력 시 규칙 기반 생성
    if not title or len(title) < 8:
        base = re.sub(r"[\"'《》«»\[\]\(\)]", "", src).strip()
        base = re.sub(r"\s+", " ", base)
        # 콤마 도치형 보장
        if "," not in base:
            if " " in base:
                first, rest = base.split(" ", 1)
                base = f"{first}, {rest}"
            else:
                base = base + ","
        title = base

    # ── 완곡어 제거(치환)
    title = re.sub(r"(준비\s*중|논의|계획|가능성|에서|서)\b", "도전", title)

    # ── 이모지 보강
    if not re.search(r"[⚖️💥🛡️⚠️📉📈🔥]", title):
        title = title.rstrip() + "⚖️💥"

    # ── 느낌표 보강
    if "!" not in title:
        title = title.rstrip(" .") + "!"

    # ── 길이 트리밍(꼬리의 이모지/느낌표 보존)
    MAXLEN = 36
    if len(title) > MAXLEN:
        m = re.search(r"[⚖️💥🛡️⚠️📉📈🔥]+!?$", title)
        tail = m.group(0) if m else "!"
        core = re.sub(r"[⚖️💥🛡️⚠️📉📈🔥!]+$", "", title).rstrip(" ,·—-")
        core = core[:max(1, MAXLEN - len(tail))].rstrip(" ,·—-")
        title = core + tail

    # ── 최종 콤마 도치형 확인(없으면 강제)
    if "," not in title:
        parts = title.rstrip("!").split()
        if len(parts) >= 2:
            tail = re.search(r"[⚖️💥🛡️⚠️📉📈🔥]+!?$", title)
            tail = tail.group(0) if tail else "!"
            core = " ".join(parts)
            first, rest = parts[0], " ".join(parts[1:])
            core = f"{first}, {rest}"
            core = core[:max(1, MAXLEN - len(tail))].rstrip(" ,·—-")
            title = core + tail

    return title

# ─── 불용어·조사 제거용 상수 ──────────
_KR_STOP_SUFFIX = (
    "의", "에", "에서", "에게", "으로", "적으로", "적", "적인"
)
_KR_FILTER_CHARS = re.compile(r"[“”\"\'’‘·…\s]+")  # 특수따옴표·공백
_NUM_EMOJI       = re.compile(r"[0-9️⃣-🔟©®™✳︎✴️💡✨🚫⬆️⬇️🚀]+")
_VALID_KR_EN     = re.compile(r"[가-힣A-Za-z0-9\-]+")

def sanitize_tags(raw: list[str], max_tags: int = 10) -> list[str]:
    """쉼표·스페이스로 분리한 태그 후보 → 조사·접미사·이모지·숫자 제거"""
    clean = []
    for tag in raw:
        t = _NUM_EMOJI.sub("", _KR_FILTER_CHARS.sub("", tag)).strip()
        for suf in _KR_STOP_SUFFIX:
            if t.endswith(suf):
                t = t[:-len(suf)]
        t = "".join(_VALID_KR_EN.findall(t))
        if 2 <= len(t) <= 15:
            clean.append(t)
    return list(dict.fromkeys(clean))[:max_tags]
    
def tag_names(txt: str) -> list[str]:
    """
    GPT 결과에서 ‘🏷️ 태그: …’ 한 줄만 추출해
    → 콤마(,) 기준 분리
    → sanitize_tags()로 조사·접미사·이모지 제거
    → '벨라루스'만 불용어로 제외
    → 최대 6개 반환
    """
    stop_words = {"벨라루스"}  # ← 여기만 제외

    # ① ‘🏷️ 태그:’ 줄만 안전하게 잡기 (< 또는 줄바꿈 전까지만)
    m = re.search(r"🏷️\s*태그[^:]*[:：]\s*([^<\n]+)", txt)
    if not m:
        return []

    # ② 콤마(,)로 분리
    raw_tags = [t.strip("–-#• ") for t in m.group(1).split(",")]

    # ③ 정제 → 불용어 제외 → 최대 6개
    cleaned = [t for t in sanitize_tags(raw_tags) if t and t not in stop_words]
    return cleaned[:6]

def tag_id(name: str) -> int | None:
    """
    - 정확히 같은 이름(tag)이 이미 있으면 그 ID 사용
    - 없으면 새로 생성
    - POST 시 'term_exists' 에러(이미 존재)면 그 term_id 사용
    """
    # 1) 같은 이름이 존재하는지 먼저 검색 (여유 있게 100개까지)
    r = requests.get(
        TAGS_API,
        params={"search": name, "per_page": 100},
        auth=(USER, APP_PW),
        timeout=10
    )
    if r.ok:
        for term in r.json():
            if term["name"] == name:        # 정확히 일치하는 이름
                return term["id"]

    # 2) 없으면 생성 시도
    c = requests.post(
        TAGS_API, json={"name": name},
        auth=(USER, APP_PW), timeout=10
    )

    # 2-A) 새로 생성된 경우
    if c.status_code == 201:
        return c.json().get("id")

    # 2-B) 이미 존재 → WP가 term_exists와 함께 기존 ID 반환
    if c.status_code == 400 and c.json().get("code") == "term_exists":
        return c.json()["data"]["term_id"]

    logging.warning("태그 '%s' 처리 실패: %s %s", name, c.status_code, c.text)
    return None

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
    
    # ▶ 디버그 1: publish() 진입 확인
    logging.debug(f"▶ publish() 성공, 이제 Yoast 메타 자동화 시작(post_id={r.json()['id']})")

    # ★ Yoast SEO 메타 자동 생성 & 업로드
    post_id = r.json()["id"]
    try:
        # ▶ 디버그 2: 메타 생성 호출 직전
        logging.debug("▶ Calling generate_meta()")
        meta = generate_meta(article)
        # ▶ 디버그 3: 메타 생성 결과 확인
        logging.debug(f"▶ generate_meta() 리턴값: {meta}")

        push_meta(post_id, meta)
        logging.info("  🟢 Yoast 메타 적용 완료")
    except Exception as e:
        logging.warning("Yoast 메타 실패: %s", e)


def main():
    logging.basicConfig(
        level=logging.DEBUG,                  # <<< DEBUG 로 변경
        stream=sys.stdout,
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

        # ─── [DEBUG] 파싱 결과 확인 ───────────────────────
        if art:
            logging.debug("  🟢 parse OK | 제목: %s | img: %s",
                          art["title"], art["image"])
        else:
            logging.debug("  🔴 parse returned None")
            continue
        # ────────────────────────────────────────────────

        # ─── GPT 리라이팅 ────────────────────────────────
        try:
            txt = rewrite(art)
            logging.debug("  🟢 GPT OK | 길이: %d chars", len(txt))  # <<<
        except Exception as e:
            logging.warning("GPT 오류: %s", e)
            continue

        # ─── 태그 추출 & 게시 ────────────────────────────
        # 1) 본문에 있는 ‘🏷️ 태그: …’에서 추출
        names = tag_names(txt)

        # 2) 폴백: 본문에 태그 줄이 없으면 Yoast 메타 생성 결과의 tags 사용
        if not names:
            try:
                meta_for_tags = generate_meta(art)  # from yoast_meta import generate_meta
                names = [t.strip() for t in meta_for_tags.get("tags", []) if t and t.strip()]
                logging.debug("  🧷 tag fallback from yoast: %s", names)
            except Exception as e:
                logging.warning("  🧷 tag fallback 실패: %s", e)
                names = []

        # 3) 로컬 불용어 세트 + 중복 제거 + 최대 6개 제한 (전역 STOP 불필요)
        stop_local = {"벨라루스", "뉴스", "기사", "국제", "정치", "경제", "사회"}
        seen_names = set()
        filtered = []
        for n in names:
            n = n.strip()
            if not n or n in stop_local:
                continue
            if n not in seen_names:
                seen_names.add(n)
                filtered.append(n)
            if len(filtered) >= 6:
                break

        # 4) 이름 -> WP 태그 ID
        tag_ids = [tid for n in filtered if (tid := tag_id(n))]

        try:
            publish(art, txt, tag_ids)
            logging.debug("  🟢 publish OK")
            seen.add(norm(url))
            save_seen(seen)
        except Exception as e:
            logging.warning("업로드 실패: %s", e)

        time.sleep(1.5)

if __name__ == "__main__":
    main()
