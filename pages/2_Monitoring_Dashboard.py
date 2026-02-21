"""Page 2: 모니터링 대시보드 – 타겟 vs 실측 비교, UWA/GWA/LWA 판정."""
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import BIN_PITCH_MM, load_masters
from core.dummy_data import generate_dummy_actual
from core.mrad_calculator import calc_gwa, calc_lwa, calc_uwa, judge_gwa, judge_lwa
from core.profile_engine import generate_full_profile
from core.wedge_geometry import ProductMaster


# ── 페이지 설정 ──────────────────────────────────────────
st.header("Monitoring Dashboard")
masters = load_masters()

if not masters:
    st.warning("제품 마스터가 없습니다. Profile Generator에서 먼저 제품을 등록하세요.")
    st.stop()

# ── 사이드바: 제품 선택 + 더미 데이터 파라미터 ────────────
with st.sidebar:
    st.subheader("제품 선택")
    selected_name = st.selectbox("Recipe (제품명)", list(masters.keys()))

    st.divider()
    st.subheader("Dummy Data Settings")
    st.caption("실측 데이터 시뮬레이션 파라미터")
    noise_std = st.slider("Noise Std (mil)", 0.0, 1.0, 0.25, 0.05)
    offset = st.slider("Global Offset (mil)", -2.0, 2.0, 0.0, 0.1)
    bump_on = st.checkbox("Add Local Bump", value=False)
    bump_bin = st.number_input("Bump Center (bin)", 1, 449, 200, disabled=not bump_on)
    bump_amp = st.number_input("Bump Amplitude (mil)", -3.0, 3.0, 1.0, 0.1, disabled=not bump_on)
    seed = st.number_input("Random Seed", 0, 9999, 42)

    st.divider()
    st.subheader("Spec Tolerances")
    gwa_tol = st.number_input("GWA Tolerance (mrad)", value=0.03, step=0.01, format="%.3f")
    lwa_tol = st.number_input("LWA Tolerance (mrad)", value=0.15, step=0.01, format="%.3f")

# ── 제품 로드 & 프로파일 생성 ─────────────────────────────
m = masters[selected_name]
product = ProductMaster.from_dict(m)
df_target = generate_full_profile(product)

positions = df_target["Position_mm"].values
target_mil = df_target["Target_mil"].values

# ── 더미 실측 데이터 ──────────────────────────────────────
actual_mil = generate_dummy_actual(
    target_mil,
    noise_std=noise_std,
    offset=offset,
    bump_center_bin=(bump_bin - 1) if bump_on else None,
    bump_amplitude=bump_amp if bump_on else 0,
    seed=seed,
)

layout = product.layout()

# ══════════════════════════════════════════════════════════
# TAB 1: 전체 프로파일
# ══════════════════════════════════════════════════════════
tab1, tab2, tab3, tab4 = st.tabs([
    "Full Profile", "Left Product", "Right Product", "LWA Detail"
])

with tab1:
    fig = go.Figure()

    # 제품 영역 배경
    fig.add_vrect(
        x0=layout["left_start_mm"], x1=layout["left_end_mm"],
        fillcolor="rgba(0,100,255,0.05)", line_width=0,
        annotation_text="L", annotation_position="top left",
    )
    if product.dual_cut:
        fig.add_vrect(
            x0=layout["right_start_mm"], x1=layout["right_end_mm"],
            fillcolor="rgba(255,100,0,0.05)", line_width=0,
            annotation_text="R", annotation_position="top right",
        )

    fig.add_trace(go.Scatter(
        x=positions, y=target_mil,
        mode="lines", name="Target",
        line=dict(color="blue", width=2),
    ))
    fig.add_trace(go.Scatter(
        x=positions, y=actual_mil,
        mode="lines", name="Actual",
        line=dict(color="red", width=1.5, dash="dot"),
    ))

    # 차이 하이라이트
    diff = np.abs(actual_mil - target_mil)
    threshold = 1.0  # mil
    exceedance = diff > threshold
    if np.any(exceedance):
        exceed_pos = positions[exceedance]
        exceed_val = actual_mil[exceedance]
        fig.add_trace(go.Scatter(
            x=exceed_pos, y=exceed_val,
            mode="markers", name=f"|Δ| > {threshold} mil",
            marker=dict(color="orange", size=4, symbol="circle"),
        ))

    fig.update_layout(
        title=f"Full Profile: {product.name} ({'2-Cut' if product.dual_cut else 'Single'})",
        xaxis_title="Position (mm)",
        yaxis_title="Caliper (mil)",
        height=450,
        hovermode="x unified",
    )
    st.plotly_chart(fig, use_container_width=True)


