import requests
import json
import os
from bs4 import BeautifulSoup, NavigableString, Tag
from urllib.parse import urljoin

# ✅ 환경변수로부터 인증 정보 불러오기
WP_USERNAME = os.getenv("WP_USERNAME")
WP_APP_PASSWORD = os.getenv("WP_APP_PASSWORD")
WP_API_URL = "https://belatri.info/wp-json/wp/v2/posts"
TAG_API_URL = "https://belatri.info/wp-json/wp/v2/tags"

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
UDF_BASE_URL = "https://udf.name/news/"
HEADERS = {"User-Agent": "Mozilla/5.0"}
SEEN_FILE = "seen_urls.json"

# ✅ 이전에 본 URL 로딩
def load_seen_urls():
    if os.path.exists(SEEN_FILE):
        with open(SEEN_FILE, "r", encoding="utf-8") as f:
            return set(json.load(f))
    return set()

def save_seen_urls(urls):
    with open(SEEN_FILE, "w", encoding="utf-8") as f:
        json.dump(list(urls), f, ensure_ascii=False, indent=2)

# ✅ 기사 링크 수집
def get_article_links():
    response = requests.get(UDF_BASE_URL, headers=HEADERS)
    if response.status_code != 200:
        print(f"❌ 메인 페이지 요청 실패: {response.status_code}")
        return []

    soup = BeautifulSoup(response.text, "html.parser")
    links = []
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if (
            href.startswith("https://udf.name/news/") and
            href.endswith(".html") and
            href.count("/") >= 5
        ):
            links.append(href)
    return list(set(links))

# ✅ 기사 내용 추출
def extract_article(url):
    response = requests.get(url, headers=HEADERS)
    if response.status_code != 200:
        print(f"❌ 요청 실패: {url} | {response.status_code}")
        return None

    soup = BeautifulSoup(response.text, "html.parser")

    title = soup.find("h1", class_="newtitle")
    title_text = title.get_text(strip=True) if title else "제목 없음"

    author = soup.find("div", class_="author")
    author_text = author.get_text(strip=True) if author else "출처 없음"

    image = soup.find("img", class_="lazy")
    image_url = "https://udf.name" + image["data-src"] if image else None

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
        "title": title_text,
        "author": author_text,
        "image": image_url,
        "url": url,
        "content": content
    }

# ✅ ChatGPT 리라이팅 + 태그 추출
def rewrite_with_chatgpt(article):
    prompt = f"""
다음은 벨라루스 관련 외신 기사입니다. 아래 양식에 맞춰 한국 독자를 위한 블로그 게시글을 작성해주세요.

🎯 작성 조건:
- 기사 내용을 바탕으로 **요약하거나 해석하지 말고**, **문체와 구조만 바꿔서 재작성**해주세요.
- **기사의 정보는 그대로 유지**하고, **한국어로 자연스럽고 가독성 높게** 작성해주세요.
- **제목(H1), 부제(H2), 내용 문단(H3)** 등으로 구분해 블로그에 최적화된 구조로 작성해주세요.
- **본문에서 주요 키워드를 추출해 태그용 키워드로 함께 제공**해주세요.

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
    result = res.json()["choices"][0]["message"]["content"]
    return result

# ✅ 태그 자동 등록 (중복 확인 포함)
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

# ✅ WordPress 업로드
def post_to_wordpress(title, content, tags):
    data = {
        "title": title,
        "content": content,
        "status": "publish",
        "tags": tags  # ✅ 태그 포함
    }
    res = requests.post(WORDPRESS_API_URL, headers=HEADERS, json=data)

    print(f"📡 [응답 코드] {res.status_code}")
    print(f"📨 [응답 본문] {res.text[:500]}")

    return res.status_code == 201

# ✅ 메인 실행
if __name__ == "__main__":
    print("🔍 크롤링 시작")
    seen = load_seen_urls()
    all_links = get_article_links()
    new_links = [link for link in all_links if link not in seen]
    print(f"📰 새 기사 수: {len(new_links)}")

    for url in new_links:
        article = extract_article(url)
        if not article or not article["content"]:
            continue
        rewritten = rewrite_with_chatgpt(article)

        # 🎯 GPT 출력에서 태그 추출 (예: "- 초점 키프레이즈: 벨라루스 경제 위기")
        tag_lines = [line for line in rewritten.splitlines() if "초점 키프레이즈:" in line]
        tags = tag_lines[0].split(":", 1)[1].strip().split() if tag_lines else []

        success = post_to_wordpress(article["title"], rewritten, tags)
        if success:
            print(f"✅ 업로드 성공: {article['title']}")
            seen.add(url)
        else:
            print(f"❌ 업로드 실패: {article['title']}")

    save_seen_urls(seen)
    print("✅ 작업 완료")
