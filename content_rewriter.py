# content_rewriter.py

import openai
import os

# 환경 변수에서 API 키 로드
openai.api_key = os.getenv("OPENAI_API_KEY")

def rewrite_content(data: dict) -> str:
    """
    1) build_prompt로 사용자 프롬프트 생성
    2) GPT에 요청 (v1+ API)
    3) 응답 텍스트 반환
    """
    prompt = build_prompt(data)
    print("📤 GPT 요청 중...")
    
    # v1+ 클라이언트 방식
    res = openai.chat.completions.create(
        model="gpt-4o",
        messages=[
            {
                "role": "system",
                "content": (
                    "당신은 한국인 여행자를 위한 글을 작성하는 편집자입니다. "
                    "너무 AI처럼 보이지 않게 자연스럽고 생생하게 씁니다."
                )
            },
            {"role": "user", "content": prompt}
        ],
        temperature=0.7
    )

    # v1+ 응답 접근 방식
    return res.choices[0].message.content


def build_prompt(data: dict) -> str:
    """
    data 딕셔너리의 각 필드를 읽어
    GPT에게 전달할 사용자 프롬프트 문자열을 생성합니다.
    """
    menu_formatted = "\n".join(f"- {item}" for item in data.get("menu_items", []))
    reviews_formatted = "\n".join(f'- "{r}"' for r in data.get("reviews", []))

    return f"""
카페 정보를 바탕으로, 한국 독자에게 어필할 수 있도록 자연스럽게 소개글을 작성해줘.
- 카페는 민스크에 있고, 너무 노골적인 목적 언급 없이 분위기와 특징 중심으로 써줘
- 문체는 부드러운 설명체, 자연스럽게 이어지도록
- 마지막에는 위치, 연락처, 메뉴, 지도, 리뷰 등을 한국식으로 구성해
- 본문 말미에 원본 출처와 저작권 문구도 포함해

📄 원본 정보:
제목: {data.get("title", "")}
주소: {data.get("address", "")}
영업시간: {data.get("hours", "")}
연락처: {data.get("phone", "")}
추천 메뉴:
{menu_formatted}

방문자 리뷰:
{reviews_formatted}

지도 링크: {data.get("map_url", "")}
원본 출처: {data.get("source_url", "")}
""".strip()


if __name__ == "__main__":
    # 로컬 테스트
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
    content = rewrite_content(sample_data)
    print(content)
