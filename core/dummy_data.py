"""더미 실측 데이터 생성기.

타겟 프로파일에 노이즈/오프셋/로컬 범프를 추가하여 실측 시뮬레이션.
"""
from __future__ import annotations

import numpy as np


def generate_dummy_actual(
    target_mil: np.ndarray,
    noise_std: float = 0.3,
    offset: float = 0.0,
    bump_center_bin: int | None = None,
    bump_amplitude: float = 0.0,
    bump_width: int = 20,
    seed: int | None = None,
) -> np.ndarray:
    """타겟 프로파일에 노이즈를 추가하여 더미 실측 데이터 생성.

    Args:
        target_mil: 449 bin 타겟 캘리퍼 (mil)
        noise_std: 가우시안 노이즈 표준편차 (mil)
        offset: 전체 오프셋 (mil)
        bump_center_bin: 로컬 범프 중심 bin (0-indexed)
        bump_amplitude: 로컬 범프 크기 (mil)
        bump_width: 로컬 범프 반폭 (bins)
        seed: 난수 시드
    """
    rng = np.random.default_rng(seed)
    n = len(target_mil)

    actual = target_mil.copy().astype(float) + offset
    actual += rng.normal(0, noise_std, n)

    if bump_center_bin is not None and bump_amplitude != 0:
        x = np.arange(n)
        bump = bump_amplitude * np.exp(-0.5 * ((x - bump_center_bin) / bump_width) ** 2)
        actual += bump

    # NaN 유지
    actual[np.isnan(target_mil)] = np.nan

    return actual


def generate_scan_series(
    target_mil: np.ndarray,
    n_scans: int = 10,
    noise_std: float = 0.3,
    drift_rate: float = 0.02,
    seed: int = 42,
) -> list[np.ndarray]:
    """시간에 따른 연속 스캔 시뮬레이션 (느린 드리프트 포함)."""
    scans = []
    for i in range(n_scans):
        offset = drift_rate * i
        actual = generate_dummy_actual(
            target_mil,
            noise_std=noise_std,
            offset=offset,
            seed=seed + i,
        )
        scans.append(actual)
    return scans
