"""PVB Wedge Film Caliper Monitoring Dashboard – Main Entry (Monitoring Dashboard)."""
import re
import time

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import streamlit as st

from config import (
    BIN_AXIS_TICK_LABELS, BIN_AXIS_TICK_POSITIONS, BIN_PITCH_MM,
    CENTER_TRIM_MM, DIE_FULL_WIDTH_MM, auto_refresh_masters, is_dual_cut,
    is_sql_configured, load_masters,
)
from core.cut_detector import apply_offset_to_layout, calc_drift_offset, detect_thin_edges
from core.dummy_data import generate_dummy_actual, generate_scan_series
from core.mrad_calculator import (
    calc_gwa, calc_lwa, calc_multi_scan_angles, calc_uwa,
    judge_gwa, judge_lwa, summarize_angles,
)
from core.profile_engine import generate_full_profile
from core.recipe_matcher import match_recipe, parse_recipe
from core.roll_aggregator import RollBuffer, ScanRecord, build_roll_buffer_from_scans, fetch_current_roll_buffer
from core.sample_data import (
    fetch_sample_latest, fetch_sample_recent, list_sample_files,
    sample_available, set_sample_csv,
)
from core.sql_data import fetch_latest_scan
from core.wedge_geometry import ProductMaster

st.set_page_config(
    page_title="L9 Wedge Caliper Monitor",
    page_icon="📐",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── 자동 동기화 ──────────────────────────────────────────
auto_refresh_masters()

# ── 페이지 설정 ──────────────────────────────────────────
st.markdown("""
<style>
    /* 메인 콘텐츠 패딩 최소화 – 전체 너비 활용 */
    .stMainBlockContainer {
        padding-top: 1rem !important;
        padding-left: 1rem !important;
        padding-right: 1rem !important;
        padding-bottom: 0.5rem !important;
        max-width: 100% !important;
    }
</style>
""", unsafe_allow_html=True)
st.caption("**Monitoring Dashboard**")
masters = load_masters()

if not masters:
    st.warning("제품 마스터가 없습니다. Profile Generator에서 먼저 제품을 등록하세요.")
    st.stop()

# ── 사이드바: 필터 + 제품 선택 + 더미 데이터 파라미터 ────
with st.sidebar:
    st.subheader("Filter")

    # 라인 필터
    all_lines = sorted(set(m.get("extr_line", "L9") for m in masters.values()))
    if len(all_lines) > 1:
        selected_lines = st.multiselect("Extr. Line", all_lines, default=all_lines, key="mon_line")
    else:
        selected_lines = all_lines

    # 상태 필터
    all_statuses = sorted(set(m.get("status", "Unknown") for m in masters.values()))
    if len(all_statuses) > 1:
        selected_statuses = st.multiselect("Status", all_statuses, default=all_statuses, key="mon_status")
    else:
        selected_statuses = all_statuses

    # Cut Type 필터
    def _resolve_cut_tag(m: dict) -> str:
        ct_val = m.get("cut_type", "auto")
        if ct_val in ("single_left_dual", "single_right_dual"):
            return "Dual Shape"
        if ct_val in ("single_left", "single_right", "single_center"):
            return "Single"
        if ct_val == "dual":
            return "2-Cut"
        rw = float(m.get("roll_width_mm", 0))
        ct_mm = float(m.get("center_trim_mm", CENTER_TRIM_MM))
        return "2-Cut" if is_dual_cut(rw, ct_mm) else "Single"

    all_cut_tags = sorted(set(_resolve_cut_tag(m) for m in masters.values()))
    if len(all_cut_tags) > 1:
        selected_cut_tags = st.multiselect("Cut Type", all_cut_tags, default=all_cut_tags, key="mon_cut_filter")
    else:
        selected_cut_tags = all_cut_tags

    # 필터 적용
    filtered_names = sorted([
        name for name, m in masters.items()
        if m.get("extr_line", "L9") in selected_lines
        and m.get("status", "Unknown") in selected_statuses
        and _resolve_cut_tag(m) in selected_cut_tags
    ])

    st.caption(f"필터 결과: {len(filtered_names)} / {len(masters)} 제품")

    st.divider()
    st.subheader("Data Source")
    _sql_ok = is_sql_configured()
    _sample_ok = sample_available()
    if not _sql_ok:
        if _sample_ok:
            st.caption("SQL 미설정 → Test Mode (샘플 CSV)")
        else:
            st.caption("SQL 미설정 & 샘플 없음")
    _src_options = ["Live (SQL)", "Test (Sample)"]
    data_source = st.radio(
        "데이터 소스",
        _src_options,
        index=0 if _sql_ok else 1,
        key="data_source",
        horizontal=True,
        disabled=not _sql_ok,
    )
    is_live = data_source == "Live (SQL)" and _sql_ok
    is_sample = data_source == "Test (Sample)"

    if is_live:
        auto_refresh = st.checkbox("Auto Refresh", value=False, key="auto_refresh")
        refresh_interval = st.number_input(
            "Refresh Interval (sec)", 3, 60, 5, key="refresh_interval",
        ) if auto_refresh else 5

    st.divider()
    st.subheader("제품 선택")
    if not filtered_names:
        st.warning("필터 조건에 맞는 제품이 없습니다.")
        st.stop()
    search_query = st.text_input("제품명 검색", "", placeholder="W2264 입력하면 필터...", key="mon_search")
    if search_query:
        matched = [n for n in sorted(filtered_names) if search_query.upper() in n.upper()]
        st.caption(f"검색 결과: **{len(matched)}**개 매칭")
        if not matched:
            st.warning("검색 결과가 없습니다.")
            st.stop()
    else:
        matched = sorted(filtered_names)
    if not matched:
        st.warning("필터 조건에 맞는 제품이 없습니다.")
        st.stop()

    def _cut_label(name: str) -> str:
        m = masters.get(name)
        if not m:
            return name
        rw = float(m.get("roll_width_mm", 0))
        ct_mm = float(m.get("center_trim_mm", CENTER_TRIM_MM))
        tag = "2-Cut" if is_dual_cut(rw, ct_mm) else "Single"
        return f"{name} ({tag})"

    # Live/Sample 모드: Recipe로 사전 매칭하여 selectbox 기본값 설정
    _auto_matched_name = None
    _match_msg = ""
    if is_live or is_sample:
        _pre_scan = fetch_latest_scan() if is_live else fetch_sample_latest()
        if _pre_scan:
            _pre_result = match_recipe(_pre_scan[1], list(masters.keys()))
            if _pre_result:
                _auto_matched_name = _pre_result.master_key
                _match_msg = _pre_result.message

    # selectbox index 결정
    _select_idx = 0
    if _auto_matched_name and _auto_matched_name in matched:
        _select_idx = matched.index(_auto_matched_name)

    _auto_select = (is_live or is_sample) and _auto_matched_name is not None
    selected_name = st.selectbox(
        "Recipe (제품명)", matched,
        index=_select_idx,
        format_func=_cut_label,
        disabled=_auto_select,
        help="데이터 Recipe로 자동 선택됨" if _auto_select else None,
    )

    st.divider()
    st.subheader("Cut Type Override")
    from core.wedge_geometry import VALID_CUT_TYPES
    cut_type_options = list(VALID_CUT_TYPES)
    cut_type_labels = {
        "auto": "Auto (폭 기준 자동)",
        "dual": "2-Cut (좌+우)",
        "single_left": "Single Left (우측 flat)",
        "single_right": "Single Right (좌측 flat)",
        "single_center": "Single Center",
        "single_left_dual": "Single Left - Dual Shape",
        "single_right_dual": "Single Right - Dual Shape",
    }
    mon_default_cut = masters[selected_name].get("cut_type", "auto") if selected_name in masters else "auto"
    mon_cut_idx = cut_type_options.index(mon_default_cut) if mon_default_cut in cut_type_options else 0
    mon_cut_type = st.selectbox(
        "Cut Type",
        cut_type_options,
        index=mon_cut_idx,
        format_func=lambda x: cut_type_labels.get(x, x),
        key="mon_cut_type",
    )

    if is_sample:
        st.divider()
        st.subheader("Sample Data")
        _csv_files = list_sample_files()
        if _csv_files:
            _csv_names = [f.name for f in _csv_files]
            _csv_sel = st.selectbox("CSV 파일", _csv_names, key="sample_csv")
            _csv_path = next(f for f in _csv_files if f.name == _csv_sel)
            set_sample_csv(_csv_path)
            st.caption(f"Using: {_csv_sel}")
        else:
            st.warning("data/sample-*.csv 파일이 없습니다.")

    st.divider()
    st.subheader("Spec Tolerances")
    gwa_tol = st.number_input("GWA Tolerance (mrad)", value=0.03, step=0.01, format="%.3f")
    lwa_tol = st.number_input("LWA Tolerance (mrad)", value=0.15, step=0.01, format="%.3f")

# ── 데이터 로드 (Live / Sample) ───────────────────────────
_use_flat_fallback = False
scan_time = None
scan_recipe = ""
scan_rollid = ""
scan_rollno = ""

if is_live or is_sample:
    # 데이터 소스에서 최신 스캔 가져오기
    scan_result = fetch_latest_scan() if is_live else fetch_sample_latest()
    if scan_result is None:
        _src_label = "SQL Server" if is_live else "샘플 CSV"
        st.error(f"{_src_label} 데이터가 없습니다.")
        st.stop()

    scan_time, scan_recipe, scan_rollid, scan_rollno, actual_mil = scan_result
    _sql_parsed = parse_recipe(scan_recipe)

    # Recipe에 "MRAD" 없으면 플랫 제품으로 자동 인식
    _recipe_is_flat = _sql_parsed.mrad is None

    # 마스터 자동 매칭 (정규화 + 제품코드 기반)
    _match_result = match_recipe(scan_recipe, list(masters.keys()))
    if _match_result:
        selected_name = _match_result.master_key
    else:
        _use_flat_fallback = True

    # 헤더 표시
    _mode_label = "Live" if is_live else "Sample"
    if _use_flat_fallback:
        _match_display = '<span style="color:#FF8A65;">미등록 (Flat Fallback)</span>'
    elif _match_result and _match_result.confidence == "fuzzy":
        _match_display = (
            f'<span style="color:#FFD54F;">{selected_name}</span> '
            f'<span style="font-size:0.8em;">({_match_result.message})</span>'
        )
    else:
        _match_display = f'<span style="color:#4FC3F7;">{selected_name}</span>'

    st.markdown(
        f'<div style="font-size:1.8rem; font-weight:bold;">'
        f'{_mode_label} | Scan: {scan_time} | '
        f'Roll: {scan_rollno or scan_rollid or "-"} | '
        f'Recipe: {scan_recipe} → {_match_display}'
        f'</div>',
        unsafe_allow_html=True,
    )

# ── 제품 로드 & 프로파일 생성 ─────────────────────────────
if _use_flat_fallback:
    # 마스터 미등록 → 플랫 대체 제품 생성
    _flat_cal = float(np.nanmedian(actual_mil)) if np.any(~np.isnan(actual_mil)) else 30.0
    m = {
        "name": scan_recipe or "Unknown",
        "wedge_angle_mrad": 0.0,
        "roll_width_mm": DIE_FULL_WIDTH_MM,
        "flat_width_mm": DIE_FULL_WIDTH_MM,
        "thin_edge_cal_mil": _flat_cal,
        "cut_type": "single_center",
    }
    _roll_tag = f' | Roll: {scan_rollno}' if scan_rollno else ''
    st.markdown(
        f'<div style="font-size:1.8rem; font-weight:bold;">'
        f'<span style="color:#FF8A65;">{m["name"]}</span> | Flat Product (0 mrad){_roll_tag} | '
        f'Caliper: {_flat_cal:.2f} mil (median)</div>',
        unsafe_allow_html=True,
    )
else:
    # ── 선택된 제품 메타데이터 표시 ─────────────────────────
    meta = masters[selected_name]
    _roll_tag = f' | Roll: {scan_rollno}' if scan_rollno else ''
    st.markdown(
        f'<div style="font-size:1.8rem; font-weight:bold;">'
        f'<span style="color:#4FC3F7;">{selected_name}</span>{_roll_tag} | '
        f'Line: {meta.get("extr_line", "-")} | '
        f'Status: {meta.get("status", "-")} | '
        f'PVB: {meta.get("pvb_type", "-")}</div>',
        unsafe_allow_html=True,
    )
    m = dict(masters[selected_name])
    m["cut_type"] = mon_cut_type  # 사이드바에서 선택한 cut type 적용

    # Recipe에 MRAD가 없으면 플랫 강제 (마스터에 wedge 있어도)
    if (is_live or is_sample) and _recipe_is_flat:
        m["wedge_angle_mrad"] = 0.0

product = ProductMaster.from_dict(m)

# 웨지 각도 0인 경우 (마스터 등록 플랫 제품 포함) → 플랫 처리
is_flat_product = product.wedge_angle_mrad == 0.0

df_target = generate_full_profile(product)

positions = df_target["Position_mm"].values
target_mil = df_target["Target_mil"].values
bin_nos = df_target["Bin"].values

# 플랫 제품: 타겟을 수평선(목표두께)으로 설정
if is_flat_product:
    _flat_target_cal = product.thin_edge_cal_mil  # 마스터 목표두께
    if _flat_target_cal <= 0:
        # 마스터에 목표두께 없으면 실측 median 폴백
        _flat_target_cal = float(np.nanmedian(actual_mil)) if np.any(~np.isnan(actual_mil)) else 30.0
    target_mil = np.full_like(positions, _flat_target_cal)

# actual_mil은 Live/Sample 모드 모두 위에서 이미 로드됨

raw_layout = product.layout()
ct = product.resolved_cut_type

# ── 컷지점 검출 + 드리프트 보정 (STEP C) ────────────────
if not is_flat_product:
    detected = detect_thin_edges(actual_mil, raw_layout)
    drift = calc_drift_offset(raw_layout, detected)

    with st.sidebar:
        st.divider()
        st.subheader("Drift Correction")
        _left_det = detected["left_thin_edge_bin"]
        _left_off = drift["left_offset_bins"]
        st.caption(
            f"Left thin edge: bin **{_left_det}** "
            f"(target bin {raw_layout['left_start_bin']}, offset **{_left_off:+d}**)"
        )
        manual_left = st.number_input(
            "Left Manual Adj (bins)", -20, 20, 0, key="man_left",
            help="자동검출 기준에서 추가 보정. +면 오른쪽 이동",
        )

        if "right_end_bin" in raw_layout:
            _right_det = detected["right_thin_edge_bin"]
            _right_off = drift["right_offset_bins"]
            st.caption(
                f"Right thin edge: bin **{_right_det}** "
                f"(target bin {raw_layout['right_end_bin']}, offset **{_right_off:+d}**)"
            )
            manual_right = st.number_input(
                "Right Manual Adj (bins)", -20, 20, 0, key="man_right",
                help="자동검출 기준에서 추가 보정. +면 오른쪽 이동",
            )
        else:
            manual_right = 0

    layout = apply_offset_to_layout(raw_layout, drift, manual_left, manual_right)
else:
    layout = raw_layout

# ── 롤 버퍼 구축 + 멀티스캔 집계 (STEP D/E) ─────────────
roll_buf = None
roll_summary_left = None
roll_summary_right = None
_agg_scan_count = 0

if not is_flat_product:
    _show_left_agg = ct not in ("single_right",)
    _show_right_agg = (
        layout.get("right_start_mm") is not None
        and ct not in ("single_left", "single_center")
    )

    # 멀티스캔 데이터 확보
    _all_data = None
    if (is_live or is_sample) and not _use_flat_fallback:
        if is_live:
            roll_buf = fetch_current_roll_buffer(selected_name, max_scans=500)
        else:
            # Sample 모드: CSV에서 멀티스캔 → 롤 버퍼
            _sample_scans = fetch_sample_recent(n=500)
            if _sample_scans:
                roll_buf = build_roll_buffer_from_scans(_sample_scans, selected_name)

        if roll_buf and roll_buf.count >= 2:
            with st.sidebar:
                st.divider()
                st.subheader("Aggregation")
                st.caption(f"Roll: {roll_buf.count} scans")
                _use_time_filter = st.checkbox("Time Filter", value=False, key="time_filter")
                if _use_time_filter and roll_buf.start_time and roll_buf.end_time:
                    from datetime import time as dt_time
                    _t_start = st.time_input("From", dt_time(0, 0), key="agg_start")
                    _t_end = st.time_input("To", dt_time(23, 59), key="agg_end")
                    _filtered = roll_buf.get_time_filtered(
                        start=roll_buf.start_time.replace(
                            hour=_t_start.hour, minute=_t_start.minute, second=0,
                        ),
                        end=roll_buf.end_time.replace(
                            hour=_t_end.hour, minute=_t_end.minute, second=59,
                        ),
                    )
                    if _filtered:
                        _all_data = np.array([s.actual_mil for s in _filtered])
                        st.caption(f"Filtered: {len(_filtered)} scans")
                    else:
                        _all_data = roll_buf.get_all_data()
                        st.warning("필터 결과 0건 → 전체 사용")
                else:
                    _all_data = roll_buf.get_all_data()

    # 집계 계산
    if _all_data is not None and len(_all_data) >= 2:
        _agg_scan_count = len(_all_data)
        if _show_left_agg:
            _left_angles = calc_multi_scan_angles(
                positions, _all_data, layout, product, "left",
            )
            roll_summary_left = summarize_angles(
                _left_angles, product.wedge_angle_mrad, gwa_tol, lwa_tol,
            )
        if _show_right_agg:
            _right_angles = calc_multi_scan_angles(
                positions, _all_data, layout, product, "right",
            )
            roll_summary_right = summarize_angles(
                _right_angles, product.wedge_angle_mrad, gwa_tol, lwa_tol,
            )

# ══════════════════════════════════════════════════════════
# TAB 1: 전체 프로파일
# ══════════════════════════════════════════════════════════
tab1, tab2, tab3, tab4 = st.tabs([
    "Full Profile", "Left Product", "Right Product", "LWA Detail"
])

with tab1:
    fig = go.Figure()

    # 제품 영역 배경 (어노테이션 없이 색상만)
    fig.add_vrect(x0=layout["left_start_mm"], x1=layout["left_end_mm"],
                  fillcolor="rgba(0,100,255,0.05)", line_width=0)
    if layout.get("right_start_mm") is not None:
        fig.add_vrect(x0=layout["right_start_mm"], x1=layout["right_end_mm"],
                      fillcolor="rgba(255,100,0,0.05)", line_width=0)

    if is_flat_product:
        # 플랫 제품: 전체 영역을 Flat 색상으로 표시
        fig.add_vrect(x0=layout["left_start_mm"], x1=layout["left_end_mm"],
                      fillcolor="rgba(0,255,0,0.06)", line_width=0)
        _lwe = layout["left_end_mm"]
        if layout.get("right_start_mm") is not None:
            _rws = layout["right_start_mm"]
    else:
        # Wedge / Flat 구간 (좌측)
        if ct not in ("single_right",):
            _lwp = product.wedge_portion_mm
            _lwe = layout["left_start_mm"] + _lwp
            fig.add_vrect(x0=layout["left_start_mm"], x1=_lwe,
                          fillcolor="rgba(255,255,0,0.06)", line_width=0)
            fig.add_vrect(x0=_lwe, x1=layout["left_end_mm"],
                          fillcolor="rgba(0,255,0,0.06)", line_width=0)
        # Wedge / Flat 구간 (우측)
        if layout.get("right_start_mm") is not None and ct not in ("single_left",):
            _rwp = product.wedge_portion_mm
            _rws = layout["right_end_mm"] - _rwp
            fig.add_vrect(x0=layout["right_start_mm"], x1=_rws,
                          fillcolor="rgba(0,255,0,0.06)", line_width=0)
            fig.add_vrect(x0=_rws, x1=layout["right_end_mm"],
                          fillcolor="rgba(255,255,0,0.06)", line_width=0)

        # HUD 영역
        if product.hud_bot_mm and product.hud_top_mm:
            if ct not in ("single_right",):
                _lte = layout["left_start_mm"]
                fig.add_vrect(x0=_lte + product.hud_bot_mm, x1=_lte + product.hud_top_mm,
                              fillcolor="rgba(255,0,255,0.08)", line_width=1,
                              line=dict(color="magenta", dash="dash"))
            if layout.get("right_start_mm") is not None and ct not in ("single_left",):
                _rte = layout["right_end_mm"]
                fig.add_vrect(x0=_rte - product.hud_top_mm, x1=_rte - product.hud_bot_mm,
                              fillcolor="rgba(255,0,255,0.08)", line_width=1,
                              line=dict(color="magenta", dash="dash"))

    fig.add_trace(go.Scatter(
        x=positions, y=target_mil, customdata=bin_nos,
        mode="lines", name="Target",
        line=dict(color="blue", width=2),
        hovertemplate="Bin %{customdata} | %{x:.1f}mm<br>%{y:.2f} mil<extra>Target</extra>",
    ))
    fig.add_trace(go.Scatter(
        x=positions, y=actual_mil, customdata=bin_nos,
        mode="lines", name="Actual",
        line=dict(color="red", width=1.5, dash="dot"),
        hovertemplate="Bin %{customdata} | %{x:.1f}mm<br>%{y:.2f} mil<extra>Actual</extra>",
    ))

    # 차이 하이라이트
    diff = np.abs(actual_mil - target_mil)
    threshold = 1.0  # mil
    exceedance = diff > threshold
    if np.any(exceedance):
        exceed_pos = positions[exceedance]
        exceed_val = actual_mil[exceedance]
        exceed_bins = bin_nos[exceedance]
        fig.add_trace(go.Scatter(
            x=exceed_pos, y=exceed_val, customdata=exceed_bins,
            mode="markers", name=f"|Δ| > {threshold} mil",
            marker=dict(color="orange", size=4, symbol="circle"),
            hovertemplate="Bin %{customdata} | %{x:.1f}mm<br>%{y:.2f} mil<extra>Exceed</extra>",
        ))

    # ── LWA Out-of-Spec 화살표 마커 ──
    _target_mrad = product.wedge_angle_mrad
    if not is_flat_product and product.hud_bot_mm and product.hud_top_mm:
        _lwa_out_x, _lwa_out_y, _lwa_out_v = [], [], []
        _fp_show_left = ct not in ("single_right",)
        _fp_show_right = (layout.get("right_start_mm") is not None
                          and ct not in ("single_left", "single_center"))
        if _fp_show_left:
            _lp, _lv = calc_lwa(positions, actual_mil,
                                product.hud_bot_mm, product.hud_top_mm,
                                layout["left_start_mm"], "left")
            if len(_lv) > 0:
                _om = np.abs(_lv - _target_mrad) > lwa_tol
                if np.any(_om):
                    _lwa_out_x.extend(_lp[_om])
                    _lwa_out_y.extend(np.interp(_lp[_om], positions, actual_mil))
                    _lwa_out_v.extend(_lv[_om])
        if _fp_show_right:
            _rp, _rv = calc_lwa(positions, actual_mil,
                                product.hud_bot_mm, product.hud_top_mm,
                                layout["right_end_mm"], "right")
            if len(_rv) > 0:
                _om = np.abs(_rv - _target_mrad) > lwa_tol
                if np.any(_om):
                    _lwa_out_x.extend(_rp[_om])
                    _lwa_out_y.extend(np.interp(_rp[_om], positions, actual_mil))
                    _lwa_out_v.extend(_rv[_om])
        if _lwa_out_x:
            _lwa_out_x = np.array(_lwa_out_x)
            _lwa_out_y = np.array(_lwa_out_y)
            _lwa_out_v = np.array(_lwa_out_v)
            _y_offset = (actual_mil.max() - actual_mil.min()) * 0.06
            fig.add_trace(go.Scatter(
                x=_lwa_out_x, y=_lwa_out_y + _y_offset,
                mode="markers", name=f"LWA Out ({len(_lwa_out_x)}pts)",
                marker=dict(
                    symbol="triangle-down", size=11,
                    color="rgba(255,50,100,0.95)",
                    line=dict(color="white", width=1.5),
                ),
                customdata=np.round(_lwa_out_v, 4),
                hovertemplate="%{x:.0f}mm<br>Cal: %{y:.2f} mil<br>LWA: %{customdata} mrad<extra>LWA OUT</extra>",
            ))

    # ── 구간 라벨 (annotation) ──
    def _add_label(x_c, text, y_p, color="white", size=11):
        fig.add_annotation(x=x_c, y=y_p, text=f"<b>{text}</b>",
                           xref="x", yref="paper", showarrow=False,
                           font=dict(color=color, size=size),
                           bgcolor="rgba(0,0,0,0.6)", borderpad=3)

    if is_flat_product:
        _add_label((layout["left_start_mm"] + layout["left_end_mm"]) / 2,
                   "Flat Product", 1.02, color="lime")
    else:
        _add_label((layout["left_start_mm"] + layout["left_end_mm"]) / 2,
                   "Left Product", 1.02, color="dodgerblue")
        if layout.get("right_start_mm") is not None:
            _add_label((layout["right_start_mm"] + layout["right_end_mm"]) / 2,
                       "Right Product", 1.02, color="orange")
        if ct not in ("single_right",):
            _add_label((layout["left_start_mm"] + _lwe) / 2, "Wedge", 0.05, color="yellow", size=10)
            _add_label((_lwe + layout["left_end_mm"]) / 2, "Flat", 0.05, color="lime", size=10)
        if layout.get("right_start_mm") is not None and ct not in ("single_left",):
            _add_label((layout["right_start_mm"] + _rws) / 2, "Flat", 0.05, color="lime", size=10)
            _add_label((_rws + layout["right_end_mm"]) / 2, "Wedge", 0.05, color="yellow", size=10)
        if product.hud_bot_mm and product.hud_top_mm and ct not in ("single_right",):
            _hc = layout["left_start_mm"] + (product.hud_bot_mm + product.hud_top_mm) / 2
            _add_label(_hc, "HUD (L)", 0.5, color="magenta", size=10)
        if product.hud_bot_mm and product.hud_top_mm and layout.get("right_start_mm") is not None and ct not in ("single_left",):
            _hc = layout["right_end_mm"] - (product.hud_bot_mm + product.hud_top_mm) / 2
            _add_label(_hc, "HUD (R)", 0.5, color="magenta", size=10)

    # Bin No 상단 축: 50 간격
    _bin_ticks = [1] + list(range(50, 449, 50)) + [449]
    _bin_pos = [(b - 1) * BIN_PITCH_MM for b in _bin_ticks]
    _bin_lbl = [str(b) for b in _bin_ticks]

    fig.update_layout(
        title=f"Full Profile: {product.name} ({'Flat' if is_flat_product else product.cut_label})",
        xaxis_title="Position (mm)",
        yaxis_title="Caliper (mil)",
        height=500, hovermode="closest",
        margin=dict(t=60, b=40, l=50, r=30),
        legend=dict(yanchor="top", y=0.99, xanchor="right", x=0.99),
        xaxis2=dict(
            title="Bin No", overlaying="x", side="top", matches="x",
            tickmode="array", tickvals=_bin_pos, ticktext=_bin_lbl,
            showgrid=False, tickangle=0, tickfont=dict(size=11),
        ),
    )
    fig.add_trace(go.Scatter(x=[None], y=[None], xaxis="x2", showlegend=False, hoverinfo="skip"))
    st.plotly_chart(fig, use_container_width=True, config={"edits": {"legendPosition": True}})

    # ── Spec Judgment (Full Profile) ──────────────────
    _wa_t = product.wedge_angle_mrad
    _wp_fp = product.wedge_portion_mm

    st.markdown(f"**Angle Target : {_wa_t:.4f} mrad**")

    if is_flat_product:
        # 플랫 제품: 편차(variation) 판정
        _valid = ~np.isnan(actual_mil)
        _valid_cal = actual_mil[_valid]
        if len(_valid_cal) > 0:
            _flat_mean = float(np.nanmean(_valid_cal))
            _flat_std = float(np.nanstd(_valid_cal))
            _flat_range = float(np.nanmax(_valid_cal) - np.nanmin(_valid_cal))
            _flat_max_dev = float(np.max(np.abs(_valid_cal - _flat_target_cal)))
            _flat_judge = "OK" if _flat_max_dev <= lwa_tol * 25.4 else "NG"

            st.markdown(f"**Flat Product** | Target: {_flat_target_cal:.2f} mil")
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Mean", f"{_flat_mean:.2f} mil")
            c2.metric("Std Dev", f"{_flat_std:.3f} mil")
            c3.metric("Range", f"{_flat_range:.2f} mil")
            c4.metric("Max Dev", f"{_flat_max_dev:.2f} mil",
                      _flat_judge,
                      delta_color="normal" if _flat_judge == "OK" else "inverse")
        else:
            st.info("플랫 제품 – 유효 데이터 없음")

    _show_left = ct not in ("single_right",) and not is_flat_product
    _show_right = (layout.get("right_start_mm") is not None
                   and ct not in ("single_left", "single_center")
                   and not is_flat_product)

    def _show_side_metrics(side_label, te_pos, direction):
        """한쪽 제품의 UWA/GWA/LWA metric 카드 표시."""
        flat_pos = te_pos + _wp_fp if direction == "left" else te_pos - _wp_fp
        uwa_v = calc_uwa(positions, actual_mil, min(te_pos, flat_pos), max(te_pos, flat_pos))
        uwa_j = "PASS" if abs(uwa_v - _wa_t) <= gwa_tol else "FAIL"

        st.caption(f"**{side_label} Product**")
        c1, c2, c3 = st.columns(3)
        c1.metric("UWA", f"{uwa_v:.4f} mrad",
                  f"{uwa_j} (spec +/-{gwa_tol})",
                  delta_color="normal" if uwa_j == "PASS" else "inverse")

        if product.gwa_bot_mm and product.gwa_top_mm:
            gwa_v = calc_gwa(positions, actual_mil,
                             product.gwa_bot_mm, product.gwa_top_mm, te_pos, direction)
            gwa_j = judge_gwa(gwa_v, _wa_t, gwa_tol)
            c2.metric("GWA", f"{gwa_v:.4f} mrad",
                      f"{gwa_j} (spec +/-{gwa_tol})",
                      delta_color="normal" if gwa_j == "PASS" else "inverse")
        else:
            c2.metric("GWA", "N/A", "미정의")

        if product.hud_bot_mm and product.hud_top_mm:
            _, lv = calc_lwa(positions, actual_mil,
                             product.hud_bot_mm, product.hud_top_mm, te_pos, direction)
            if len(lv) > 0:
                lj, lf = judge_lwa(lv, _wa_t, lwa_tol)
                c3.metric("LWA", f"{lv.min():.4f} ~ {lv.max():.4f}",
                          f"{'PASS' if lj == 'PASS' else f'FAIL ({lf}pts)'} (spec +/-{lwa_tol})",
                          delta_color="normal" if lj == "PASS" else "inverse")
            else:
                c3.metric("LWA", "N/A", "데이터 없음")
        else:
            c3.metric("LWA", "N/A", "미정의")

    if _show_left:
        _show_side_metrics("Left", layout["left_start_mm"], "left")
    if _show_right:
        _show_side_metrics("Right", layout["right_end_mm"], "right")

    # ── 롤 집계 판정 테이블 (STEP D) ──────────────────────
    def _render_judgment_table(side_label, summary):
        """한쪽 제품의 판정 테이블: 행=지표, 열=Target/Avg/Worst/Last/판정."""
        if summary is None:
            return

        rows = []
        for key, label in [("uwa", "UWA"), ("gwa", "GWA"), ("lwa", "LWA")]:
            s = summary[key]
            if s is None:
                rows.append({
                    "Metric": label, "Target": f"{_wa_t:.4f}",
                    "Average": "N/A", "Worst": "N/A", "Last": "N/A", "Judge": "-",
                })
            else:
                rows.append({
                    "Metric": label,
                    "Target": f"{_wa_t:.4f}",
                    "Average": f"{s['avg']:.4f}",
                    "Worst": f"{s['worst']:.4f}",
                    "Last": f"{s['last']:.4f}",
                    "Judge": "NG" if s["worst_judge"] == "FAIL" else "OK",
                })

        df = pd.DataFrame(rows)

        def _style_row(row):
            """NG 행 전체 빨간 하이라이트, OK는 초록."""
            if row["Judge"] == "NG":
                return ["background-color: #ff4444; color: white; font-weight: bold"] * len(row)
            if row["Judge"] == "OK":
                return ["background-color: #2d5a2d; color: #88ff88"] * len(row)
            return [""] * len(row)

        styled = df.style.apply(_style_row, axis=1)
        st.dataframe(styled, use_container_width=True, hide_index=True)

    if (roll_summary_left or roll_summary_right) and not is_flat_product:
        st.divider()
        # 헤더
        _rollno_label = ""
        if roll_buf and roll_buf.scans and roll_buf.scans[0].rollno:
            _rollno_label = f" | ROLLNO: {roll_buf.scans[0].rollno}"
        _time_range = ""
        if roll_buf and roll_buf.start_time:
            _time_range = f" ({roll_buf.start_time} ~ {roll_buf.end_time})"
        _mode_label = "Live" if is_live else "Test"
        st.markdown(
            f'**Roll Judgment{_rollno_label}** — '
            f'{_agg_scan_count} scans [{_mode_label}]{_time_range}'
        )

        if roll_summary_left and roll_summary_right:
            _jc1, _jc2 = st.columns(2)
            with _jc1:
                st.caption("**Left Product**")
                _render_judgment_table("Left", roll_summary_left)
            with _jc2:
                st.caption("**Right Product**")
                _render_judgment_table("Right", roll_summary_right)
        elif roll_summary_left:
            st.caption("**Left Product**")
            _render_judgment_table("Left", roll_summary_left)
        elif roll_summary_right:
            st.caption("**Right Product**")
            _render_judgment_table("Right", roll_summary_right)


# ── 헬퍼: 한 컷 제품 차트 ────────────────────────────────
def _plot_cut(
    cut_label: str,
    start_mm: float,
    end_mm: float,
    thin_edge_pos_mm: float,
    direction: str,
    wedge_portion_override: float = None,
    is_flat_only: bool = False,
):
    """한 컷 제품의 프로파일 + 구간 표시."""
    mask = (positions >= start_mm) & (positions <= end_mm)
    pos_cut = positions[mask]
    tgt_cut = target_mil[mask]
    act_cut = actual_mil[mask]
    bins_cut = bin_nos[mask]

    fig = go.Figure()

    # Wedge / Flat 구간 (어노테이션 없이 색상만)
    wp = wedge_portion_override if wedge_portion_override is not None else product.wedge_portion_mm
    if is_flat_only:
        fig.add_vrect(x0=start_mm, x1=end_mm,
                       fillcolor="rgba(0,200,100,0.12)", line_width=0)
        _w_mid = (start_mm + end_mm) / 2
    elif direction == "left":
        wedge_end = start_mm + wp
        fig.add_vrect(x0=start_mm, x1=wedge_end,
                       fillcolor="rgba(255,200,0,0.12)", line_width=0)
        fig.add_vrect(x0=wedge_end, x1=end_mm,
                       fillcolor="rgba(0,200,100,0.12)", line_width=0)
    else:
        wedge_start = end_mm - wp
        fig.add_vrect(x0=start_mm, x1=wedge_start,
                       fillcolor="rgba(0,200,100,0.12)", line_width=0)
        fig.add_vrect(x0=wedge_start, x1=end_mm,
                       fillcolor="rgba(255,200,0,0.12)", line_width=0)

    # HUD 영역
    hud_abs_bot = hud_abs_top = None
    if product.hud_bot_mm and product.hud_top_mm:
        if direction == "left":
            hud_abs_bot = thin_edge_pos_mm + product.hud_bot_mm
            hud_abs_top = thin_edge_pos_mm + product.hud_top_mm
        else:
            hud_abs_bot = thin_edge_pos_mm - product.hud_top_mm
            hud_abs_top = thin_edge_pos_mm - product.hud_bot_mm
        fig.add_vrect(x0=hud_abs_bot, x1=hud_abs_top,
                       fillcolor="rgba(255,0,255,0.08)",
                       line=dict(color="magenta", width=1, dash="dash"))

    fig.add_trace(go.Scatter(x=pos_cut, y=tgt_cut, customdata=bins_cut,
                              mode="lines", name="Target",
                              line=dict(color="blue", width=2),
                              hovertemplate="Bin %{customdata} | %{x:.1f}mm<br>%{y:.2f} mil<extra>Target</extra>"))
    fig.add_trace(go.Scatter(x=pos_cut, y=act_cut, customdata=bins_cut,
                              mode="lines", name="Actual",
                              line=dict(color="red", width=1.5, dash="dot"),
                              hovertemplate="Bin %{customdata} | %{x:.1f}mm<br>%{y:.2f} mil<extra>Actual</extra>"))

    # ── LWA Out-of-Spec 화살표 마커 ──
    if not is_flat_only and product.hud_bot_mm and product.hud_top_mm:
        _lp, _lv = calc_lwa(positions, actual_mil,
                             product.hud_bot_mm, product.hud_top_mm,
                             thin_edge_pos_mm, direction)
        if len(_lv) > 0:
            _target_wa = product.wedge_angle_mrad
            _om = np.abs(_lv - _target_wa) > lwa_tol
            if np.any(_om):
                _ox = _lp[_om]
                _oy = np.interp(_ox, positions, actual_mil)
                _ov = _lv[_om]
                _y_off = (act_cut.max() - act_cut.min()) * 0.06
                fig.add_trace(go.Scatter(
                    x=_ox, y=_oy + _y_off,
                    mode="markers", name=f"LWA Out ({len(_ox)}pts)",
                    marker=dict(
                        symbol="triangle-down", size=11,
                        color="rgba(255,50,100,0.95)",
                        line=dict(color="white", width=1.5),
                    ),
                    customdata=np.round(_ov, 4),
                    hovertemplate="%{x:.0f}mm<br>Cal: %{y:.2f} mil<br>LWA: %{customdata} mrad<extra>LWA OUT</extra>",
                ))

    # ── 구간 라벨 (annotation) ──
    def _lbl(x_c, text, y_p, color="white", size=10):
        fig.add_annotation(x=x_c, y=y_p, text=f"<b>{text}</b>",
                           xref="x", yref="paper", showarrow=False,
                           font=dict(color=color, size=size),
                           bgcolor="rgba(0,0,0,0.6)", borderpad=3)

    if is_flat_only:
        _lbl(_w_mid, "Flat", 0.05, color="lime")
    elif direction == "left":
        _lbl((start_mm + wedge_end) / 2, "Wedge", 0.05, color="yellow")
        _lbl((wedge_end + end_mm) / 2, "Flat", 0.05, color="lime")
    else:
        _lbl((start_mm + wedge_start) / 2, "Flat", 0.05, color="lime")
        _lbl((wedge_start + end_mm) / 2, "Wedge", 0.05, color="yellow")

    if hud_abs_bot is not None:
        _lbl((hud_abs_bot + hud_abs_top) / 2, "HUD", 0.5, color="magenta")

    # Bin No 상단 축
    _bt = [1] + list(range(50, 449, 50)) + [449]
    _bp = [(b - 1) * BIN_PITCH_MM for b in _bt]
    _bl = [str(b) for b in _bt]

    fig.update_layout(
        title=f"{cut_label}: {product.name}",
        xaxis_title="Position (mm)", yaxis_title="Caliper (mil)",
        height=450, hovermode="closest",
        margin=dict(t=50, b=40, l=50, r=30),
        legend=dict(yanchor="top", y=0.99, xanchor="right", x=0.99),
        xaxis2=dict(
            title="Bin No", overlaying="x", side="top", matches="x",
            tickmode="array", tickvals=_bp, ticktext=_bl,
            showgrid=False, tickangle=0, tickfont=dict(size=11),
        ),
    )
    fig.add_trace(go.Scatter(x=[None], y=[None], xaxis="x2", showlegend=False, hoverinfo="skip"))
    st.plotly_chart(fig, use_container_width=True, config={"edits": {"legendPosition": True}})

    # ── Wedge Angle 판정 (compact) ───────────────────
    if direction == "left":
        te_pos = start_mm
        flat_start = start_mm + wp
    else:
        te_pos = end_mm
        flat_start = end_mm - wp

    target_wa = product.wedge_angle_mrad
    uwa = calc_uwa(positions, actual_mil, min(te_pos, flat_start), max(te_pos, flat_start))

    uwa_result = "PASS" if abs(uwa - target_wa) <= gwa_tol else "FAIL"
    col1, col2, col3 = st.columns(3)
    col1.metric("UWA", f"{uwa:.4f} mrad",
                f"{'PASS' if uwa_result == 'PASS' else 'FAIL'} (spec +/-{gwa_tol})",
                delta_color="normal" if uwa_result == "PASS" else "inverse")

    if product.gwa_bot_mm and product.gwa_top_mm:
        gwa = calc_gwa(positions, actual_mil,
                        product.gwa_bot_mm, product.gwa_top_mm, te_pos, direction)
        gwa_result = judge_gwa(gwa, target_wa, gwa_tol)
        col2.metric("GWA", f"{gwa:.4f} mrad",
                     f"{'PASS' if gwa_result == 'PASS' else 'FAIL'} (spec +/-{gwa_tol})",
                     delta_color="normal" if gwa_result == "PASS" else "inverse")

        if product.hud_bot_mm and product.hud_top_mm:
            lwa_pos, lwa_vals = calc_lwa(positions, actual_mil,
                                          product.hud_bot_mm, product.hud_top_mm, te_pos, direction)
            if len(lwa_vals) > 0:
                lwa_result, lwa_fails = judge_lwa(lwa_vals, target_wa, lwa_tol)
                col3.metric("LWA", f"{lwa_vals.min():.4f} ~ {lwa_vals.max():.4f}",
                             f"{'PASS' if lwa_result == 'PASS' else f'FAIL ({lwa_fails}pts)'} (spec +/-{lwa_tol})",
                             delta_color="normal" if lwa_result == "PASS" else "inverse")
    else:
        col2.metric("GWA", "N/A", "미정의")
        col3.metric("LWA", "N/A", "미정의")

    return te_pos


# ══════════════════════════════════════════════════════════
# TAB 2: Left Product
# ══════════════════════════════════════════════════════════
ct = product.resolved_cut_type
with tab2:
    if is_flat_product:
        st.info("플랫 제품 – 웨지 구간 없음. Full Profile 탭에서 전체 프로파일을 확인하세요.")
    elif ct == "single_right":
        if layout.get("left_start_mm") is not None:
            _plot_cut(
                "Left Product (Flat)",
                layout["left_start_mm"], layout["left_end_mm"],
                thin_edge_pos_mm=layout["left_start_mm"],
                direction="left",
                is_flat_only=True,
            )
        else:
            st.info("Single-Right 모드 – Left Product는 flat입니다.")
    elif ct == "single_right_dual":
        _plot_cut(
            "Left Product (Opposite)",
            layout["left_start_mm"], layout["left_end_mm"],
            thin_edge_pos_mm=layout["left_start_mm"],
            direction="left",
        )
    else:
        _plot_cut(
            "Left Product",
            layout["left_start_mm"], layout["left_end_mm"],
            thin_edge_pos_mm=layout["left_start_mm"],
            direction="left",
        )

# ══════════════════════════════════════════════════════════
# TAB 3: Right Product
# ══════════════════════════════════════════════════════════
with tab3:
    if is_flat_product:
        st.info("플랫 제품 – 웨지 구간 없음. Full Profile 탭에서 전체 프로파일을 확인하세요.")
    elif ct == "single_left":
        if layout.get("right_start_mm") is not None:
            _plot_cut(
                "Right Product (Flat)",
                layout["right_start_mm"], layout["right_end_mm"],
                thin_edge_pos_mm=layout["right_end_mm"],
                direction="right",
                is_flat_only=True,
            )
        else:
            st.info("Single-Left 모드 – Right Product는 flat입니다.")
    elif ct == "single_left_dual":
        _plot_cut(
            "Right Product (Opposite)",
            layout["right_start_mm"], layout["right_end_mm"],
            thin_edge_pos_mm=layout["right_end_mm"],
            direction="right",
        )
    elif layout.get("right_start_mm") is not None:
        _plot_cut(
            "Right Product",
            layout["right_start_mm"], layout["right_end_mm"],
            thin_edge_pos_mm=layout["right_end_mm"],
            direction="right",
        )
    elif ct == "single_center":
        st.info("싱글 센터 제품 – Right Product 없음")
    else:
        st.info("싱글컷 제품 – Right Product 없음")

# ══════════════════════════════════════════════════════════
# TAB 4: LWA Detail
# ══════════════════════════════════════════════════════════
with tab4:
    if is_flat_product:
        st.info("플랫 제품 (Wedge Angle = 0 mrad) – LWA 분석 대상이 아닙니다.")
    elif not (product.hud_bot_mm and product.hud_top_mm):
        st.info("HUD 영역이 정의되지 않은 제품입니다.")
    else:
        # Left
        left_te = layout["left_start_mm"]
        lwa_pos_l, lwa_val_l = calc_lwa(positions, actual_mil,
                                         product.hud_bot_mm, product.hud_top_mm, left_te, "left")

        has_right = (layout.get("right_start_mm") is not None
                     and ct not in ("single_left", "single_center"))
        fig_lwa = make_subplots(rows=1, cols=2 if has_right else 1,
                                 subplot_titles=["Left LWA"] + (["Right LWA"] if has_right else []),
                                 shared_yaxes=True,
                                 horizontal_spacing=0.03)

        target_wa = product.wedge_angle_mrad
        _spec_hi = target_wa + lwa_tol
        _spec_lo = target_wa - lwa_tol

        def _add_lwa_line(lwa_pos, lwa_val, col_idx, side_name):
            if len(lwa_val) == 0:
                return
            out_mask = np.abs(lwa_val - target_wa) > lwa_tol
            n_out = int(np.sum(out_mask))
            _leg = "legend" if col_idx == 1 else "legend2"

            fig_lwa.add_trace(go.Scatter(
                x=np.concatenate([lwa_pos, lwa_pos[::-1]]),
                y=np.concatenate([np.full_like(lwa_pos, _spec_hi),
                                  np.full_like(lwa_pos, _spec_lo)]),
                fill="toself", fillcolor="rgba(0,200,0,0.15)",
                line=dict(width=0), showlegend=True,
                name="Spec Range", hoverinfo="skip",
                legend=_leg,
            ), row=1, col=col_idx)

            for _sv in (_spec_hi, _spec_lo):
                fig_lwa.add_trace(go.Scatter(
                    x=lwa_pos, y=np.full_like(lwa_pos, _sv),
                    mode="lines", line=dict(color="yellow", width=1.5, dash="dot"),
                    showlegend=False, hoverinfo="skip",
                ), row=1, col=col_idx)

            fig_lwa.add_trace(go.Scatter(
                x=lwa_pos, y=np.full_like(lwa_pos, target_wa),
                mode="lines", line=dict(color="cyan", width=2),
                showlegend=True, name=f"Target ({target_wa:.4f})",
                hoverinfo="skip",
                legend=_leg,
            ), row=1, col=col_idx)

            fig_lwa.add_trace(go.Scatter(
                x=lwa_pos, y=lwa_val,
                mode="lines", name=f"{side_name} LWA",
                line=dict(color="lime", width=2),
                showlegend=True,
                hovertemplate="%{x:.0f}mm<br>LWA: %{y:.4f} mrad<extra></extra>",
                legend=_leg,
            ), row=1, col=col_idx)

            if n_out > 0:
                fig_lwa.add_trace(go.Scatter(
                    x=lwa_pos[out_mask], y=lwa_val[out_mask],
                    mode="markers", name=f"Out ({n_out}pts)",
                    marker=dict(color="red", size=8),
                    showlegend=True,
                    hovertemplate="%{x:.0f}mm<br>LWA: %{y:.4f} mrad<extra>OUT</extra>",
                    legend=_leg,
                ), row=1, col=col_idx)

        _add_lwa_line(lwa_pos_l, lwa_val_l, 1, "Left")

        if has_right:
            right_te = layout["right_end_mm"]
            lwa_pos_r, lwa_val_r = calc_lwa(positions, actual_mil,
                                             product.hud_bot_mm, product.hud_top_mm, right_te, "right")
            _add_lwa_line(lwa_pos_r, lwa_val_r, 2, "Right")

        _all_lwa = np.concatenate(
            [lwa_val_l] +
            ([lwa_val_r] if has_right and len(lwa_val_r) > 0 else [])
        ) if len(lwa_val_l) > 0 else np.array([target_wa])
        _max_dev = max(abs(_all_lwa.max() - target_wa), abs(_all_lwa.min() - target_wa), lwa_tol)
        _y_pad = max(_max_dev * 1.3, lwa_tol * 3)
        _y_lo = target_wa - _y_pad
        _y_hi = target_wa + _y_pad

        fig_lwa.update_xaxes(
            title_text="Position (mm)",
            tickmode="array",
            tickvals=BIN_AXIS_TICK_POSITIONS,
            ticktext=[f"{p:.0f}" for p in BIN_AXIS_TICK_POSITIONS],
        )
        fig_lwa.update_yaxes(range=[_y_lo, _y_hi])

        _bt = [1] + list(range(50, 449, 50)) + [449]
        _bp = [(b - 1) * BIN_PITCH_MM for b in _bt]
        _bl = [str(b) for b in _bt]
        _bin_top_axis = dict(
            tickmode="array", tickvals=_bp, ticktext=_bl,
            showgrid=False, tickangle=0, tickfont=dict(size=10),
            side="top",
        )

        _legend_style = dict(
            font=dict(size=10, color="white"),
            bgcolor="rgba(0,0,0,0.6)",
            bordercolor="gray", borderwidth=1,
        )
        _layout_kw = dict(
            height=500,
            yaxis_title="LWA (mrad)",
            showlegend=True,
            legend=dict(
                yanchor="top", y=0.97, xanchor="right", x=0.47,
                **_legend_style,
            ),
            margin=dict(t=50, b=50, l=50, r=20),
            xaxis3=dict(overlaying="x", matches="x", **_bin_top_axis),
        )
        fig_lwa.add_trace(go.Scatter(
            x=[None], y=[None], xaxis="x3", yaxis="y",
            showlegend=False, hoverinfo="skip"))

        if has_right:
            _layout_kw["legend2"] = dict(
                yanchor="top", y=0.97, xanchor="right", x=0.99,
                **_legend_style,
            )
            _layout_kw["xaxis4"] = dict(overlaying="x2", matches="x2", **_bin_top_axis)
            fig_lwa.add_trace(go.Scatter(
                x=[None], y=[None], xaxis="x4", yaxis="y2",
                showlegend=False, hoverinfo="skip"))

        fig_lwa.update_layout(**_layout_kw)
        st.plotly_chart(fig_lwa, use_container_width=True, config={"edits": {"legendPosition": True}})

        # ── 판정 요약 (compact) ────────────────────────────
        results = []
        uwa_l = calc_uwa(positions, actual_mil, layout["left_start_mm"],
                           layout["left_start_mm"] + product.wedge_portion_mm)
        uwa_lj = "PASS" if abs(uwa_l - target_wa) <= gwa_tol else "FAIL"
        row_data = {"Side": "Left", "Target": f"{target_wa:.4f}",
                    "UWA": f"{uwa_l:.4f}", "UWA Spec": f"+/-{gwa_tol}", "UWA Result": uwa_lj}

        if product.gwa_bot_mm and product.gwa_top_mm:
            gwa_l = calc_gwa(positions, actual_mil, product.gwa_bot_mm, product.gwa_top_mm, left_te, "left")
            gwa_j = judge_gwa(gwa_l, target_wa, gwa_tol)
            row_data["GWA"] = f"{gwa_l:.4f}"
            row_data["GWA Spec"] = f"+/-{gwa_tol}"
            row_data["GWA Result"] = gwa_j

        if len(lwa_val_l) > 0:
            lwa_j, lwa_f = judge_lwa(lwa_val_l, target_wa, lwa_tol)
            row_data["LWA Range"] = f"{lwa_val_l.min():.4f} ~ {lwa_val_l.max():.4f}"
            row_data["LWA Spec"] = f"+/-{lwa_tol}"
            row_data["LWA Result"] = lwa_j if lwa_j == "PASS" else f"FAIL ({lwa_f}pts)"

        results.append(row_data)

        if has_right:
            right_te = layout["right_end_mm"]
            uwa_r = calc_uwa(positions, actual_mil,
                              layout["right_end_mm"] - product.wedge_portion_mm, layout["right_end_mm"])
            uwa_rj = "PASS" if abs(uwa_r - target_wa) <= gwa_tol else "FAIL"
            row_data_r = {"Side": "Right", "Target": f"{target_wa:.4f}",
                          "UWA": f"{uwa_r:.4f}", "UWA Spec": f"+/-{gwa_tol}", "UWA Result": uwa_rj}

            if product.gwa_bot_mm and product.gwa_top_mm:
                gwa_r = calc_gwa(positions, actual_mil, product.gwa_bot_mm, product.gwa_top_mm, right_te, "right")
                gwa_jr = judge_gwa(gwa_r, target_wa, gwa_tol)
                row_data_r["GWA"] = f"{gwa_r:.4f}"
                row_data_r["GWA Spec"] = f"+/-{gwa_tol}"
                row_data_r["GWA Result"] = gwa_jr

                lwa_pos_r2, lwa_val_r2 = calc_lwa(positions, actual_mil,
                                                    product.hud_bot_mm, product.hud_top_mm, right_te, "right")
                if len(lwa_val_r2) > 0:
                    lwa_jr, lwa_fr = judge_lwa(lwa_val_r2, target_wa, lwa_tol)
                    row_data_r["LWA Range"] = f"{lwa_val_r2.min():.4f} ~ {lwa_val_r2.max():.4f}"
                    row_data_r["LWA Spec"] = f"+/-{lwa_tol}"
                    row_data_r["LWA Result"] = lwa_jr if lwa_jr == "PASS" else f"FAIL ({lwa_fr}pts)"

            results.append(row_data_r)

        st.dataframe(pd.DataFrame(results), use_container_width=True, hide_index=True)

# ── Auto Refresh (Live 모드) ─────────────────────────────
if is_live and auto_refresh:
    time.sleep(refresh_interval)
    st.rerun()
