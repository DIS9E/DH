# wp_publisher.py

import os
import requests
from requests.auth import HTTPBasicAuth
from slugify import slugify

WP_URL = os.getenv("WP_URL")  # 예: https://belatri.info
WP_USERNAME = os.getenv("WP_USERNAME")
WP_APP_PASSWORD = os.getenv("WP_APP_PASSWORD")

def publish_post(title: str, content: str, category_id: int = None, tags: list = None, image_url: str = None):
    auth = HTTPBasicAuth(WP_USERNAME, WP_APP_PASSWORD)
    post_data = {
        "title": title,
        "content": content,
        "status": "publish",
        "slug": slugify(title, separator="-", lowercase=True),
        "categories": [category_id] if category_id else [],
        "tags": tags if tags else []
    }

    # 대표 이미지가 있을 경우 업로드
    if image_url:
        image_id = upload_image_to_wp(image_url, auth)
        if image_id:
            post_data["featured_media"] = image_id

    endpoint = f"{WP_URL}/wp-json/wp/v2/posts"
    response = requests.post(endpoint, json=post_data, auth=auth)
    
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
