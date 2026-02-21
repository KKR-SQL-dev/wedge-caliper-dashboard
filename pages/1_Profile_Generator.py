"""Page 1: 프로파일 생성기 – 제품 스펙 → 449 bin 타겟 프로파일."""
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import (
    CENTER_TRIM_MM, DIE_FULL_WIDTH_MM, PROJECT_ROOT,
    load_masters, save_masters,
)
from core.profile_engine import generate_full_profile
from core.wedge_geometry import ProductMaster

GENERATED_DIR = PROJECT_ROOT / "data" / "generated_profiles"
GENERATED_DIR.mkdir(parents=True, exist_ok=True)


# ── 페이지 설정 ──────────────────────────────────────────
st.header("Profile Generator")
st.caption("제품 스펙을 입력하면 449 bin 타겟 프로파일을 자동 생성합니다.")

masters = load_masters()

# ── 사이드바: 제품 선택 / 신규 입력 ──────────────────────
with st.sidebar:
    st.subheader("제품 선택")
    product_names = ["(신규 입력)"] + list(masters.keys())
    selected = st.selectbox("기존 제품 로드", product_names)

    if selected != "(신규 입력)":
        m = masters[selected]
        default_name = m["name"]
        default_wa = m["wedge_angle_mrad"]
        default_rw = m["roll_width_mm"]
        default_fw = m["flat_width_mm"]
        default_te = m["thin_edge_cal_mil"]
        default_type = m.get("film_type", "Clear")
        default_hud_bot = m.get("hud_bot_mm") or 0.0
        default_hud_top = m.get("hud_top_mm") or 0.0
        default_gwa_bot = m.get("gwa_bot_mm") or 0.0
        default_gwa_top = m.get("gwa_top_mm") or 0.0
    else:
        default_name = "NEW_PRODUCT"
        default_wa = 0.64
        default_rw = 1100.0
        default_fw = 300.0
        default_te = 31.50
        default_type = "Clear"
        default_hud_bot = 0.0
        default_hud_top = 0.0
        default_gwa_bot = 0.0
        default_gwa_top = 0.0

    st.divider()
    st.subheader("제품 스펙 입력")
    name = st.text_input("제품명", value=default_name)
    wedge_angle = st.number_input("Wedge Angle (mrad)", value=default_wa, step=0.01, format="%.4f")
    roll_width = st.number_input("Roll Width (mm)", value=default_rw, step=10.0)
    flat_width = st.number_input("Flat Width (mm)", value=default_fw, step=10.0)
    thin_edge = st.number_input("Thin Edge Cal (mil)", value=default_te, step=0.1, format="%.2f")
    film_type = st.selectbox("Film Type", ["Clear", "Acoustic", "Tinted"], index=["Clear", "Acoustic", "Tinted"].index(default_type))

    st.divider()
    st.subheader("HUD / GWA 영역 (optional)")
    st.caption("thin edge 기준 거리 (mm). 0이면 미적용.")
    hud_bot = st.number_input("HUD Bot (mm)", value=default_hud_bot, step=10.0)
    hud_top = st.number_input("HUD Top (mm)", value=default_hud_top, step=10.0)
    gwa_bot = st.number_input("GWA Bot (mm)", value=default_gwa_bot, step=10.0)
    gwa_top = st.number_input("GWA Top (mm)", value=default_gwa_top, step=10.0)

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
)

# ── 자동 계산 표시 ────────────────────────────────────────
col1, col2, col3, col4 = st.columns(4)
col1.metric("Wedge Portion", f"{product.wedge_portion_mm:.0f} mm")
col2.metric("Max/Flat Cal", f"{product.max_cal_mil:.2f} mil")
col3.metric("Cut Type", "2-Cut" if product.dual_cut else "Single")
if product.dual_cut:
    edge_waste = DIE_FULL_WIDTH_MM - (roll_width * 2 + CENTER_TRIM_MM)
    col4.metric("Edge Waste (양쪽 합)", f"{edge_waste:.1f} mm")
else:
    edge_waste = DIE_FULL_WIDTH_MM - roll_width
    col4.metric("Edge Waste", f"{edge_waste:.1f} mm")

# ── 프로파일 생성 ─────────────────────────────────────────
df = generate_full_profile(product)
layout = product.layout()

# ── Plotly 차트 ───────────────────────────────────────────
fig = go.Figure()

# 제품 영역 배경
fig.add_vrect(
    x0=layout["left_start_mm"], x1=layout["left_end_mm"],
    fillcolor="rgba(0,100,255,0.07)", line_width=0,
    annotation_text="Left Product", annotation_position="top left",
)
if product.dual_cut:
    fig.add_vrect(
        x0=layout["right_start_mm"], x1=layout["right_end_mm"],
        fillcolor="rgba(255,100,0,0.07)", line_width=0,
        annotation_text="Right Product", annotation_position="top right",
    )

# Wedge / Flat 구간 구분 (좌측)
left_wedge_end_mm = layout["left_start_mm"] + product.wedge_portion_mm
fig.add_vrect(
    x0=layout["left_start_mm"], x1=left_wedge_end_mm,
    fillcolor="rgba(255,255,0,0.08)", line_width=0,
    annotation_text="Wedge", annotation_position="bottom left",
)
fig.add_vrect(
    x0=left_wedge_end_mm, x1=layout["left_end_mm"],
    fillcolor="rgba(0,255,0,0.08)", line_width=0,
    annotation_text="Flat", annotation_position="bottom left",
)

if product.dual_cut:
    right_wedge_start_mm = layout["right_end_mm"] - product.wedge_portion_mm
    fig.add_vrect(
        x0=layout["right_start_mm"], x1=right_wedge_start_mm,
        fillcolor="rgba(0,255,0,0.08)", line_width=0,
    )
    fig.add_vrect(
        x0=right_wedge_start_mm, x1=layout["right_end_mm"],
        fillcolor="rgba(255,255,0,0.08)", line_width=0,
    )

# 타겟 프로파일
fig.add_trace(go.Scatter(
    x=df["Position_mm"], y=df["Target_mil"],
    mode="lines", name="Target Profile",
    line=dict(color="blue", width=2),
))

# HUD 영역 표시
if product.hud_bot_mm and product.hud_top_mm:
    te_pos = layout["left_start_mm"]
    fig.add_vrect(
        x0=te_pos + product.hud_bot_mm, x1=te_pos + product.hud_top_mm,
        fillcolor="rgba(255,0,255,0.1)", line_width=1,
        line=dict(color="magenta", dash="dash"),
        annotation_text="HUD Area", annotation_position="top left",
    )

fig.update_layout(
    title=f"Target Profile: {name}",
    xaxis_title="Position (mm)",
    yaxis_title="Caliper (mil)",
    height=500,
    hovermode="x unified",
    legend=dict(yanchor="top", y=0.99, xanchor="right", x=0.99),
)

st.plotly_chart(fig, use_container_width=True)

# ── 데이터 테이블 (접기) ─────────────────────────────────
with st.expander("Profile Data Table"):
    st.dataframe(df, use_container_width=True, height=300)

# ── 저장 버튼 ─────────────────────────────────────────────
col_a, col_b, col_c = st.columns(3)

with col_a:
    if st.button("Save to Master JSON", type="primary"):
        masters[name] = product.to_dict()
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
