#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
내부용 태그 자동 생성 모듈
• GPT 호출 → 방문 목적·분위기·특성 기준 태그 JSON 반환
• 재시도 로직 포함
"""

import os
import time
import logging
import requests
import json
from slugify import slugify

# ────────── 환경 변수 ──────────
OPENAI_KEY = os.getenv("OPENAI_API_KEY")
GPT_MODEL  = "gpt-4o"  # 필요에 따라 조정

# ────────── GPT 프롬프트 ──────────
MASTER_PROMPT = """
당신은 ‘벨라트리(Belatri)’ 블로그의 내부 분류 태그 생성기입니다.
아래 규칙을 **반드시** 지켜주세요:

1. 입력된 맛집 정보(제목·본문·메뉴·리뷰 등)를 보고
2. 방문 목적(데이트·혼카페·업무)·분위기(조용한·북적이는)·특징(야외석·디저트 강추) 등을 기준으로
3. 최대 8개 이하의 **내부용 태그**를 JSON 배열 형태로 반환하세요.
4. 태그는 한글로, **공백 대신 하이픈(-)** 사용합니다.
5. 절대 본문에 노출되지 않으며, 내부 분류용임을 기억하세요.

예시 출력:
```json
["혼카페", "데이트-추천", "조용한-분위기", "야외-테라스", "디저트-강추"]
