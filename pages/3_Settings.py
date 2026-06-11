"""Page 3: 설정 – 마스터 엑셀 경로 지정 & 새로고침."""
import sys
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import (
    MASTER_PATH, get_excel_master_path, is_sql_configured, load_masters,
    load_settings, render_sidebar_portal, save_settings, set_excel_master_path,
)
from core.excel_importer import refresh_masters

render_sidebar_portal()
st.header("Settings")

# ── SQL Server 접속 설정 ─────────────────────────────────
st.subheader("SQL Server Connection")
_settings = load_settings()
_sql_status = "Connected" if is_sql_configured() else "Not configured"
st.caption(f"Status: **{_sql_status}**")
st.caption("환경변수(`WC_DB_HOST` 등)가 있으면 그쪽이 우선합니다.")

_db_host = st.text_input("DB Host (IP)", value=_settings.get("db_host", ""), placeholder="192.168.107.6")
_db_name = st.text_input("DB Name", value=_settings.get("db_name", "KURARAY_PLCDATA"))
_db_table = st.text_input("DB Table", value=_settings.get("db_table", "dbo.RAW_BCALIPER_L9"))
_db_user = st.text_input("DB User", value=_settings.get("db_user", ""))
_db_pwd = st.text_input("DB Password", value=_settings.get("db_pwd", ""), type="password")
_db_driver = st.text_input("ODBC Driver", value=_settings.get("db_driver", "{ODBC Driver 17 for SQL Server}"))

col_db1, col_db2 = st.columns(2)
with col_db1:
    if st.button("Save DB Settings", type="primary"):
        _settings["db_host"] = _db_host
        _settings["db_name"] = _db_name
        _settings["db_table"] = _db_table
        _settings["db_user"] = _db_user
        _settings["db_pwd"] = _db_pwd
        _settings["db_driver"] = _db_driver
        save_settings(_settings)
        st.success("DB 설정 저장 완료! 메인 페이지 새로고침하세요.")
with col_db2:
    if st.button("Test Connection"):
        from config import get_db_connection
        conn = get_db_connection()
        if conn:
            st.success("SQL Server 연결 성공!")
            conn.close()
        else:
            st.error("연결 실패. Host/User/Password를 확인하세요.")

st.divider()

# ── 마스터 엑셀 경로 ─────────────────────────────────────
st.subheader("Master Excel Path")

current_path = get_excel_master_path()
st.caption(f"현재 경로: `{current_path}`")

new_path = st.text_input(
    "엑셀 마스터 파일 경로",
    value=str(current_path),
    help="Wedge Raw test data 엑셀 파일의 전체 경로를 입력하세요.",
)

col1, col2 = st.columns(2)

with col1:
    if st.button("Save Path", type="primary"):
        p = Path(new_path)
        if p.exists() and p.suffix in (".xlsx", ".xls"):
            set_excel_master_path(new_path)
            st.success(f"경로 저장 완료: {new_path}")
        elif not p.exists():
            st.error(f"파일이 존재하지 않습니다: {new_path}")
        else:
            st.error("엑셀 파일(.xlsx, .xls)만 지원합니다.")

with col2:
    if st.button("Refresh Masters from Excel"):
        excel_path = Path(new_path) if new_path else current_path
        if excel_path.exists():
            masters = refresh_masters(excel_path, MASTER_PATH)
            st.success(f"엑셀에서 **{len(masters)}**개 제품 로드 완료!")
            st.rerun()
        else:
            st.error(f"엑셀 파일 없음: {excel_path}")

# ── 현재 마스터 상태 ─────────────────────────────────────
st.divider()
st.subheader("Master Data Status")

masters = load_masters()
st.metric("등록 제품 수", len(masters))

if masters:
    # 라인별 통계
    line_counts = {}
    status_counts = {}
    for m in masters.values():
        line = m.get("extr_line", "Unknown")
        status = m.get("status", "Unknown")
        line_counts[line] = line_counts.get(line, 0) + 1
        status_counts[status] = status_counts.get(status, 0) + 1

    col_a, col_b = st.columns(2)
    with col_a:
        st.caption("**라인별**")
        for line, count in sorted(line_counts.items()):
            st.text(f"  {line}: {count}")

    with col_b:
        st.caption("**상태별**")
        for status, count in sorted(status_counts.items()):
            st.text(f"  {status}: {count}")

    # 제품 목록 테이블
    st.divider()
    with st.expander("전체 제품 목록"):
        import pandas as pd
        rows = []
        for name, m in sorted(masters.items()):
            rows.append({
                "Product": name,
                "Line": m.get("extr_line", "-"),
                "Status": m.get("status", "-"),
                "WA (mrad)": m.get("wedge_angle_mrad", "-"),
                "Roll W (mm)": m.get("roll_width_mm", "-"),
                "Flat W (mm)": m.get("flat_width_mm", "-"),
                "Thin Edge (mil)": m.get("thin_edge_cal_mil", "-"),
                "Film Type": m.get("film_type", "-"),
                "Dual Cut": m.get("dual_cut", "-") if "dual_cut" in m else "-",
            })
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True, height=400)

# ── 파일 정보 ────────────────────────────────────────────
st.divider()
st.subheader("File Info")

excel_path = get_excel_master_path()
if excel_path.exists():
    from datetime import datetime
    mtime = datetime.fromtimestamp(excel_path.stat().st_mtime)
    st.text(f"Excel: {excel_path}")
    st.text(f"  Modified: {mtime.strftime('%Y-%m-%d %H:%M:%S')}")
    st.text(f"  Size: {excel_path.stat().st_size / 1024:.0f} KB")
else:
    st.warning(f"Excel 파일 없음: {excel_path}")

if MASTER_PATH.exists():
    from datetime import datetime
    mtime = datetime.fromtimestamp(MASTER_PATH.stat().st_mtime)
    st.text(f"JSON: {MASTER_PATH}")
    st.text(f"  Modified: {mtime.strftime('%Y-%m-%d %H:%M:%S')}")
    st.text(f"  Size: {MASTER_PATH.stat().st_size / 1024:.0f} KB")
else:
    st.text("JSON: 아직 생성되지 않음")
