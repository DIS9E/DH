# wp_publisher.py
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
WordPress 자동 업로드 모듈
• SEO 공개 태그 자동 생성 및 동기화
• 대표 이미지 업로드
• 슬러그 생성
"""

import os
import requests
from requests.auth import HTTPBasicAuth
from slugify import slugify
from tag_generator import generate_tags_for_post
from yoast_meta import sync_tags

# ────────── 환경 변수 ──────────
WP_URL          = os.getenv("WP_URL")               # ex) https://belatri.info
WP_USERNAME     = os.getenv("WP_USERNAME")          # 워드프레스 사용자명
WP_APP_PASSWORD = os.getenv("WP_APP_PASSWORD")      # 앱 비밀번호


def upload_image_to_wp(image_url: str, auth) -> int:
    """이미지 URL을 WP에 업로드하고, 미디어 ID를 반환"""
    img_resp = requests.get(image_url)
    img_resp.raise_for_status()
    img_data = img_resp.content
    filename = os.path.basename(image_url)
    headers = {
        "Content-Disposition": f"attachment; filename={filename}",
        # 서버에서 전달된 Content-Type 사용
        "Content-Type": img_resp.headers.get("Content-Type", "image/jpeg")
    }
    media_endpoint = f"{WP_URL}/wp-json/wp/v2/media"
    resp = requests.post(media_endpoint, headers=headers, data=img_data, auth=auth)
    resp.raise_for_status()
    media_id = resp.json().get("id")
    print(f"[upload_image] 성공: {filename} → ID {media_id}")
    return media_id


def publish_post(
    title: str,
    content: str,
    category_id: int = None,
    image_url: str = None,
    menu_items: list = None,
    reviews: list = None
):
    """글 작성 + SEO 공개 태그 생성·동기화 + 대표 이미지 설정"""
    auth = HTTPBasicAuth(WP_USERNAME, WP_APP_PASSWORD)

    # 1) SEO 공개 태그 생성 및 동기화
    article_data = {
        "title": title,
        "content": content,
        "menu_items": menu_items or [],
        "reviews": reviews or []
    }
    tag_names = generate_tags_for_post(article_data)
    tag_ids = sync_tags(tag_names)

    # 2) slug 생성
    slug = slugify(title, separator="-", lowercase=True)

    # 3) post_data 준비
    post_data = {
        "title":      title,
        "content":    content,
        "status":     "publish",
        "slug":       slug,
        "categories": [category_id] if category_id else [],
        "tags":       tag_ids
    }

    # 4) 대표 이미지 업로드
    if image_url:
        try:
            media_id = upload_image_to_wp(image_url, auth)
            post_data["featured_media"] = media_id
        except Exception as e:
            print(f"[publish_post] 이미지 업로드 오류: {e}")

    # 5) WP REST API로 게시
    endpoint = f"{WP_URL}/wp-json/wp/v2/posts"
    resp = requests.post(endpoint, json=post_data, auth=auth)
    if resp.status_code == 201:
        print(f"[publish_post] 게시 성공: {title}")
        return resp.json()
    else:
        print(f"[publish_post] 게시 실패({resp.status_code}): {resp.text}")
        return None

    
    if response.status_code == 201:
        print(f"✅ 게시 완료: {title}")
        return response.json()
    else:
        print(f"❌ 업로드 실패: {response.status_code} - {response.text}")
        return None

def upload_image_to_wp(image_url: str, auth) -> int:
    img_data = requests.get(image_url).content
    filename = image_url.split("/")[-1]
    
    headers = {
        "Content-Disposition": f"attachment; filename={filename}",
        "Content-Type": "image/jpeg"
    }
    
    media_endpoint = f"{WP_URL}/wp-json/wp/v2/media"
    response = requests.post(media_endpoint, headers=headers, data=img_data, auth=auth)
    
    if response.status_code == 201:
        image_id = response.json()["id"]
        print(f"🖼️ 이미지 업로드 성공: {filename} → ID {image_id}")
        return image_id
    else:
        print(f"❌ 이미지 업로드 실패: {response.status_code}")
        return None
