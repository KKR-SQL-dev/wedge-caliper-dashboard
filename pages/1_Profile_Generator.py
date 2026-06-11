"""Page 1: 프로파일 생성기 – 제품 스펙 → 449 bin 타겟 프로파일."""
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import (
    BIN_AXIS_TICK_LABELS, BIN_AXIS_TICK_POSITIONS, BIN_PITCH_MM,
    CENTER_TRIM_MM, DIE_FULL_WIDTH_MM, MASTER_PATH, PROJECT_ROOT,
    auto_refresh_masters, get_excel_master_path, is_dual_cut, load_masters,
    render_sidebar_portal, save_masters,
)
from core.excel_importer import refresh_masters
from core.profile_engine import generate_full_profile
from core.wedge_geometry import ProductMaster, VALID_CUT_TYPES

GENERATED_DIR = PROJECT_ROOT / "data" / "generated_profiles"
GENERATED_DIR.mkdir(parents=True, exist_ok=True)

# ── 자동 동기화 ──────────────────────────────────────────
auto_refresh_masters()

# ── 페이지 설정 ──────────────────────────────────────────
render_sidebar_portal()
st.header("Profile Generator")
st.caption("제품 스펙을 입력하면 449 bin 타겟 프로파일을 자동 생성합니다.")

# ── 선택된 제품명 상단 표시 ───────────────────────────────
_sel = st.session_state.get("product_select")
if _sel and _sel != "(신규 입력)":
    st.subheader(f"Selected: {_sel}")
else:
    st.subheader("Selected: (신규 입력)")

masters = load_masters()

