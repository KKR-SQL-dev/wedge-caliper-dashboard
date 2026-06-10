"""실데이터 샘플(CSV) 로더.

data/sample-real.csv를 읽어서 SQL 데이터와 동일한 형식으로 반환.
개발 PC에서 SQL 접속 없이 실데이터로 테스트 가능.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from config import NUM_BINS

# CSV 파일 경로
_DATA_DIR = Path(__file__).resolve().parent.parent / "data"
SAMPLE_CSV_WEDGE = _DATA_DIR / "sample-real.csv"
SAMPLE_CSV_FLAT = _DATA_DIR / "sample-flat-31_5.csv"

# CSV 컬럼: Time, Recipe, ROLLID, ROLLNO, Data1~Data449
_COL_NAMES = ["Time", "Recipe", "ROLLID", "ROLLNO"] + [f"Data{i}" for i in range(1, NUM_BINS + 1)]


def list_sample_files() -> list[Path]:
    """data/ 디렉토리의 sample-*.csv 파일 목록."""
    return sorted(_DATA_DIR.glob("sample-*.csv"))


def _load_csv(csv_path: Path | None = None) -> pd.DataFrame:
    """CSV를 DataFrame으로 로드."""
    if csv_path is None:
        csv_path = SAMPLE_CSV_WEDGE
    if not csv_path.exists():
        return pd.DataFrame()

    # 헤더 유무 자동 감지: 첫 줄이 "Time"으로 시작하면 헤더 있음
    with open(csv_path, "r", encoding="utf-8-sig") as f:
        first_line = f.readline().strip()
    has_header = first_line.startswith("Time")

    if has_header:
        df = pd.read_csv(csv_path, encoding="utf-8-sig", parse_dates=["Time"])
        # 컬럼명 정규화
        df.columns = [c.strip() for c in df.columns]
    else:
        df = pd.read_csv(
            csv_path, header=None, names=_COL_NAMES,
            encoding="utf-8-sig", parse_dates=["Time"],
        )
    return df.sort_values("Time", ascending=False).reset_index(drop=True)


# 현재 선택된 CSV (Streamlit session_state로 전환 가능)
_current_csv: Path | None = None


def set_sample_csv(path: Path):
    """현재 사용할 샘플 CSV 설정."""
    global _current_csv
    _current_csv = path


def get_current_csv() -> Path:
    """현재 샘플 CSV 경로."""
    return _current_csv or SAMPLE_CSV_WEDGE


def sample_available() -> bool:
    """샘플 CSV 파일이 하나라도 존재하는지."""
    return len(list_sample_files()) > 0


def fetch_sample_latest(csv_path: Path | None = None):
    """CSV에서 가장 최근 1건 반환.

    Returns:
        (time, recipe, rollid, rollno, actual_mil) 또는 None.
    """
    df = _load_csv(csv_path or get_current_csv())
    if df.empty:
        return None
    row = df.iloc[0]
    return _parse_row(row)


def fetch_sample_recent(n=500, csv_path: Path | None = None):
    """CSV에서 최근 N건 반환.

    Returns:
        list of (time, recipe, rollid, rollno, actual_mil).
    """
    df = _load_csv(csv_path or get_current_csv())
    if df.empty:
        return []
    results = []
    for _, row in df.head(n).iterrows():
        parsed = _parse_row(row)
        if parsed:
            results.append(parsed)
    return results


def _parse_row(row) -> tuple | None:
    """한 행을 (time, recipe, rollid, rollno, actual_mil) 튜플로 변환."""
    scan_time = row["Time"]
    recipe = str(row["Recipe"]).strip() if pd.notna(row["Recipe"]) else ""
    rollid = str(row["ROLLID"]).strip() if pd.notna(row["ROLLID"]) else ""
    rollno = str(row["ROLLNO"]).strip() if pd.notna(row["ROLLNO"]) else ""

    data_cols = [f"Data{i}" for i in range(1, NUM_BINS + 1)]
    actual_mil = np.array([
        float(row[c]) if pd.notna(row[c]) else np.nan
        for c in data_cols
    ])

    # 0은 "측정 없음" → NaN
    actual_mil[actual_mil == 0.0] = np.nan

    return (scan_time, recipe, rollid, rollno, actual_mil)
