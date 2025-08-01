import os, re, json, requests, random
from slugify import slugify   # pip install python-slugify
from datetime import datetime
from zoneinfo import ZoneInfo

WP_URL  = os.getenv("WP_URL", "https://belatri.info").rstrip("/")
USER    = os.getenv("WP_USERNAME")
APP_PW  = os.getenv("WP_APP_PASSWORD")
OPENKEY = os.getenv("OPENAI_API_KEY")

POSTS_API = f"{WP_URL}/wp-json/wp/v2/posts"

# ───────────────────────── GPT 프롬프트 ─────────────────────────
MASTER_PROMPT = """
당신은 ‘헤드라이트’ 뉴스레터·udf.name 메타데이터 어시스턴트다.

### 규칙
1) 모든 한국어 문장은 친근한 대화체(~요·~네요).  
2) AI 티, 의문문 금지.  
3) 메타설명 = 선언형 한 문장 140-155자.  
4) 제목·SEO 제목 45자 이내 (SEO 제목 이모지 X).  
5) 슬러그: 한국어 소문자+하이픈, 60byte 이내.  
6) 태그 5개 이상 (카테고리 공통 태그 포함).  
7) 초점 키프레이즈 5-7어절.  
8) **반드시 다음 JSON 스키마만 반환.**

```json
{{
  "title": "...",
  "tags": ["...", "..."],
  "focus_keyphrase": "...",
  "seo_title": "...",
  "slug": "...",
  "meta_description": "..."
}}
