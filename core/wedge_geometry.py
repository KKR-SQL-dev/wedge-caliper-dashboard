"""제품 마스터 데이터클래스 & 컷 타입별 레이아웃 계산.

cut_type:
  "dual"         – 2컷 (좌+우), 센터트림 사이에 배치
  "single_left"  – 싱글컷, 2컷 레이아웃의 좌측 위치에 배치
  "single_right" – 싱글컷, 2컷 레이아웃의 우측 위치에 배치
  "single_center"– 싱글컷, 다이 중앙 정렬 (폭이 너무 커서 2컷 불가)
  "auto"         – 폭 기준 자동 판별 (기본값)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from config import (
    BIN_PITCH_MM, CENTER_TRIM_MM, DIE_FULL_WIDTH_MM, MIL_TO_MM, NUM_BINS,
    is_dual_cut,
)

# 유효한 cut_type 값
VALID_CUT_TYPES = ("auto", "dual", "single_left", "single_right", "single_center")


@dataclass
class ProductMaster:
    name: str
    wedge_angle_mrad: float   # mrad
    roll_width_mm: float      # mm
    flat_width_mm: float      # mm
    thin_edge_cal_mil: float  # mil
    film_type: str = "Clear"

    # HUD / GWA 영역 (thin edge 기준 거리, mm) – 없으면 None
    hud_bot_mm: Optional[float] = None
    hud_top_mm: Optional[float] = None
    gwa_bot_mm: Optional[float] = None
    gwa_top_mm: Optional[float] = None

    # 컷 타입: "auto", "dual", "single_left", "single_right", "single_center"
    cut_type: str = "auto"

    # ── 자동 계산 필드 ────────────────────────────────
    wedge_portion_mm: float = field(init=False)
    max_cal_mil: float = field(init=False)
    dual_cut: bool = field(init=False)
    resolved_cut_type: str = field(init=False)

    def __post_init__(self):
        self.wedge_portion_mm = self.roll_width_mm - self.flat_width_mm
        self.max_cal_mil = (
            self.thin_edge_cal_mil
            + self.wedge_angle_mrad * self.wedge_portion_mm / 25.4
        )
        # cut_type 결정
        if self.cut_type == "auto":
            if is_dual_cut(self.roll_width_mm):
                self.resolved_cut_type = "dual"
            else:
                self.resolved_cut_type = "single_center"
        else:
            self.resolved_cut_type = self.cut_type

        self.dual_cut = self.resolved_cut_type == "dual"

    # ── 레이아웃 계산 ────────────────────────────────
    def layout(self) -> dict:
        """다이 폭 안에서 제품 배치 위치 계산.

        Returns dict:
            center_mm, left_start_mm, left_end_mm
            + dual이면 right_start_mm, right_end_mm
            + 각각의 bin index
        """
        center_mm = DIE_FULL_WIDTH_MM / 2.0
        half_trim = CENTER_TRIM_MM / 2.0

        if self.resolved_cut_type == "dual":
            # 좌측: center - half_trim - roll_width ~ center - half_trim
            left_end_mm = center_mm - half_trim
            left_start_mm = left_end_mm - self.roll_width_mm
            # 우측: center + half_trim ~ center + half_trim + roll_width
            right_start_mm = center_mm + half_trim
            right_end_mm = right_start_mm + self.roll_width_mm

        elif self.resolved_cut_type == "single_left":
            # 2컷 좌측 위치에 싱글 배치
            left_end_mm = center_mm - half_trim
            left_start_mm = left_end_mm - self.roll_width_mm
            right_start_mm = None
            right_end_mm = None

        elif self.resolved_cut_type == "single_right":
            # 2컷 우측 위치에 싱글 배치 → left_start/end에 우측 좌표 넣음
            right_start_mm = center_mm + half_trim
            right_end_mm = right_start_mm + self.roll_width_mm
            # left 좌표는 right 좌표로 세팅 (차트/계산 호환)
            left_start_mm = right_start_mm
            left_end_mm = right_end_mm
            right_start_mm = None
            right_end_mm = None

        else:  # single_center
            left_start_mm = center_mm - self.roll_width_mm / 2.0
            left_end_mm = center_mm + self.roll_width_mm / 2.0
            right_start_mm = None
            right_end_mm = None

        def mm_to_bin(mm_pos: float) -> int:
            return max(0, min(NUM_BINS - 1, round(mm_pos / BIN_PITCH_MM)))

        result = {
            "center_mm": center_mm,
            "left_start_mm": left_start_mm,
            "left_end_mm": left_end_mm,
            "left_start_bin": mm_to_bin(left_start_mm),
            "left_end_bin": mm_to_bin(left_end_mm),
            "cut_type": self.resolved_cut_type,
        }
        if self.dual_cut:
            result.update({
                "right_start_mm": right_start_mm,
                "right_end_mm": right_end_mm,
                "right_start_bin": mm_to_bin(right_start_mm),
                "right_end_bin": mm_to_bin(right_end_mm),
            })
        return result

    @property
    def cut_label(self) -> str:
        labels = {
            "dual": "2-Cut",
            "single_left": "Single (Left)",
            "single_right": "Single (Right)",
            "single_center": "Single (Center)",
        }
        return labels.get(self.resolved_cut_type, self.resolved_cut_type)

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "wedge_angle_mrad": self.wedge_angle_mrad,
            "roll_width_mm": self.roll_width_mm,
            "flat_width_mm": self.flat_width_mm,
            "thin_edge_cal_mil": self.thin_edge_cal_mil,
            "film_type": self.film_type,
            "hud_bot_mm": self.hud_bot_mm,
            "hud_top_mm": self.hud_top_mm,
            "gwa_bot_mm": self.gwa_bot_mm,
            "gwa_top_mm": self.gwa_top_mm,
            "cut_type": self.cut_type,
            "wedge_portion_mm": self.wedge_portion_mm,
            "max_cal_mil": round(self.max_cal_mil, 4),
            "dual_cut": self.dual_cut,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "ProductMaster":
        return cls(
            name=d["name"],
            wedge_angle_mrad=d["wedge_angle_mrad"],
            roll_width_mm=d["roll_width_mm"],
            flat_width_mm=d["flat_width_mm"],
            thin_edge_cal_mil=d["thin_edge_cal_mil"],
            film_type=d.get("film_type", "Clear"),
            hud_bot_mm=d.get("hud_bot_mm"),
            hud_top_mm=d.get("hud_top_mm"),
            gwa_bot_mm=d.get("gwa_bot_mm"),
            gwa_top_mm=d.get("gwa_top_mm"),
            cut_type=d.get("cut_type", "auto"),
        )
