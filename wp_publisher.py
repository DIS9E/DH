#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
WordPress 자동 업로드 모듈 (게시만 담당)
• 대표 이미지 업로드
• 슬러그 생성
• 상세 오류 로깅 (상태코드/본문)
• 태그/메타는 yoast_meta.py에서 별도로 적용
"""

import os
import logging
import requests
from requests.auth import HTTPBasicAuth
from slugify import slugify

__all__ = ["publish_post"]

# ────────── 환경 변수 ──────────
WP_URL          = os.getenv("WP_URL")               # ex) https://belatri.info
WP_USERNAME     = os.getenv("WP_USERNAME")          # 워드프레스 사용자명
WP_APP_PASSWORD = os.getenv("WP_APP_PASSWORD")      # 앱 비밀번호


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


def _auth() -> HTTPBasicAuth:
    return HTTPBasicAuth(WP_USERNAME, WP_APP_PASSWORD)


def _auth_check() -> None:
    """인증/엔드포인트 사전 점검: 실패해도 치명적이진 않지만 원인 파악에 도움."""
    try:
        url = f"{WP_URL}/wp-json/wp/v2/users/me"
        r = requests.get(url, auth=_auth(), timeout=20)
        logging.info(f"[wp] auth check {url} → {r.status_code}")
        # 401/403 이면 인증 문제 가능성 높음. 본문 일부 로깅
        if r.status_code >= 400:
            logging.warning(f"[wp] auth check 응답: {r.text[:300]}")
    except Exception as e:
        logging.warning(f"[wp] auth check 예외: {e}")


def upload_image_to_wp(image_url: str, auth) -> int | None:
    """이미지 URL을 WP에 업로드하고, 미디어 ID를 반환"""
    try:
        r = requests.get(image_url, timeout=30)
        r.raise_for_status()
        filename = os.path.basename(image_url.split("?")[0]) or "featured.jpg"
        headers = {
            "Content-Disposition": f"attachment; filename={filename}",
            "Content-Type": r.headers.get("Content-Type", "image/jpeg"),
        }
        media_endpoint = f"{WP_URL}/wp-json/wp/v2/media"
        up = requests.post(media_endpoint, headers=headers, data=r.content, auth=auth, timeout=60)
        logging.info(f"[upload_image] POST {media_endpoint} → {up.status_code}")
        if up.status_code != 201:
            logging.error(f"[upload_image] 실패 본문: {up.text[:500]}")
            return None
        media_id = up.json().get("id")
        logging.info(f"[upload_image] 성공: {filename} → ID {media_id}")
        return media_id
    except Exception as e:
        logging.error(f"[upload_image] 예외: {e}", exc_info=True)
        return None


def publish_post(
    title: str,
    content: str,
    category_id: int | None = None,
    image_url: str | None = None,
    menu_items: list | None = None,   # 현재는 사용하지 않지만 시그니처 유지
    reviews: list | None = None,      # 현재는 사용하지 않지만 시그니처 유지
):
    """
    글 작성 + (선택) 대표 이미지 설정.
    태그/메타는 게시 후 yoast_meta.py의 push_meta()에서 처리.
    """
    if not _check_env():
        return None

    auth = _auth()
    _auth_check()

    # 1) slug 생성 (ASCII)
    slug = slugify(title, separator="-", lowercase=True)

    # 2) post_data 준비 (태그 넣지 않음)
    post_data = {
        "title": title,
        "content": content,
        "status": "publish",
        "slug": slug,
        "categories": [category_id] if category_id else [],
    }

    # 3) 대표 이미지 업로드 (선택)
    if image_url:
        media_id = upload_image_to_wp(image_url, auth)
        if media_id:
            post_data["featured_media"] = media_id

    # 4) 게시
    endpoint = f"{WP_URL}/wp-json/wp/v2/posts"
    try:
        resp = requests.post(endpoint, json=post_data, auth=auth, timeout=60)
        logging.info(f"[publish_post] POST {endpoint} → {resp.status_code}")
        if resp.status_code == 201:
            logging.info(f"[publish_post] 게시 성공: {title}")
            return resp.json()
        else:
            # 실패 사유를 정확히 보기 위해 본문 최대 1000자 로그
            body = resp.text
            logging.error(f"[publish_post] 게시 실패 상태: {resp.status_code}")
            logging.error(f"[publish_post] 실패 본문: {body[:1000]}")
            return None
    except Exception as e:
        logging.error(f"[publish_post] 예외: {e}", exc_info=True)
        return None
