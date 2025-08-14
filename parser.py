#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Cafehouse 개별 글에서 정보 파싱
- 제목, 본문, 이미지, 주소, 시간, 전화번호, 리뷰, 메뉴, 지도 iframe 등 수집
"""

import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin
import re

def parse_post(url: str) -> dict:
    print(f"📄 파싱 중: {url}")
    r = requests.get(url, timeout=10)
    soup = BeautifulSoup(r.text, "html.parser")

    title = soup.select_one("h1.entry-title").text.strip()
    content_div = soup.select_one("div.tdb_single_content")
    if not content_div:
        return {}

    # 이미지 수집
    images = [img["src"] for img in content_div.select("img") if img.get("src")]

    # 주소/시간/전화 파싱
    text_blocks = soup.select("div.tdb_single_content p")
    address = hours = phone = ""
    for p in text_blocks:
        txt = p.text.strip()
        if "Адрес" in txt or "ул." in txt:
            address = txt
        if "до" in txt and ":" in txt:
            hours = txt
        if "+375" in txt:
            phone = txt

    # 메뉴 추정
    menu_items = []
    for li in content_div.select("ul li"):
        item = li.text.strip()
        if item and len(item) <= 100:
            menu_items.append(item)

    # 리뷰 추정
    reviews = []
    for p in content_div.select("p"):
        txt = p.text.strip()
        if 20 < len(txt) < 200 and any(word in txt.lower() for word in ["вкус", "уют", "кофе", "атмосфер"]):
            reviews.append(txt)

    # 지도 iframe
    iframe = soup.select_one("iframe")
    map_url = iframe["src"] if iframe else None

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
