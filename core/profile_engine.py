"""449 bin 타겟 프로파일 생성 엔진.

좌측 제품: thin edge(좌 가장자리) → wedge 상승 → flat → 센터트림
우측 제품: 센터트림 → flat → wedge 하강 → thin edge(우 가장자리)
대칭 미러 구조.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from config import BIN_PITCH_MM, CENTER_TRIM_MM, DIE_FULL_WIDTH_MM, NUM_BINS
from core.wedge_geometry import ProductMaster


def generate_profile(product: ProductMaster) -> pd.DataFrame:
    """449 bin 타겟 프로파일을 생성한다.

    Returns:
        DataFrame with columns: Bin, Position_mm, Target_mil
    """
    positions = np.arange(NUM_BINS) * BIN_PITCH_MM
    cals = np.full(NUM_BINS, np.nan)

    layout = product.layout()

    if product.dual_cut:
        # ── 좌측 제품: thin→wedge→flat ──
        _fill_single_cut(
            cals, positions,
            start_mm=layout["left_start_mm"],
            end_mm=layout["left_end_mm"],
            product=product,
            direction="left",  # thin edge 왼쪽, thick 오른쪽
        )
        # ── 우측 제품: flat→wedge→thin (미러) ──
        _fill_single_cut(
            cals, positions,
            start_mm=layout["right_start_mm"],
            end_mm=layout["right_end_mm"],
            product=product,
            direction="right",  # thick 왼쪽, thin edge 오른쪽
        )
    else:
        _fill_single_cut(
            cals, positions,
            start_mm=layout["left_start_mm"],
            end_mm=layout["left_end_mm"],
            product=product,
            direction="left",
        )

    return pd.DataFrame({
        "Bin": np.arange(1, NUM_BINS + 1),
        "Position_mm": positions,
        "Target_mil": cals,
    })


def _fill_single_cut(
    cals: np.ndarray,
    positions: np.ndarray,
    start_mm: float,
    end_mm: float,
    product: ProductMaster,
    direction: str,
):
    """한 컷 영역의 캘리퍼 값을 채운다.

    direction='left':  start→wedge상승→flat→end  (thin edge가 start 쪽)
    direction='right': start→flat→wedge하강→end  (thin edge가 end 쪽)
    """
    wedge_portion = product.wedge_portion_mm
    flat_width = product.flat_width_mm
    thin_cal = product.thin_edge_cal_mil
    max_cal = product.max_cal_mil
    slope_mil_per_mm = product.wedge_angle_mrad / 25.4  # mil/mm

    for i in range(len(cals)):
        pos = positions[i]
        if pos < start_mm or pos > end_mm:
            continue

        if direction == "left":
            # 거리 = thin edge(start) 부터의 거리
            dist = pos - start_mm
            if dist <= wedge_portion:
                cals[i] = thin_cal + slope_mil_per_mm * dist
            else:
                cals[i] = max_cal  # flat
        else:  # right (미러)
            # 거리 = thin edge(end) 부터의 거리 (역방향)
            dist = end_mm - pos
            if dist <= wedge_portion:
                cals[i] = thin_cal + slope_mil_per_mm * dist
            else:
                cals[i] = max_cal  # flat


def generate_full_profile(product: ProductMaster) -> pd.DataFrame:
    """449 bin 전체 프로파일 (edge 포함, NaN이 아닌 연속값).

    thin edge 바깥 edge 영역은 웨지 기울기를 연장하여 리니어하게 감소.
    센터트림 영역(2컷)은 max_cal로 채움.
    """
    df = generate_profile(product)
    positions = df["Position_mm"].values
    target = df["Target_mil"].values.copy()
    slope = product.wedge_angle_mrad / 25.4  # mil/mm

    valid_indices = np.where(~np.isnan(target))[0]
    if len(valid_indices) == 0:
        df["Target_mil"] = target
        return df

    fv = valid_indices[0]   # first valid bin (left thin edge)
    lv = valid_indices[-1]  # last valid bin

    if product.dual_cut:
        # 좌측 edge: left thin edge에서 기울기 연장 (계속 감소)
        if fv > 0:
            distances = positions[fv] - positions[:fv]
            target[:fv] = target[fv] - slope * distances

        # 우측 edge: right thin edge에서 기울기 연장 (계속 감소)
        if lv < len(target) - 1:
            distances = positions[lv + 1:] - positions[lv]
            target[lv + 1:] = target[lv] - slope * distances

        # 센터트림: 양쪽 flat(max_cal) 사이 → forward fill
        still_nan = np.isnan(target)
        if np.any(still_nan):
            s = pd.Series(target)
            target = s.ffill().bfill().values
    else:
        # 싱글컷: 좌측 = thin edge (기울기 연장), 우측 = flat (상수 외삽)
        if fv > 0:
            distances = positions[fv] - positions[:fv]
            target[:fv] = target[fv] - slope * distances

        if lv < len(target) - 1:
            target[lv + 1:] = target[lv]

    df["Target_mil"] = target
    return df
