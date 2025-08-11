#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
wp_publisher.py — WordPress 업로드(게시만 담당)
- 태그/메타는 yoast_meta.generate_meta(), push_meta()에서 처리
- 여기서는 글 게시 + 대표 이미지 업로드만 수행
"""

import os
import requests
from requests.auth import HTTPBasicAuth
from slugify import slugify
from urllib.parse import urlparse
from typing import Optional, Dict, Any

# ────────── 환경 변수 ──────────
WP_URL          = (os.getenv("WP_URL") or "").rstrip("/")        # ex) https://belatri.info
WP_USERNAME     = os.getenv("WP_USERNAME")                       # 워드프레스 사용자명
WP_APP_PASSWORD = os.getenv("WP_APP_PASSWORD")                   # 앱 비밀번호

def _auth() -> HTTPBasicAuth:
    return HTTPBasicAuth(WP_USERNAME, WP_APP_PASSWORD)

def _media_endpoint() -> str:
    return f"{WP_URL}/wp-json/wp/v2/media"

def _posts_endpoint() -> str:
    return f"{WP_URL}/wp-json/wp/v2/posts"

def _guess_filename(image_url: str) -> str:
    try:
        path = urlparse(image_url).path
        name = os.path.basename(path)
        return name or "image.jpg"
    except Exception:
        return "image.jpg"

def upload_image_to_wp(image_url: str, auth: HTTPBasicAuth) -> Optional[int]:
    """
    이미지 URL을 다운로드 후 WP에 업로드하고, 성공 시 미디어 ID 반환
    실패 시 None
    """
    try:
        r = requests.get(image_url, timeout=20)
        r.raise_for_status()
        filename = _guess_filename(image_url)
        content_type = r.headers.get("Content-Type", "image/jpeg")

        headers = {
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Content-Type": content_type
        }
        up = requests.post(_media_endpoint(), headers=headers, data=r.content, auth=auth, timeout=30)
        if up.status_code == 201:
            media_id = up.json().get("id")
            print(f"[upload_image] 성공: {filename} → ID {media_id}")
            return media_id
        else:
            print(f"[upload_image] 업로드 실패({up.status_code}): {up.text[:200]}")
            return None
    except Exception as e:
        print(f"[upload_image] 오류: {e}")
        return None

def publish_post(
    title: str,
    content: str,
    category_id: Optional[int] = None,
    image_url: Optional[str] = None,
    status: str = "publish"
) -> Optional[Dict[str, Any]]:
    """
    글 작성 + (선택) 대표 이미지 설정만 수행
    - 태그는 여기서 다루지 않음 (yoast_meta.push_meta에서 처리)
    """
    if not WP_URL or not WP_USERNAME or not WP_APP_PASSWORD:
        print("[publish_post] 환경 변수(WP_URL/USERNAME/APP_PASSWORD) 누락")
        return None

    auth = _auth()

    # 1) 슬러그 생성 (게시 직전에 확정)
    slug = slugify(title, separator="-", lowercase=True)

    # 2) 기본 post payload
    post_data = {
        "title":      title,
        "content":    content,
        "status":     status,
        "slug":       slug,
        "categories": [category_id] if category_id else []
        # 태그는 비움: yoast_meta.push_meta()에서 생성/부착
    }

    # 3) 대표 이미지 업로드 (있으면)
    if image_url:
        media_id = upload_image_to_wp(image_url, auth)
        if media_id:
            post_data["featured_media"] = media_id

    # 4) 게시
    try:
        resp = requests.post(_posts_endpoint(), json=post_data, auth=auth, timeout=30)
        if resp.status_code == 201:
            print(f"[publish_post] 게시 성공: {title}")
            return resp.json()
        else:
            print(f"[publish_post] 게시 실패({resp.status_code}): {resp.text[:300]}")
            return None
    except Exception as e:
        print(f"[publish_post] 요청 오류: {e}")
        return None
