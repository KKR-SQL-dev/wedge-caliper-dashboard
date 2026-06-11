"""완성 타겟 프로파일 임포트 모듈.

data/targets/ 폴더의 CSV/Excel 파일에서 제품별 449 bin 타겟을 로드.
파라미터 재생성 없이 저장값 그대로 사용.

지원 형식:
  CSV: Bin, Position_mm, {제품코드}_target_mil, ... (449행)
  Excel: 시트별 또는 컬럼별 제품 (동일 구조)

레시피 매칭:
  정규화된 제품코드로 매칭 (recipe_matcher 사용).
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from config import NUM_BINS

_TARGETS_DIR = Path(__file__).resolve().parent.parent / "data" / "targets"

# 캐시: {product_code: np.ndarray(449,)}
_cache: dict[str, np.ndarray] = {}
_loaded = False


def _parse_code_from_col(col_name: str) -> str:
    """컬럼명에서 제품코드 추출. 예: 'W2264AD_target_mil' → 'W2264AD'."""
    s = str(col_name).strip()
    # _target_mil, _mil, _target 접미사 제거
    for suffix in ("_target_mil", "_mil", "_target"):
        if s.lower().endswith(suffix):
            s = s[: -len(suffix)]
            break
    return s.strip()


def _load_all():
    """data/targets/ 폴더의 모든 CSV/Excel에서 타겟 로드."""
    global _loaded
    _cache.clear()

    if not _TARGETS_DIR.exists():
        _loaded = True
        return

    # CSV 파일
    for f in sorted(_TARGETS_DIR.glob("*.csv")):
        try:
            df = pd.read_csv(f)
            _import_df(df, f.name)
        except Exception:
            pass

    # Excel 파일
    for f in sorted(_TARGETS_DIR.glob("*.xlsx")):
        try:
            xls = pd.ExcelFile(f)
            for sheet in xls.sheet_names:
                df = pd.read_excel(f, sheet_name=sheet)
                _import_df(df, f"{f.name}:{sheet}")
        except Exception:
            pass

    _loaded = True


def _import_df(df: pd.DataFrame, source: str):
    """DataFrame에서 제품별 449 bin 타겟 추출."""
    if len(df) < NUM_BINS:
        return

    # 첫 NUM_BINS 행만 사용
    df = df.head(NUM_BINS)

    # Bin, Position_mm 등 메타 컬럼 제외, 나머지가 제품 타겟
    skip_cols = {"bin", "position_mm", "position", "slice", "slice_no"}
    for col in df.columns:
        if col.lower().strip() in skip_cols:
            continue
        vals = pd.to_numeric(df[col], errors="coerce").values
        if np.all(np.isnan(vals)):
            continue

        code = _parse_code_from_col(col)
        if not code:
            continue

        # 449개 값 → numpy array
        target = np.full(NUM_BINS, np.nan)
        n = min(len(vals), NUM_BINS)
        target[:n] = vals[:n]
        _cache[code] = target


def get_imported_target(product_code: str) -> np.ndarray | None:
    """제품코드로 임포트된 449 bin 타겟 반환. 없으면 None."""
    if not _loaded:
        _load_all()
    return _cache.get(product_code)


def match_imported_target(recipe: str, master_keys: list[str] = None) -> tuple[str | None, np.ndarray | None]:
    """레시피 문자열로 임포트된 타겟 매칭 시도.

    1. 정확한 코드 매칭
    2. recipe_matcher로 정규화 매칭

    Returns:
        (matched_code, target_449) 또는 (None, None)
    """
    if not _loaded:
        _load_all()

    if not _cache:
        return None, None

    # 1. 정확 매칭
    if recipe in _cache:
        return recipe, _cache[recipe]

    # 2. 정규화 매칭 (recipe_matcher 사용)
    from core.recipe_matcher import match_recipe
    cache_keys = list(_cache.keys())
    result = match_recipe(recipe, cache_keys)
    if result:
        return result.master_key, _cache[result.master_key]

    return None, None


def list_imported_products() -> list[str]:
    """임포트된 제품코드 목록."""
    if not _loaded:
        _load_all()
    return sorted(_cache.keys())


def reload():
    """캐시 초기화 + 재로드."""
    global _loaded
    _loaded = False
    _load_all()
