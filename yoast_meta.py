#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Yoast SEO 메타데이터 자동화 모듈
• GPT 호출 → 초점 키프레이즈·SEO 제목·슬러그·메타 설명 JSON 생성
• WordPress REST PATCH로 _yoast_wpseo_* 필드 업로드
"""

import os
import re
import json
import requests
from slugify import slugify
from bs4 import BeautifulSoup

# ────────── 환경 변수 ──────────
WP_URL  = os.getenv("WP_URL", "https://belatri.info").rstrip("/")
USER    = os.getenv("WP_USERNAME")
APP_PW  = os.getenv("WP_APP_PASSWORD")
OPENKEY = os.getenv("OPENAI_API_KEY")

POSTS_API = f"{WP_URL}/wp-json/wp/v2/posts"

# ────────── GPT 프롬프트 ──────────
MASTER_PROMPT = """
당신은 ‘헤드라이트’ 뉴스레터·udf.name 메타데이터 어시스턴트다.

### 규칙
1) 모든 한국어 문장은 친근한 대화체(~요·~네요).
2) AI 티 나는 표현, 의문문 금지.
3) 메타설명은 선언형 한 문장 140–155자.
4) 제목·SEO 제목은 45자 이내 (SEO 제목에 이모지 제외).
5) 슬러그는 한국어 소문자+하이픈, 최대 60byte.
6) 태그는 최소 5개(카테고리 공통 태그 포함).
7) 초점 키프레이즈는 5–7어절.
8) 아래 JSON 스키마 **딱 하나**만 반환.

{
  "title": "...",
  "tags": ["...", "..."],
  "focus_keyphrase": "...",
  "seo_title": "...",
  "slug": "...",
  "meta_description": "..."
}
"""  # ← 닫는 따옴표 3개 꼭!

# ────────── GPT 호출 헬퍼 ──────────
def _gpt(prompt: str) -> dict:
    headers = {
        "Authorization": f"Bearer {OPENKEY}",
        "Content-Type":  "application/json"
    }
    data = {
        "model":       "gpt-4o",
        "messages":    [{"role":"user","content":prompt}],
        "temperature": 0.4,
        "max_tokens":  400
    }
    r = requests.post(
        "https://api.openai.com/v1/chat/completions",
        headers=headers, json=data, timeout=60
    )
    r.raise_for_status()
    # 반환된 content는 JSON 문자열이므로 dict로 변환
    return json.loads(r.json()["choices"][0]["message"]["content"])

# ────────── 메타 JSON 생성 ──────────
def generate_meta(article: dict) -> dict:
    """
    article dict를 받아 GPT 호출 → 규격에 맞춘 meta dict 반환
    """
    # 본문 HTML에서 텍스트만 추출해 600자 샘플 생성
    text    = BeautifulSoup(article["html"], "html.parser").get_text(" ", strip=True)
    snippet = re.sub(r"\s+", " ", text)[:600]

    # 프롬프트 조립
    prompt = (
        MASTER_PROMPT
        + f"\n\n기사 제목: {article['title']}"
        + f"\n기사 본문 일부: {snippet}"
    )
    meta = _gpt(prompt)

    # 슬러그 보정: 한글 소문자+하이픈, 최대 60byte
    meta["slug"] = slugify(meta["slug"], lowercase=True, allow_unicode=True)[:60]
    # 메타설명 길이 보정
    if len(meta["meta_description"]) > 155:
        meta["meta_description"] = meta["meta_description"][:154] + "…"

    return meta

# ────────── WP 메타 PATCH ──────────
def push_meta(post_id: int, meta: dict):
    """
    generate_meta() 결과를 받아
    WordPress REST API로 Yoast 메타 필드 & 슬러그를 업데이트
    """
    payload = {
        "slug": meta["slug"],
        "meta": {
            "_yoast_wpseo_focuskw":  meta["focus_keyphrase"],
            "_yoast_wpseo_title":    meta["seo_title"],
            "_yoast_wpseo_metadesc": meta["meta_description"]
        }
    }
    r = requests.post(
        f"{POSTS_API}/{post_id}",
        json=payload,
        auth=(USER, APP_PW),
        timeout=20
    )
    r.raise_for_status()
