"""449 bin 타겟 프로파일 생성 엔진.

cut_type별 프로파일 형상:
  dual              – 좌(thin→wedge→flat) + 센터트림 + 우(flat→wedge→thin) 대칭
  single_center     – 다이 중앙에 단일 웨지 제품
  single_left       – 좌측 웨지 제품 + 우측 flat
  single_right      – 우측 웨지 제품 + 좌측 flat
  single_left_dual  – 좌측 메인 웨지 + 우측 남는 폭 웨지 (짝짝이)
  single_right_dual – 우측 메인 웨지 + 좌측 남는 폭 웨지 (짝짝이)
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from config import BIN_PITCH_MM, DIE_FULL_WIDTH_MM, NUM_BINS
from core.wedge_geometry import ProductMaster


def generate_profile(product: ProductMaster) -> pd.DataFrame:
    """449 bin 타겟 프로파일을 생성한다.

    Returns:
        DataFrame with columns: Bin, Position_mm, Target_mil
    """
    positions = np.arange(NUM_BINS) * BIN_PITCH_MM
    cals = np.full(NUM_BINS, np.nan)

    layout = product.layout()
    ct = product.resolved_cut_type

    if ct == "dual":
        # 좌측: thin→wedge→flat
        _fill_wedge_cut(
            cals, positions,
            start_mm=layout["left_start_mm"],
            end_mm=layout["left_end_mm"],
            product=product,
            direction="left",
        )
        # 우측: flat→wedge→thin (미러)
        _fill_wedge_cut(
            cals, positions,
            start_mm=layout["right_start_mm"],
            end_mm=layout["right_end_mm"],
            product=product,
            direction="right",
        )

    elif ct == "single_center":
        _fill_wedge_cut(
            cals, positions,
            start_mm=layout["left_start_mm"],
            end_mm=layout["left_end_mm"],
            product=product,
            direction="left",
        )

    elif ct == "single_left":
        # 좌측: 웨지 제품
        _fill_wedge_cut(
            cals, positions,
            start_mm=layout["left_start_mm"],
            end_mm=layout["left_end_mm"],
            product=product,
            direction="left",
        )
        # 우측: flat (max_cal로 채움)
        if layout.get("right_start_mm") is not None:
            _fill_flat(
                cals, positions,
                start_mm=layout["right_start_mm"],
                end_mm=layout["right_end_mm"],
                cal_mil=product.max_cal_mil,
            )

    elif ct == "single_right":
        # 우측: 웨지 제품
        _fill_wedge_cut(
            cals, positions,
            start_mm=layout["right_start_mm"],
            end_mm=layout["right_end_mm"],
            product=product,
            direction="right",
        )
        # 좌측: flat (max_cal로 채움)
        if layout.get("left_start_mm") is not None:
            _fill_flat(
                cals, positions,
                start_mm=layout["left_start_mm"],
                end_mm=layout["left_end_mm"],
                cal_mil=product.max_cal_mil,
            )

    elif ct == "single_left_dual":
        # 좌측 메인: 정상 웨지
        _fill_wedge_cut(
            cals, positions,
            start_mm=layout["left_start_mm"],
            end_mm=layout["left_end_mm"],
            product=product,
            direction="left",
        )
        # 우측 opposite: max_cal 동일, 기울기 동일, 좁으면 thin edge만 높아짐
        opp_rw = layout["right_end_mm"] - layout["right_start_mm"]
        opp_slope = product.wedge_angle_mrad / 25.4  # 기울기 동일
        opp_wp = min(product.wedge_portion_mm, opp_rw)
        opp_thin = product.max_cal_mil - opp_slope * opp_wp
        _fill_wedge_cut_custom(
            cals, positions,
            start_mm=layout["right_start_mm"],
            end_mm=layout["right_end_mm"],
            direction="right",
            thin_cal=opp_thin,
            max_cal=product.max_cal_mil,
            wedge_portion_mm=opp_wp,
            slope_mil_per_mm=opp_slope,
        )

    elif ct == "single_right_dual":
        # 우측 메인: 정상 웨지
        _fill_wedge_cut(
            cals, positions,
            start_mm=layout["right_start_mm"],
            end_mm=layout["right_end_mm"],
            product=product,
            direction="right",
        )
        # 좌측 opposite: max_cal 동일, 기울기 동일, 좁으면 thin edge만 높아짐
        opp_rw = layout["left_end_mm"] - layout["left_start_mm"]
        opp_slope = product.wedge_angle_mrad / 25.4  # 기울기 동일
        opp_wp = min(product.wedge_portion_mm, opp_rw)
        opp_thin = product.max_cal_mil - opp_slope * opp_wp
        _fill_wedge_cut_custom(
            cals, positions,
            start_mm=layout["left_start_mm"],
            end_mm=layout["left_end_mm"],
            direction="left",
            thin_cal=opp_thin,
            max_cal=product.max_cal_mil,
            wedge_portion_mm=opp_wp,
            slope_mil_per_mm=opp_slope,
        )

    return pd.DataFrame({
        "Bin": np.arange(1, NUM_BINS + 1),
        "Position_mm": positions,
        "Target_mil": cals,
    })


def _fill_wedge_cut(
    cals: np.ndarray,
    positions: np.ndarray,
    start_mm: float,
    end_mm: float,
    product: ProductMaster,
    direction: str,
):
    """한 컷 영역의 캘리퍼 값을 채운다 (ProductMaster 스펙 사용)."""
    _fill_wedge_cut_custom(
        cals, positions, start_mm, end_mm, direction,
        thin_cal=product.thin_edge_cal_mil,
        max_cal=product.max_cal_mil,
        wedge_portion_mm=product.wedge_portion_mm,
        slope_mil_per_mm=product.wedge_angle_mrad / 25.4,
    )


def _fill_wedge_cut_custom(
    cals: np.ndarray,
    positions: np.ndarray,
    start_mm: float,
    end_mm: float,
    direction: str,
    thin_cal: float,
    max_cal: float,
    wedge_portion_mm: float,
    slope_mil_per_mm: float,
):
    """한 컷 영역의 캘리퍼 값을 채운다 (커스텀 파라미터).

    direction='left':  start→wedge상승→flat→end  (thin edge가 start 쪽)
    direction='right': start→flat→wedge하강→end  (thin edge가 end 쪽)
    """
    for i in range(len(cals)):
        pos = positions[i]
        if pos < start_mm or pos > end_mm:
            continue

        if direction == "left":
            dist = pos - start_mm
            if dist <= wedge_portion_mm:
                cals[i] = thin_cal + slope_mil_per_mm * dist
            else:
                cals[i] = max_cal
        else:  # right (미러)
            dist = end_mm - pos
            if dist <= wedge_portion_mm:
                cals[i] = thin_cal + slope_mil_per_mm * dist
            else:
                cals[i] = max_cal


def _fill_flat(
    cals: np.ndarray,
    positions: np.ndarray,
    start_mm: float,
    end_mm: float,
    cal_mil: float,
):
    """영역을 일정 두께(flat)로 채운다."""
    for i in range(len(cals)):
        pos = positions[i]
        if start_mm <= pos <= end_mm:
            cals[i] = cal_mil


def generate_full_profile(product: ProductMaster) -> pd.DataFrame:
    """449 bin 전체 프로파일 (edge 포함, NaN이 아닌 연속값).

    thin edge 바깥 edge 영역은 웨지 기울기를 연장하여 리니어하게 감소.
    센터트림 영역(dual 계열)은 인접 flat 값으로 채움.
    """
    df = generate_profile(product)
    positions = df["Position_mm"].values
    target = df["Target_mil"].values.copy()
    slope = product.wedge_angle_mrad / 25.4  # mil/mm

    valid_indices = np.where(~np.isnan(target))[0]
    if len(valid_indices) == 0:
        df["Target_mil"] = target
        return df

    fv = valid_indices[0]   # first valid bin
    lv = valid_indices[-1]  # last valid bin

    ct = product.resolved_cut_type

    if ct in ("dual", "single_left_dual", "single_right_dual"):
        # 좌측 edge: 기울기 연장 (계속 감소)
        if fv > 0:
            distances = positions[fv] - positions[:fv]
            target[:fv] = target[fv] - slope * distances

        # 우측 edge: 기울기 연장 (계속 감소)
        if lv < len(target) - 1:
            distances = positions[lv + 1:] - positions[lv]
            target[lv + 1:] = target[lv] - slope * distances

        # 센터트림: forward fill
        still_nan = np.isnan(target)
        if np.any(still_nan):
            s = pd.Series(target)
            target = s.ffill().bfill().values

    elif ct in ("single_left", "single_right"):
        # 양쪽 모두 edge 연장
        if fv > 0:
            distances = positions[fv] - positions[:fv]
            target[:fv] = target[fv] - slope * distances

        if lv < len(target) - 1:
            distances = positions[lv + 1:] - positions[lv]
            target[lv + 1:] = target[lv] - slope * distances

        # 센터트림 gap은 ffill
        still_nan = np.isnan(target)
        if np.any(still_nan):
            s = pd.Series(target)
            target = s.ffill().bfill().values

    else:  # single_center
        if fv > 0:
            distances = positions[fv] - positions[:fv]
            target[:fv] = target[fv] - slope * distances

        if lv < len(target) - 1:
            target[lv + 1:] = target[lv]

    df["Target_mil"] = target
    return df
