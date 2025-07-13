import requests
import json
import os
from bs4 import BeautifulSoup, NavigableString, Tag
from urllib.parse import urljoin, urlparse
from requests.auth import HTTPBasicAuth

# ✅ 환경변수 불러오기
WP_USERNAME = os.getenv("WP_USERNAME")
WP_APP_PASSWORD = os.getenv("WP_APP_PASSWORD")
WP_API_URL = "https://belatri.info/wp-json/wp/v2/posts"
TAG_API_URL = "https://belatri.info/wp-json/wp/v2/tags"
MEDIA_API_URL = "https://belatri.info/wp-json/wp/v2/media"
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

UDF_BASE_URL = "https://udf.name/news/"
HEADERS = {"User-Agent": "Mozilla/5.0"}
SEEN_FILE = "seen_urls.json"

# ✅ URL 정규화
def normalize_url(url):
    parsed = urlparse(url)
    return f"{parsed.scheme}://{parsed.netloc}{parsed.path}"

# ✅ 이전 URL 불러오기
def load_seen_urls():
    if os.path.exists(SEEN_FILE):
        with open(SEEN_FILE, "r", encoding="utf-8") as f:
            return set(json.load(f))
    return set()

def save_seen_urls(urls):
    with open(SEEN_FILE, "w", encoding="utf-8") as f:
        json.dump(list(urls), f, ensure_ascii=False, indent=2)

# ✅ WordPress에서 이미 등록된 source_url 가져오기
def get_existing_source_urls():
    page = 1
    existing_urls = set()
    while True:
        res = requests.get(
            WP_API_URL,
            params={"per_page": 100, "page": page},
            auth=(WP_USERNAME, WP_APP_PASSWORD)
        )
        if res.status_code != 200:
            break
        posts = res.json()
        if not posts:
            break
        for post in posts:
            meta = post.get("meta", {})
            url = meta.get("_source_url")
            if url:
                existing_urls.add(normalize_url(url))
        page += 1
    return existing_urls

# ✅ 기사 링크 수집
def get_article_links():
    res = requests.get(UDF_BASE_URL, headers=HEADERS)
    if res.status_code != 200:
        print(f"❌ 메인 페이지 요청 실패: {res.status_code}")
        return []
    soup = BeautifulSoup(res.text, "html.parser")
    links = []
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if href.startswith("https://udf.name/news/") and href.endswith(".html") and href.count("/") >= 5:
            links.append(normalize_url(href))
    return list(set(links))

# ✅ 기사 내용 추출
def extract_article(url):
    res = requests.get(url, headers=HEADERS)
    if res.status_code != 200:
        print(f"❌ 요청 실패: {url} | {res.status_code}")
        return None
    soup = BeautifulSoup(res.text, "html.parser")
    title = soup.find("h1", class_="newtitle")
    author = soup.find("div", class_="author")
    image = soup.find("img", class_="lazy")
    content_block = soup.find("div", id="zooming")
    content_lines = []
    if content_block:
        for el in content_block.descendants:
            if isinstance(el, NavigableString):
                txt = el.strip()
                if txt:
                    content_lines.append(txt)
            elif isinstance(el, Tag) and el.name in ["p", "br"]:
                content_lines.append("\n")
    content = "\n".join(line for line in content_lines if line.strip())
    content = content.replace("dle_leech_begin", "").replace("dle_leech_end", "").strip()
    return {
        "title": title.get_text(strip=True) if title else "제목 없음",
        "author": author.get_text(strip=True) if author else "출처 없음",
        "image": "https://udf.name" + image["data-src"] if image else None,
        "url": url,
        "content": content
    }

# ✅ 이미지 업로드
def upload_image_to_wordpress(image_url):
    if not image_url:
        return None
    try:
        img_data = requests.get(image_url).content
        filename = image_url.split("/")[-1]
        media_headers = {
            "Content-Disposition": f"attachment; filename={filename}",
            "Content-Type": "image/jpeg",
            "Authorization": f"Basic {requests.auth._basic_auth_str(WP_USERNAME, WP_APP_PASSWORD)}"
        }
        res = requests.post(
            MEDIA_API_URL,
            headers=media_headers,
            data=img_data
        )
        if res.status_code == 201:
            return res.json()["id"]
        else:
            print(f"❌ 이미지 업로드 실패: {res.status_code}")
            return None
    except Exception as e:
        print(f"❌ 이미지 처리 오류: {e}")
        return None

