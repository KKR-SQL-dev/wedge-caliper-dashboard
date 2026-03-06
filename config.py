"""L9 라인 상수 및 단위 변환 함수."""
import json
from pathlib import Path

# ── L9 장비 스펙 ──────────────────────────────────────────
NUM_BINS = 449
BIN_PITCH_INCH = 0.24805
BIN_PITCH_MM = BIN_PITCH_INCH * 25.4          # 6.30047 mm (정확값 6.3005)
DIE_FULL_WIDTH_INCH = 111.375
DIE_FULL_WIDTH_MM = DIE_FULL_WIDTH_INCH * 25.4  # 2,828.925 mm
NUM_DIE_LIPS = 99
DIE_LIP_PITCH_INCH = 1.125
CENTER_TRIM_MM = 25.4                           # 1 inch

# ── SQL Server 연결 설정 ──────────────────────────────────
DB_HOST = "KR-KURARAYSQL"
DB_NAME = "KURARAY_PLCDATA"
DB_TABLE = "dbo.RAW_BCALIPER_L9"
DB_USER = "sa"
DB_PWD = "Kuraray1"
DB_DRIVER = "{ODBC Driver 18 for SQL Server}"


def get_db_connection():
    """SQL Server 연결 객체 반환. 실패 시 None."""
    try:
        import pyodbc
        conn = pyodbc.connect(
            f"DRIVER={DB_DRIVER};"
            f"SERVER={DB_HOST};"
            f"DATABASE={DB_NAME};"
            f"UID={DB_USER};"
            f"PWD={DB_PWD};"
            "TrustServerCertificate=yes;",
            timeout=5,
        )
        return conn
    except Exception:
        return None


# ── 단위 변환 ─────────────────────────────────────────────
MIL_TO_MM = 0.0254        # 1 mil = 0.0254 mm
MM_TO_MIL = 1.0 / MIL_TO_MM  # ≈ 39.3701


def mil_to_mm(mil: float) -> float:
    return mil * MIL_TO_MM


def mm_to_mil(mm: float) -> float:
    return mm * MM_TO_MIL


def calc_mrad(cal_top_mil: float, cal_bot_mil: float, distance_mm: float) -> float:
    """mrad = (Δcal_mil × 0.0254) / distance_mm × 1000."""
    if distance_mm == 0:
        return 0.0
    return (cal_top_mil - cal_bot_mil) * MIL_TO_MM / distance_mm * 1000.0


def bin_positions_mm() -> list[float]:
    """449 bin의 mm 위치 리스트 (0-indexed)."""
    return [i * BIN_PITCH_MM for i in range(NUM_BINS)]


# ── Bin No 보조 x축 틱 데이터 ────────────────────────────
_BIN_TICKS = [1] + list(range(25, NUM_BINS, 25)) + [NUM_BINS]
BIN_AXIS_TICK_POSITIONS = [(b - 1) * BIN_PITCH_MM for b in _BIN_TICKS]
BIN_AXIS_TICK_LABELS = [str(b) for b in _BIN_TICKS]


def is_dual_cut(roll_width_mm: float, center_trim_mm: float = CENTER_TRIM_MM) -> bool:
    """2컷 가능 여부: (roll_width × 2) + center_trim ≤ 2828.9mm."""
    return (roll_width_mm * 2 + center_trim_mm) <= DIE_FULL_WIDTH_MM


# ── 프로젝트 경로 & 설정 ─────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parent
MASTER_PATH = PROJECT_ROOT / "data" / "product_master.json"
SETTINGS_PATH = PROJECT_ROOT / "data" / "settings.json"
DEFAULT_EXCEL_PATH = PROJECT_ROOT / "Wedge Raw test data.xlsx"


def load_settings() -> dict:
    """data/settings.json에서 설정 로드."""
    if SETTINGS_PATH.exists():
        with open(SETTINGS_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_settings(settings: dict):
    """설정을 data/settings.json에 저장."""
    SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(SETTINGS_PATH, "w", encoding="utf-8") as f:
        json.dump(settings, f, indent=2, ensure_ascii=False)


def get_excel_master_path() -> Path:
    """설정에서 엑셀 마스터 경로를 가져오거나 기본값 반환."""
    settings = load_settings()
    p = settings.get("excel_master_path")
    if p:
        return Path(p)
    return DEFAULT_EXCEL_PATH


def set_excel_master_path(path: str | Path):
    """엑셀 마스터 경로를 설정에 저장."""
    settings = load_settings()
    settings["excel_master_path"] = str(path)
    save_settings(settings)


# ── 마스터 데이터 I/O ────────────────────────────────────
def load_masters() -> dict:
    """product_master.json에서 제품 마스터 로드."""
    if MASTER_PATH.exists():
        with open(MASTER_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_masters(masters: dict):
    """제품 마스터를 product_master.json에 저장."""
    MASTER_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(MASTER_PATH, "w", encoding="utf-8") as f:
        json.dump(masters, f, indent=2, ensure_ascii=False)


def should_refresh_masters() -> bool:
    """엑셀이 JSON보다 최신이면 True."""
    excel_path = get_excel_master_path()
    if not excel_path.exists():
        return False
    if not MASTER_PATH.exists():
        return True
    return excel_path.stat().st_mtime > MASTER_PATH.stat().st_mtime


def auto_refresh_masters():
    """엑셀이 더 최신이면 자동으로 마스터를 새로고침."""
    if should_refresh_masters():
        from core.excel_importer import refresh_masters
        refresh_masters(get_excel_master_path(), MASTER_PATH)
