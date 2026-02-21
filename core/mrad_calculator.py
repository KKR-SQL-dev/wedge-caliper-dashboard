"""UWA / GWA / LWA 계산 모듈."""
from __future__ import annotations

import numpy as np
from scipy.stats import linregress

from config import MIL_TO_MM


def _resolve_abs_range(
    rel_bot_mm: float,
    rel_top_mm: float,
    thin_edge_pos_mm: float,
    direction: str,
) -> tuple[float, float]:
    """thin edge 기준 상대 거리를 절대 위치(mm)로 변환.

    left:  thin edge가 왼쪽 → 오른쪽으로 +
    right: thin edge가 오른쪽 → 왼쪽으로 -

    Returns:
        (abs_lo, abs_hi) – 항상 abs_lo < abs_hi
    """
    if direction == "left":
        return thin_edge_pos_mm + rel_bot_mm, thin_edge_pos_mm + rel_top_mm
    else:
        return thin_edge_pos_mm - rel_top_mm, thin_edge_pos_mm - rel_bot_mm


def calc_uwa(
    positions_mm: np.ndarray,
    cals_mil: np.ndarray,
    thin_edge_pos_mm: float,
    flat_start_pos_mm: float,
) -> float:
    """UWA: 전체 wedge 구간(thin edge ~ flat start) 기울기 (mrad).

    선형회귀로 기울기를 구한 뒤 mrad로 변환.
    항상 양수 (웨지 기울기 크기).
    """
    lo = min(thin_edge_pos_mm, flat_start_pos_mm)
    hi = max(thin_edge_pos_mm, flat_start_pos_mm)
    mask = (positions_mm >= lo) & (positions_mm <= hi)
    pos = positions_mm[mask]
    cal = cals_mil[mask]
    if len(pos) < 2:
        return 0.0
    slope, _, _, _, _ = linregress(pos, cal)
    return abs(slope * MIL_TO_MM * 1000.0)


def calc_gwa(
    positions_mm: np.ndarray,
    cals_mil: np.ndarray,
    gwa_bot_mm: float,
    gwa_top_mm: float,
    thin_edge_pos_mm: float,
    direction: str = "left",
) -> float:
    """GWA: GWA 영역 전체의 기울기 (mrad).

    선형회귀로 계산, 항상 양수.
    direction='right'이면 thin edge에서 왼쪽으로 거리를 계산.
    """
    abs_lo, abs_hi = _resolve_abs_range(
        gwa_bot_mm, gwa_top_mm, thin_edge_pos_mm, direction
    )
    mask = (positions_mm >= abs_lo) & (positions_mm <= abs_hi)
    pos = positions_mm[mask]
    cal = cals_mil[mask]
    if len(pos) < 2:
        return 0.0
    slope, _, _, _, _ = linregress(pos, cal)
    return abs(slope * MIL_TO_MM * 1000.0)


def calc_lwa(
    positions_mm: np.ndarray,
    cals_mil: np.ndarray,
    hud_bot_mm: float,
    hud_top_mm: float,
    thin_edge_pos_mm: float,
    direction: str = "left",
    window_mm: float = 40.0,
) -> tuple[np.ndarray, np.ndarray]:
    """LWA: +/-window_mm 슬라이딩 윈도우로 로컬 기울기 계산.

    direction='right'이면 thin edge에서 왼쪽으로 거리를 계산하고
    기울기 부호를 반전하여 양의 웨지 방향으로 보고.

    Returns:
        (center_positions_mm, lwa_mrad) – HUD 영역 내 각 포인트의 로컬 기울기
    """
    abs_lo, abs_hi = _resolve_abs_range(
        hud_bot_mm, hud_top_mm, thin_edge_pos_mm, direction
    )

    hud_mask = (positions_mm >= abs_lo) & (positions_mm <= abs_hi)
    hud_pos = positions_mm[hud_mask]

    centers = []
    slopes = []

    for cp in hud_pos:
        win_mask = (positions_mm >= cp - window_mm) & (positions_mm <= cp + window_mm)
        wp = positions_mm[win_mask]
        wc = cals_mil[win_mask]
        if len(wp) < 2:
            continue
        slope, _, _, _, _ = linregress(wp, wc)
        mrad_val = slope * MIL_TO_MM * 1000.0
        if direction == "right":
            mrad_val = -mrad_val
        centers.append(cp)
        slopes.append(mrad_val)

    return np.array(centers), np.array(slopes)


def judge_gwa(gwa_mrad: float, target_mrad: float, tolerance: float = 0.03) -> str:
    """GWA 판정: target +/- tolerance."""
    if abs(gwa_mrad - target_mrad) <= tolerance:
        return "PASS"
    return "FAIL"


def judge_lwa(
    lwa_mrad: np.ndarray, target_mrad: float, tolerance: float = 0.15
) -> tuple[str, int]:
    """LWA 판정: 모든 포인트가 target +/- tolerance 이내인지.

    Returns:
        (overall_result, fail_count)
    """
    deviations = np.abs(lwa_mrad - target_mrad)
    fail_count = int(np.sum(deviations > tolerance))
    return ("PASS" if fail_count == 0 else "FAIL", fail_count)