# ── 사이드바: 필터 + 제품 선택 / 신규 입력 ────────────────
with st.sidebar:
    # 엑셀 새로고침 버튼
    if st.button("Refresh from Excel", type="secondary"):
        excel_path = get_excel_master_path()
        if excel_path.exists():
            masters = refresh_masters(excel_path, MASTER_PATH)
            st.success(f"엑셀에서 {len(masters)}개 제품 로드 완료!")
            st.rerun()
        else:
            st.error(f"엑셀 파일 없음: {excel_path}")

    st.divider()
    st.subheader("Filter")

    # 라인 필터
    all_lines = sorted(set(m.get("extr_line", "L9") for m in masters.values()))
    if len(all_lines) > 1:
        selected_lines = st.multiselect("Extr. Line", all_lines, default=all_lines)
    else:
        selected_lines = all_lines

    # 상태 필터
    all_statuses = sorted(set(m.get("status", "Unknown") for m in masters.values()))
    if len(all_statuses) > 1:
        selected_statuses = st.multiselect("Status", all_statuses, default=all_statuses)
    else:
        selected_statuses = all_statuses

    # Cut Type 필터
    def _resolve_cut_tag(m: dict) -> str:
        """마스터 dict에서 cut type 태그를 결정."""
        ct = m.get("cut_type", "auto")
        if ct in ("single_left_dual", "single_right_dual"):
            return "Dual Shape"
        if ct in ("single_left", "single_right", "single_center"):
            return "Single"
        if ct == "dual":
            return "2-Cut"
        # auto → 폭 기준 판별
        rw = float(m.get("roll_width_mm", 0))
        ct_mm = float(m.get("center_trim_mm", CENTER_TRIM_MM))
        return "2-Cut" if is_dual_cut(rw, ct_mm) else "Single"

    all_cut_tags = sorted(set(_resolve_cut_tag(m) for m in masters.values()))
    if len(all_cut_tags) > 1:
        selected_cut_tags = st.multiselect("Cut Type", all_cut_tags, default=all_cut_tags)
    else:
        selected_cut_tags = all_cut_tags

    # 필터 적용
    filtered_names = [
        name for name, m in masters.items()
        if m.get("extr_line", "L9") in selected_lines
        and m.get("status", "Unknown") in selected_statuses
        and _resolve_cut_tag(m) in selected_cut_tags
    ]

    st.caption(f"필터 결과: {len(filtered_names)} / {len(masters)} 제품")

    st.divider()
    st.subheader("제품 선택")
    search_query = st.text_input("제품명 검색", "", placeholder="W2264 입력하면 필터...")

    def _cut_label(name: str) -> str:
        """제품명 옆에 (2-Cut) / (Single) 자동 표시."""
        m = masters.get(name)
        if not m:
            return name
        rw = float(m.get("roll_width_mm", 0))
        ct_mm = float(m.get("center_trim_mm", CENTER_TRIM_MM))
        tag = "2-Cut" if is_dual_cut(rw, ct_mm) else "Single"
        return f"{name} ({tag})"

    if search_query:
        matched = [n for n in sorted(filtered_names) if search_query.upper() in n.upper()]
        st.caption(f"검색 결과: **{len(matched)}**개 매칭")
        if len(matched) == 0:
            st.warning("검색 결과가 없습니다.")
            product_names = ["(신규 입력)"]
        else:
            product_names = matched
    else:
        matched = sorted(filtered_names)
        product_names = ["(신규 입력)"] + matched

    selected = st.selectbox(
        "제품 선택" if search_query else "기존 제품 로드",
        product_names,
        format_func=lambda x: x if x == "(신규 입력)" else _cut_label(x),
        key="product_select",
    )

    if selected != "(신규 입력)":
        m = masters[selected]
        default_name = m["name"]
        default_wa = float(m["wedge_angle_mrad"])
        default_rw = float(m["roll_width_mm"])
        default_fw = float(m["flat_width_mm"])
        default_te = float(m["thin_edge_cal_mil"])
        default_type = m.get("film_type", "Clear")
        default_cut_type = m.get("cut_type", "auto")
        default_center_trim = float(m.get("center_trim_mm", CENTER_TRIM_MM))
        default_hud_bot = float(m.get("hud_bot_mm") or 0)
        default_hud_top = float(m.get("hud_top_mm") or 0)
        default_gwa_bot = float(m.get("gwa_bot_mm") or 0)
        default_gwa_top = float(m.get("gwa_top_mm") or 0)
        default_band_width = float(m.get("band_width_mm") or 0)
        default_clear_width = float(m.get("clear_width_mm") or 0)
    else:
        default_name = "NEW_PRODUCT"
        default_wa = 0.64
        default_rw = 1100.0
        default_fw = 300.0
        default_te = 31.50
        default_type = "Clear"
        default_cut_type = "auto"
        default_center_trim = CENTER_TRIM_MM
        default_hud_bot = 0.0
        default_hud_top = 0.0
        default_gwa_bot = 0.0
        default_gwa_top = 0.0
        default_band_width = 0.0
        default_clear_width = 0.0

    st.divider()
    st.subheader("제품 스펙 입력")
    name = st.text_input("제품명", value=default_name)
    wedge_angle = st.number_input("Wedge Angle (mrad)", value=default_wa, step=0.01, format="%.4f")
    roll_width = st.number_input("Roll Width (mm)", value=default_rw, step=10.0)
    flat_width = st.number_input("Flat Width (mm)", value=default_fw, step=10.0)
    band_width = st.number_input("Band Width (mm)", value=default_band_width, step=10.0, help="밴드 폭. 0이면 미적용.")
    clear_width = st.number_input("Clear Width (mm)", value=default_clear_width, step=10.0, help="클리어 폭. 0이면 미적용.")
    thin_edge = st.number_input("Thin Edge Cal (mil)", value=default_te, step=0.1, format="%.2f")
    film_type = st.selectbox("Film Type", ["Clear", "Acoustic", "Tinted"], index=["Clear", "Acoustic", "Tinted"].index(default_type) if default_type in ["Clear", "Acoustic", "Tinted"] else 0)

    st.divider()
    st.subheader("Cut Type & Center Trim")
    cut_type_options = list(VALID_CUT_TYPES)
    cut_type_labels = {
        "auto": "Auto (폭 기준 자동)",
        "dual": "2-Cut (좌+우)",
        "single_left": "Single Left (우측 flat)",
        "single_right": "Single Right (좌측 flat)",
        "single_center": "Single Center",
        "single_left_dual": "Single Left - Dual Shape (짝짝이)",
        "single_right_dual": "Single Right - Dual Shape (짝짝이)",
    }
    cut_type_idx = cut_type_options.index(default_cut_type) if default_cut_type in cut_type_options else 0
    cut_type = st.selectbox(
        "Cut Type",
        cut_type_options,
        index=cut_type_idx,
        format_func=lambda x: cut_type_labels.get(x, x),
    )

    center_trim = st.number_input(
        "Center Trim (mm)", value=default_center_trim, step=1.0, format="%.1f",
        help="센터트림 폭 (기본 25.4mm = 1 inch)",
    )

    st.divider()
    st.subheader("HUD / GWA 영역 (optional)")
    st.caption("thin edge 기준 거리 (mm). 0이면 미적용.")
    hud_bot = st.number_input("HUD Bot (mm)", value=default_hud_bot, step=10.0)
    hud_top = st.number_input("HUD Top (mm)", value=default_hud_top, step=10.0)
    gwa_bot = st.number_input("GWA Bot (mm)", value=default_gwa_bot, step=10.0)
    gwa_top = st.number_input("GWA Top (mm)", value=default_gwa_top, step=10.0)

