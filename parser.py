#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
WordPress 자동 업로드 모듈 (대표 이미지 없이, 본문 이미지만 삽입)
• 슬러그 생성 (한글 지원)
• 본문 상단에 이미지 삽입
• 지도 iframe 포함
• 상세 오류 로깅
• 태그/메타는 yoast_meta.py에서 별도로 적용
"""

import os
import logging
import requests
from requests.auth import HTTPBasicAuth
from slugify import slugify

__all__ = ["publish_post", "wp_selftest"]

# ────────── 환경 변수 ──────────
WP_URL          = (os.getenv("WP_URL") or "").strip().rstrip("/")      # ex) https://belatri.info
WP_USERNAME     = (os.getenv("WP_USERNAME") or "").strip()             # 로그인 ID
WP_APP_PASSWORD = (os.getenv("WP_APP_PASSWORD") or "").strip()         # 앱 비밀번호

# ────────── 설정 ──────────
UA = "BelatriBot/1.0 (+WP REST) requests"
TIMEOUT_GET  = 30
TIMEOUT_POST = 60

def _check_env() -> bool:
    ok = True
    if not WP_URL:
        logging.error("[wp] WP_URL 환경변수가 설정되지 않았습니다.")
        ok = False
    if not WP_USERNAME:
        logging.error("[wp] WP_USERNAME 환경변수가 설정되지 않았습니다.")
        ok = False
    if not WP_APP_PASSWORD:
        logging.error("[wp] WP_APP_PASSWORD 환경변수가 설정되지 않았습니다.")
        ok = False
    return ok

def _make_session() -> requests.Session:
    s = requests.Session()
    s.headers.update({"User-Agent": UA})
    s.auth = HTTPBasicAuth(WP_USERNAME, WP_APP_PASSWORD)
    return s

def wp_selftest(session: requests.Session | None = None) -> bool:
    try:
        sess = session or _make_session()
        url  = f"{WP_URL}/wp-json/wp/v2/users/me"
        r = sess.get(url, timeout=TIMEOUT_GET)
        logging.info(f"[wp_selftest] GET {url} → {r.status_code}")
        if r.status_code == 200:
            return True
        logging.error(f"[wp_selftest] 실패({r.status_code}): {r.text[:400]}")
        return False
    except Exception as e:
        logging.error(f"[wp_selftest] 예외: {e}", exc_info=True)
        return False

def publish_post(
    title: str,
    content: str,
    category_id: int | None = None,
    image_url: str | None = None,     # 무시됨
    menu_items: list | None = None,
    reviews: list | None = None,
    map_url: str | None = None,
    images: list | None = None,       # 본문 이미지 추가
):
    if not _check_env():
        return None

    session = _make_session()

    if not wp_selftest(session):
        logging.error("[publish_post] 인증 실패: Application Password/서버 설정 확인 필요")
        return None

    # 슬러그 생성
    slug = slugify(title, separator="-", lowercase=True, allow_unicode=True)

    # 본문 이미지 HTML (상단 삽입용)
    img_html = ""
    if images:
        for img_url in images:
            img_html += f'<p><img src="{img_url}" alt="{title}" style="max-width:100%; height:auto;"></p>\n'

    # 지도 삽입
    map_iframe = ""
    if map_url:
        map_iframe = f"""
<div style="margin-top:20px">
  <iframe src="{map_url}" width="100%" height="300" style="border:0;" allowfullscreen loading="lazy" referrerpolicy="no-referrer-when-downgrade"></iframe>
</div>
""".strip()

    # 최종 본문 구성
    full_content = f"{img_html}\n{content}\n\n{map_iframe}"

    # 게시물 데이터
    post_data = {
        "title": title,
        "content": full_content,
        "status": "publish",
        "slug": slug,
        "categories": [category_id] if category_id else [2437],  # 기본 카테고리
    }

    # 업로드 요청
    endpoint = f"{WP_URL}/wp-json/wp/v2/posts"
    try:
        resp = session.post(endpoint, json=post_data, timeout=TIMEOUT_POST)
        logging.info(f"[publish_post] POST {endpoint} → {resp.status_code}")
        if resp.status_code == 201:
            logging.info(f"[publish_post] 게시 성공: {title}")
            return resp.json()
        else:
            logging.error(f"[publish_post] 게시 실패 상태: {resp.status_code}")
            logging.error(f"[publish_post] 실패 본문: {resp.text[:1000]}")
            return None
    except Exception as e:
        logging.error(f"[publish_post] 예외: {e}", exc_info=True)
        return None

if __name__ == "__main__":
    sample = "https://koko.by/cafehouse/13610-tako-burrito"
    from pprint import pprint
    pprint(parse_post(sample))
