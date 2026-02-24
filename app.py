"""PVB Wedge Film Caliper Monitoring Dashboard – Main Entry."""
import streamlit as st

from config import auto_refresh_masters, load_masters, get_excel_master_path

st.set_page_config(
    page_title="L9 Wedge Caliper Monitor",
    page_icon="📐",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── 앱 시작 시 엑셀 → JSON 자동 동기화 ──────────────────
auto_refresh_masters()

masters = load_masters()
excel_path = get_excel_master_path()

st.title("L9 PVB Wedge Film Caliper Monitoring")
st.markdown("""
### Welcome

**L9 라인** PVB 웨지 필름의 두께(캘리퍼) 모니터링 대시보드입니다.

왼쪽 사이드바에서 페이지를 선택하세요:

| 페이지 | 설명 |
|--------|------|
| **Profile Generator** | 제품 스펙 입력 → 449 bin 타겟 프로파일 생성 |
| **Monitoring Dashboard** | 타겟 vs 실측 비교, UWA/GWA/LWA 판정 |
| **Settings** | 마스터 엑셀 경로 설정 & 새로고침 |

---

**장비 스펙 (L9)**
- 캘리퍼 bin 수: **449**
- Bin 피치: **6.3005 mm**
- 다이 풀 폭: **2,828.9 mm**
- 센터트림: **25.4 mm** (1 inch)
""")

st.info(f"등록 제품 수: **{len(masters)}** | 마스터 경로: `{excel_path}`")
