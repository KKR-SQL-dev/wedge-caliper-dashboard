"""롤 단위 스캔 집계 모듈.

Recipe가 바뀌면 새 롤 시작으로 간주.
현재 롤의 모든 스캔을 버퍼에 축적하여 Avg/Worst/Last 통계 산출 기반 제공.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

import numpy as np

from config import NUM_BINS


@dataclass
class ScanRecord:
    """단일 스캔 레코드."""
    time: datetime
    recipe: str
    actual_mil: np.ndarray  # shape (449,)


@dataclass
class RollBuffer:
    """한 롤(동일 Recipe 연속 구간)의 스캔 버퍼."""
    recipe: str
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    scans: list[ScanRecord] = field(default_factory=list)

    @property
    def count(self) -> int:
        return len(self.scans)

    def add_scan(self, scan: ScanRecord):
        """스캔 추가. 시간 순서대로 넣을 것."""
        self.scans.append(scan)
        if self.start_time is None or scan.time < self.start_time:
            self.start_time = scan.time
        if self.end_time is None or scan.time > self.end_time:
            self.end_time = scan.time

    def get_all_data(self) -> np.ndarray:
        """모든 스캔 데이터를 (N, 449) 행렬로 반환."""
        if not self.scans:
            return np.empty((0, NUM_BINS))
        return np.array([s.actual_mil for s in self.scans])

    def get_latest(self) -> Optional[ScanRecord]:
        """가장 최근 스캔."""
        return self.scans[-1] if self.scans else None

    def get_time_filtered(
        self, start: Optional[datetime] = None, end: Optional[datetime] = None
    ) -> list[ScanRecord]:
        """시간 구간으로 필터링된 스캔 리스트."""
        result = self.scans
        if start:
            result = [s for s in result if s.time >= start]
        if end:
            result = [s for s in result if s.time <= end]
        return result


def build_roll_buffer_from_scans(
    scan_list: list[tuple],
    target_recipe: str,
) -> RollBuffer:
    """SQL에서 가져온 스캔 리스트로 현재 롤 버퍼 구축.

    scan_list: [(time, recipe, actual_mil), ...] — 최신 순(DESC)
    target_recipe: 현재 매칭된 레시피명

    최신 스캔부터 역순으로 같은 recipe인 연속 구간만 취한다.
    recipe가 바뀌는 지점 = 이전 롤의 끝.
    """
    buf = RollBuffer(recipe=target_recipe)

    for scan_time, recipe, actual_mil in scan_list:
        # recipe 정규화 (공백 제거, 대문자)
        norm = recipe.strip().upper().replace(" ", "")
        target_norm = target_recipe.strip().upper().replace(" ", "")

        # 동일 recipe 여부 (prefix 매칭 허용)
        if norm == target_norm or norm.startswith(target_norm) or target_norm.startswith(norm):
            buf.add_scan(ScanRecord(time=scan_time, recipe=recipe, actual_mil=actual_mil))
        else:
            # recipe 변경 = 롤 경계 → 여기서 중단
            break

    # 시간 순서대로 정렬 (SQL은 DESC로 가져오므로)
    buf.scans.sort(key=lambda s: s.time)
    if buf.scans:
        buf.start_time = buf.scans[0].time
        buf.end_time = buf.scans[-1].time

    return buf


def fetch_current_roll_buffer(
    target_recipe: str,
    max_scans: int = 500,
) -> Optional[RollBuffer]:
    """SQL에서 현재 롤의 모든 스캔을 가져와 RollBuffer 구축.

    Args:
        target_recipe: 현재 매칭된 레시피명
        max_scans: 최대 조회 건수

    Returns:
        RollBuffer 또는 연결 실패 시 None
    """
    from core.sql_data import fetch_recent_scans

    scans = fetch_recent_scans(n=max_scans)
    if not scans:
        return None

    return build_roll_buffer_from_scans(scans, target_recipe)
