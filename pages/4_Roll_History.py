"""Page 4: Roll History — 롤(ROLLNO)별 집계 판정 이력."""
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import streamlit as st

st.set_page_config(page_title="Roll History", layout="wide")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import (
    BIN_PITCH_MM, NUM_BINS, auto_refresh_masters, is_sql_configured,
    load_masters,
)
from core.mrad_calculator import calc_multi_scan_angles, summarize_angles
from core.profile_engine import generate_full_profile
from core.recipe_matcher import match_recipe, parse_recipe
from core.sample_data import fetch_sample_recent, sample_available
from core.sql_data import fetch_recent_scans
from core.wedge_geometry import ProductMaster

auto_refresh_masters()
masters = load_masters()
master_keys = list(masters.keys())

st.caption("**Roll History**")

if not masters:
    st.warning("제품 마스터가 없습니다.")
    st.stop()

# ── 데이터 소스 ──────────────────────────────────────────
with st.sidebar:
    st.subheader("Data Source")
    _sql_ok = is_sql_configured()
    _sample_ok = sample_available()
    _src = st.radio(
        "소스", ["Live (SQL)", "Test (Sample)"],
        index=0 if _sql_ok else 1,
        horizontal=True, disabled=not _sql_ok,
    )
    _is_live = _src == "Live (SQL)" and _sql_ok
    max_scans = st.number_input("Max Scans", 100, 5000, 1000, step=100)

    st.divider()
    st.subheader("Spec Tolerances")
    gwa_tol = st.number_input("GWA Tol (mrad)", value=0.03, step=0.01, format="%.3f", key="rh_gwa")
    lwa_tol = st.number_input("LWA Tol (mrad)", value=0.15, step=0.01, format="%.3f", key="rh_lwa")

# ── 데이터 로드 ──────────────────────────────────────────
with st.spinner("Loading scans..."):
    if _is_live:
        raw_scans = fetch_recent_scans(n=max_scans)
    else:
        raw_scans = fetch_sample_recent(n=max_scans)

if not raw_scans:
    st.warning("데이터가 없습니다.")
    st.stop()

st.caption(f"Loaded: {len(raw_scans)} scans")

# ── 롤별 그룹핑 (ROLLNO 기준) ────────────────────────────
rolls: dict[str, list] = {}  # rollno → [scan_tuples]
for scan in raw_scans:
    rollno = scan[3] if len(scan) >= 5 else ""
    if not rollno:
        rollno = "UNKNOWN"
    if rollno not in rolls:
        rolls[rollno] = []
    rolls[rollno].append(scan)

# 시간순 정렬 (각 롤 내부)
for rollno in rolls:
    rolls[rollno].sort(key=lambda s: s[0])

# 롤을 최신 순으로 정렬
sorted_rolls = sorted(rolls.items(), key=lambda kv: kv[1][-1][0], reverse=True)

st.caption(f"Rolls: {len(sorted_rolls)}")

# ── 롤별 집계 계산 ───────────────────────────────────────
positions = np.arange(NUM_BINS) * BIN_PITCH_MM

rows = []
for rollno, scans in sorted_rolls:
    recipe_raw = scans[0][1]
    rollid = scans[0][2] if len(scans[0]) >= 5 else ""
    start_time = scans[0][0]
    end_time = scans[-1][0]
    n_scans = len(scans)

    # 레시피 매칭
    mr = match_recipe(recipe_raw, master_keys)
    matched_name = mr.master_key if mr else None
    rp = parse_recipe(recipe_raw)
    is_flat = rp.mrad is None

    row = {
        "ROLLNO": rollno,
        "ROLLID": rollid,
        "Recipe": recipe_raw,
        "Matched": matched_name or "(미등록)",
        "Start": str(start_time)[:19],
        "End": str(end_time)[:19],
        "Scans": n_scans,
    }

    if matched_name and matched_name in masters and not is_flat and n_scans >= 2:
        m = dict(masters[matched_name])
        product = ProductMaster.from_dict(m)
        if product.wedge_angle_mrad > 0:
            df_target = generate_full_profile(product)
            layout = product.layout()
            all_data = np.array([s[-1] for s in scans])

            # Left 집계
            try:
                angles = calc_multi_scan_angles(positions, all_data, layout, product, "left")
                summary = summarize_angles(angles, product.wedge_angle_mrad, gwa_tol, lwa_tol)
                row["UWA Avg"] = f"{summary['uwa']['avg']:.4f}"
                row["UWA Worst"] = f"{summary['uwa']['worst']:.4f}"
                row["UWA Last"] = f"{summary['uwa']['last']:.4f}"
                row["UWA Judge"] = "NG" if summary["uwa"]["worst_judge"] == "FAIL" else "OK"

                if summary["gwa"]:
                    row["GWA Avg"] = f"{summary['gwa']['avg']:.4f}"
                    row["GWA Worst"] = f"{summary['gwa']['worst']:.4f}"
                    row["GWA Judge"] = "NG" if summary["gwa"]["worst_judge"] == "FAIL" else "OK"

                if summary["lwa"]:
                    row["LWA Avg"] = f"{summary['lwa']['avg']:.4f}"
                    row["LWA Worst"] = f"{summary['lwa']['worst']:.4f}"
                    row["LWA Judge"] = "NG" if summary["lwa"]["worst_judge"] == "FAIL" else "OK"
            except Exception:
                pass  # 계산 실패 시 빈칸

    # 종합 판정: UWA/GWA/LWA 중 하나라도 NG면 NG
    judges = [row.get("UWA Judge", ""), row.get("GWA Judge", ""), row.get("LWA Judge", "")]
    if "NG" in judges:
        row["Overall"] = "NG"
    elif any(j == "OK" for j in judges):
        row["Overall"] = "OK"
    else:
        row["Overall"] = "-"

    rows.append(row)

# ── 테이블 표시 ──────────────────────────────────────────
df = pd.DataFrame(rows)

# 표시 컬럼 정리
display_cols = ["ROLLNO", "Recipe", "Matched", "Start", "End", "Scans"]
for c in ["UWA Avg", "UWA Worst", "UWA Judge", "GWA Avg", "GWA Worst", "GWA Judge",
          "LWA Avg", "LWA Worst", "LWA Judge", "Overall"]:
    if c in df.columns:
        display_cols.append(c)

df_display = df[[c for c in display_cols if c in df.columns]]

# NG 하이라이트
def _style_row(row):
    overall = row.get("Overall", "")
    if overall == "NG":
        return ["background-color: #ff4444; color: white; font-weight: bold"] * len(row)
    if overall == "OK":
        return ["background-color: #2d5a2d; color: #88ff88"] * len(row)
    return [""] * len(row)

styled = df_display.style.apply(_style_row, axis=1)
st.dataframe(styled, use_container_width=True, hide_index=True, height=600)

# ── 통계 요약 ────────────────────────────────────────────
if "Overall" in df.columns:
    col1, col2, col3 = st.columns(3)
    total = len(df)
    ok_count = int((df["Overall"] == "OK").sum())
    ng_count = int((df["Overall"] == "NG").sum())
    col1.metric("Total Rolls", total)
    col2.metric("OK", ok_count)
    col3.metric("NG", ng_count, delta_color="inverse" if ng_count > 0 else "normal")
