"""레시피 매칭 모듈 — 정규화 + 제품코드 기반 매칭.

SQL Recipe명과 마스터 레시피명이 글자 그대로 다를 수 있다.
예) "W2232 ALT 3CUT 0.34MRAD" ↔ "W2232ALT"  (공백/descriptor 차이)

전략:
  1. 정규화: 대문자, 공백 정리, 콤마→점
  2. 제품코드 추출: 앞쪽 [영문+숫자+변형코드], 뒤의 mrad/cut은 descriptor
  3. 코드 매칭: 코드가 같으면 매칭 (descriptor 생략 허용)
  4. Levenshtein 폴백: 편집거리 2 이내면 "추정 매칭"
  5. 실패 시 None
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional


@dataclass
class ParsedRecipe:
    """파싱된 레시피 정보."""
    raw: str            # 원본 문자열
    normalized: str     # 정규화된 전체 문자열
    product_code: str   # 제품코드 (매칭 키)
    mrad: Optional[float] = None   # 웨지 앵글 (있으면)
    cut_count: Optional[int] = None  # 컷 수 (있으면)


def normalize(raw: str) -> str:
    """정규화: 대문자, 콤마→점, 중복 공백 정리, 앞뒤 트림."""
    s = raw.upper().strip()
    s = s.replace(",", ".")  # 0,34 → 0.34
    s = re.sub(r"\s+", " ", s)  # 중복 공백 → 단일
    return s


def parse_recipe(raw: str) -> ParsedRecipe:
    """레시피 문자열을 파싱하여 제품코드 + descriptor 분리.

    예:
      "W2232 ALT 3CUT 0.34MRAD" → code="W2232ALT", mrad=0.34, cut=3
      "W2232ALT"                 → code="W2232ALT"
      "W2264 AD 2CUT 0.64MRAD"  → code="W2264AD", mrad=0.64, cut=2
    """
    norm = normalize(raw)
    parts = norm.split()

    code_parts = []
    mrad_val = None
    cut_val = None

    for p in parts:
        # N.NNMRAD 패턴
        m_mrad = re.match(r"^(\d+\.?\d*)MRAD$", p)
        if m_mrad:
            mrad_val = float(m_mrad.group(1))
            continue

        # NCUT 패턴
        m_cut = re.match(r"^(\d+)CUT$", p)
        if m_cut:
            cut_val = int(m_cut.group(1))
            continue

        # 나머지는 제품코드
        code_parts.append(p)

    product_code = "".join(code_parts)  # 공백 없이 합침

    return ParsedRecipe(
        raw=raw,
        normalized=norm,
        product_code=product_code,
        mrad=mrad_val,
        cut_count=cut_val,
    )


def _levenshtein(s1: str, s2: str) -> int:
    """편집 거리 (Levenshtein distance)."""
    if len(s1) < len(s2):
        return _levenshtein(s2, s1)
    if len(s2) == 0:
        return len(s1)
    prev = list(range(len(s2) + 1))
    for i, c1 in enumerate(s1):
        curr = [i + 1]
        for j, c2 in enumerate(s2):
            curr.append(min(
                prev[j + 1] + 1,    # 삭제
                curr[j] + 1,        # 삽입
                prev[j] + (c1 != c2),  # 교체
            ))
        prev = curr
    return prev[-1]


@dataclass
class MatchResult:
    """매칭 결과."""
    master_key: str          # 매칭된 마스터 키
    confidence: str          # "exact", "code", "fuzzy"
    message: str = ""        # 사용자 표시용 메시지


def match_recipe(
    sql_recipe: str,
    master_keys: list[str],
) -> Optional[MatchResult]:
    """SQL Recipe를 마스터 키 목록에서 매칭.

    Args:
        sql_recipe: SQL에서 읽은 Recipe 문자열
        master_keys: product_master.json의 키 목록

    Returns:
        MatchResult 또는 None (미매칭)
    """
    sql_parsed = parse_recipe(sql_recipe)
    sql_code = sql_parsed.product_code

    if not sql_code:
        return None

    # 마스터 키도 파싱하여 코드 추출 + 인덱스 구축
    master_codes: dict[str, str] = {}  # code → master_key
    for mk in master_keys:
        mk_parsed = parse_recipe(mk)
        master_codes[mk_parsed.product_code] = mk

    # 1단계: 정확 문자열 매칭 (원본 키)
    if sql_code in master_keys:
        return MatchResult(master_key=sql_code, confidence="exact")

    # 2단계: 제품코드 매칭 (양쪽 파싱된 코드 비교)
    if sql_code in master_codes:
        return MatchResult(
            master_key=master_codes[sql_code],
            confidence="code",
            message=f"코드 매칭: {sql_code}",
        )

    # 3단계: 한쪽이 다른쪽의 prefix인 경우
    for mc, mk in master_codes.items():
        if mc.startswith(sql_code) or sql_code.startswith(mc):
            return MatchResult(
                master_key=mk,
                confidence="code",
                message=f"코드 prefix 매칭: {sql_code} ↔ {mc}",
            )

    # 4단계: Levenshtein 퍼지 매칭 (편집거리 2 이내)
    best_dist = 999
    best_mk = None
    best_mc = None
    for mc, mk in master_codes.items():
        d = _levenshtein(sql_code, mc)
        if d < best_dist:
            best_dist = d
            best_mk = mk
            best_mc = mc

    if best_dist <= 2 and best_mk:
        return MatchResult(
            master_key=best_mk,
            confidence="fuzzy",
            message=f"추정 매칭: {sql_code} ≈ {best_mc} (편집거리 {best_dist}) — 맞나요?",
        )

    return None
