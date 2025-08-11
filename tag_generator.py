#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
본문/제목/메뉴/리뷰에서 바로 키워드를 추출해 태그를 생성합니다.
- 하드코딩된 카테고리/사전 없이, uni/bigram 빈도 기반 추출
- 러시아어/한국어/영어 혼합 텍스트 지원(불용어 제거 + 길이 필터)
"""

import re
from typing import List, Dict
from bs4 import BeautifulSoup

# 최소 불용어 셋 (과적용 방지)
RU_STOP = {
    "и","в","во","не","что","он","на","я","с","со","как","а","то","все","она","так","его","но","да","ты",
    "к","у","же","вы","за","бы","по","ее","мне","было","были","ни","если","или","же","чем","без","при",
    "это","этот","эта","эти","там","тут","тогда","где","когда","мы","они","быть","есть","нет","для","про",
}
EN_STOP = {
    "the","a","an","and","or","of","to","in","on","at","for","by","with","is","are","was","were","be","as","it",
    "this","that","these","those","from","into","about","over","under","out","up","down",
}
KR_STOP = {
    "있다","없다","하다","했다","하는","그리고","그러나","하지만","또한","등","것","수","이","그","저","요","네요",
    "에서","으로","부터","까지","에게","보다","의","에",
    "는","은","이","가","을","를","와","과","도","만","다","같은","정도","또","또는",
}
STOP = RU_STOP | EN_STOP | KR_STOP


def _normalize_text(title: str, html: str, menus: List[str], reviews: List[str]) -> str:
    txt = (title or "") + " "
    txt += BeautifulSoup(html or "", "html.parser").get_text(" ", strip=True)
    if menus:
        txt += " " + " ".join(menus)
    if reviews:
        txt += " " + " ".join(reviews)
    return re.sub(r"\s+", " ", txt).strip()


def _tokens(text: str) -> List[str]:
    # 한글/키릴/라틴/숫자 토큰
    raw = re.findall(r"[0-9A-Za-zА-Яа-яЁё가-힣]+", text)
    toks = [t.lower() for t in raw]
    # 길이 2 미만 + 불용어 제거
    return [t for t in toks if len(t) >= 2 and t not in STOP]


def _ngrams(tokens: List[str], n: int) -> List[str]:
    grams: List[str] = []
    for i in range(len(tokens) - n + 1):
        piece = tokens[i:i+n]
        if all(p in STOP for p in piece):
            continue
        grams.append(" ".join(piece))
    return grams


def _score_keywords(tokens: List[str], top_k: int = 12) -> List[str]:
    # unigram / bigram 빈도 합산 (bigram 가중치↑)
    uni: Dict[str, int] = {}
    bi:  Dict[str, int] = {}
    for w in tokens:
        uni[w] = uni.get(w, 0) + 1
    for g in _ngrams(tokens, 2):
        bi[g] = bi.get(g, 0) + 1

    scores: Dict[str, float] = {}
    for w, c in uni.items():
        scores[w] = scores.get(w, 0) + c
    for g, c in bi.items():
        scores[g] = scores.get(g, 0) + c * 3  # bigram 가중치

    # 스코어↓, 길이 긴 표현 우선
    candidates = sorted(scores.items(), key=lambda kv: (-kv[1], -len(kv[0])))

    # 중복/부분문자열 제거(더 긴 구 우선 보존)
    chosen: List[str] = []
    for phrase, _ in candidates:
        if any(phrase in x or x in phrase for x in chosen):
            continue
        chosen.append(phrase)
        if len(chosen) >= top_k:
            break

    return [c.strip() for c in chosen if c.strip()]


def generate_tags_for_post(article: dict, limit: int = 12) -> List[str]:
    """
    입력:
        {
          "title": str,
          "content": html or text,
          "menu_items": [str],
          "reviews": [str]
        }
    출력: 본문 기반 태그 리스트(최대 limit)
    """
    text = _normalize_text(
        article.get("title", ""),
        article.get("content", ""),
        article.get("menu_items") or [],
        article.get("reviews") or [],
    )
    toks = _tokens(text)
    return _score_keywords(toks, top_k=limit)
