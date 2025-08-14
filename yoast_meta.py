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
import datetime
import sys

# ────────── 환경 변수 ──────────
WP_URL    = os.getenv("WP_URL", "https://belatri.info").rstrip("/")
USER      = os.getenv("WP_USERNAME")
APP_PW    = os.getenv("WP_APP_PASSWORD")
OPENKEY   = os.getenv("OPENAI_API_KEY")
POSTS_API = f"{WP_URL}/wp-json/wp/v2/posts"
TAGS_API  = f"{WP_URL}/wp-json/wp/v2/tags"

if not all([USER, APP_PW, OPENKEY]):
    sys.exit("❌ 필수 환경변수(WP_USERNAME, WP_APP_PASSWORD, OPENAI_API_KEY)가 누락되었습니다.")

# ────────── GPT 프롬프트 ──────────
MASTER_PROMPT = """
당신은 ‘벨라트리(Belatri)’ 블로그의 **벨라루스 맛집 소개** SEO 메타데이터 어시스턴트입니다.  
아래 규칙을 **반드시** 지켜주세요:

1. **언어 & 문체**  
   - 모든 한국어 문장은 친근한 대화체(~요·~네요)로 작성합니다.  
   - AI 티 나는 표현·낚시성 문장 금지.

2. **초점 키프레이즈 (focus_keyphrase)**  
   - 3–7어절 이내로 구성하세요.  
   - ‘벨라루스 맛집’, ‘현지인 추천 맛집’, ‘브레스트 레스토랑’ 등 실제 검색어 포함

3. **SEO 제목 (seo_title)**  
   - 45자 이내, 핵심 키워드를 앞쪽에 배치하세요.  
   - 이모지·특수문자 제외.

4. **슬러그 (slug)**  
   - 한글 소문자 + 하이픈(-) 조합, 최대 60바이트.  
   - 핵심 키워드 포함

5. **메타 설명 (meta_description)**  
   - 140~155자, 맛집의 특징, 추천 메뉴, 분위기 등 포함

6. **추천 태그 (tags)**  
   - 최소 6개
   - [지역] 예: 민스크, 브레스트, 고멜, 그로드노, 비텝스크, 모길료프
   - [유형] 예: 분위기맛집, 현지인추천, 데이트코스, 브런치카페

7. **아래 JSON 스키마만 반환**:

```json
{
  "title": "...",               
  "tags": ["...", "..."],       
  "focus_keyphrase": "...",     
  "seo_title": "...",           
  "slug": "...",                
  "meta_description": "..."     
}
```
"""

# ────────── GPT JSON 보정 ──────────
def extract_json(raw: str) -> dict:
    m = re.search(r"(\{[\s\S]*\})", raw)
    if not m:
        raise ValueError("JSON 블록을 찾을 수 없습니다.")
    return json.loads(m.group(1))

# ────────── GPT 호출 ──────────
def _gpt(prompt: str) -> dict:
    headers = {
        "Authorization": f"Bearer {OPENKEY}",
        "Content-Type":  "application/json",
    }
    last_err = None

    for attempt in range(3):
        messages = [
            {"role": "system", "content": MASTER_PROMPT},
            {"role": "user", "content": prompt}
        ]
        if attempt > 0:
            messages.insert(1, {
                "role": "system",
                "content": "응답을 순수 JSON 구조로만 다시 보내주세요."
            })

        try:
            resp = requests.post(
                "https://api.openai.com/v1/chat/completions",
                headers=headers,
                json={
                    "model": "gpt-4o",
                    "messages": messages,
                    "temperature": 0.4,
                    "max_tokens": 400
                },
                timeout=60
            )
            resp.raise_for_status()
            content = resp.json()["choices"][0]["message"]["content"]
            try:
                return json.loads(content)
            except json.JSONDecodeError:
                return extract_json(content)
        except Exception as e:
            last_err = e
            logging.warning(f"GPT 응답 파싱 실패 (시도 {attempt+1}): {e}")
            time.sleep(1)

    raise RuntimeError(f"GPT JSON 파싱 재시도 실패: {last_err}")

# ────────── 메타 생성 ──────────
def generate_meta(article: dict) -> dict:
    text    = BeautifulSoup(article["html"], "html.parser").get_text(" ", strip=True)
    snippet = re.sub(r"\s+", " ", text)[:600]

    prompt = f"기사 제목: {article['title']}\n기사 본문 일부: {snippet}"
    meta = _gpt(prompt)

    meta['slug'] = slugify(meta.get('slug', ''), lowercase=True, allow_unicode=False)[:60]
    if len(meta.get("meta_description", "")) > 155:
        meta["meta_description"] = meta["meta_description"][:154].rstrip() + "…"

    return meta

# ────────── 태그 동기화 ──────────
def sync_tags(names: list[str]) -> list[int]:
    logging.debug(f"[sync_tags] 호출 (UTC): {datetime.datetime.utcnow().isoformat()}")
    logging.debug(f"[sync_tags] USER: {bool(USER)}, APP_PW: {bool(APP_PW)}")

    clean_names = [re.sub(r"<[^>]+>", "", n).strip() for n in names if n.strip()]

    resp = requests.get(TAGS_API, params={"per_page": 100}, auth=(USER, APP_PW))
    resp.raise_for_status()
    existing = {t["name"]: t["id"] for t in resp.json()}

    ids = []
    for name in clean_names:
        if name in existing:
            ids.append(existing[name])
            continue

        payload = {"name": name, "slug": slugify(name, lowercase=True, allow_unicode=False)}
        r = requests.post(TAGS_API, auth=(USER, APP_PW), json=payload)
        if r.ok:
            ids.append(r.json()["id"])
        else:
            r2 = requests.get(TAGS_API, params={"search": name}, auth=(USER, APP_PW))
            if r2.ok and r2.json():
                ids.append(r2.json()[0]["id"])
            else:
                logging.error(f"태그 '{name}' 생성/검색 실패")
    return ids

# ────────── 메타 + 태그 업로드 ──────────
def push_meta(post_id: int, meta: dict):
    payload = {
        "slug":  meta["slug"],
        "title": meta.get("title", ""),
        "tags":  sync_tags(meta.get("tags", [])),
        "meta": {
            "_yoast_wpseo_focuskw":  meta.get("focus_keyphrase", ""),
            "_yoast_wpseo_title":    meta.get("seo_title", ""),
            "_yoast_wpseo_metadesc": meta.get("meta_description", "")
        }
    }
    r = requests.post(f"{POSTS_API}/{post_id}", json=payload, auth=(USER, APP_PW), timeout=20)
    r.raise_for_status()
    logging.debug(f"🎯 Yoast PATCH 응답: {r.status_code}")

# ────────── 처리 루프 (예시) ──────────
def main():
    new_posts = fetch_new_posts_from_udf()  # ← 외부 정의 필요
    for post in new_posts:
        try:
            meta = generate_meta({"html": post["html"], "title": post["title"]})
            push_meta(post["id"], meta)
            time.sleep(1)
        except Exception as e:
            logging.error(f"❌ 포스트 {post['id']} 메타 적용 실패: {e}")

if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)
    main()

