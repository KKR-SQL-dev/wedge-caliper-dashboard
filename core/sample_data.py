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
SAMPLE_CSV = Path(__file__).resolve().parent.parent / "data" / "sample-real.csv"

# CSV 컬럼: Time, Recipe, ROLLID, ROLLNO, Data1~Data449 (헤더 없음)
_COL_NAMES = ["Time", "Recipe", "ROLLID", "ROLLNO"] + [f"Data{i}" for i in range(1, NUM_BINS + 1)]


def _load_csv() -> pd.DataFrame:
    """CSV를 DataFrame으로 로드. 캐시."""
    if not SAMPLE_CSV.exists():
        return pd.DataFrame()
    df = pd.read_csv(
        SAMPLE_CSV, header=None, names=_COL_NAMES,
        encoding="utf-8-sig", parse_dates=["Time"],
    )
    return df.sort_values("Time", ascending=False).reset_index(drop=True)


def sample_available() -> bool:
    """샘플 CSV 파일이 존재하는지."""
    return SAMPLE_CSV.exists()


def fetch_sample_latest():
    """CSV에서 가장 최근 1건 반환.

    Returns:
        (time, recipe, rollid, rollno, actual_mil) 또는 None.
    """
    df = _load_csv()
    if df.empty:
        return None
    row = df.iloc[0]
    return _parse_row(row)


def fetch_sample_recent(n=500):
    """CSV에서 최근 N건 반환.

    Returns:
        list of (time, recipe, rollid, rollno, actual_mil).
    """
    df = _load_csv()
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
