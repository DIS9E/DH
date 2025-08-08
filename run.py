#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
run.py – 전체 파이프라인 실행기
1. koko_crawler로 URL 수집
2. parser로 정보 파싱
3. content_rewriter로 한국어 재작성
4. wp_publisher로 글 업로드 + SEO 공개 태그 자동 삽입
5. yoast_meta로 SEO 메타 적용
"""

import os
import logging
from koko_crawler import crawl_cafehouse_pages
from parser import parse_post
from content_rewriter import rewrite_content
from wp_publisher import publish_post
from yoast_meta import generate_meta, push_meta

# ────────── 설정 ──────────
logging.basicConfig(level=logging.INFO)
CATEGORY_ID = int(os.getenv("WP_CAFE_CATEGORY_ID", 0))  # 민스크 맛집 > 카페 카테고리 ID


def main():
    posts = crawl_cafehouse_pages()
    for post in posts:
        url = post.get("url")
        title = post.get("title")
        logging.info(f"[run] 처리 시작: {title} ({url})")

        # 1) 데이터 파싱
        data = parse_post(url)
        if not data:
            logging.warning(f"[run] 파싱 실패: {url}")
            continue

        # 2) 콘텐츠 재작성
        content = rewrite_content(data)

        # 3) 워드프레스 업로드
        wp_res = publish_post(
            title=data["title"],
            content=content,
            category_id=CATEGORY_ID,
            image_url=(data.get("images") or [None])[0],
            menu_items=data.get("menu_items"),
            reviews=data.get("reviews")
        )
        if not wp_res:
            logging.error(f"[run] 게시 실패: {title}")
            continue

        post_id = wp_res.get("id")

        # 4) SEO 메타 적용
        try:
            meta = generate_meta({"html": content, "title": data["title"]})
            push_meta(post_id, meta)
            logging.info(f"[run] 메타 적용 성공: post_id={post_id}")
        except Exception as e:
            logging.error(f"[run] 메타 적용 실패 (post_id={post_id}): {e}", exc_info=True)


if __name__ == "__main__":
    main()
