#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
WordPress 자동 업로드 모듈 (게시만 담당)
• 대표 이미지 업로드
• 슬러그 생성
• 태그/메타는 yoast_meta.py에서 처리
"""

import os
import requests
from requests.auth import HTTPBasicAuth
from slugify import slugify

# ────────── 환경 변수 ──────────
WP_URL          = os.getenv("WP_URL")               # ex) https://belatri.info
WP_USERNAME     = os.getenv("WP_USERNAME")          # 워드프레스 사용자명
WP_APP_PASSWORD = os.getenv("WP_APP_PASSWORD")      # 앱 비밀번호


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
        up.raise_for_status()
        media_id = up.json().get("id")
        print(f"[upload_image] 성공: {filename} → ID {media_id}")
        return media_id
    except Exception as e:
        print(f"[upload_image] 오류: {e}")
        return None


def publish_post(
    title: str,
    content: str,
    category_id: int | None = None,
    image_url: str | None = None,
    menu_items: list | None = None,
    reviews: list | None = None,
):
    """글 작성 + (선택) 대표 이미지 설정. 태그/메타는 나중에 yoast_meta에서 업데이트."""
    auth = HTTPBasicAuth(WP_USERNAME, WP_APP_PASSWORD)

    # 1) slug 생성
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
    resp = requests.post(endpoint, json=post_data, auth=auth, timeout=60)
    if resp.status_code == 201:
        print(f"[publish_post] 게시 성공: {title}")
        return resp.json()
    else:
        print(f"[publish_post] 게시 실패({resp.status_code}): {resp.text}")
        return None
