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


# ══════════════════════════════════════════════════════════
# 멀티스캔 집계 (Avg / Worst / Last)
# ══════════════════════════════════════════════════════════

def calc_multi_scan_angles(
    positions_mm: np.ndarray,
    scans_mil: np.ndarray,
    product_layout: dict,
    product,
    side: str = "left",
) -> dict:
    """여러 스캔에 대해 UWA/GWA/LWA를 일괄 계산.

    Args:
        positions_mm: (449,) bin 위치
        scans_mil: (N, 449) 멀티스캔 데이터
        product_layout: 보정된 layout dict
        product: ProductMaster 인스턴스
        side: "left" 또는 "right"

    Returns:
        dict with uwa_values, gwa_values, lwa_worst_values (각각 ndarray, 스캔별)
    """
    n_scans = scans_mil.shape[0]
    target_wa = product.wedge_angle_mrad
    wp = product.wedge_portion_mm

    uwa_vals = np.zeros(n_scans)
    gwa_vals = np.full(n_scans, np.nan)
    lwa_worst_vals = np.full(n_scans, np.nan)  # 각 스캔의 LWA 중 타겟에서 최대 편차

    if side == "left":
        te_pos = product_layout["left_start_mm"]
        flat_pos = te_pos + wp
    else:
        te_pos = product_layout["right_end_mm"]
        flat_pos = te_pos - wp

    for i in range(n_scans):
        cal = scans_mil[i]

        # UWA
        uwa_vals[i] = calc_uwa(positions_mm, cal, min(te_pos, flat_pos), max(te_pos, flat_pos))

        # GWA
        if product.gwa_bot_mm and product.gwa_top_mm:
            gwa_vals[i] = calc_gwa(
                positions_mm, cal,
                product.gwa_bot_mm, product.gwa_top_mm, te_pos, side,
            )

        # LWA — worst deviation from target per scan
        if product.hud_bot_mm and product.hud_top_mm:
            _, lv = calc_lwa(
                positions_mm, cal,
                product.hud_bot_mm, product.hud_top_mm, te_pos, side,
            )
            if len(lv) > 0:
                deviations = np.abs(lv - target_wa)
                lwa_worst_vals[i] = lv[np.argmax(deviations)]

    return {
        "uwa": uwa_vals,
        "gwa": gwa_vals,
        "lwa_worst": lwa_worst_vals,
    }


def summarize_angles(
    angle_values: dict,
    target_mrad: float,
    gwa_tol: float = 0.03,
    lwa_tol: float = 0.15,
) -> dict:
    """멀티스캔 각도 값에서 Avg/Worst/Last + 판정 산출.

    Args:
        angle_values: calc_multi_scan_angles() 결과
        target_mrad: 타겟 웨지 앵글
        gwa_tol: GWA 톨러런스
        lwa_tol: LWA 톨러런스

    Returns:
        dict with:
            uwa: {avg, worst, last, worst_judge}
            gwa: {avg, worst, last, worst_judge}
            lwa: {avg, worst, last, worst_judge}
            n_scans: int
    """
    uwa = angle_values["uwa"]
    gwa = angle_values["gwa"]
    lwa = angle_values["lwa_worst"]

    n = len(uwa)
    result = {"n_scans": n}

    # UWA
    uwa_devs = np.abs(uwa - target_mrad)
    worst_idx = int(np.argmax(uwa_devs))
    result["uwa"] = {
        "avg": float(np.mean(uwa)),
        "worst": float(uwa[worst_idx]),
        "last": float(uwa[-1]) if n > 0 else 0.0,
        "worst_judge": "PASS" if uwa_devs[worst_idx] <= gwa_tol else "FAIL",
    }

    # GWA
    valid_gwa = gwa[~np.isnan(gwa)]
    if len(valid_gwa) > 0:
        gwa_devs = np.abs(valid_gwa - target_mrad)
        gwa_worst_idx = int(np.argmax(gwa_devs))
        result["gwa"] = {
            "avg": float(np.mean(valid_gwa)),
            "worst": float(valid_gwa[gwa_worst_idx]),
            "last": float(valid_gwa[-1]),
            "worst_judge": "PASS" if gwa_devs[gwa_worst_idx] <= gwa_tol else "FAIL",
        }
    else:
        result["gwa"] = None

    # LWA
    valid_lwa = lwa[~np.isnan(lwa)]
    if len(valid_lwa) > 0:
        lwa_devs = np.abs(valid_lwa - target_mrad)
        lwa_worst_idx = int(np.argmax(lwa_devs))
        result["lwa"] = {
            "avg": float(np.mean(valid_lwa)),
            "worst": float(valid_lwa[lwa_worst_idx]),
            "last": float(valid_lwa[-1]),
            "worst_judge": "PASS" if lwa_devs[lwa_worst_idx] <= lwa_tol else "FAIL",
        }
    else:
        result["lwa"] = None

    return result


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