# ── 선택된 제품 메타데이터 표시 ─────────────────────────────
if selected != "(신규 입력)" and selected in masters:
    meta = masters[selected]
    meta_cols = st.columns(5)
    meta_cols[0].caption(f"Line: **{meta.get('extr_line', '-')}**")
    meta_cols[1].caption(f"Status: **{meta.get('status', '-')}**")
    meta_cols[2].caption(f"PVB: **{meta.get('pvb_type', '-')}**")
    meta_cols[3].caption(f"Pattern: **{meta.get('pattern', '-')}**")
    meta_cols[4].caption(f"Band: **{meta.get('band_color', '-')}**")

# ── 제품 객체 생성 ────────────────────────────────────────
product = ProductMaster(
    name=name,
    wedge_angle_mrad=wedge_angle,
    roll_width_mm=roll_width,
    flat_width_mm=flat_width,
    thin_edge_cal_mil=thin_edge,
    film_type=film_type,
    hud_bot_mm=hud_bot if hud_bot > 0 else None,
    hud_top_mm=hud_top if hud_top > 0 else None,
    gwa_bot_mm=gwa_bot if gwa_bot > 0 else None,
    gwa_top_mm=gwa_top if gwa_top > 0 else None,
    cut_type=cut_type,
    center_trim_mm=center_trim,
)

# ── 자동 계산 표시 ────────────────────────────────────────
ct = product.resolved_cut_type
if ct in ("single_left_dual", "single_right_dual"):
    col1, col2, col3, col4, col5 = st.columns(5)
    col1.metric("Wedge Portion", f"{product.wedge_portion_mm:.0f} mm")
    col2.metric("Max/Flat Cal", f"{product.max_cal_mil:.2f} mil")
    col3.metric("Cut Type", product.cut_label)
    col4.metric("Opposite Roll W", f"{product.opposite_roll_width_mm:.0f} mm")
    col5.metric("Opposite Flat W", f"{product.opposite_flat_width_mm:.0f} mm")
elif ct == "dual":
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Wedge Portion", f"{product.wedge_portion_mm:.0f} mm")
    col2.metric("Max/Flat Cal", f"{product.max_cal_mil:.2f} mil")
    col3.metric("Cut Type", product.cut_label)
    edge_waste = DIE_FULL_WIDTH_MM - (roll_width * 2 + center_trim)
    col4.metric("Edge Waste (양쪽 합)", f"{edge_waste:.1f} mm")
else:
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Wedge Portion", f"{product.wedge_portion_mm:.0f} mm")
    col2.metric("Max/Flat Cal", f"{product.max_cal_mil:.2f} mil")
    col3.metric("Cut Type", product.cut_label)
    edge_waste = DIE_FULL_WIDTH_MM - roll_width
    col4.metric("Edge Waste", f"{edge_waste:.1f} mm")

# ── 프로파일 생성 ─────────────────────────────────────────
df = generate_full_profile(product)
layout = product.layout()

# ── Plotly 차트 ───────────────────────────────────────────
fig = go.Figure()

# 제품 영역 배경 (좌측)
fig.add_vrect(x0=layout["left_start_mm"], x1=layout["left_end_mm"],
              fillcolor="rgba(0,100,255,0.07)", line_width=0)
# 제품 영역 배경 (우측)
if layout.get("right_start_mm") is not None:
    fig.add_vrect(x0=layout["right_start_mm"], x1=layout["right_end_mm"],
                  fillcolor="rgba(255,100,0,0.07)", line_width=0)

