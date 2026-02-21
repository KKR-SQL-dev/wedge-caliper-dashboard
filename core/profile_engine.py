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

    제품 바깥 edge 영역은 thin_edge_cal 값으로 외삽.
    """
    df = generate_profile(product)
    # edge 영역: 가장 가까운 유효값으로 외삽
    target = df["Target_mil"].values.copy()

    # 왼쪽 edge 채우기
    first_valid = np.where(~np.isnan(target))[0]
    if len(first_valid) > 0:
        fv = first_valid[0]
        target[:fv] = target[fv]
        # 오른쪽 edge 채우기
        last_valid = first_valid[-1]
        target[last_valid + 1:] = target[last_valid]

    df["Target_mil"] = target
    return df