# ✅ GPT 리라이팅
def rewrite_with_chatgpt(article):
    prompt = f"""
다음은 벨라루스 관련 외신 기사입니다. 아래 양식에 맞춰 한국 독자를 위한 블로그 게시글을 작성해주세요.

🎯 작성 조건:
- 기사 내용을 바탕으로 **요약하거나 해석하지 말고**, **문체와 구조만 바꿔서 재작성**해주세요.
- **기사의 정보는 그대로 유지**하고, **한국어로 자연스럽고 가독성 높게** 작성해주세요.
- **제목(H1), 부제(H2), 내용 문단(H3)** 등으로 구분해 블로그에 최적화된 구조로 작성해주세요.
- **이모지와 친절한 문체**, **by. 에디터 서명**, **관련 키워드 태그 포함**으로 구성해주세요.

🧾 출력 형식:

# [📰 제목]
> 블로그 게시글의 핵심을 반영한 명확하고 간결한 제목

## ✍️ 편집자 주
- 전체 기사 맥락을 1~2문장으로 요약한 편집자 코멘트

## 📌 핵심 내용
### 📍 요약 1
### 📍 요약 2

## 🗞️ 원문 재작성
### 🌪️ [소제목 H3 - 주제1]
- 문단 내용 충실히 유지하며 자연스럽게 풀어쓰기

### ⚠️ [소제목 H3 - 주제2]
- 이어지는 내용도 충분히 설명하며 구조적 리라이팅

## 📎 관련 정보 또는 시사점
- 추가 설명, 배경 맥락 정리

## 🔗 출처
- 원문 링크: {article["url"]}

## 🏷️ 태그 키워드
– 벨라루스  
– 정치  
– {article["author"]}  

by. LEE🌳

📰 기사 원문:
{article["content"]}
"""
    headers = {
        "Authorization": f"Bearer {OPENAI_API_KEY}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": "gpt-4o",
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.4
    }
    res = requests.post("https://api.openai.com/v1/chat/completions", headers=headers, json=payload)
    return res.json()["choices"][0]["message"]["content"]

# ✅ 태그 ID 생성
def create_or_get_tag_id(tag_name):
    response = requests.get(TAG_API_URL, params={"search": tag_name})
    if response.status_code == 200 and response.json():
        return response.json()[0]["id"]
    res = requests.post(TAG_API_URL,
        auth=(WP_USERNAME, WP_APP_PASSWORD),
        json={"name": tag_name})
    if res.status_code == 201:
        return res.json()["id"]
    return None

# ✅ 포스트 업로드
def post_to_wordpress(title, content, tags, featured_image_id=None, source_url=None):
    data = {
        "title": title,
        "content": content,
        "status": "publish",
        "tags": tags,
        "meta": {
            "_source_url": source_url  # 커스텀 필드로 원본 URL 저장
        }
    }
    if featured_image_id:
        data["featured_media"] = featured_image_id
    res = requests.post(
        WP_API_URL,
        headers=HEADERS,
        json=data,
        auth=HTTPBasicAuth(WP_USERNAME, WP_APP_PASSWORD)
    )
    print(f"📡 [응답 코드] {res.status_code}")
    print(f"📨 [응답 본문] {res.text[:300]}")
    return res.status_code == 201

# ✅ 메인 실행
if __name__ == "__main__":
    print("🔍 크롤링 시작")
    seen = load_seen_urls()
    existing = get_existing_source_urls()
    all_links = get_article_links()
    new_links = [link for link in all_links if normalize_url(link) not in seen and normalize_url(link) not in existing]
    print(f"📰 새 기사 수: {len(new_links)}")

    for url in new_links:
        article = extract_article(url)
        if not article or not article["content"]:
            continue

        rewritten = rewrite_with_chatgpt(article)
        lines = rewritten.splitlines()
        title_line = next((line for line in lines if line.startswith("# ")), article["title"])
        title_clean = title_line.replace("# ", "").strip()

        tag_lines = [line for line in rewritten.splitlines() if "초점 키프레이즈:" in line]
        tag_names = tag_lines[0].split(":", 1)[1].strip().split() if tag_lines else []
        tag_ids = [create_or_get_tag_id(tag) for tag in tag_names]

        image_id = upload_image_to_wordpress(article["image"])
        success = post_to_wordpress(title_clean, rewritten, tag_ids, image_id, source_url=normalize_url(article["url"]))

        if success:
            print(f"✅ 업로드 성공: {title_clean}")
            seen.add(normalize_url(url))
            save_seen_urls(seen)
        else:
            print(f"❌ 업로드 실패: {title_clean}")

    print("✅ 전체 작업 완료")