# Wedge / Flat 구간 구분 (좌측)
if ct not in ("single_right",):
    left_wp = product.wedge_portion_mm
    left_wedge_end_mm = layout["left_start_mm"] + left_wp
    fig.add_vrect(x0=layout["left_start_mm"], x1=left_wedge_end_mm,
                  fillcolor="rgba(255,255,0,0.08)", line_width=0)
    fig.add_vrect(x0=left_wedge_end_mm, x1=layout["left_end_mm"],
                  fillcolor="rgba(0,255,0,0.08)", line_width=0)
else:
    fig.add_vrect(x0=layout["left_start_mm"], x1=layout["left_end_mm"],
                  fillcolor="rgba(0,255,0,0.08)", line_width=0)

# Wedge / Flat 구간 구분 (우측)
if layout.get("right_start_mm") is not None:
    if ct == "single_left":
        fig.add_vrect(x0=layout["right_start_mm"], x1=layout["right_end_mm"],
                      fillcolor="rgba(0,255,0,0.08)", line_width=0)
    else:
        right_wp = product.wedge_portion_mm
        right_wedge_start_mm = layout["right_end_mm"] - right_wp
        fig.add_vrect(x0=layout["right_start_mm"], x1=right_wedge_start_mm,
                      fillcolor="rgba(0,255,0,0.08)", line_width=0)
        fig.add_vrect(x0=right_wedge_start_mm, x1=layout["right_end_mm"],
                      fillcolor="rgba(255,255,0,0.08)", line_width=0)

# HUD 영역 표시
if product.hud_bot_mm and product.hud_top_mm:
    if ct not in ("single_right",):
        left_te = layout["left_start_mm"]
        fig.add_vrect(x0=left_te + product.hud_bot_mm, x1=left_te + product.hud_top_mm,
                      fillcolor="rgba(255,0,255,0.1)", line_width=1,
                      line=dict(color="magenta", dash="dash"))
    if layout.get("right_start_mm") is not None and ct not in ("single_left",):
        right_te = layout["right_end_mm"]
        fig.add_vrect(x0=right_te - product.hud_top_mm, x1=right_te - product.hud_bot_mm,
                      fillcolor="rgba(255,0,255,0.1)", line_width=1,
                      line=dict(color="magenta", dash="dash"))

# Dual Shape: 메인쪽 강조
if ct in ("single_left_dual", "single_right_dual"):
    main_side = layout.get("main_side", "left")
    _ms = layout["left_start_mm"] if main_side == "left" else layout["right_start_mm"]
    _me = layout["left_end_mm"] if main_side == "left" else layout["right_end_mm"]
    fig.add_vrect(x0=_ms, x1=_me, fillcolor="rgba(0,0,0,0)", line_width=2,
                  line=dict(color="green", dash="solid"))

# 타겟 프로파일
fig.add_trace(go.Scatter(
    x=df["Position_mm"], y=df["Target_mil"],
    customdata=df["Bin"],
    mode="lines", name="Target Profile",
    line=dict(color="blue", width=2),
    hovertemplate="Bin %{customdata} | %{x:.1f}mm<br>%{y:.2f} mil<extra>Target</extra>",
))

# ── 구간 라벨 (fig.add_annotation) — 각 구간 중앙에 겹치지 않게 배치 ──
# yref="paper" → 0=차트 하단, 1=차트 상단
# 상단 레이어 (y=1.02): Left/Right Product
# 하단 레이어 (y=-0.06): Wedge/Flat
# 중간 레이어 (y=0.5):  HUD

def _add_label(x_center, text, y_paper, color="white", size=11):
    fig.add_annotation(
        x=x_center, y=y_paper, text=f"<b>{text}</b>",
        xref="x", yref="paper",
        showarrow=False, font=dict(color=color, size=size),
        bgcolor="rgba(0,0,0,0.6)", borderpad=3,
    )

# Left Product
_add_label((layout["left_start_mm"] + layout["left_end_mm"]) / 2,
           "Left Product", 1.02, color="dodgerblue")

# Right Product
if layout.get("right_start_mm") is not None:
    _add_label((layout["right_start_mm"] + layout["right_end_mm"]) / 2,
               "Right Product", 1.02, color="orange")

