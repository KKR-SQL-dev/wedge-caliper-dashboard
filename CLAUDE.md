# Wedge PVB Film Caliper Monitoring Dashboard

## 프로젝트 개요
PVB 필름 생산 공장(L9 라인)의 실시간 두께(캘리퍼) 모니터링 대시보드 개발

## 장비 스펙 (L9 라인)
- 다이립 수: 99개
- 다이립 피치: 1.125인치 (28.575mm)
- 다이 풀 폭: 111.375인치 (2,828.9mm)
- 캘리퍼 측정 bin 수: 449개
- bin 피치: 0.24805인치 (6.3005mm)
- 검산: 449 × 0.24805 = 111.375인치 (정확히 일치해야 함)

## 단위 규칙 (절대 지킬 것)
- 두께: **mil** (1mil = 0.0254mm)
- 길이/폭/위치: **mm**
- 기울기: **mrad**
- 계산할 때 반올림하지 말고 정확한 값 사용할 것

## 필름 구조
- 센터트림(1인치 = 25.4mm) 기준으로 좌/우 2컷 제품 생산
- 롤 폭이 너무 넓으면 싱글컷
- 2컷 조건: (롤폭 × 2) + 25.4mm ≤ 2,828.9mm

### 프로파일 형태
```
두께(mil)
 ▲
 │         ┌──플랫──┐
 │        ╱         ╲
 │       ╱   웨지     ╲
 │      ╱    구간      ╲
ThinEdge──╱────────────────╲── 미니멈 캘리퍼 (컷 포인트)
 │      ╱                    ╲
 │     ╱                      ╲
 └────╱────────────────────────╲──► bin
    엣지 │← ── 제품(롤폭) ── →│ 엣지
    버림        이게 제품         버림
```

### 2컷 레이아웃
```
←──────────── 449 bin (111.375") ────────────→
엣지 │ 좌(웨지+플랫) │ 1"센터트림 │ 우(플랫+웨지) │ 엣지
     얇→→→두꺼운쪽      │      두꺼운쪽←←←얇
```

## Wedge Angle 구간 정의

### UWA (Universal Wedge Angle)
- 범위: 전체 웨지 구간 (thin edge ~ flat start)
- 제품 슬로프 전구간의 기울기

### GWA (Global Wedge Angle)
- 범위: HUD Projection Area (HUD Bot ~ HUD Top, thin edge 기준 거리)
- HUD 영역 전체의 기울기 (하나의 값)
- 스펙 tolerance: ±0.03 mrad

### LWA (Local Wedge Angle)
- 범위: GWA와 동일 (HUD Projection Area)
- 계산: ±40mm 윈도우로 슬라이딩하면서 로컬 기울기 계산
- 스펙 tolerance: ±0.15 mrad (NSG 기준 preferring ±0.10)

### mrad 계산 공식
```
mrad = (캘리퍼_top(mil) - 캘리퍼_bot(mil)) × 0.0254 / (위치차이_mm) × 1000
```

## L9 제품 마스터 데이터

### W2264AC
- Wedge Angle: 0.64 mrad
- Roll Width: 1,300mm
- Flat Width: 300mm
- Wedge Portion: 1,000mm
- Thin Edge Cal: 31.50 mil (0.80mm)
- Max/Flat Edge Cal: 56.69 mil (1.44mm)
- Type: Clear
- HUD/GWA: 데이터 없음 (N/A)

### W2264AD
- Wedge Angle: 0.64 mrad
- Roll Width: 960mm
- Flat Width: 300mm
- Wedge Portion: 660mm
- Thin Edge Cal: 31.50 mil (0.80mm)
- Max/Flat Edge Cal: 48.13 mil (1.222mm)
- Type: Clear
- HUD Bot: 262mm, HUD Top: 502mm (thin edge 기준)
- GWA Bot: 120mm, GWA Top: 580mm (thin edge 기준)

### W2264AE
- Wedge Angle: 0.64 mrad
- Roll Width: 1,100mm
- Flat Width: 300mm
- Wedge Portion: 800mm
- Thin Edge Cal: 31.50 mil (0.80mm)
- Max/Flat Edge Cal: 51.65 mil (1.312mm)
- Type: Clear
- HUD Bot: 200mm, HUD Top: 600mm (thin edge 기준)
- GWA Bot: 150mm, GWA Top: 600mm (thin edge 기준)

## 고객 스펙 참고 (NSG/SGS)

### NSG
- Wedge angle range: 0.2 ~ 0.7 (up to 0.8) mrad
- GWA tolerance: ±0.03 mrad
- LWA tolerance: ±0.15 (preferring ±0.10)
- Projection area: 150 ~ 550mm from motor edge
- LWA 계산: slope function ±40mm range

### SGS
- Wedge angle: 0.38, 0.41, 0.47 mrad
- GWA tolerance: ±0.03 mrad
- LWA tolerance: ±0.15
- Projection area: 220 ~ 580mm from motor edge
- Minimum film thickness: 0.73 (clear), 0.76 (acoustic)

## 시스템 아키텍처

### 데이터 흐름
```
[SQL Server: KR-KURARAYSQL]
  DB: KURARAY_PLCDATA
  테이블: RAW_BCALIPER_L9 등
  매 스캔 → 449 bin 캘리퍼 데이터 + 제품명(Recipe)
        ↓
[마스터 엑셀] 제품명으로 자동 매칭 → 타겟 프로파일 생성
        ↓
[대시보드] 타겟 vs 액츄얼 실시간 비교
        ↓
  구간별 이탈 감지 → 하이라이트 + 알림
```

### 개발 순서
1. **1단계 (현재)**: 마스터 엑셀 기반 타겟 프로파일 + 더미 데이터로 대시보드 UI
2. **2단계**: SQL Server 원격 연결 (pyodbc) → 실시간 데이터
3. **3단계**: 자동 판정 + 알림

### SQL 연결 정보 (2단계)
```python
import pyodbc
conn = pyodbc.connect(
    'DRIVER={ODBC Driver 18 for SQL Server};'
    'SERVER=서버주소;'
    'DATABASE=KURARAY_PLCDATA;'
    'UID=아이디;'
    'PWD=비밀번호;'
)
```

### SQL 테이블 컬럼 구조
- [Time]: 측정 시간
- [Recipe]: 제품명 (마스터 매칭 키)
- [Data1] ~ [Data449]: 449 bin 캘리퍼 데이터 (mil)

## 대시보드 요구사항
- 제품명(Recipe)으로 마스터 자동 매칭 (유저 조작 없음)
- 타겟 프로파일 vs 액츄얼 프로파일 겹쳐서 표시
- 좌/우 2컷 제품별 분리 표시
- UWA/GWA/LWA 구간 표시
- 구간별 mrad 실시간 계산 + 스펙 판정
- 벗어나는 구간 하이라이트

## 개발 환경
- OS: Windows (PC)
- Python: 3.14.3
- Git: 2.53.0
- Claude Code: v2.1.50 (Opus 4.6, Claude Max)
- 프로젝트 폴더: C:\Users\KR-TCN51C\projects
- 마스터 파일: Wedge_Raw_test_data.xlsx (프로젝트 폴더에 복사할 것)

## 참고 파일
- Wedge_Raw_test_data.xlsx: 제품 마스터 (헤더 row 2, 데이터 row 3~)
- L9_target_profiles.csv: 생성된 449 bin 타겟 프로파일 (3제품)
