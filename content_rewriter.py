import openai
import os
import re

openai.api_key = os.getenv("OPENAI_API_KEY")

def rewrite_content(data: dict) -> tuple[str, str]:
    """
    GPT를 호출해 새 제목과 본문을 받아
    HTML 포맷으로 조립해 반환합니다.
    → (본문 HTML, 새 제목)
    """
    prompt = build_prompt(data)
    print("📤 GPT 요청 중...")

    res = openai.chat.completions.create(
        model="gpt-4o",
        messages=[
            {
                "role": "system",
                "content": "당신은 부드럽고 설명형 여행 매거진 스타일의 편집자입니다. "
                           "한국어로 새 제목과 소개 본문을 작성해 주세요. 형식은 반드시 다음을 따르세요:\n\n"
                           "제목: ...\n\n본문: ...\n\n"
                           "HTML 없이, 마크다운이나 태그 없이 작성해 주세요."
            },
            {"role": "user", "content": prompt}
        ],
        temperature=0.7
    )

    content = res.choices[0].message.content.strip()

    # 🔍 제목과 본문 분리
    title_match = re.search(r"제목\s*[:：]\s*(.+)", content)
    body_match  = re.search(r"본문\s*[:：]\s*(.+)", content, re.DOTALL)

    new_title = title_match.group(1).strip() if title_match else data["title"]
    body      = body_match.group(1).strip() if body_match else content

    # ────────── 부가 블록 ──────────
    menu_items = data.get("menu_items", [])
    reviews    = data.get("reviews", [])

    menu_html = f"""
<h3>뭐 먹지</h3>
<ul>
{''.join(f"<li>{item}</li>" for item in menu_items)}
</ul>
""".strip() if menu_items else ""

    review_html = f"""
<h3>분위기 & 이용 팁</h3>
<ul>
{''.join(f"<li>{r}</li>" for r in reviews)}
</ul>
""".strip() if reviews else ""

    info_parts = []
    if data.get("address"):
        info_parts.append(f"<b>주소:</b> {data['address']}")
    if data.get("hours"):
        info_parts.append(f"<b>영업시간:</b> {data['hours']}")
    if data.get("phone"):
        info_parts.append(f"<b>연락처:</b> {data['phone']}")

    info_block = f"""
<h3>기본 정보</h3>
<p>{"<br>".join(info_parts)}</p>
""".strip() if info_parts else ""

    map_block = f"""
<iframe src="{data['map_url']}" width="100%" height="300" style="border:0;" allowfullscreen loading="lazy"></iframe>
""".strip() if data.get("map_url") else ""

    source_block = f"""
<p class="source">원문: <a href="{data['source_url']}" rel="nofollow noopener">출처</a> · 저작권은 원문 사이트에 있으며 본 글은 소개 목적의 요약/비평입니다.</p>
""".strip()

    html = f"""
<h2>{new_title}</h2>
<p>{body}</p>
{menu_html}
{review_html}
{info_block}
{map_block}
{source_block}
""".strip()

    return html, new_title


def build_prompt(data: dict) -> str:
    """
    GPT에게 전달할 사용자 프롬프트 문자열을 생성합니다.
    → 제목과 소개 본문을 모두 요청
    """
    menu_formatted = "\n".join(f"- {item}" for item in data.get("menu_items", []))
    reviews_formatted = "\n".join(f'- "{r}"' for r in data.get("reviews", []))

    return f"""
당신은 한국인 여행자에게 벨라루스 민스크의 카페를 소개하는 여행 매거진 작가입니다.
이 카페에 대한 '제목'과 '소개 본문'을 새롭게 작성해 주세요.

- 분위기, 대표 메뉴, 이용 팁 중심
- HTML, 마크다운, 태그 없이 순수 텍스트
- 반드시 아래 형식을 지켜 주세요:

제목: ...

본문: ...

제공 정보:
제목: {data.get("title", "")}

추천 메뉴:
{menu_formatted or '정보 없음'}

방문자 리뷰:
{reviews_formatted or '리뷰 없음'}
""".strip()
