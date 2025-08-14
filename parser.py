#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Cafehouse 개별 글에서 정보 파싱
- 제목, 본문, 이미지, 주소, 시간, 전화번호, 리뷰, 메뉴, 지도 iframe 등 수집
- 예외 처리 및 크롤링 안정화 포함
"""

import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin
import re
import logging

def parse_post(url: str) -> dict | None:
    try:
        print(f"📄 파싱 중: {url}")
        r = requests.get(url, timeout=15)
        r.raise_for_status()

        soup = BeautifulSoup(r.text, "html.parser")

        # ────────── 제목 ──────────
        title_tag = soup.select_one("h1.entry-title")
        if not title_tag:
            logging.warning(f"[parser] 제목 태그 없음: {url}")
            return None
        title = title_tag.text.strip()

        # ────────── 본문 콘텐츠 ──────────
        content_div = soup.select_one("div.tdb_single_content")
        if not content_div:
            logging.warning(f"[parser] 본문 div 없음: {url}")
            return None

        # ────────── 이미지 수집 ──────────
        images = [img["src"] for img in content_div.select("img") if img.get("src")]

        # ────────── 주소/영업시간/전화 ──────────
        text_blocks = content_div.select("p")
        address = hours = phone = ""
        for p in text_blocks:
            txt = p.get_text(strip=True)
            if "Адрес" in txt or "ул." in txt:
                address = txt
            if "до" in txt and ":" in txt:
                hours = txt
            if "+375" in txt or txt.startswith("8 (0"):
                phone = txt

        # ────────── 메뉴 ──────────
        menu_items = []
        for li in content_div.select("ul li"):
            item = li.get_text(strip=True)
            if item and len(item) <= 100:
                menu_items.append(item)

        # ────────── 리뷰 ──────────
        reviews = []
        for p in content_div.select("p"):
            txt = p.get_text(strip=True)
            if 20 < len(txt) < 250 and any(word in txt.lower() for word in [
                "вкус", "уют", "кофе", "атмосфер", "обслужив", "приятн", "рекоменд", "заведение", "дизайн"
            ]):
                reviews.append(txt)

        # ────────── 지도 iframe ──────────
        iframe = soup.select_one("iframe")
        map_url = iframe["src"] if iframe and iframe.get("src") else None

        # ────────── 결과 반환 ──────────
        return {
            "title": title,
            "html": str(content_div),
            "images": images,
            "address": address,
            "hours": hours,
            "phone": phone,
            "menu_items": menu_items,
            "reviews": reviews,
            "map_url": map_url,
            "source_url": url,
        }
