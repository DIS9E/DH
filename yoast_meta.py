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
당신은 ‘헤드라이트’ 뉴스레터·udf.name 메타데이터 어시스턴트입니다.  
아래 규칙을 **반드시** 지켜주세요:

1. **언어 & 문체**  
   - 모든 한국어 문장은 친근한 대화체(~요·~네요)로 작성합니다.  
   - AI 티 나는 표현·과도한 클릭 유도(“지금 클릭하세요!” 등) 금지.

2. **초점 키프레이즈 (focus_keyphrase)**  
   - 5–7어절 이내로 구성하세요.  
   - 기사 핵심을 담되, **검색량이 높은 실제 키워드**를 반드시 포함하십시오.

3. **SEO 제목 (seo_title)**  
   - 45자 이내, 핵심 키워드를 앞부분에 배치하세요.  
   - 이모지·특수문자 제외.

4. **슬러그 (slug)**  
   - **한글 소문자 + 하이픈(-)** 조합(ASCII만), 최대 60바이트.  
   - 가능한 한 **핵심 키워드** 포함.

5. **메타 설명 (meta_description)**  
   - **140~155자**, “누가·무엇을·어디서·왜·어떻게”를 한 문장에 담아 사건 맥락을 전달하세요.  
   - 현재 진행형·사실 전달형·전문가 분석 어조  
   - 과장·낚시성·AI 티 금지.

6. **추천 태그 (tags)**  
   - 최소 5개, 기사 카테고리 공통 태그 포함.

7. **반드시 아래 JSON 스키마 하나만 반환** (다른 텍스트 절대 포함 금지):

```json
{
  "title": "...",               // 45자 이내, 흥미 유발 & 핵심 키워드 포함
  "tags": ["...", "..."],       // 추천 태그 목록
  "focus_keyphrase": "...",     // 검색량 높은 5–7어절 키프레이즈
  "seo_title": "...",           // SEO 최적화 제목
  "slug": "...",                // 한글+하이픈 기반 슬러그
  "meta_description": "..."     // 140~155자 한 문장 메타 설명
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
    """
    Yoast 관련 메타만 업데이트한다.
    (중요) WP 기본 필드(title/slug/tags/categories)는 절대 수정하지 않는다.
    """
    yoast_meta = {
        "_yoast_wpseo_focuskw":               meta.get("focus_keyphrase", "") or "",
        "_yoast_wpseo_focuskw_text_input":    meta.get("focus_keyphrase", "") or "",
        "_yoast_wpseo_title":                 meta.get("seo_title", "") or "",
        "_yoast_wpseo_metadesc":              meta.get("meta_description", "") or "",
    }

    payload = {"meta": yoast_meta}  # ← title/slug/tags 넣지 마세요

    r = requests.post(
        f"{POSTS_API}/{post_id}",
        json=payload,
        auth=(USER, APP_PW),
        timeout=20
    )
    r.raise_for_status()
    logging.debug(f"🎯 Yoast-only PATCH 응답: {r.status_code}")

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

