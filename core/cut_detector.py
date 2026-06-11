"""실측 데이터에서 컷지점(thin edge) 자동 검출 + 드리프트 오프셋 계산.

웨지 필름의 컷지점 = 미니멈 캘리퍼 위치 (thin edge).
2컷 제품: 좌측 thin edge(좌측 최소) + 우측 thin edge(우측 최소)
싱글컷: thin edge 1개

타겟 레이아웃의 thin edge 위치와 실측 thin edge 위치의 차이 = 드리프트(bin offset).
"""
from __future__ import annotations

import numpy as np
from scipy.signal import savgol_filter

from config import BIN_PITCH_MM, NUM_BINS


def _smooth(data: np.ndarray, window: int = 15) -> np.ndarray:
    """Savitzky-Golay 스무딩. NaN은 보간 후 처리."""
    clean = np.copy(data)
    nans = np.isnan(clean)
    if np.any(nans):
        clean[nans] = np.nanmean(clean)
    if len(clean) < window:
        return clean
    return savgol_filter(clean, window_length=window, polyorder=2)


def detect_thin_edges(
    actual_mil: np.ndarray,
    layout: dict,
    margin_bins: int = 15,
) -> dict:
    """실측 449 bin에서 thin edge(미니멈 캘리퍼) 위치를 검출.

    Args:
        actual_mil: 449 bin 실측 캘리퍼 (mil)
        layout: ProductMaster.layout() 결과 (타겟 배치 정보)
        margin_bins: 타겟 thin edge 주변 탐색 범위 (±bins)

    Returns:
        dict with:
            left_thin_edge_bin: int | None
            left_thin_edge_mm: float | None
            right_thin_edge_bin: int | None  (2컷만)
            right_thin_edge_mm: float | None (2컷만)
    """
    smoothed = _smooth(actual_mil)
    positions_mm = np.arange(NUM_BINS) * BIN_PITCH_MM

    result = {
        "left_thin_edge_bin": None,
        "left_thin_edge_mm": None,
        "right_thin_edge_bin": None,
        "right_thin_edge_mm": None,
    }

    # 좌측 thin edge 검출
    target_left_bin = layout["left_start_bin"]
    lo = max(0, target_left_bin - margin_bins)
    hi = min(NUM_BINS - 1, target_left_bin + margin_bins)
    if lo < hi:
        search = smoothed[lo:hi + 1]
        min_idx = lo + int(np.argmin(search))
        result["left_thin_edge_bin"] = min_idx
        result["left_thin_edge_mm"] = positions_mm[min_idx]

    # 우측 thin edge 검출 (2컷 계열만)
    if "right_end_bin" in layout:
        target_right_bin = layout["right_end_bin"]
        lo = max(0, target_right_bin - margin_bins)
        hi = min(NUM_BINS - 1, target_right_bin + margin_bins)
        if lo < hi:
            search = smoothed[lo:hi + 1]
            min_idx = lo + int(np.argmin(search))
            result["right_thin_edge_bin"] = min_idx
            result["right_thin_edge_mm"] = positions_mm[min_idx]

    return result


def calc_drift_offset(
    layout: dict,
    detected: dict,
) -> dict:
    """타겟 thin edge vs 실측 thin edge의 드리프트(오프셋) 계산.

    Returns:
        dict with:
            left_offset_bins: int (양수 = 실측이 타겟보다 오른쪽)
            left_offset_mm: float
            right_offset_bins: int | None
            right_offset_mm: float | None
    """
    result = {
        "left_offset_bins": 0,
        "left_offset_mm": 0.0,
        "right_offset_bins": None,
        "right_offset_mm": None,
    }

    if detected["left_thin_edge_bin"] is not None:
        target_bin = layout["left_start_bin"]
        actual_bin = detected["left_thin_edge_bin"]
        result["left_offset_bins"] = actual_bin - target_bin
        result["left_offset_mm"] = result["left_offset_bins"] * BIN_PITCH_MM

    if detected["right_thin_edge_bin"] is not None and "right_end_bin" in layout:
        target_bin = layout["right_end_bin"]
        actual_bin = detected["right_thin_edge_bin"]
        result["right_offset_bins"] = actual_bin - target_bin
        result["right_offset_mm"] = result["right_offset_bins"] * BIN_PITCH_MM

    return result


def apply_offset_to_layout(
    layout: dict,
    drift: dict,
    manual_left_adj: int = 0,
    manual_right_adj: int = 0,
) -> dict:
    """드리프트 오프셋 + 수동 보정을 적용한 새 레이아웃 반환.

    Args:
        layout: 원본 타겟 레이아웃
        drift: calc_drift_offset() 결과
        manual_left_adj: 수동 좌측 보정 (bins, +면 오른쪽)
        manual_right_adj: 수동 우측 보정 (bins, +면 오른쪽)

    Returns:
        보정된 layout dict (원본 구조 동일, 위치값만 이동)
    """
    left_total_bins = drift["left_offset_bins"] + manual_left_adj
    left_shift_mm = left_total_bins * BIN_PITCH_MM

    adjusted = dict(layout)  # shallow copy

    adjusted["left_start_mm"] = layout["left_start_mm"] + left_shift_mm
    adjusted["left_end_mm"] = layout["left_end_mm"] + left_shift_mm
    adjusted["left_start_bin"] = layout["left_start_bin"] + left_total_bins
    adjusted["left_end_bin"] = layout["left_end_bin"] + left_total_bins

    if "right_start_mm" in layout and layout["right_start_mm"] is not None:
        if drift["right_offset_bins"] is not None:
            right_total_bins = drift["right_offset_bins"] + manual_right_adj
        else:
            right_total_bins = manual_right_adj
        right_shift_mm = right_total_bins * BIN_PITCH_MM

        adjusted["right_start_mm"] = layout["right_start_mm"] + right_shift_mm
        adjusted["right_end_mm"] = layout["right_end_mm"] + right_shift_mm
        adjusted["right_start_bin"] = layout["right_start_bin"] + right_total_bins
        adjusted["right_end_bin"] = layout["right_end_bin"] + right_total_bins

    return adjusted
