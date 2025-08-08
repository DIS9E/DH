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
당신은 ‘벨라트리(Belatri)’ 블로그의 **민스크 맛집 소개** SEO 메타데이터 어시스턴트입니다.  
아래 규칙을 **반드시** 지켜주세요:

1. **언어 & 문체**  
   - 모든 한국어 문장은 친근한 대화체(~요·~네요)로 작성합니다.  
   - AI 티 나는 표현·낚시성 문장 금지.

2. **초점 키프레이즈 (focus_keyphrase)**  
   - 3–7어절 이내로 구성하세요.  
   - ‘민스크 맛집’, ‘현지인 맛집’, ‘분위기 좋은 레스토랑’ 등 실제 검색에 쓰일 법한 키워드를 포함합니다.

3. **SEO 제목 (seo_title)**  
   - 45자 이내, 핵심 키워드를 앞쪽에 배치하세요.  
   - 이모지·특수문자 제외.

4. **슬러그 (slug)**  
   - **한글 소문자 + 하이픈(-)** 조합(ASCII만), 최대 60바이트.  
   - 핵심 키워드가 포함되도록 합니다.

5. **메타 설명 (meta_description)**  
   - **140~155자**, “무엇을·어디서·왜·어떻게”가 한 문장에 자연스럽게 담기도록.  
   - 맛집의 특징, 추천 메뉴, 분위기 등을 간략히 언급하세요.

6. **추천 태그 (tags)**  
   - 최소 5개, ‘민스크맛집’, ‘현지인추천’, ‘분위기맛집’ 등 내부 분류용 태그를 제안합니다.

7. **반드시 아래 JSON 스키마 하나만 반환** (다른 텍스트 절대 포함 금지):

```json
{
  "title": "...",               // 45자 이내, 흥미 유발 & 핵심 키워드 포함
  "tags": ["...", "..."],       // 추천 태그 목록
  "focus_keyphrase": "...",     // 3–7어절 키프레이즈
  "seo_title": "...",           // SEO 최적화 제목
  "slug": "...",                // 한글+하이픈 슬러그
  "meta_description": "..."     // 140~155자 메타 설명
}
"""

# ────────── GPT JSON 보정 헬퍼 ──────────
def extract_json(raw: str) -> dict:
    """중괄호로 감싸진 JSON 덩어리만 뽑아냅니다."""
    m = re.search(r"(\{[\s\S]*\})", raw)
    if not m:
        raise ValueError("JSON 블록을 찾을 수 없습니다.")
    return json.loads(m.group(1))

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
            # 재시도 땐 “순수 JSON만” 요청
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
        resp.raise_for_status()
        content = resp.json()["choices"][0]["message"]["content"]
        # 1) 우선 순수 JSON 직접 파싱
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            logging.warning(f"직접 JSON 로드 실패, content에서 추출 시도: {content[:30]}...")
            # 2) content 내 JSON 블록 추출
            try:
                return extract_json(content)
            except Exception as e:
                last_err = e
                logging.warning(f"content 기반 JSON 추출 실패(시도 {attempt+1}): {e}")
                time.sleep(1)
                continue

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

    # 슬러그 보정 (ASCII 슬러그)
    meta['slug'] = slugify(
        meta.get('slug', ''),
        lowercase=True,
        allow_unicode=False
    )[:60]

    # 메타설명 길이 보정
    if len(meta.get("meta_description", "")) > 155:
        meta["meta_description"] = meta["meta_description"][0:154].rstrip() + "…"

    return meta

# ────────── WP 태그 동기화 ──────────
def sync_tags(names: list[str]) -> list[int]:
    clean_names = []
    for n in names:
        c = re.sub(r"<[^>]+>", "", n).strip()
        if c:
            clean_names.append(c)

    resp = requests.get(TAGS_API, params={"per_page":100})
    resp.raise_for_status()
    existing = {t["name"]: t["id"] for t in resp.json()}

    ids = []
    for name in clean_names:
        if name in existing:
            ids.append(existing[name])
        else:
            payload = {"name": name, "slug": slugify(name, lowercase=True, allow_unicode=False)}
            try:
                r = requests.post(TAGS_API, auth=(USER, APP_PW), json=payload)
                r.raise_for_status()
                ids.append(r.json()["id"])
            except requests.exceptions.HTTPError as e:
                logging.warning(f"태그 생성 실패 '{name}': {e}. 기존 태그 재조회합니다.")
                r2 = requests.get(TAGS_API, params={"search": name})
                if r2.ok and r2.json():
                    ids.append(r2.json()[0]["id"])
                else:
                    logging.error(f"태그 '{name}' 검색에도 실패했습니다.")
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
    new_posts = fetch_new_posts_from_udf()  # UDF에서 새 글 리스트 호출
    for post in new_posts:
        try:
            meta = generate_meta({"html": post["html"], "title": post["title"]})
            push_meta(post["id"], meta)
            time.sleep(1)
        except Exception as e:
            logging.error(f"포스트 {post['id']} 메타 적용 실패: {e}")

if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)
    main()

