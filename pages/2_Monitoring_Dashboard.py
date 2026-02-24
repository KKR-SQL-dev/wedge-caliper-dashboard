"""Page 2: 모니터링 대시보드 – 타겟 vs 실측 비교, UWA/GWA/LWA 판정."""
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import BIN_PITCH_MM, CENTER_TRIM_MM, auto_refresh_masters, is_dual_cut, load_masters
from core.dummy_data import generate_dummy_actual
from core.mrad_calculator import calc_gwa, calc_lwa, calc_uwa, judge_gwa, judge_lwa
from core.profile_engine import generate_full_profile
from core.wedge_geometry import ProductMaster

# ── 자동 동기화 ──────────────────────────────────────────
auto_refresh_masters()

# ── 페이지 설정 ──────────────────────────────────────────
st.header("Monitoring Dashboard")
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

    # 필터 적용
    filtered_names = sorted([
        name for name, m in masters.items()
        if m.get("extr_line", "L9") in selected_lines
        and m.get("status", "Unknown") in selected_statuses
    ])

    st.caption(f"필터 결과: {len(filtered_names)} / {len(masters)} 제품")

    st.divider()
    st.subheader("제품 선택")
    if not filtered_names:
        st.warning("필터 조건에 맞는 제품이 없습니다.")
        st.stop()
    search_query = st.text_input("제품명 검색", "", placeholder="W2264 입력하면 필터...", key="mon_search")
    if search_query:
        matched = [n for n in filtered_names if search_query.upper() in n.upper()]
    else:
        matched = filtered_names
    if not matched:
        st.warning("검색 결과 없음")
        st.stop()

    def _cut_label(name: str) -> str:
        m = masters.get(name)
        if not m:
            return name
        rw = float(m.get("roll_width_mm", 0))
        ct_mm = float(m.get("center_trim_mm", CENTER_TRIM_MM))
        tag = "2-Cut" if is_dual_cut(rw, ct_mm) else "Single"
        return f"{name} ({tag})"

    selected_name = st.selectbox(
        "Recipe (제품명)", matched,
        format_func=_cut_label,
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

# ── 선택된 제품 메타데이터 표시 ─────────────────────────────
meta = masters[selected_name]
meta_cols = st.columns(5)
meta_cols[0].caption(f"Line: **{meta.get('extr_line', '-')}**")
meta_cols[1].caption(f"Status: **{meta.get('status', '-')}**")
meta_cols[2].caption(f"PVB: **{meta.get('pvb_type', '-')}**")
meta_cols[3].caption(f"Pattern: **{meta.get('pattern', '-')}**")
meta_cols[4].caption(f"Band: **{meta.get('band_color', '-')}**")

# ── 제품 로드 & 프로파일 생성 ─────────────────────────────
m = dict(masters[selected_name])
m["cut_type"] = mon_cut_type  # 사이드바에서 선택한 cut type 적용
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
    if layout.get("right_start_mm") is not None:
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
        title=f"Full Profile: {product.name} ({product.cut_label})",
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
    wedge_portion_override: float = None,
    is_flat_only: bool = False,
):
    """한 컷 제품의 프로파일 + 구간 표시."""
    mask = (positions >= start_mm) & (positions <= end_mm)
    pos_cut = positions[mask]
    tgt_cut = target_mil[mask]
    act_cut = actual_mil[mask]

    fig = go.Figure()

    # Wedge / Flat 구간
    wp = wedge_portion_override if wedge_portion_override is not None else product.wedge_portion_mm
    if is_flat_only:
        fig.add_vrect(x0=start_mm, x1=end_mm,
                       fillcolor="rgba(0,200,100,0.12)", line_width=0,
                       annotation_text="Flat", annotation_position="top left")
    elif direction == "left":
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
ct = product.resolved_cut_type
with tab2:
    if ct == "single_right":
        # 좌측은 flat only
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
        # 좌측은 남는 폭 웨지 (같은 wedge_portion, flat만 더 넓음)
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
    if ct == "single_left":
        # 우측은 flat only
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
        # 우측은 남는 폭 웨지 (같은 wedge_portion, flat만 더 넓음)
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
    if not (product.hud_bot_mm and product.hud_top_mm):
        st.info("HUD 영역이 정의되지 않은 제품입니다.")
    else:
        st.subheader("LWA Sliding Window Detail")
        st.caption("±40mm 윈도우로 슬라이딩하며 계산한 로컬 기울기")

        # Left
        left_te = layout["left_start_mm"]
        lwa_pos_l, lwa_val_l = calc_lwa(positions, actual_mil,
                                         product.hud_bot_mm, product.hud_top_mm, left_te, "left")

        has_right = layout.get("right_start_mm") is not None
        fig_lwa = make_subplots(rows=1, cols=2 if has_right else 1,
                                 subplot_titles=["Left LWA"] + (["Right LWA"] if has_right else []),
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

        if has_right:
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
        if has_right:
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