# ── 헬퍼: 한 컷 제품 차트 ────────────────────────────────
def _plot_cut(
    cut_label: str,
    start_mm: float,
    end_mm: float,
    thin_edge_pos_mm: float,
    direction: str,
):
    """한 컷 제품의 프로파일 + 구간 표시."""
    mask = (positions >= start_mm) & (positions <= end_mm)
    pos_cut = positions[mask]
    tgt_cut = target_mil[mask]
    act_cut = actual_mil[mask]

    fig = go.Figure()

    # Wedge / Flat 구간
    wp = product.wedge_portion_mm
    if direction == "left":
        wedge_end = start_mm + wp
        fig.add_vrect(x0=start_mm, x1=wedge_end,
                       fillcolor="rgba(255,200,0,0.12)", line_width=0,
                       annotation_text="Wedge", annotation_position="top left")
        fig.add_vrect(x0=wedge_end, x1=end_mm,
                       fillcolor="rgba(0,200,100,0.12)", line_width=0,
                       annotation_text="Flat", annotation_position="top right")
    else:
        wedge_start = end_mm - wp
        fig.add_vrect(x0=start_mm, x1=wedge_start,
                       fillcolor="rgba(0,200,100,0.12)", line_width=0,
                       annotation_text="Flat", annotation_position="top left")
        fig.add_vrect(x0=wedge_start, x1=end_mm,
                       fillcolor="rgba(255,200,0,0.12)", line_width=0,
                       annotation_text="Wedge", annotation_position="top right")

    # HUD 영역
    if product.hud_bot_mm and product.hud_top_mm:
        if direction == "left":
            hud_abs_bot = thin_edge_pos_mm + product.hud_bot_mm
            hud_abs_top = thin_edge_pos_mm + product.hud_top_mm
        else:
            hud_abs_bot = thin_edge_pos_mm - product.hud_top_mm
            hud_abs_top = thin_edge_pos_mm - product.hud_bot_mm
        fig.add_vrect(x0=hud_abs_bot, x1=hud_abs_top,
                       fillcolor="rgba(255,0,255,0.08)",
                       line=dict(color="magenta", width=1, dash="dash"),
                       annotation_text="HUD", annotation_position="top left")

    fig.add_trace(go.Scatter(x=pos_cut, y=tgt_cut, mode="lines", name="Target",
                              line=dict(color="blue", width=2)))
    fig.add_trace(go.Scatter(x=pos_cut, y=act_cut, mode="lines", name="Actual",
                              line=dict(color="red", width=1.5, dash="dot")))

    fig.update_layout(
        title=f"{cut_label}: {product.name}",
        xaxis_title="Position (mm)", yaxis_title="Caliper (mil)",
        height=400, hovermode="x unified",
    )
    st.plotly_chart(fig, use_container_width=True)

    # ── mrad 계산 ─────────────────────────────────────
    # UWA
    if direction == "left":
        te_pos = start_mm
        flat_start = start_mm + wp
    else:
        te_pos = end_mm
        flat_start = end_mm - wp

    uwa = calc_uwa(positions, actual_mil, min(te_pos, flat_start), max(te_pos, flat_start))

    col1, col2, col3 = st.columns(3)
    col1.metric("UWA", f"{uwa:.4f} mrad", f"Target: {product.wedge_angle_mrad:.4f}")

    if product.gwa_bot_mm and product.gwa_top_mm:
        gwa = calc_gwa(positions, actual_mil,
                        product.gwa_bot_mm, product.gwa_top_mm, te_pos, direction)
        gwa_result = judge_gwa(gwa, product.wedge_angle_mrad, gwa_tol)
        col2.metric("GWA", f"{gwa:.4f} mrad",
                     f"{'PASS' if gwa_result == 'PASS' else 'FAIL'} (±{gwa_tol})")

        if product.hud_bot_mm and product.hud_top_mm:
            lwa_pos, lwa_vals = calc_lwa(positions, actual_mil,
                                          product.hud_bot_mm, product.hud_top_mm, te_pos, direction)
            if len(lwa_vals) > 0:
                lwa_result, lwa_fails = judge_lwa(lwa_vals, product.wedge_angle_mrad, lwa_tol)
                lwa_min = lwa_vals.min()
                lwa_max = lwa_vals.max()
                col3.metric("LWA Range", f"{lwa_min:.4f} ~ {lwa_max:.4f} mrad",
                             f"{'PASS' if lwa_result == 'PASS' else f'FAIL ({lwa_fails} pts)'}")

    return te_pos


