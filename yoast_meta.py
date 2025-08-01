import os, re, json, requests, random
from slugify import slugify   # pip install python-slugify
from datetime import datetime
from zoneinfo import ZoneInfo

WP_URL  = os.getenv("WP_URL", "https://belatri.info").rstrip("/")
USER    = os.getenv("WP_USERNAME")
APP_PW  = os.getenv("WP_APP_PASSWORD")
OPENKEY = os.getenv("OPENAI_API_KEY")

POSTS_API = f"{WP_URL}/wp-json/wp/v2/posts"

# ───── GPT 프롬프트 ─────
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
"""  
