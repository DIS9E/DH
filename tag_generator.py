#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SEO 최적화용 태그 생성기
• GPT 호출 → 검색 엔진 최적화용 태그 JSON 배열 반환
"""

import os, time, logging, requests, json
from slugify import slugify

OPENAI_KEY = os.getenv("OPENAI_API_KEY")
GPT_MODEL  = "gpt-4o"

MASTER_PROMPT = """
당신은 ‘벨라트리(Belatri)’ 블로그의 SEO 태그 생성기입니다.
입력된 맛집 정보(제목·본문·메뉴·리뷰)를 보고
검색 엔진에서 잘 걸릴 키워드 태그를 최대 8개 이하로 JSON 배열 형태로 반환하세요.
예: ["민스크맛집","감성카페","야외테라스","디저트강추"]
"""

def generate_tags_for_post(article: dict) -> list[str]:
    snippet = (
        f"제목: {article['title']}\n"
        f"본문: {article['content'][:250]}\n"
        f"메뉴: {', '.join(article.get('menu_items',[])[:3])}\n"
        f"리뷰: {', '.join(article.get('reviews',[])[:2])}"
    )
    for attempt in range(3):
        try:
            resp = requests.post(
                "https://api.openai.com/v1/chat/completions",
                headers={"Authorization":f"Bearer {OPENAI_KEY}"},
                json={
                  "model": GPT_MODEL,
                  "messages":[
                    {"role":"system","content":MASTER_PROMPT},
                    {"role":"user","content":snippet}
                  ],
                  "temperature":0.5,
                  "max_tokens":100
                },
                timeout=30
            )
            resp.raise_for_status()
            tags = json.loads(resp.json()["choices"][0]["message"]["content"].strip())
            return [slugify(t,separator="-",lowercase=False) for t in tags]
        except Exception as e:
            logging.warning(f"[tag_generator] 실패 {attempt+1}/3: {e}")
            time.sleep(1)
    logging.error("[tag_generator] 최종 실패, 빈 리스트 반환")
    return []