# ══════════════════════════════════════════════════════════
# TAB 2: Left Product
# ══════════════════════════════════════════════════════════
with tab2:
    left_te_pos = _plot_cut(
        "Left Product",
        layout["left_start_mm"], layout["left_end_mm"],
        thin_edge_pos_mm=layout["left_start_mm"],
        direction="left",
    )

# ══════════════════════════════════════════════════════════
# TAB 3: Right Product
# ══════════════════════════════════════════════════════════
with tab3:
    if product.dual_cut:
        right_te_pos = _plot_cut(
            "Right Product",
            layout["right_start_mm"], layout["right_end_mm"],
            thin_edge_pos_mm=layout["right_end_mm"],
            direction="right",
        )
    else:
        st.info("싱글컷 제품 – Right Product 없음")

# ══════════════════════════════════════════════════════════
# TAB 4: LWA Detail
# ══════════════════════════════════════════════════════════
with tab4:
    if not (product.hud_bot_mm and product.hud_top_mm):
        st.info("HUD 영역이 정의되지 않은 제품입니다.")
    else:
        st.subheader("LWA Sliding Window Detail")
        st.caption("±40mm 윈도우로 슬라이딩하며 계산한 로컬 기울기")

        # Left
        left_te = layout["left_start_mm"]
        lwa_pos_l, lwa_val_l = calc_lwa(positions, actual_mil,
                                         product.hud_bot_mm, product.hud_top_mm, left_te, "left")

        fig_lwa = make_subplots(rows=1, cols=2 if product.dual_cut else 1,
                                 subplot_titles=["Left LWA"] + (["Right LWA"] if product.dual_cut else []),
                                 shared_yaxes=True)

        target_wa = product.wedge_angle_mrad

        if len(lwa_val_l) > 0:
            colors_l = ["green" if abs(v - target_wa) <= lwa_tol else "red" for v in lwa_val_l]
            fig_lwa.add_trace(go.Bar(
                x=lwa_pos_l, y=lwa_val_l, marker_color=colors_l,
                name="Left LWA", width=BIN_PITCH_MM * 0.8,
            ), row=1, col=1)

            fig_lwa.add_hline(y=target_wa, line_color="blue", line_dash="dash", row=1, col=1)
            fig_lwa.add_hline(y=target_wa + lwa_tol, line_color="gray", line_dash="dot", row=1, col=1)
            fig_lwa.add_hline(y=target_wa - lwa_tol, line_color="gray", line_dash="dot", row=1, col=1)

        if product.dual_cut:
            right_te = layout["right_end_mm"]
            lwa_pos_r, lwa_val_r = calc_lwa(positions, actual_mil,
                                             product.hud_bot_mm, product.hud_top_mm, right_te, "right")
            if len(lwa_val_r) > 0:
                colors_r = ["green" if abs(v - target_wa) <= lwa_tol else "red" for v in lwa_val_r]
                fig_lwa.add_trace(go.Bar(
                    x=lwa_pos_r, y=lwa_val_r, marker_color=colors_r,
                    name="Right LWA", width=BIN_PITCH_MM * 0.8,
                ), row=1, col=2)
                fig_lwa.add_hline(y=target_wa, line_color="blue", line_dash="dash", row=1, col=2)
                fig_lwa.add_hline(y=target_wa + lwa_tol, line_color="gray", line_dash="dot", row=1, col=2)
                fig_lwa.add_hline(y=target_wa - lwa_tol, line_color="gray", line_dash="dot", row=1, col=2)

        fig_lwa.update_layout(
            height=400,
            yaxis_title="LWA (mrad)",
            showlegend=False,
        )
        st.plotly_chart(fig_lwa, use_container_width=True)

        # ── 판정 요약 ─────────────────────────────────────
        st.subheader("Spec Judgment Summary")

        results = []
        # Left
        uwa_l = calc_uwa(positions, actual_mil, layout["left_start_mm"],
                           layout["left_start_mm"] + product.wedge_portion_mm)
        row_data = {"Side": "Left", "UWA (mrad)": f"{uwa_l:.4f}"}

        if product.gwa_bot_mm and product.gwa_top_mm:
            gwa_l = calc_gwa(positions, actual_mil, product.gwa_bot_mm, product.gwa_top_mm, left_te, "left")
            gwa_j = judge_gwa(gwa_l, target_wa, gwa_tol)
            row_data["GWA (mrad)"] = f"{gwa_l:.4f}"
            row_data["GWA Judge"] = gwa_j

        if len(lwa_val_l) > 0:
            lwa_j, lwa_f = judge_lwa(lwa_val_l, target_wa, lwa_tol)
            row_data["LWA Min"] = f"{lwa_val_l.min():.4f}"
            row_data["LWA Max"] = f"{lwa_val_l.max():.4f}"
            row_data["LWA Judge"] = lwa_j
            row_data["LWA Fails"] = lwa_f

        results.append(row_data)

        # Right
        if product.dual_cut:
            right_te = layout["right_end_mm"]
            uwa_r = calc_uwa(positions, actual_mil,
                              layout["right_end_mm"] - product.wedge_portion_mm, layout["right_end_mm"])
            row_data_r = {"Side": "Right", "UWA (mrad)": f"{uwa_r:.4f}"}

            if product.gwa_bot_mm and product.gwa_top_mm:
                gwa_r = calc_gwa(positions, actual_mil, product.gwa_bot_mm, product.gwa_top_mm, right_te, "right")
                gwa_jr = judge_gwa(gwa_r, target_wa, gwa_tol)
                row_data_r["GWA (mrad)"] = f"{gwa_r:.4f}"
                row_data_r["GWA Judge"] = gwa_jr

                lwa_pos_r2, lwa_val_r2 = calc_lwa(positions, actual_mil,
                                                    product.hud_bot_mm, product.hud_top_mm, right_te, "right")
                if len(lwa_val_r2) > 0:
                    lwa_jr, lwa_fr = judge_lwa(lwa_val_r2, target_wa, lwa_tol)
                    row_data_r["LWA Min"] = f"{lwa_val_r2.min():.4f}"
                    row_data_r["LWA Max"] = f"{lwa_val_r2.max():.4f}"
                    row_data_r["LWA Judge"] = lwa_jr
                    row_data_r["LWA Fails"] = lwa_fr

            results.append(row_data_r)

        df_summary = pd.DataFrame(results)
        st.dataframe(df_summary, use_container_width=True, hide_index=True)
