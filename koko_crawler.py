#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
parser.py – 카페 상세 페이지 파서

반환 dict 키:
- url            : 상세 페이지 URL
- title          : 글 제목
- address        : 주소
- hours          : 영업시간 (리스트를 세미콜론으로 묶은 문자열)
- map_html       : <ymaps> 임베드 HTML
- excerpt        : 첫 줄 소개 (메타 설명용)
- html           : 본문 요약 HTML (<strong> 태그 포함)
- menu_items     : 메뉴 항목 리스트 (추후 CSS 확인)
- reviews        : 리뷰 리스트 (추후 CSS 확인)
- images         : 이미지 URL 리스트 (추후 CSS 확인)
"""

import requests
from bs4 import BeautifulSoup

HEADERS = {"User-Agent": "Mozilla/5.0"}

def parse_post(url: str) -> dict | None:
    resp = requests.get(url, headers=HEADERS)
    if resp.status_code != 200:
        return None
    soup = BeautifulSoup(resp.text, "html.parser")

    # 1) 제목
    title_tag = soup.select_one("h1.pagetitle.posttitle._js-pagetitle-text")
    title = title_tag.get_text(strip=True) if title_tag else ""

    # 2) 주소
    addr_tag = soup.find("div", class_="text")
    address = addr_tag.get_text(strip=True) if addr_tag else ""

    # 3) 영업시간 (주소 다음에 나오는 div 중 'с','до' 포함)
    hours_list = []
    if addr_tag:
        for sib in addr_tag.find_next_siblings("div"):
            text = sib.get_text(" ", strip=True)
            if "с" in text and "до" in text:
                hours_list.append(text)
            else:
                break
    hours = "; ".join(hours_list)

    # 4) 지도 임베드 (<ymaps> 태그 전체)
    map_tag = soup.find("ymaps")
    map_html = str(map_tag) if map_tag else ""

    # 5) 메타 설명용 소개 한 줄 (<span itemprop="name">)
    ex_tag = soup.select_one("span[itemprop='name']")
    excerpt = ex_tag.get_text(strip=True) if ex_tag else ""

    # 6) 본문 요약 HTML (<strong> 태그)
    strong_tag = soup.select_one("strong")
    html = str(strong_tag) if strong_tag else ""

    # 7) 메뉴·리뷰·이미지 (추후 CSS 확인 필요)
    menu_items = []  # e.g. [li.get_text() for li in soup.select("ul.menu-list li")]
    reviews    = []  # e.g. [p.get_text()  for p in soup.select("div.post-review p")]
    images     = []  # e.g. [img["src"]   for img in soup.select("div.gallery img")]

    return {
        "url":         url,
        "title":       title,
        "address":     address,
        "hours":       hours,
        "map_html":    map_html,
        "excerpt":     excerpt,
        "html":        html,
        "menu_items":  menu_items,
        "reviews":     reviews,
        "images":      images,
    }


if __name__ == "__main__":
    example_url = "https://koko.by/cafehouse/13610-tako-burrito"
    data = parse_post(example_url)
    from pprint import pprint
    pprint(data)
