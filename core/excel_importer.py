"""엑셀 마스터 파일에서 L9/L8-L9 제품을 임포트하는 모듈.

단위 변환:
  - Roll Width, Flat Width: cm → mm (×10)
  - Thin Edge Cal: mm → mil (÷0.0254)
  - Wedge Angle, HUD/GWA Bot/Top: 변환 없음 (이미 mrad, mm)
"""
from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd

from config import MM_TO_MIL

logger = logging.getLogger(__name__)

# 엑셀 컬럼 인덱스 (header=1 기준, 데이터 row 1~)
COL = {
    "status": 5,
    "product_code": 6,
    "pattern": 8,
    "band_color": 9,
    "pvb_type": 10,
    "extr_line": 13,
    "wedge_angle_mrad": 14,
    "roll_width_cm": 15,
    "flat_width_cm": 16,
    "band_width_cm": 17,
    "thin_edge_cal_mm": 19,
    "hud_bot_mm": 20,
    "hud_top_mm": 21,
    "gwa_bot_mm": 24,
    "gwa_top_mm": 25,
    "film_type": 53,
}

STATUS_MAP = {"C": "Commercial", "D": "Developmental", "O": "Obsolete"}


def _safe_float(val, default=None) -> float | None:
    """NaN/빈값을 None으로, 나머지를 float로 변환."""
    try:
        f = float(val)
        if pd.isna(f):
            return default
        return f
    except (ValueError, TypeError):
        return default


def import_from_excel(excel_path: str | Path) -> dict:
    """엑셀 마스터 파일에서 L9/L8-L9 제품을 읽어 딕셔너리로 반환.

    Returns:
        {product_code: {name, wedge_angle_mrad, roll_width_mm, ...}, ...}
    """
    excel_path = Path(excel_path)
    if not excel_path.exists():
        logger.warning("엑셀 마스터 파일 없음: %s", excel_path)
        return {}

    df = pd.read_excel(excel_path, header=1)
    # row 0 = 컬럼 설명 헤더, row 1~ = 실제 데이터
    data = df.iloc[1:]

    # L9 / L8-L9 필터
    line_col = data.iloc[:, COL["extr_line"]].astype(str)
    mask = line_col.str.contains("L9", na=False)
    l9_data = data[mask]

    masters = {}
    skipped = 0

    for _, row in l9_data.iterrows():
        product_code = str(row.iloc[COL["product_code"]]).strip()
        if not product_code or product_code == "nan":
            skipped += 1
            continue

        wedge_angle = _safe_float(row.iloc[COL["wedge_angle_mrad"]])
        roll_width_cm = _safe_float(row.iloc[COL["roll_width_cm"]])
        flat_width_cm = _safe_float(row.iloc[COL["flat_width_cm"]])
        thin_edge_mm = _safe_float(row.iloc[COL["thin_edge_cal_mm"]])

        # 필수 필드 누락 시 스킵
        if any(v is None for v in [wedge_angle, roll_width_cm, flat_width_cm, thin_edge_mm]):
            skipped += 1
            logger.debug("필수 필드 누락 스킵: %s", product_code)
            continue

        # 단위 변환
        roll_width_mm = roll_width_cm * 10.0
        flat_width_mm = flat_width_cm * 10.0
        thin_edge_mil = thin_edge_mm * MM_TO_MIL  # mm → mil

        # HUD / GWA (이미 mm, None 가능)
        hud_bot = _safe_float(row.iloc[COL["hud_bot_mm"]])
        hud_top = _safe_float(row.iloc[COL["hud_top_mm"]])
        gwa_bot = _safe_float(row.iloc[COL["gwa_bot_mm"]])
        gwa_top = _safe_float(row.iloc[COL["gwa_top_mm"]])

        # 메타데이터
        status_code = str(row.iloc[COL["status"]]).strip()
        status = STATUS_MAP.get(status_code, status_code)
        extr_line = str(row.iloc[COL["extr_line"]]).strip()
        pvb_type = str(row.iloc[COL["pvb_type"]]).strip()
        pattern = str(row.iloc[COL["pattern"]]).strip()
        band_color = str(row.iloc[COL["band_color"]]).strip()

        film_type_raw = str(row.iloc[COL["film_type"]]).strip()
        if film_type_raw in ("nan", "NaN", ""):
            # band_color로 추론
            film_type = "Clear" if band_color == "Clear" else "Acoustic"
        elif "Clear" in film_type_raw:
            film_type = "Clear"
        elif "S/B" in film_type_raw or "Shade" in film_type_raw:
            film_type = "Acoustic"
        else:
            film_type = film_type_raw

        masters[product_code] = {
            "name": product_code,
            "wedge_angle_mrad": wedge_angle,
            "roll_width_mm": roll_width_mm,
            "flat_width_mm": flat_width_mm,
            "thin_edge_cal_mil": round(thin_edge_mil, 4),
            "film_type": film_type,
            "hud_bot_mm": hud_bot,
            "hud_top_mm": hud_top,
            "gwa_bot_mm": gwa_bot,
            "gwa_top_mm": gwa_top,
            # 메타데이터
            "status": status,
            "extr_line": extr_line,
            "pvb_type": pvb_type,
            "pattern": pattern,
            "band_color": band_color,
        }

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
