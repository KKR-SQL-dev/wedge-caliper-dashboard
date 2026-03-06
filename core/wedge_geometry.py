"""제품 마스터 데이터클래스 & 컷 타입별 레이아웃 계산.

cut_type:
  "dual"              – 2컷 (좌+우), 센터트림 사이에 배치
  "single_left"       – 좌측에 웨지 제품, 우측은 flat
  "single_right"      – 우측에 웨지 제품, 좌측은 flat
  "single_center"     – 싱글컷, 다이 중앙 정렬
  "single_left_dual"  – 양쪽 웨지 형상, 좌측 메인 (우측은 남는 폭)
  "single_right_dual" – 양쪽 웨지 형상, 우측 메인 (좌측은 남는 폭)
  "auto"              – 폭 기준 자동 판별 (기본값)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from config import (
    BIN_PITCH_MM, CENTER_TRIM_MM, DIE_FULL_WIDTH_MM, MIL_TO_MM, NUM_BINS,
    is_dual_cut,
)

# 유효한 cut_type 값
VALID_CUT_TYPES = (
    "auto", "dual", "single_left", "single_right", "single_center",
    "single_left_dual", "single_right_dual",
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

    # 컷 타입
    cut_type: str = "auto"

    # 센터트림 폭 (제품별 가변, 기본 1인치)
    center_trim_mm: float = CENTER_TRIM_MM

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
            if is_dual_cut(self.roll_width_mm, self.center_trim_mm):
                self.resolved_cut_type = "dual"
            else:
                self.resolved_cut_type = "single_center"
        else:
            self.resolved_cut_type = self.cut_type

        self.dual_cut = self.resolved_cut_type in ("dual", "single_left_dual", "single_right_dual")

    @property
    def opposite_roll_width_mm(self) -> float:
        """Dual Shape 시 반대쪽 롤폭 = 다이폭 - 센터트림 - 메인롤폭."""
        return DIE_FULL_WIDTH_MM - self.center_trim_mm - self.roll_width_mm

    @property
    def opposite_flat_width_mm(self) -> float:
        """반대쪽 flat 폭 = 반대쪽 롤폭 - 동일한 wedge_portion."""
        return max(0.0, self.opposite_roll_width_mm - self.wedge_portion_mm)

    # ── 레이아웃 계산 ────────────────────────────────
    def layout(self) -> dict:
        """다이 폭 안에서 제품 배치 위치 계산.

        Returns dict:
            center_mm, left_start_mm, left_end_mm
            + dual 계열이면 right_start_mm, right_end_mm
            + 각각의 bin index
            + Dual Shape이면 opposite 정보
        """
        center_mm = DIE_FULL_WIDTH_MM / 2.0
        ct = self.resolved_cut_type

        right_start_mm = None
        right_end_mm = None

        if ct == "dual":
            # 대칭: 센터트림 기준 좌우 동일 폭, edge waste 균등
            half_trim = self.center_trim_mm / 2.0
            left_end_mm = center_mm - half_trim
            left_start_mm = left_end_mm - self.roll_width_mm
            right_start_mm = center_mm + half_trim
            right_end_mm = right_start_mm + self.roll_width_mm

        elif ct == "single_left":
            # 좌측 웨지 제품, 우측 flat — 좌측 edge 정렬
            left_start_mm = 0.0
            left_end_mm = self.roll_width_mm
            right_start_mm = left_end_mm + self.center_trim_mm
            right_end_mm = DIE_FULL_WIDTH_MM

        elif ct == "single_right":
            # 우측 웨지 제품, 좌측 flat — 우측 edge 정렬
            right_end_mm = DIE_FULL_WIDTH_MM
            right_start_mm = right_end_mm - self.roll_width_mm
            left_end_mm = right_start_mm - self.center_trim_mm
            left_start_mm = 0.0

        elif ct == "single_left_dual":
            # 좌측 메인 + 우측 남는 폭 웨지, edge waste 균등
            opp_rw = self.opposite_roll_width_mm
            total = self.roll_width_mm + self.center_trim_mm + opp_rw
            half_waste = max(0.0, DIE_FULL_WIDTH_MM - total) / 2.0
            left_start_mm = half_waste
            left_end_mm = left_start_mm + self.roll_width_mm
            right_start_mm = left_end_mm + self.center_trim_mm
            right_end_mm = right_start_mm + opp_rw

        elif ct == "single_right_dual":
            # 우측 메인 + 좌측 남는 폭 웨지, edge waste 균등
            opp_rw = self.opposite_roll_width_mm
            total = opp_rw + self.center_trim_mm + self.roll_width_mm
            half_waste = max(0.0, DIE_FULL_WIDTH_MM - total) / 2.0
            left_start_mm = half_waste
            left_end_mm = left_start_mm + opp_rw
            right_start_mm = left_end_mm + self.center_trim_mm
            right_end_mm = right_start_mm + self.roll_width_mm

        else:  # single_center
            left_start_mm = center_mm - self.roll_width_mm / 2.0
            left_end_mm = center_mm + self.roll_width_mm / 2.0

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
        if right_start_mm is not None:
            result.update({
                "right_start_mm": right_start_mm,
                "right_end_mm": right_end_mm,
                "right_start_bin": mm_to_bin(right_start_mm),
                "right_end_bin": mm_to_bin(right_end_mm),
            })

        # Dual Shape 추가 정보
        if self.resolved_cut_type in ("single_left_dual", "single_right_dual"):
            result["main_side"] = "left" if "left" in self.resolved_cut_type else "right"
            result["opposite_roll_width_mm"] = self.opposite_roll_width_mm

        return result

    @property
    def cut_label(self) -> str:
        labels = {
            "dual": "2-Cut",
            "single_left": "Single (Left)",
            "single_right": "Single (Right)",
            "single_center": "Single (Center)",
            "single_left_dual": "Single Left (Dual Shape)",
            "single_right_dual": "Single Right (Dual Shape)",
        }
        return labels.get(self.resolved_cut_type, self.resolved_cut_type)

    def to_dict(self) -> dict:
        d = {
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
            "center_trim_mm": self.center_trim_mm,
            "wedge_portion_mm": self.wedge_portion_mm,
            "max_cal_mil": self.max_cal_mil,
            "dual_cut": self.dual_cut,
        }
        if self.resolved_cut_type in ("single_left_dual", "single_right_dual"):
            d["opposite_roll_width_mm"] = self.opposite_roll_width_mm
            d["opposite_flat_width_mm"] = self.opposite_flat_width_mm
        return d

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
            center_trim_mm=float(d.get("center_trim_mm", CENTER_TRIM_MM)),
        )
