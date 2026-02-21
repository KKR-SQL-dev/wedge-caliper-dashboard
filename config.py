"""L9 라인 상수 및 단위 변환 함수."""
import json
from pathlib import Path

# ── L9 장비 스펙 ──────────────────────────────────────────
NUM_BINS = 449
BIN_PITCH_INCH = 0.24805
BIN_PITCH_MM = BIN_PITCH_INCH * 25.4          # 6.30047 mm (정확값 6.3005)
DIE_FULL_WIDTH_INCH = 111.375
DIE_FULL_WIDTH_MM = DIE_FULL_WIDTH_INCH * 25.4  # 2,828.925 mm
NUM_DIE_LIPS = 99
DIE_LIP_PITCH_INCH = 1.125
CENTER_TRIM_MM = 25.4                           # 1 inch

# ── 단위 변환 ─────────────────────────────────────────────
MIL_TO_MM = 0.0254        # 1 mil = 0.0254 mm
MM_TO_MIL = 1.0 / MIL_TO_MM  # ≈ 39.3701


def mil_to_mm(mil: float) -> float:
    return mil * MIL_TO_MM


def mm_to_mil(mm: float) -> float:
    return mm * MM_TO_MIL


def calc_mrad(cal_top_mil: float, cal_bot_mil: float, distance_mm: float) -> float:
    """mrad = (Δcal_mil × 0.0254) / distance_mm × 1000."""
    if distance_mm == 0:
        return 0.0
    return (cal_top_mil - cal_bot_mil) * MIL_TO_MM / distance_mm * 1000.0


def bin_positions_mm() -> list[float]:
    """449 bin의 mm 위치 리스트 (0-indexed)."""
    return [i * BIN_PITCH_MM for i in range(NUM_BINS)]


def is_dual_cut(roll_width_mm: float) -> bool:
    """2컷 가능 여부: (roll_width × 2) + 25.4mm ≤ 2828.9mm."""
    return (roll_width_mm * 2 + CENTER_TRIM_MM) <= DIE_FULL_WIDTH_MM


# ── 프로젝트 경로 & 마스터 데이터 I/O ───────────────────
PROJECT_ROOT = Path(__file__).resolve().parent
MASTER_PATH = PROJECT_ROOT / "data" / "product_master.json"


def load_masters() -> dict:
    """product_master.json에서 제품 마스터 로드."""
    if MASTER_PATH.exists():
        with open(MASTER_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_masters(masters: dict):
    """제품 마스터를 product_master.json에 저장."""
    with open(MASTER_PATH, "w", encoding="utf-8") as f:
        json.dump(masters, f, indent=2, ensure_ascii=False)
