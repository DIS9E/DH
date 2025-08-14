import openai
import os

# 환경 변수에서 API 키 로드
openai.api_key = os.getenv("OPENAI_API_KEY")

def rewrite_content(data: dict) -> str:
    """
    1) build_prompt로 사용자 프롬프트 생성
    2) GPT에 요청 (v1+ API)
    3) HTML 구조로 본문 조립하여 반환
    """
    prompt = build_prompt(data)
    print("\U0001F4E4 GPT 요청 중...")

    # GPT 호출
    res = openai.chat.completions.create(
        model="gpt-4o",
        messages=[
            {
                "role": "system",
                "content": "당신은 부드럽고 설명형 여행 매거진 스타일의 소개글을 쓰는 편집자입니다. HTML 없이 본문만 작성하세요."
            },
            {"role": "user", "content": prompt}
        ],
        temperature=0.7
    )

    body = res.choices[0].message.content.strip()

    # HTML 조립
    menu_html = "\n".join(f"<li>{item}</li>" for item in data.get("menu_items", []))
    review_html = "\n".join(f"<li>{r}</li>" for r in data.get("reviews", []))

    info = []
    if data.get("address"):
        info.append(f"<b>주소:</b> {data['address']}")
    if data.get("hours"):
        info.append(f"<b>영업시간:</b> {data['hours']}")
    if data.get("phone"):
        info.append(f"<b>연락처:</b> {data['phone']}")

    map_block = (
        f'<iframe src="{data["map_url"]}" width="100%" height="300" style="border:0;" '
        f'allowfullscreen loading="lazy"></iframe>' if data.get("map_url") else ""
    )

    return f"""
<h2>{data['title']}</h2>
<p>{body}</p>

<h3>뭐 먹지</h3>
<ul>{menu_html}</ul>

<h3>분위기 & 이용 팁</h3>
<ul>{review_html}</ul>

<h3>기본 정보</h3>
<p>{"<br>".join(info)}</p>
{map_block}

<p class=\"source\">원문: <a href=\"{data['source_url']}\" rel=\"nofollow noopener\">출처</a> · 저작권은 원문 사이트에 있으며 본 글은 소개 목적의 요약/비평입니다.</p>
""".strip()

def build_prompt(data: dict) -> str:
    """
    GPT에게 전달할 사용자 프롬프트 문자열을 생성합니다.
    오직 소개 본문만 작성하도록 유도합니다.
    """
    menu_formatted = "\n".join(f"- {item}" for item in data.get("menu_items", []))
    reviews_formatted = "\n".join(f'- "{r}"' for r in data.get("reviews", []))

    return f"""
- 이 글은 민스크의 한 카페를 한국 여행자에게 소개하는 목적입니다.
- 분위기, 대표 메뉴, 이용 팁 등 중심으로 소개해 주세요.
- HTML 없이 소개 본문만 작성해 주세요.
- 주소, 지도, 연락처, 출처 등은 쓰지 마세요.

제목: {data.get("title", "")}

추천 메뉴:
{menu_formatted}

방문자 리뷰:
{reviews_formatted}
""".strip()

if __name__ == "__main__":
    sample_data = {
        "title": "테스트 카페",
        "address": "Минск, ул. Пример, 1",
        "hours": "с 10:00 до 22:00",
        "phone": "+375291234567",
        "menu_items": ["아메리카노 – 5 BYN", "치즈케이크 – 7 BYN"],
        "reviews": ["분위기가 정말 좋아요.", "커피 맛이 훌륭합니다."],
        "map_url": "https://maps.example.com",
        "source_url": "https://koko.by/cafehouse/example"
    }
    html = rewrite_content(sample_data)
    print(html)
