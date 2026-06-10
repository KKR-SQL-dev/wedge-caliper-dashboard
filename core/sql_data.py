"""SQL Server에서 캘리퍼 스캔 데이터를 조회하는 모듈."""
import numpy as np

from config import NUM_BINS, get_db_connection, get_db_table


def _parse_row(row, columns):
    """한 행을 파싱하여 (time, recipe, rollid, rollno, actual_mil) 반환."""
    time_idx = columns.index("Time")
    recipe_idx = columns.index("Recipe")

    scan_time = row[time_idx]
    recipe = str(row[recipe_idx]).strip() if row[recipe_idx] else ""

    # ROLLID / ROLLNO (없으면 빈 문자열)
    rollid = ""
    rollno = ""
    if "ROLLID" in columns:
        _v = row[columns.index("ROLLID")]
        rollid = str(_v).strip() if _v is not None else ""
    if "ROLLNO" in columns:
        _v = row[columns.index("ROLLNO")]
        rollno = str(_v).strip() if _v is not None else ""

    # Data1 ~ Data449 → numpy array
    data_indices = []
    for i in range(1, NUM_BINS + 1):
        col_name = f"Data{i}"
        if col_name in columns:
            data_indices.append(columns.index(col_name))

    if len(data_indices) != NUM_BINS:
        return None

    actual_mil = np.array([
        float(row[idx]) if row[idx] is not None else np.nan
        for idx in data_indices
    ])

    # 0은 "측정 없음" → NaN 처리 (차트/계산에서 제외)
    actual_mil[actual_mil == 0.0] = np.nan

    return (scan_time, recipe, rollid, rollno, actual_mil)


def fetch_latest_scan():
    """가장 최근 1건의 스캔 데이터 조회.

    Returns:
        (time, recipe, rollid, rollno, actual_mil_449_array) 또는 실패 시 None.
    """
    conn = get_db_connection()
    if conn is None:
        return None
    try:
        cursor = conn.cursor()
        cursor.execute(f"SELECT TOP 1 * FROM {get_db_table()} ORDER BY [Time] DESC")
        row = cursor.fetchone()
        if row is None:
            return None
        columns = [col[0] for col in cursor.description]
        return _parse_row(row, columns)
    except Exception:
        return None
    finally:
        conn.close()


def fetch_recent_scans(n=10):
    """최근 N건의 스캔 데이터 조회 (트렌드 분석용).

    Returns:
        list of (time, recipe, rollid, rollno, actual_mil_449_array) 또는 빈 리스트.
    """
    conn = get_db_connection()
    if conn is None:
        return []
    try:
        cursor = conn.cursor()
        cursor.execute(f"SELECT TOP {int(n)} * FROM {get_db_table()} ORDER BY [Time] DESC")
        rows = cursor.fetchall()
        if not rows:
            return []

        columns = [col[0] for col in cursor.description]

        results = []
        for row in rows:
            parsed = _parse_row(row, columns)
            if parsed:
                results.append(parsed)

        return results
    except Exception:
        return []
    finally:
        conn.close()
