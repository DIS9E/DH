# content_rewriter.py

import openai
import os

openai.api_key = os.getenv("OPENAI_API_KEY")

def rewrite_content(data: dict) -> str:
    prompt = build_prompt(data)
    print("📤 GPT 요청 중...")
    
    res = openai.ChatCompletion.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": "당신은 한국인 여행자를 위한 글을 작성하는 편집자입니다. 너무 AI처럼 보이지 않게 자연스럽고 생생하게 씁니다."},
            {"role": "user", "content": prompt}
        ],
        temperature=0.7
    )

    output = res["choices"][0]["message"]["content"]
    return output

def build_prompt(data: dict) -> str:
    menu_formatted = "\n".join(f"- {item}" for item in data["menu_items"])
    reviews_formatted = "\n".join(f'- "{r}"' for r in data["reviews"])

    return f"""
카페 정보를 바탕으로, 한국 독자에게 어필할 수 있도록 자연스럽게 소개글을 작성해줘.
- 카페는 민스크에 있고, 너무 노골적인 목적 언급 없이 분위기와 특징 중심으로 써줘
- 문체는 부드러운 설명체, 자연스럽게 이어지도록
- 마지막에는 위치, 연락처, 메뉴, 지도, 리뷰 등을 한국식으로 구성해
- 본문 말미에 원본 출처와 저작권 문구도 포함해

📄 원본 정보:
제목: {data["title"]}
주소: {data["address"]}
영업시간: {data["hours"]}
연락처: {data["phone"]}
추천 메뉴:
{menu_formatted}

방문자 리뷰:
{reviews_formatted}

지도 링크: {data["map_url"]}
원본 출처: {data["source_url"]}
"""
