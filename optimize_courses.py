import csv
import re
import sys
import random
import json
from collections import defaultdict
from dataclasses import dataclass, field
from typing import List, Set, Tuple, Dict, Any

# --- グローバル設定 ---

# Windows環境での文字化け対策
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')

# --- データ構造定義 ---

@dataclass
class Course:
    """授業情報を格納するデータクラス"""
    no: str
    lang: str
    title_en: str
    title_ja: str
    schedule_str: str
    classroom: str
    mode: str
    instructor: str
    credits: int
    link: str
    schedule: Set[Tuple[str, int]] = field(default_factory=set, init=False)
    subject: str = field(default="", init=False)
    level: int = field(default=0, init=False)

    def __post_init__(self):
        self.parse_schedule()
        self.parse_course_no()

    def parse_schedule(self):
        """ "3/TU,2/TH" を {('TU', 3), ('TH', 2)} に変換 """
        cleaned_str = re.sub(r'[\\*()]', '', self.schedule_str)
        if not cleaned_str:
            return
        day_map = {"M": "月", "TU": "火", "W": "水", "TH": "木", "F": "金", "SA": "土", "SU": "日"}
        try:
            for part in cleaned_str.split(','):
                if '/' in part:
                    period, day_abbr = part.strip().split('/')
                    day = day_map.get(day_abbr.upper())
                    if day and period.isdigit():
                        self.schedule.add((day, int(period)))
        except (ValueError, IndexError):
            pass

    def parse_course_no(self):
        """ 'GEC101' から 'GEC' と 100 を抽出 """
        match = re.match(r'([A-Z]+)(\d+)', self.no)
        if match:
            self.subject = match.group(1)
            self.level = (int(match.group(2)) // 100) * 100

    def conflicts_with(self, other: 'Course') -> bool:
        """ 他の授業との時間割の競合を判定 """
        return bool(self.schedule and other.schedule and not self.schedule.isdisjoint(other.schedule))

# --- アルゴリズム本体 ---

class PatternBasedOptimizer:
    """時間割パターンに基づいて履修を最適化するクラス"""
    def __init__(self, all_courses: List[Course], settings: Dict[str, Any], patterns: Dict):
        self.all_courses = all_courses
        self.settings = settings
        self.patterns = patterns
        self.course_map = {c.no: c for c in all_courses}
        self.course_scores = {}

        # 設定値を展開
        self.constraints = settings.get('constraints', {})
        self.optimizer_settings = settings.get('optimizer_settings', {})
        
        self.max_credits = self.constraints.get('max_credits')
        self.min_credits = self.constraints.get('min_credits')
        self.desired_nos = set(self.constraints.get('desired_nos'))
        
        self.temperature = self.optimizer_settings.get('temperature')
        self.max_candidates = self.optimizer_settings.get('max_candidates')
        
        # 除外設定を解析
        raw_excluded = set(self.constraints.get('excluded_nos', []))
        self.excluded_prefixes = {s for s in raw_excluded if s.isalpha() and s.isupper()}
        self.excluded_exact_nos = raw_excluded - self.excluded_prefixes
        
        # 番台制約設定を解析
        level_constraints = self.optimizer_settings.get('course_level_constraints', {})
        self.major_subjects_config = level_constraints.get('major_subjects', {})
        self.other_subjects_config = level_constraints.get('other_subjects', {})
        self.major_subject_codes = set(self.major_subjects_config.get('codes', []))
        
        self._score_courses()

        # 代替科目検索用のマップを作成
        self.schedule_to_courses: Dict[Tuple[str, int], List[Course]] = defaultdict(list)
        for course in self.all_courses:
            if self._is_course_valid(course):
                for slot in course.schedule:
                    self.schedule_to_courses[slot].append(course)

    def run(self):
        if not self.patterns:
            print("エラー: パターンが読み込めなかったため、最適化を実行できません。")
            return
        print("最適化プロセスを開始します...")
        self._score_patterns()
        pattern_keys = self._select_best_patterns()
        if not pattern_keys:
            print("適切な時間割パターンが見つかりませんでした。")
            return
        
        candidates = [self._fill_remaining_credits(self._build_initial_timetable(key)) for key in pattern_keys]
        candidates_with_keys = list(zip(pattern_keys, candidates))
        
        self._display_results(candidates_with_keys)

    def _is_course_valid(self, course: Course) -> bool:
        """授業が全ての制約（除外、番台）を満たすか判定"""
        # 従来の除外設定
        if course.no in self.excluded_exact_nos or course.subject in self.excluded_prefixes:
            return False

        # 番台制約
        is_major = course.subject in self.major_subject_codes
        if is_major:
            min_level = self.major_subjects_config.get('min_level', 0)
            max_level = self.major_subjects_config.get('max_level', 9999)
        else:
            min_level = self.other_subjects_config.get('min_level', 0)
            max_level = self.other_subjects_config.get('max_level', 9999)

        if not (min_level <= course.level <= max_level):
            return False
            
        return True

    def _score_courses(self):
        """全コースの基本スコアを計算"""
        priority_subjects = set(self.optimizer_settings.get('priority_subjects', []))
        level_priorities = self.optimizer_settings.get('level_priorities', {})
        
        for course in self.all_courses:
            score = 1
            if course.subject in priority_subjects:
                score += 10
            if course.subject in level_priorities:
                if course.level == level_priorities[course.subject]:
                    score += 5
                elif abs(course.level - level_priorities[course.subject]) <= 100:
                    score += 2
            self.course_scores[course.no] = score
        print(f"{len(self.course_scores)}件のコースのスコアリングが完了しました。")

    def _score_patterns(self):
        """各パターンのスコアを計算"""
        self.pattern_scores = {}
        for key, data in self.patterns.items():
            courses = [self.course_map[no] for no in data['courses'] if no in self.course_map and self._is_course_valid(self.course_map[no])]
            courses = self._prepare_candidates(courses)
            
            best_courses = []
            for course in courses:
                if not self._check_conflict(best_courses + [course]):
                    best_courses.append(course)
            
            self.pattern_scores[key] = {
                "score": sum(self.course_scores.get(c.no, 0) for c in best_courses),
                "courses": best_courses
            }
        print(f"{len(self.pattern_scores)}件のパターンのスコアリングが完了しました。")

    def _is_schedule_allowed(self, schedule_items: Set[Tuple[str, int]], ignore_unavailable: bool = False) -> bool:
        """スケジュールが制約（空き日、不可コマ）に違反しないかチェック"""
        off_days = set(self.constraints.get('off_days', []))
        for day, period in schedule_items:
            if day in off_days:
                return False
        
        if not ignore_unavailable:
            unavailable_slots = {tuple(s) for s in self.constraints.get('unavailable_slots', [])}
            for day, period in schedule_items:
                if (day, period) in unavailable_slots:
                    return False
        return True

    def _select_best_patterns(self) -> List[str]:
        """最適なパターンを選択"""
        mandatory_courses = self._get_courses_by_nos(self.constraints.get('mandatory_nos', []))
        if self._check_conflict(mandatory_courses):
            print("エラー: 必修科目が競合しています。")
            return None
        if sum(c.credits for c in mandatory_courses) > self.max_credits:
            print(f"エラー: 必修科目だけで上限({self.max_credits})単位を超えています。")
            return None
        
        mandatory_schedule = {slot for c in mandatory_courses for slot in c.schedule}
        valid_patterns = []
        for key, data in self.pattern_scores.items():
            pattern_schedule = {tuple(s) for s in self.patterns[key]['schedule']}
            if not self._is_schedule_allowed(pattern_schedule):
                continue
            if not pattern_schedule.isdisjoint(mandatory_schedule):
                continue
            valid_patterns.append((data['score'], key))
        
        valid_patterns.sort(key=lambda x: x[0], reverse=True)
        print(f"制約を考慮した結果、{len(valid_patterns)}件の有効なパターンが見つかりました。")
        return [key for _, key in valid_patterns[:self.max_candidates]]

    def _build_initial_timetable(self, pattern_key: str) -> List[Course]:
        """初期時間割を構築"""
        timetable = self._get_courses_by_nos(self.constraints.get('mandatory_nos', []))
        courses_from_pattern = self.pattern_scores[pattern_key]['courses']
        for course in courses_from_pattern:
            if sum(c.credits for c in timetable) + course.credits > self.max_credits:
                continue
            if not self._check_conflict(timetable + [course]):
                timetable.append(course)
        return timetable

    def _fill_remaining_credits(self, timetable: List[Course]) -> List[Course]:
        """残りの単位を埋める（必要なら制約緩和）"""
        # 1. 通常の制約で単位を埋める
        timetable = self._fill_pass(timetable, ignore_unavailable=False)

        # 2. 最低単位数に満たない場合、不可コマ制約を緩和して再度試行
        if sum(c.credits for c in timetable) < self.min_credits:
            print(f"注意: 候補の一つが最低単位数({self.min_credits})に届かなかったため、不可コマ設定を緩和して追加科目を検索します。")
            timetable = self._fill_pass(timetable, ignore_unavailable=True)
            
        return timetable

    def _fill_pass(self, timetable: List[Course], ignore_unavailable: bool) -> List[Course]:
        """指定された制約で単位を埋めるヘルパー関数"""
        current_credits = sum(c.credits for c in timetable)
        
        existing_nos = {c.no for c in timetable}
        candidates = [c for c in self.all_courses if c.no not in existing_nos and self._is_course_valid(c)]
        candidates = self._prepare_candidates(candidates)
        
        for course in candidates:
            if current_credits >= self.min_credits:
                break
            if not self._is_schedule_allowed(course.schedule, ignore_unavailable=ignore_unavailable):
                continue
            if current_credits + course.credits > self.max_credits:
                continue
            if not self._check_conflict(timetable + [course]):
                timetable.append(course)
                current_credits += course.credits
        
        return timetable

    def _display_results(self, candidates: List[Tuple[str, List[Course]]]):
        """結果を表示"""
        if not candidates:
            print("最終的な時間割候補を生成できませんでした。")
            return
        for idx, (key, timetable) in enumerate(candidates, 1):
            if not timetable: continue
            print("\n" + "="*50 + f"\n候補 #{idx} / パターン: {key}\n" + "="*50)
            print(f"合計単位数: {sum(c.credits for c in timetable)} (下限 {self.min_credits} / 上限 {self.max_credits})\n")
            
            # --- 候補科目リスト ---
            print("--- 候補科目 ---")
            sorted_timetable = sorted(timetable, key=lambda c: (c.subject, c.no))
            for c in sorted_timetable:
                print(f"  - [{c.no}] {c.title_ja.ljust(25)} ({c.credits}単位) {c.schedule_str}")

            # --- 時間割グリッド表示 ---
            grid = defaultdict(dict)
            for c in timetable:
                for day, period in c.schedule:
                    grid[day][period] = f"[{c.subject}]"
            
            days = ["月", "火", "水", "木", "金", "土"]
            print("\n" + "--- 時間割グリッド ---")
            header = " | " + " | ".join([f"{day:<6}" for day in days])
            print(header + "\n" + "-" * len(header))
            for p in range(1, 8):
                print(f"{p}限" + "".join([f"| {grid[day].get(p, '      '):<6}" for day in days]))

            # --- 代替科目の表示 ---
            alternatives_map = {}
            for c in sorted_timetable:
                other_courses_in_timetable = [other for other in timetable if other.no != c.no]
                
                potential_alternatives = []
                if not c.schedule: continue

                for slot in c.schedule:
                    for alt_course in self.schedule_to_courses.get(slot, []):
                        if alt_course.no != c.no and alt_course not in timetable and alt_course not in potential_alternatives:
                             potential_alternatives.append(alt_course)

                final_alternatives = []
                current_credits_without_c = sum(oc.credits for oc in other_courses_in_timetable)
                for alt in potential_alternatives:
                    if not self._check_conflict(other_courses_in_timetable + [alt]):
                        if current_credits_without_c + alt.credits <= self.max_credits:
                            final_alternatives.append(alt)
                
                if final_alternatives:
                    alternatives_map[c.no] = (c, final_alternatives)

            if alternatives_map:
                print("\n" + "--- 候補科目 ---")
                print("    └─他の選択肢")
                for c in sorted_timetable:
                    if c.no in alternatives_map:
                        original_course, alt_list = alternatives_map[c.no]
                        print(f"\n      ▼ [{original_course.no}] {original_course.title_ja} の代替:")
                        for alt in sorted(alt_list, key=lambda x: (x.subject, x.no)):
                            print(f"         - [{alt.no}] {alt.title_ja}")

            print("\n" + "="*50 + "\n")

    def _get_courses_by_nos(self, nos: List[str]) -> List[Course]:
        return [self.course_map[no] for no in nos if no in self.course_map]

    def _prepare_candidates(self, courses: List[Course]) -> List[Course]:
        """temperatureに応じて候補を並び替え"""
        temp_ratio = self.temperature / 100
        if self.desired_nos and temp_ratio == 0:
            courses = [c for c in courses if c.no in self.desired_nos]
        if temp_ratio == 1:
            random.shuffle(courses)
            return courses
        
        def score(c: Course):
            base = self.course_scores.get(c.no, 0)
            pref = (1 - temp_ratio) * (100 if c.no in self.desired_nos else 0)
            rand = temp_ratio * random.random() * 20
            return base + pref + rand
        
        return sorted(courses, key=score, reverse=True)

    @staticmethod
    def _check_conflict(timetable: List[Course]) -> bool:
        return any(timetable[i].conflicts_with(timetable[j]) for i in range(len(timetable)) for j in range(i + 1, len(timetable)))

# --- ファイルI/O とメインロジック ---

def load_courses_from_csv(filepath: str) -> List[Course]:
    """CSVから授業リストを読み込む"""
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            reader = csv.reader(f)
            next(reader)
            return [Course(no=r[0], lang=r[1], title_en=r[2], title_ja=r[3], schedule_str=r[4],
                           classroom=r[5], mode=r[6], instructor=r[7], credits=int(r[8]) if r[8].isdigit() else 0,
                           link=r[9] if len(r) > 9 else "") for r in reader if len(r) >= 9]
    except FileNotFoundError:
        print(f"エラー: 授業ファイルが見つかりません: {filepath}")
    except Exception as e:
        print(f"CSV読み込みエラー: {e}")
    return []

def load_json_file(filepath: str, file_description: str) -> Dict:
    """汎用JSONファイルローダー"""
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        print(f"エラー: {file_description}が見つかりません: {filepath}")
    except json.JSONDecodeError:
        print(f"エラー: {file_description}の形式が正しくありません: {filepath}")
    return {}

def get_default_settings() -> Dict:
    """全てのデフォルト設定を返す"""
    return {
        "file_paths": {
            "courses_csv": "2025W_normalized.csv",
            "patterns_json": "schedule_patterns.json"
        },
        "constraints": {
            "mandatory_nos": [], "excluded_nos": [], "desired_nos": [],
            "min_credits": 16, "max_credits": 18,
            "off_days": ["土", "日"], "unavailable_slots": []
        },
        "optimizer_settings": {
            "priority_subjects": [], "level_priorities": {},
            "temperature": 50, "max_candidates": 10,
            "course_level_constraints": {
                "major_subjects": {"codes": [], "min_level": 0, "max_level": 9999},
                "other_subjects": {"min_level": 0, "max_level": 9999}
            }
        }
    }

def merge_settings(defaults: Dict, user: Dict) -> Dict:
    """ユーザー設定をデフォルトにマージ（ネスト対応）"""
    merged = defaults.copy()
    for key, user_val in user.items():
        if key in merged and isinstance(merged[key], dict) and isinstance(user_val, dict):
            merged[key] = merge_settings(merged[key], user_val)
        else:
            merged[key] = user_val
    return merged

def validate_and_process_settings(settings: Dict) -> Dict:
    """設定値のバリデーションと型変換"""
    s = settings.copy()
    
    # constraints
    c = s['constraints']
    c['min_credits'] = int(c.get('min_credits', 16))
    c['max_credits'] = int(c.get('max_credits', 18))
    c['unavailable_slots'] = [tuple(slot.values()) for slot in c.get('unavailable_slots', [])]

    # optimizer_settings
    o = s['optimizer_settings']
    o['temperature'] = max(0, min(100, int(o.get('temperature', 50))))
    o['max_candidates'] = max(1, min(10, int(o.get('max_candidates', 10))))
    
    # course_level_constraints (nested in optimizer_settings)
    clc = o.get('course_level_constraints', {})
    if 'major_subjects' in clc:
        clc['major_subjects']['min_level'] = int(clc['major_subjects'].get('min_level', 0))
        clc['major_subjects']['max_level'] = int(clc['major_subjects'].get('max_level', 9999))
    if 'other_subjects' in clc:
        clc['other_subjects']['min_level'] = int(clc['other_subjects'].get('min_level', 0))
        clc['other_subjects']['max_level'] = int(clc['other_subjects'].get('max_level', 9999))
    
    return s

if __name__ == '__main__':
    SETTINGS_JSON_PATH = 'user_settings.json'
    
    # 設定の読み込みとマージ
    default_settings = get_default_settings()
    user_settings = load_json_file(SETTINGS_JSON_PATH, "ユーザー設定ファイル")
    
    if not user_settings:
        print(f"警告: '{SETTINGS_JSON_PATH}' が見つからないか空です。デフォルト設定を使用します。")
        final_settings = default_settings
    else:
        final_settings = merge_settings(default_settings, user_settings)
        print(f"'{SETTINGS_JSON_PATH}' からユーザー設定を読み込みました。")

    final_settings = validate_and_process_settings(final_settings)
    
    # ファイル読み込み
    paths = final_settings['file_paths']
    all_courses = load_courses_from_csv(paths['courses_csv'])
    patterns = load_json_file(paths['patterns_json'], "時間割パターンファイル")

    if all_courses and patterns:
        print(f"{len(all_courses)}件の授業データを読み込みました。")
        print(f"{len(patterns)}件のパターンを読み込みました。")
        optimizer = PatternBasedOptimizer(all_courses, final_settings, patterns)
        optimizer.run()
