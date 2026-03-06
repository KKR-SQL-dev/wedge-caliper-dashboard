"""SQL Server에서 캘리퍼 스캔 데이터를 조회하는 모듈."""
import numpy as np

from config import DB_TABLE, NUM_BINS, get_db_connection


def fetch_latest_scan():
    """가장 최근 1건의 스캔 데이터 조회.

    Returns:
        (time, recipe, actual_mil_449_array) 또는 연결/데이터 실패 시 None.
    """
    conn = get_db_connection()
    if conn is None:
        return None
    try:
        cursor = conn.cursor()
        cursor.execute(f"SELECT TOP 1 * FROM {DB_TABLE} ORDER BY [Time] DESC")
        row = cursor.fetchone()
        if row is None:
            return None

        columns = [col[0] for col in cursor.description]

        # Time, Recipe 컬럼 위치 찾기
        time_idx = columns.index("Time")
        recipe_idx = columns.index("Recipe")

        scan_time = row[time_idx]
        recipe = str(row[recipe_idx]).strip() if row[recipe_idx] else ""

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

        return (scan_time, recipe, actual_mil)
    except Exception:
        return None
    finally:
        conn.close()


def fetch_recent_scans(n=10):
    """최근 N건의 스캔 데이터 조회 (트렌드 분석용).

    Returns:
        list of (time, recipe, actual_mil_449_array) 또는 빈 리스트.
    """
    conn = get_db_connection()
    if conn is None:
        return []
    try:
        cursor = conn.cursor()
        cursor.execute(f"SELECT TOP {int(n)} * FROM {DB_TABLE} ORDER BY [Time] DESC")
        rows = cursor.fetchall()
        if not rows:
            return []

        columns = [col[0] for col in cursor.description]
        time_idx = columns.index("Time")
        recipe_idx = columns.index("Recipe")

        data_indices = []
        for i in range(1, NUM_BINS + 1):
            col_name = f"Data{i}"
            if col_name in columns:
                data_indices.append(columns.index(col_name))

        if len(data_indices) != NUM_BINS:
            return []

        results = []
        for row in rows:
            scan_time = row[time_idx]
            recipe = str(row[recipe_idx]).strip() if row[recipe_idx] else ""
            actual_mil = np.array([
                float(row[idx]) if row[idx] is not None else np.nan
                for idx in data_indices
            ])
            results.append((scan_time, recipe, actual_mil))

        return results
    except Exception:
        return []
    finally:
        conn.close()
