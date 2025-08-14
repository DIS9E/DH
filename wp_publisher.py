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

__all__ = ["publish_post", "wp_selftest"]

# ────────── 환경 변수 ──────────
WP_URL          = (os.getenv("WP_URL") or "").strip().rstrip("/")      # ex) https://belatri.info
WP_USERNAME     = (os.getenv("WP_USERNAME") or "").strip()             # 로그인 ID (공백/개행 제거)
WP_APP_PASSWORD = (os.getenv("WP_APP_PASSWORD") or "").strip()         # 앱 비밀번호 (공백/개행 제거)

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
    """
    Application Password 인증 자가 테스트.
    - /users/me 200이면 대체로 정상.
    - 401/403/리버스프록시 문제는 본문 일부 로깅.
    """
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


def upload_image_to_wp(image_url: str, session: requests.Session) -> int | None:
    """이미지 URL을 WP에 업로드하고, 미디어 ID를 반환"""
    try:
        r = session.get(image_url, timeout=TIMEOUT_GET)
        r.raise_for_status()

        # 파일 확장자 필터링 (WP에서 막는 형식 제거)
        blocked_exts = [".svg", ".webp", ".avif", ".ico"]
        if any(image_url.lower().endswith(ext) for ext in blocked_exts):
            logging.warning(f"[upload_image] 지원하지 않는 이미지 포맷 건너뜀: {image_url}")
            return None

        filename = os.path.basename(image_url.split("?")[0]) or "featured.jpg"
        
        # Content-Type 강제 지정 (jpeg로 고정, 안정성 우선)
        headers = {
            "Content-Disposition": f"attachment; filename={filename}",
            "Content-Type": "image/jpeg"
        }

        media_endpoint = f"{WP_URL}/wp-json/wp/v2/media"
        up = session.post(media_endpoint, headers=headers, data=r.content, timeout=TIMEOUT_POST)
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

    session = _make_session()

    # 인증 사전 점검 (실패하면 바로 중단)
    if not wp_selftest(session):
        logging.error("[publish_post] 인증 실패: Application Password/서버 설정 확인 필요")
        return None

    # 1) slug 생성 (ASCII)
    slug = slugify(title, separator="-", lowercase=True)

    # 2) post_data 준비 (태그는 여기서 넣지 않음)
    post_data = {
        "title": title,
        "content": content,
        "status": "publish",
        "slug": slug,
        "categories": [category_id] if category_id else [],
    }

    # 3) 대표 이미지 업로드 (선택)
    if image_url:
        media_id = upload_image_to_wp(image_url, session)
        if media_id:
            post_data["featured_media"] = media_id

    # 4) 게시
    endpoint = f"{WP_URL}/wp-json/wp/v2/posts"
    try:
        resp = session.post(endpoint, json=post_data, timeout=TIMEOUT_POST)
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
