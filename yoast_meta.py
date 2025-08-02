#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Yoast SEO 메타데이터 자동화 모듈
• GPT 호출 → 초점 키프레이즈·SEO 제목·슬러그·메타 설명 JSON 생성 (재시도 로직 포함)
• WordPress REST PATCH로 _yoast_wpseo_* 필드 + title, tags 업로드
"""

import time
import os
import re
import json
import logging
import requests
from slugify import slugify
from bs4 import BeautifulSoup

# ────────── 환경 변수 ──────────
WP_URL    = os.getenv("WP_URL", "https://belatri.info").rstrip("/")
USER      = os.getenv("WP_USERNAME")
APP_PW    = os.getenv("WP_APP_PASSWORD")
OPENKEY   = os.getenv("OPENAI_API_KEY")
POSTS_API = f"{WP_URL}/wp-json/wp/v2/posts"
TAGS_API  = f"{WP_URL}/wp-json/wp/v2/tags"

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
"""

# ────────── GPT JSON 보정 헬퍼 ──────────
def extract_json(raw: str) -> dict:
    """중괄호 범위만 잘라서 JSON 디코드 시도"""
    m = re.search(r"\{(?:[^{}]|(?R))*\}", raw)
    return json.loads(m.group(0)) if m else {}

# ────────── GPT 호출 헬퍼 (재시도 3회) ──────────
def _gpt(prompt: str) -> dict:
    headers = {
        "Authorization": f"Bearer {OPENKEY}",
        "Content-Type":  "application/json",
    }
    last_err = None

    for attempt in range(3):
        messages = [
            {"role": "system",  "content": MASTER_PROMPT},
            {"role": "user",    "content": prompt}
        ]
        if attempt > 0:
            messages.insert(1, {
                "role": "system",
                "content": "응답을 순수 JSON 구조로만 다시 보내주세요."
            })

        resp = requests.post(
            "https://api.openai.com/v1/chat/completions",
            headers=headers,
            json={
                "model":       "gpt-4o",
                "messages":    messages,
                "temperature": 0.4,
                "max_tokens":  400,
            },
            timeout=60
        )
        try:
            resp.raise_for_status()
            content = resp.json()["choices"][0]["message"]["content"].strip()
            return json.loads(content)
        except (json.JSONDecodeError, ValueError):
            # 순수 JSON 아닐 경우, 중괄호만 뽑아서 다시 파싱
            try:
                return extract_json(resp.text)
            except Exception as e:
                last_err = e
                logging.warning(f"GPT JSON 파싱 실패 (시도 {attempt+1}): {e}")
                time.sleep(1)
        except Exception as e:
            logging.error(f"GPT 호출 오류: {e}")
            raise

    raise RuntimeError(f"GPT JSON 파싱 재시도 실패: {last_err}")

# ────────── 메타 JSON 생성 ──────────
def generate_meta(article: dict) -> dict:
    text    = BeautifulSoup(article["html"], "html.parser").get_text(" ", strip=True)
    snippet = re.sub(r"\s+", " ", text)[:600]

    prompt = (
        MASTER_PROMPT
        + f"\n\n기사 제목: {article['title']}"
        + f"\n기사 본문 일부: {snippet}"
    )
    meta = _gpt(prompt)
    logging.debug(f"▶ Generated meta: {meta}")

    # 슬러그 보정
    meta["slug"] = slugify(
        meta.get("slug", ""),
        lowercase=True,
        allow_unicode=True
    )[:60]

    # 메타설명 길이 보정
    if len(meta.get("meta_description", "")) > 155:
        meta["meta_description"] = meta["meta_description"][:154] + "…"

    return meta

# ────────── WP 태그 동기화 ──────────
def sync_tags(names: list[str]) -> list[int]:
    # 기존 태그 조회
    existing = {t["name"]: t["id"] for t in requests.get(TAGS_API, params={"per_page":100}).json()}
    ids = []
    for name in names:
        if name in existing:
            ids.append(existing[name])
        else:
            r = requests.post(TAGS_API, auth=(USER, APP_PW), json={"name": name})
            r.raise_for_status()
            ids.append(r.json()["id"])
    return ids

# ────────── WP 메타 + title, tags PATCH ──────────
def push_meta(post_id: int, meta: dict):
    payload = {
        "slug":  meta["slug"],
        "title": meta.get("title", ""),
        "tags":  sync_tags(meta.get("tags", [])),
        "meta": {
            "_yoast_wpseo_focuskw":  meta.get("focus_keyphrase", ""),
            "_yoast_wpseo_title":    meta.get("seo_title", ""),
            "_yoast_wpseo_metadesc": meta.get("meta_description", ""),
        }
    }
    r = requests.post(
        f"{POSTS_API}/{post_id}",
        json=payload,
        auth=(USER, APP_PW),
        timeout=20
    )
    r.raise_for_status()
    logging.debug(f"🎯 Yoast PATCH 응답: {r.status_code}")

# ────────── 예시: 새 글 처리 루프 ──────────
def main():
    # (여기에 실제로 UDF에서 새 글 리스트 가져오는 로직을 넣으세요)
    new_posts = fetch_new_posts_from_udf()  # → [{'id':123, 'html':..., 'title':...}, ...]
    for post in new_posts:
        try:
            meta = generate_meta({"html": post["html"], "title": post["title"]})
            push_meta(post["id"], meta)
            time.sleep(1)  # API rate limit 대비
        except Exception as e:
            logging.error(f"포스트 {post['id']} 메타 적용 실패: {e}")

if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)
    main()
