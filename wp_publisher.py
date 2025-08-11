#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
WordPress 자동 업로드 모듈
• 본문 키워드 추출(tag_generator) → 태그 동기화(yoast_meta.sync_tags)
• 대표 이미지 업로드
• 슬러그 생성 후 게시
"""

import os
import requests
from requests.auth import HTTPBasicAuth
from slugify import slugify
from tag_generator import generate_tags_for_post
from yoast_meta import sync_tags


WP_URL          = (os.getenv("WP_URL") or "").rstrip("/")
WP_USERNAME     = os.getenv("WP_USERNAME")
WP_APP_PASSWORD = os.getenv("WP_APP_PASSWORD")


def _check_env():
    missing = []
    if not WP_URL:          missing.append("WP_URL")
    if not WP_USERNAME:     missing.append("WP_USERNAME")
    if not WP_APP_PASSWORD: missing.append("WP_APP_PASSWORD")
    if missing:
        raise RuntimeError(f"환경 변수 누락: {', '.join(missing)}")


def upload_image_to_wp(image_url: str, auth) -> int | None:
    """이미지 URL → WP 미디어 업로드 → 미디어 ID 반환"""
    try:
        r = requests.get(image_url, timeout=30)
        r.raise_for_status()
        filename = os.path.basename(image_url.split("?")[0]) or "image.jpg"
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
    reviews: list | None = None
):
    """
    글 작성 + (본문 기반) 태그 생성/동기화 + 대표 이미지 설정 + 게시
    """
    _check_env()
    auth = HTTPBasicAuth(WP_USERNAME, WP_APP_PASSWORD)

    # 1) 태그 생성(본문에서 직접 추출)
    article_data = {
        "title": title,
        "content": content,
        "menu_items": menu_items or [],
        "reviews": reviews or [],
    }
    tag_names = generate_tags_for_post(article_data)
    tag_ids   = sync_tags(tag_names)

    # 2) 슬러그
    slug = slugify(title, separator="-", lowercase=True)

    # 3) 게시 데이터
    post_data = {
        "title":      title,
        "content":    content,
        "status":     "publish",
        "slug":       slug,
        "categories": [category_id] if category_id else [],
        "tags":       tag_ids,
    }

    # 4) 대표 이미지
    if image_url:
        media_id = upload_image_to_wp(image_url, auth)
        if media_id:
            post_data["featured_media"] = media_id

    # 5) 게시
    endpoint = f"{WP_URL}/wp-json/wp/v2/posts"
    resp = requests.post(endpoint, json=post_data, auth=auth, timeout=60)
    if resp.status_code == 201:
        print(f"[publish_post] 게시 성공: {title}")
        return resp.json()
    else:
        print(f"[publish_post] 게시 실패({resp.status_code}): {resp.text}")
        return None
