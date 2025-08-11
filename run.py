#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import time
import logging

from koko_crawler import crawl_cafehouse_pages
from parser import parse_post
from content_rewriter import rewrite_content
from wp_publisher import publish_post
from yoast_meta import generate_meta, push_meta

logging.basicConfig(level=logging.INFO)
CATEGORY_ID = int(os.getenv("WP_CAFE_CATEGORY_ID", "0"))  # 필요 없으면 0

def main():
    posts = crawl_cafehouse_pages()
    for post in posts:
        url = post.get("url")
        title = post.get("title")
        logging.info(f"[run] 처리 시작: {title} ({url})")

        # 1) 파싱
        data = parse_post(url)
        if not data:
            logging.warning(f"[run] 파싱 실패: {url}")
            continue

        # 2) 재작성
        content = rewrite_content(data)

        # 3) 게시 (태그/메타는 아직 X)
        image_url = (data.get("images") or [None])[0]
        wp_res = publish_post(
            title=data["title"],
            content=content,
            category_id=CATEGORY_ID if CATEGORY_ID else None,
            image_url=image_url,
            menu_items=data.get("menu_items"),
            reviews=data.get("reviews"),
        )
        if not wp_res:
            logging.error(f"[run] 게시 실패: {data['title']}")
            continue

        post_id = wp_res.get("id")

        # 4) 메타/태그 생성 & 적용 (yoast_meta에서 처리)
        try:
            meta = generate_meta({"html": content, "title": data["title"]})
            push_meta(post_id, meta)
            logging.info(f"[run] 메타 적용 성공: post_id={post_id}")
        except Exception as e:
            logging.error(f"[run] 메타 적용 실패 (post_id={post_id}): {e}", exc_info=True)

        time.sleep(0.5)

if __name__ == "__main__":
    main()