# Wedge / Flat (좌측)
if ct not in ("single_right",):
    _add_label((layout["left_start_mm"] + left_wedge_end_mm) / 2,
               "Wedge", 0.05, color="yellow", size=10)
    _add_label((left_wedge_end_mm + layout["left_end_mm"]) / 2,
               "Flat", 0.05, color="lime", size=10)
else:
    _add_label((layout["left_start_mm"] + layout["left_end_mm"]) / 2,
               "Flat", 0.05, color="lime", size=10)

# Wedge / Flat (우측)
if layout.get("right_start_mm") is not None and ct not in ("single_left",):
    _add_label((layout["right_start_mm"] + right_wedge_start_mm) / 2,
               "Flat", 0.05, color="lime", size=10)
    _add_label((right_wedge_start_mm + layout["right_end_mm"]) / 2,
               "Wedge", 0.05, color="yellow", size=10)

# HUD (좌측)
if product.hud_bot_mm and product.hud_top_mm and ct not in ("single_right",):
    _hud_l_center = layout["left_start_mm"] + (product.hud_bot_mm + product.hud_top_mm) / 2
    _add_label(_hud_l_center, "HUD (L)", 0.5, color="magenta", size=10)

# HUD (우측)
if product.hud_bot_mm and product.hud_top_mm and layout.get("right_start_mm") is not None and ct not in ("single_left",):
    _hud_r_center = layout["right_end_mm"] - (product.hud_bot_mm + product.hud_top_mm) / 2
    _add_label(_hud_r_center, "HUD (R)", 0.5, color="magenta", size=10)

# Dual Shape: MAIN 라벨
if ct in ("single_left_dual", "single_right_dual"):
    _add_label((_ms + _me) / 2, "MAIN", 0.92, color="lime", size=10)

# ── 레이아웃 ─────────────────────────────────────────────
# Bin No 상단 축: 50 간격, 깔끔하게
_bin_ticks_50 = [1] + list(range(50, 449, 50)) + [449]
_bin_tick_pos_50 = [(b - 1) * BIN_PITCH_MM for b in _bin_ticks_50]
_bin_tick_lbl_50 = [str(b) for b in _bin_ticks_50]

fig.update_layout(
    title=f"Target Profile: {name}",
    xaxis_title="Position (mm)",
    yaxis_title="Caliper (mil)",
    height=550,
    hovermode="closest",
    legend=dict(yanchor="top", y=0.99, xanchor="right", x=0.99),
    margin=dict(t=80, b=60),
    xaxis2=dict(
        title="Bin No",
        overlaying="x",
        side="top",
        matches="x",
        tickmode="array",
        tickvals=_bin_tick_pos_50,
        ticktext=_bin_tick_lbl_50,
        showgrid=False,
        tickangle=0,
        tickfont=dict(size=11),
    ),
)
fig.add_trace(go.Scatter(x=[None], y=[None], xaxis="x2", showlegend=False, hoverinfo="skip"))

st.plotly_chart(fig, use_container_width=True, config={"edits": {"legendPosition": True}})

# ── 데이터 테이블 (접기) ─────────────────────────────────
with st.expander("Profile Data Table"):
    st.dataframe(df, use_container_width=True, height=300)

# ── 저장 버튼 ─────────────────────────────────────────────
col_a, col_b, col_c = st.columns(3)

with col_a:
    if st.button("Save to Master JSON", type="primary"):
        d = product.to_dict()
        d["band_width_mm"] = band_width
        d["clear_width_mm"] = clear_width
        # 기존 메타데이터 보존 (line, status, pvb_type 등)
        if name in masters:
            for k in ("extr_line", "status", "pvb_type", "pattern", "band_color"):
                if k in masters[name] and k not in d:
                    d[k] = masters[name][k]
        masters[name] = d
        save_masters(masters)
        st.success(f"'{name}' saved to product_master.json")

with col_b:
    csv_data = df.to_csv(index=False)
    st.download_button(
        "Download CSV",
        data=csv_data,
        file_name=f"{name}_target_profile.csv",
        mime="text/csv",
    )

with col_c:
    if st.button("Save CSV to Server"):
        out_path = GENERATED_DIR / f"{name}_target_profile.csv"
        df.to_csv(out_path, index=False)
        st.success(f"Saved: {out_path}")
