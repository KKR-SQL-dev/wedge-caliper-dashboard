"""제품 마스터 데이터클래스 & 2컷/싱글컷 레이아웃 계산."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from config import (
    BIN_PITCH_MM, CENTER_TRIM_MM, DIE_FULL_WIDTH_MM, MIL_TO_MM, NUM_BINS,
    is_dual_cut,
)


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

    # ── 자동 계산 필드 ────────────────────────────────
    wedge_portion_mm: float = field(init=False)
    max_cal_mil: float = field(init=False)
    dual_cut: bool = field(init=False)

    def __post_init__(self):
        self.wedge_portion_mm = self.roll_width_mm - self.flat_width_mm
        # max_cal = thin_edge + wedge_angle(mrad) × wedge_portion(mm) / 25.4
        self.max_cal_mil = (
            self.thin_edge_cal_mil
            + self.wedge_angle_mrad * self.wedge_portion_mm / 25.4
        )
        self.dual_cut = is_dual_cut(self.roll_width_mm)

    # ── 레이아웃 계산 (bin 단위) ──────────────────────
    def layout(self) -> dict:
        """다이 폭 안에서 좌/우 제품 배치 bin 인덱스 계산.

        Returns dict:
            center_mm, left_start_mm, left_end_mm, right_start_mm, right_end_mm
            + 각각의 bin index
        """
        center_mm = DIE_FULL_WIDTH_MM / 2.0

        if self.dual_cut:
            half_trim = CENTER_TRIM_MM / 2.0
            # 좌측 제품: center - half_trim - roll_width ~ center - half_trim
            left_end_mm = center_mm - half_trim
            left_start_mm = left_end_mm - self.roll_width_mm
            # 우측 제품: center + half_trim ~ center + half_trim + roll_width
            right_start_mm = center_mm + half_trim
            right_end_mm = right_start_mm + self.roll_width_mm
        else:
            # 싱글컷: 중앙 정렬
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
        }
        if self.dual_cut:
            result.update({
                "right_start_mm": right_start_mm,
                "right_end_mm": right_end_mm,
                "right_start_bin": mm_to_bin(right_start_mm),
                "right_end_bin": mm_to_bin(right_end_mm),
            })
        return result

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
        )
