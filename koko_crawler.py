#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
parser.py – 상세 페이지 파싱기

• URL 요청 → BeautifulSoup 파싱
• title, address, hours, map_html, excerpt, html, menu_items, reviews, images 반환
"""

import requests
from bs4 import BeautifulSoup

HEADERS = {"User-Agent": "Mozilla/5.0"}

def parse_post(url: str) -> dict:
    """
    아래 형식의 dict를 반환합니다. 실패 시에도 None이 아닌 dict로 반환하여
    run.py 측에서 파싱 실패가 뜨는 일을 막아 줍니다.
    {
      "url": url,
      "title": ...,
      "address": ...,
      "hours": ...,
      "map_html": ...,
      "excerpt": ...,
      "html": ...,
      "menu_items": [...],
      "reviews": [...],
      "images": [...]
    }
    """
    resp = requests.get(url, headers=HEADERS)
    # 요청 실패여도 None 대신 최소한의 빈 dict 반환
    if resp.status_code != 200:
        return {
            "url": url, "title": "", "address": "", "hours": "",
            "map_html": "", "excerpt": "", "html": "",
            "menu_items": [], "reviews": [], "images": []
        }

    soup = BeautifulSoup(resp.text, "html.parser")

    # 1) 제목
    title_tag = soup.select_one("h1.pagetitle.posttitle._js-pagetitle-text")
    title = title_tag.get_text(strip=True) if title_tag else ""

    # 2) 주소
    addr_tag = soup.find("div", class_="text")
    address = addr_tag.get_text(strip=True) if addr_tag else ""

    # 3) 영업시간 (주소 다음 div 중 'с','до' 포함된 것들만)
    hours_list = []
    if addr_tag:
        for sib in addr_tag.find_next_siblings("div"):
            txt = sib.get_text(" ", strip=True)
            if "с" in txt and "до" in txt:
                hours_list.append(txt)
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

    # 7) 메뉴·리뷰·이미지 (추후 CSS 선택자 확인 후 채워 주세요)
    menu_items = []  # 예: [li.get_text(strip=True) for li in soup.select("ul.menu-list li")]
    reviews    = []  # 예: [p.get_text(strip=True)  for p in soup.select("div.post-review p")]
    images     = []  # 예: [img["src"]              for img in soup.select("div.gallery img")]

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
    # 로컬 테스트용 예시
    example = "https://koko.by/cafehouse/13610-tako-burrito"
    from pprint import pprint
    pprint(parse_post(example))
