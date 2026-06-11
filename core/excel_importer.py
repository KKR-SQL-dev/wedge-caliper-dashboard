"""엑셀 마스터 파일에서 제품 스펙을 임포트하는 모듈.

대상 파일: data/Wedge products and development.xlsx
시트: W-code list (헤더 R5, 데이터 R6~)

단위 변환:
  - Roll Width, Flat Width: cm → mm (×10)
  - Thin Edge Cal, Max Cal: mm → mil (÷0.0254)
  - Wedge Angle, HUD/GWA Bot/Top: 변환 없음 (이미 mrad, mm)
"""
from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd

from config import MM_TO_MIL

logger = logging.getLogger(__name__)

# 엑셀 컬럼명 → 내부 필드명 매핑
_COL_MAP = {
    "Product Code": "name",
    "Developmental, Commercial, Obsolete": "_status_code",
    "Extr. Line": "extr_line",
    "Wedge Angle (mrad)": "wedge_angle_mrad",
    "Roll Width (cm)": "_roll_width_cm",
    "Flat Width (cm)": "_flat_width_cm",
    "Band Width (cm)": "_band_width_cm",
    "Clear width (cm)": "_clear_width_cm",
    "Thin Edge Cal. (mm)": "_thin_edge_mm",
    "Max/ Flat Edge Cal. (mm)": "_max_cal_mm",
    "Wedge Portion (cm)": "_wedge_portion_cm",
    "HUD Bot. (mm)": "hud_bot_mm",
    "HUD Top (mm)": "hud_top_mm",
    "GWA Bot. (mm)": "gwa_bot_mm",
    "GWA Top (mm)": "gwa_top_mm",
    "PVB Type": "pvb_type",
    "Pattern": "pattern",
    "Band color": "band_color",
}

STATUS_MAP = {"C": "Commercial", "D": "Developmental", "O": "Obsolete"}


def _safe_float(val, default=None) -> float | None:
    """NaN/빈값/N/A를 None으로, 나머지를 float로 변환."""
    if val is None:
        return default
    s = str(val).strip()
    if s in ("", "nan", "NaN", "N/A", "n/a", "None"):
        return default
    try:
        f = float(s)
        if pd.isna(f):
            return default
        return f
    except (ValueError, TypeError):
        return default


def import_from_excel(excel_path: str | Path, line_filter: str = "L9") -> dict:
    """엑셀 마스터 파일에서 제품을 읽어 딕셔너리로 반환.

    Args:
        excel_path: 엑셀 파일 경로
        line_filter: 라인 필터 (예: "L9"). 빈 문자열이면 전체.

    Returns:
        {product_code: {name, wedge_angle_mrad, roll_width_mm, ...}, ...}
    """
    excel_path = Path(excel_path)
    if not excel_path.exists():
        logger.warning("엑셀 마스터 파일 없음: %s", excel_path)
        return {}

    # W-code list 시트, 헤더 = R5 (0-indexed row 4)
    try:
        df = pd.read_excel(excel_path, sheet_name="W-code list", header=4)
    except Exception as e:
        logger.error("엑셀 읽기 실패: %s", e)
        return {}

    # 라인 필터
    if line_filter and "Extr. Line" in df.columns:
        mask = df["Extr. Line"].astype(str).str.contains(line_filter, na=False)
        df = df[mask]

    masters = {}
    skipped = 0

    for _, row in df.iterrows():
        code = str(row.get("Product Code", "")).strip()
        if not code or code == "nan":
            skipped += 1
            continue

        angle = _safe_float(row.get("Wedge Angle (mrad)"))
        rw_cm = _safe_float(row.get("Roll Width (cm)"))
        fw_cm = _safe_float(row.get("Flat Width (cm)"))
        te_mm = _safe_float(row.get("Thin Edge Cal. (mm)"))

        # 필수 필드 누락 → 스킵
        if any(v is None for v in [angle, rw_cm, fw_cm, te_mm]):
            skipped += 1
            continue

        # 단위 변환
        roll_width_mm = rw_cm * 10.0
        flat_width_mm = fw_cm * 10.0
        thin_edge_mil = te_mm * MM_TO_MIL  # mm → mil

        # Max Cal (엑셀 공식값 사용, 없으면 계산)
        max_cal_mm = _safe_float(row.get("Max/ Flat Edge Cal. (mm)"))

        # HUD / GWA (이미 mm)
        hud_bot = _safe_float(row.get("HUD Bot. (mm)"))
        hud_top = _safe_float(row.get("HUD Top (mm)"))
        gwa_bot = _safe_float(row.get("GWA Bot. (mm)"))
        gwa_top = _safe_float(row.get("GWA Top (mm)"))

        # 추가 필드
        bw_cm = _safe_float(row.get("Band Width (cm)"))
        cw_cm = _safe_float(row.get("Clear width (cm)"))

        # 메타데이터
        status_code = str(row.get("Developmental, Commercial, Obsolete", "")).strip()
        status = STATUS_MAP.get(status_code, status_code)
        extr_line = str(row.get("Extr. Line", "")).strip()
        pvb_type = str(row.get("PVB Type", "")).strip()
        pattern = str(row.get("Pattern", "")).strip()
        band_color = str(row.get("Band color", "")).strip()
        film_type = "Clear" if band_color == "Clear" else pvb_type

        # 중복 코드: 나중 행이 이김 (보통 최신 정보)
        masters[code] = {
            "name": code,
            "wedge_angle_mrad": angle,
            "roll_width_mm": roll_width_mm,
            "flat_width_mm": flat_width_mm,
            "thin_edge_cal_mil": round(thin_edge_mil, 4),
            "film_type": film_type,
            "hud_bot_mm": hud_bot,
            "hud_top_mm": hud_top,
            "gwa_bot_mm": gwa_bot,
            "gwa_top_mm": gwa_top,
            "center_trim_mm": 25.4,  # 기본값
            # 메타데이터
            "status": status,
            "extr_line": extr_line,
            "pvb_type": pvb_type,
            "pattern": pattern,
            "band_color": band_color,
        }
        # max_cal_mm가 있으면 참고용으로 저장
        if max_cal_mm and max_cal_mm > 0:
            masters[code]["max_cal_mm_ref"] = max_cal_mm
        if bw_cm is not None:
            masters[code]["band_width_mm"] = bw_cm * 10.0
        if cw_cm is not None:
            masters[code]["clear_width_mm"] = cw_cm * 10.0

    logger.info("엑셀 임포트 완료: %d 제품 로드, %d 스킵", len(masters), skipped)
    return masters


def refresh_masters(excel_path: str | Path, json_path: str | Path) -> dict:
    """엑셀에서 읽어서 JSON으로 저장하고 결과를 반환."""
    import json

    masters = import_from_excel(excel_path)
    if masters:
        json_path = Path(json_path)
        json_path.parent.mkdir(parents=True, exist_ok=True)
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(masters, f, indent=2, ensure_ascii=False)
        logger.info("마스터 JSON 저장: %s (%d 제품)", json_path, len(masters))
    return masters
