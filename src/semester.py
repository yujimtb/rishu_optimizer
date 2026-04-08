"""
学期コンテキストモジュール

学期ID (例: 2026S, 2026A, 2025W) からファイルパスを自動解決し、
デフォルトの学期日程を提供する。

学期ID形式: YYYY[S|A|W]
  S = 春学期 (Spring)
  A = 秋学期 (Autumn)
  W = 冬学期 (Winter)
"""

import datetime
import json
import re
from pathlib import Path

# プロジェクトルート (src/ の親ディレクトリ)
PROJECT_ROOT = Path(__file__).resolve().parent.parent

# 学期種別コード
VALID_TERM_CODES = {"S", "A", "W"}

# 学期種別→日本語名
TERM_NAMES = {
    "S": "春学期 (Spring)",
    "A": "秋学期 (Autumn)",
    "W": "冬学期 (Winter)",
}

# 学期種別ごとのデフォルト日程
DEFAULT_TERM_DATES = {
    "S": {"start_month": 4, "start_day": 7, "weeks": 10},
    "A": {"start_month": 9, "start_day": 1, "weeks": 10},
    "W": {"start_month": 12, "start_day": 1, "weeks": 10},
}

_SEMESTER_ID_RE = re.compile(r"^(\d{4})([SAW])$")


def parse_semester_id(semester_id: str) -> tuple[int, str]:
    """学期IDを (年, 種別コード) に分解する。無効な形式なら ValueError。"""
    m = _SEMESTER_ID_RE.match(semester_id.upper())
    if not m:
        raise ValueError(
            f"無効な学期ID: '{semester_id}' — 形式は YYYY[S|A|W] (例: 2026S)"
        )
    return int(m.group(1)), m.group(2)


class SemesterContext:
    """学期コンテキスト — ファイルパス解決とデフォルト日程を提供"""

    def __init__(self, semester_id: str):
        self.year, self.term_code = parse_semester_id(semester_id)
        self.semester_id = f"{self.year}{self.term_code}"

    # ── ファイルパス解決 ──

    @property
    def semester_dir(self) -> Path:
        return PROJECT_ROOT / "data" / "semesters" / self.semester_id

    @property
    def raw_csv_path(self) -> Path:
        return self.semester_dir / "raw.csv"

    @property
    def normalized_csv_path(self) -> Path:
        return self.semester_dir / "normalized.csv"

    @property
    def patterns_json_path(self) -> Path:
        return self.semester_dir / "patterns.json"

    @property
    def settings_path(self) -> Path:
        return PROJECT_ROOT / "settings" / f"{self.semester_id}.json"

    @staticmethod
    def period_csv_path() -> Path:
        return PROJECT_ROOT / "data" / "period.csv"

    @staticmethod
    def period_times_json_path() -> Path:
        return PROJECT_ROOT / "data" / "period_times.json"

    @staticmethod
    def global_settings_path() -> Path:
        return PROJECT_ROOT / "settings" / "global.json"

    # ── デフォルト日程 ──

    def default_term_dates(self) -> tuple[datetime.date, datetime.date]:
        """学期種別からデフォルトの開始日・終了日を返す。"""
        # グローバル設定にカスタム日程があればそちらを優先
        overrides = self._load_date_overrides()
        if overrides:
            return overrides

        defaults = DEFAULT_TERM_DATES[self.term_code]
        start = datetime.date(self.year, defaults["start_month"], defaults["start_day"])
        end = start + datetime.timedelta(weeks=defaults["weeks"])
        return start, end

    def _load_date_overrides(self) -> tuple[datetime.date, datetime.date] | None:
        """学期設定ファイルに start_date/end_date があればそれを読む。"""
        if not self.settings_path.exists():
            return None
        try:
            data = json.loads(self.settings_path.read_text(encoding="utf-8"))
            start_str = data.get("start_date")
            end_str = data.get("end_date")
            if start_str and end_str:
                start = datetime.date.fromisoformat(start_str)
                end = datetime.date.fromisoformat(end_str)
                return start, end
        except (json.JSONDecodeError, ValueError):
            pass
        return None

    # ── 表示 ──

    @property
    def term_name(self) -> str:
        return TERM_NAMES[self.term_code]

    def __repr__(self) -> str:
        return f"SemesterContext({self.semester_id!r})"


# ── ユーティリティ関数 ──


def list_semesters() -> list[str]:
    """data/semesters/ にある学期ディレクトリの一覧を返す (ID順ソート)。"""
    semesters_dir = PROJECT_ROOT / "data" / "semesters"
    if not semesters_dir.exists():
        return []
    ids = []
    for p in sorted(semesters_dir.iterdir()):
        if p.is_dir() and _SEMESTER_ID_RE.match(p.name):
            ids.append(p.name)
    return ids


def detect_latest_semester() -> str | None:
    """最新の学期IDを自動検出する。"""
    semesters = list_semesters()
    if not semesters:
        return None
    # ソートキー: 年 → 学期順 (S=0, A=1, W=2)
    order = {"S": 0, "A": 1, "W": 2}
    return max(semesters, key=lambda s: (int(s[:-1]), order.get(s[-1], 9)))


def load_merged_settings(ctx: SemesterContext) -> dict:
    """global.json をベースに、学期設定でオーバーライド（マージ）して返す。"""
    global_path = ctx.global_settings_path()
    semester_path = ctx.settings_path

    settings: dict = {}
    if global_path.exists():
        try:
            settings = json.loads(global_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, ValueError):
            pass

    if semester_path.exists():
        try:
            semester_settings = json.loads(semester_path.read_text(encoding="utf-8"))
            _deep_merge(settings, semester_settings)
        except (json.JSONDecodeError, ValueError):
            pass

    return settings


def _deep_merge(base: dict, override: dict) -> None:
    """override の値で base を再帰的に上書きする (in-place)。"""
    for key, value in override.items():
        if key in base and isinstance(base[key], dict) and isinstance(value, dict):
            _deep_merge(base[key], value)
        else:
            base[key] = value
