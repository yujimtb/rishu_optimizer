import csv
import re
import sys
import random
import json
import datetime
from collections import defaultdict
from dataclasses import dataclass, field
from typing import List, Set, Tuple, Dict, Any, Optional

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
    # schedule: Set of (Day, Period, IsException)
    schedule: Set[Tuple[str, int, bool]] = field(default_factory=set, init=False)
    subject: str = field(default="", init=False)
    level: int = field(default=0, init=False)

    def __post_init__(self):
        self.parse_schedule()
        # ICS検索用にフラグは保持しつつ、表示用文字列からは*と()を削除
        self.schedule_str = self.schedule_str.replace('*', '').replace('(', '').replace(')', '')
        self.parse_course_no()

    def parse_schedule(self):
        """ 
        "*4/M, 2/TH" -> {('月', 4, True), ('木', 2, False)} 
        *がついている場合は変則時間(Exception)フラグをTrueにする
        """
        # カッコなどは除去するが、*は判定のために一時的に残す
        cleaned_str = re.sub(r'[()]', '', self.schedule_str)
        if not cleaned_str:
            return
        
        day_map = {"M": "月", "TU": "火", "W": "水", "TH": "木", "F": "金", "SA": "土", "SU": "日"}
        
        try:
            for part in cleaned_str.split(','):
                part = part.strip()
                if '/' in part:
                    # 変則フラグチェック
                    is_exception = '*' in part
                    
                    # *を除去してパース
                    clean_part = part.replace('*', '')
                    period_str, day_abbr = clean_part.split('/')
                    
                    day = day_map.get(day_abbr.upper())
                    if day and period_str.isdigit():
                        self.schedule.add((day, int(period_str), is_exception))
        except (ValueError, IndexError):
            pass

    def parse_course_no(self):
        """ 'GEC101' から 'GEC' と 100 を抽出 """
        match = re.match(r'([A-Z]+)(\d+)', self.no)
        if match:
            self.subject = match.group(1)
            self.level = (int(match.group(2)) // 100) * 100

    def conflicts_with(self, other: 'Course') -> bool:
        """ 他の授業との時間割の競合を判定 (変則フラグは無視して時間枠だけで判定) """
        my_slots = {(d, p) for d, p, _ in self.schedule}
        other_slots = {(d, p) for d, p, _ in other.schedule}
        return not my_slots.isdisjoint(other_slots)

# --- アルゴリズム本体 ---

class PatternBasedOptimizer:
    def __init__(self, all_courses: List[Course], settings: Dict[str, Any], patterns: Dict, period_data: Dict):
        self.all_courses = all_courses
        self.settings = settings
        self.patterns = patterns
        self.period_data = period_data # period_times.json
        self.course_map = {c.no: c for c in all_courses}
        self.course_scores = {}

        # 設定値を展開
        self.constraints = settings.get('constraints', {})
        self.optimizer_settings = settings.get('optimizer_settings', {})

        self.mandatory_nos = set(self.constraints.get('mandatory_nos', []))
        self.mandatory_courses = self._get_courses_by_nos(self.mandatory_nos)
        # 必修のスケジュール: (Day, Period) のセット
        self.mandatory_schedule = {(d, p) for c in self.mandatory_courses for d, p, _ in c.schedule}
        
        self.max_credits = self.constraints.get('max_credits')
        self.min_credits = self.constraints.get('min_credits')
        self.desired_nos = set(self.constraints.get('desired_nos'))
        self.unavailable_slots = {tuple(s) for s in self.constraints.get('unavailable_slots', [])}
        
        self.temperature = self.optimizer_settings.get('temperature')
        self.max_candidates = self.optimizer_settings.get('max_candidates')
        
        # 除外設定
        raw_excluded = set(self.constraints.get('excluded_nos', []))
        self.excluded_prefixes = {s for s in raw_excluded if s.isalpha() and s.isupper()}
        self.excluded_exact_nos = raw_excluded - self.excluded_prefixes
        
        # 番台制約
        level_constraints = self.optimizer_settings.get('course_level_constraints', {})
        self.major_subjects_config = level_constraints.get('major_subjects', {})
        self.other_subjects_config = level_constraints.get('other_subjects', {})
        self.major_subject_codes = set(self.major_subjects_config.get('codes', []))
        
        self._score_courses()
        self.schedule_to_courses = defaultdict(list)
        for course in self.all_courses:
            if self._is_course_valid(course):
                for d, p, _ in course.schedule:
                    self.schedule_to_courses[(d, p)].append(course)

    def _get_courses_by_nos(self, nos: Set[str]) -> List[Course]:
        return [self.course_map[no] for no in nos if no in self.course_map]

    def run(self):
        print("最適化プロセスを開始します...")
        self._score_patterns()
        pattern_keys = self._select_best_patterns()
        
        if not pattern_keys:
            print("有効な時間割パターンが見つかりませんでした。")
            return

        if self._check_conflict(self.mandatory_courses):
            print("エラー: 必修科目が競合しています。")
            return

        mandatory_credits = sum(c.credits for c in self.mandatory_courses)
        if mandatory_credits > self.max_credits:
            print(f"警告: 必修科目の合計単位数({mandatory_credits})が最大単位数({self.max_credits})を超えています。")

        unique_candidates = []
        seen_grids = set()
        
        visible_days = set(["月", "火", "水", "木", "金", "土"])
        
        for key in pattern_keys:
            variations = self._fill_remaining_credits(self._build_initial_timetable(key))
            if not variations: continue
            
            for timetable in variations:
                # 時間割の「型」で重複判定 (表示範囲: 月-土, 1-7限)
                visual_slots = []
                for c in timetable:
                    for d, p, _ in c.schedule:
                        if d in visible_days and 1 <= p <= 7:
                            visual_slots.append((d, p))
                
                occupied = frozenset(visual_slots)
                
                if occupied in seen_grids:
                    continue
                seen_grids.add(occupied)
                unique_candidates.append(timetable)
                if len(unique_candidates) >= self.max_candidates:
                    break
            
            if len(unique_candidates) >= self.max_candidates:
                break

        if not unique_candidates:
            print("候補を生成できませんでした。")
            return

        self._display_results(unique_candidates)
        self._interactive_mode(unique_candidates)

    def _interactive_mode(self, candidates: List[List[Course]]):
        """対話型編集モード"""
        while True:
            print("\n" + "="*60)
            print("【操作メニュー】")
            print(f"  select <1-{len(candidates)}>: 候補を選択して編集・保存モードへ")
            print("  q: 終了")
            print("="*60)
            
            choice = input("> ").strip().lower()
            if choice == 'q':
                break
            
            if choice.startswith('select '):
                try:
                    idx = int(choice.split()[1]) - 1
                    if 0 <= idx < len(candidates):
                        self._edit_candidate(candidates[idx])
                    else:
                        print("無効な番号です。")
                except ValueError:
                    print("番号を指定してください。例: select 1")

    def _edit_candidate(self, timetable: List[Course]):
        """個別の候補編集ループ"""
        current_courses = list(timetable)
        
        while True:
            # 現在の状態を表示
            print("\n" + "-"*30 + " 現在の時間割 " + "-"*30)
            sorted_courses = sorted(current_courses, key=lambda c: (c.subject, c.no))
            total_credits = sum(c.credits for c in sorted_courses)
            
            print(f"合計単位: {total_credits}")
            for c in sorted_courses:
                print(f"  [{c.no}] {c.title_ja} ({c.credits}) {c.schedule_str}")
            
            print("\n【編集コマンド】")
            print("  add <CourseNo> : 科目を追加")
            print("  del <CourseNo> : 科目を削除") # User might use del or rm
            print("  list           : 追加可能な科目候補を表示")
            print("  save           : ICSファイルに出力して終了")
            print("  back           : メニューに戻る")
            
            cmd = input("(edit) > ").strip()
            
            if cmd == 'list':
                print("\n--- 科目別入れ替え候補 ---")
                
                # 候補プール（現在の科目以外で有効なもの）
                valid_pool = [c for c in self.all_courses 
                              if c.no not in {x.no for x in current_courses} 
                              and self._is_course_valid(c)]
                
                # 1. 既存の各科目に対する入れ替え候補を表示
                sorted_current = sorted(current_courses, key=lambda x: x.no)
                
                for curr in sorted_current:
                    # 必修科目は入れ替え対象外なので表示しない
                    if curr.no in self.mandatory_nos:
                        continue
                        
                    print(f"[{curr.no}] {curr.title_ja} ({curr.credits}) {curr.schedule_str}")
                    
                    # curr と入れ替え可能な候補を探す
                    # 条件: curr とは競合するが、それ以外の現在の科目とは競合しない
                    rest = [c for c in current_courses if c.no != curr.no]
                    
                    swaps = []
                    for cand in valid_pool:
                        if cand.conflicts_with(curr):
                            # 他の科目とも競合していないかチェック
                            if not any(cand.conflicts_with(r) for r in rest):
                                swaps.append(cand)
                    
                    swaps.sort(key=lambda x: x.no)
                    if swaps:
                        for s in swaps:
                            print(f"  - [{s.no}] {s.title_ja} ({s.credits}) {s.schedule_str}")
                    else:
                        print("  - (入れ替え候補なし)")

                # 2. 新規追加可能（どの科目とも競合しない）候補
                print("\n--- 新規追加可能 (競合なし) ---")
                addable = []
                for cand in valid_pool:
                    if not any(cand.conflicts_with(c) for c in current_courses):
                        addable.append(cand)
                
                addable.sort(key=lambda x: x.no)
                if addable:
                    for a in addable:
                        print(f"  [{a.no}] {a.title_ja} ({a.credits}) {a.schedule_str}")
                    print(f"  (計 {len(addable)} 件)")
                else:
                    print("  (なし)")
                
                continue
            
            if cmd == 'back':
                break
            
            if cmd == 'save':
                self._export_to_ics(current_courses)
                return # 保存したらメニューに戻る（あるいは終了）

            if cmd.startswith('rm '):
                target_no = cmd.split()[1].upper()
                original_len = len(current_courses)
                current_courses = [c for c in current_courses if c.no != target_no]
                if len(current_courses) < original_len:
                    print(f"削除しました: {target_no}")
                else:
                    print(f"見つかりませんでした: {target_no}")

            elif cmd.startswith('add '):
                target_no = cmd.split()[1].upper()
                if target_no in {c.no for c in current_courses}:
                    print("既に追加されています。")
                    continue
                
                new_course = self.course_map.get(target_no)
                if not new_course:
                    print(f"コースが見つかりません: {target_no}")
                    continue
                
                # 競合チェック
                conflicts = [c for c in current_courses if c.conflicts_with(new_course)]
                if conflicts:
                    names = ", ".join([c.no for c in conflicts])
                    print(f"競合しています: {names}")
                    continue
                
                current_courses.append(new_course)
                print(f"追加しました: {new_course.title_ja}")

    def _export_to_ics(self, timetable: List[Course]):
        """ICS出力処理"""
        filename = input("出力ファイル名 (default: my_schedule.ics): ").strip()
        if not filename:
            filename = "my_schedule.ics"
        if not filename.endswith('.ics'):
            filename += ".ics"

        print("カレンダーの種類を選択してください:")
        print("1. 平常 (Regular)")
        print("2. キリスト教週間 (Christian Week)")
        type_choice = input("> ").strip()
        schedule_type = "christian_week" if type_choice == "2" else "regular"

        # 開始日の設定
        today = datetime.date.today()
        # 次の月曜日をデフォルトに
        default_start = today + datetime.timedelta(days=(7 - today.weekday()))
        date_str = input(f"学期開始日 (YYYY-MM-DD) [Default: {default_start}]: ").strip()
        
        try:
            start_date = datetime.datetime.strptime(date_str, "%Y-%m-%d").date() if date_str else default_start
        except ValueError:
            print("日付形式が不正です。デフォルトを使用します。")
            start_date = default_start

        # 終了日の設定
        default_end = start_date + datetime.timedelta(weeks=10)
        end_str = input(f"学期終了日 (YYYY-MM-DD) [Default: {default_end}]: ").strip()
        
        try:
            term_end = datetime.datetime.strptime(end_str, "%Y-%m-%d").date() if end_str else default_end
        except ValueError:
            print("日付形式が不正です。デフォルトを使用します。")
            term_end = default_end

        # ICS生成
        lines = [
            "BEGIN:VCALENDAR",
            "VERSION:2.0",
            "PRODID:-//OptiCourse//Optimizer//EN",
            "CALSCALE:GREGORIAN",
            "METHOD:PUBLISH"
        ]
        
        end_date_str = term_end.strftime("%Y%m%dT235959")
        day_offset_map = {"月": 0, "火": 1, "水": 2, "木": 3, "金": 4, "土": 5, "日": 6}
        day_abbr_rev = {"MO": "月", "TU": "火", "WE": "水", "TH": "木", "FR": "金", "SA": "土", "SU": "日"}

        # 時間定義の取得
        # period_data["schedule_types"][schedule_type]["variations"] -> List
        # standardとexceptionの辞書を作る
        time_defs = self.period_data.get("schedule_types", {}).get(schedule_type, {}).get("variations", [])
        standard_times = {}
        exception_times = {}
        exception_conditions = set()

        for var in time_defs:
            if var["type"] == "standard":
                standard_times = var["periods"]
            elif var["type"] == "exception":
                exception_times = var["periods"]
                if var["conditions"]:
                    exception_conditions = set(var["conditions"])

        for course in timetable:
            # Courseのscheduleは (DayJA, PeriodInt, IsExceptionBool)
            for day_ja, period, is_exception in course.schedule:
                
                # 時間取得ロジック
                # 1. IsExceptionがTrue (CSVで*付き)
                # 2. または、"*期間/曜日" (例 "*4/M") が period_times.json の conditions に含まれる場合
                #    (後者は、CSVに*がなくても、period定義側で「月4は常に変則」と定義されているケースを想定したいが、
                #     現状のJSON構造だと condition 文字列を作って照合する必要がある)
                
                # 逆変換して条件文字列を作成 (*4/M)
                day_en_list = [k for k, v in day_map_rev.items() if v == day_ja]
                day_en = day_en_list[0] if day_en_list else ""
                
                # 時限キー (JSONは文字列キー "1", "2"...)
                p_key = str(period)
                time_range = None

                target_type = "exception" if is_exception else "standard"
                
                for var in time_defs:
                    if var["type"] != target_type:
                        continue
                    
                    if target_type == "standard":
                        if p_key in var["periods"]:
                            time_range = var["periods"][p_key]
                            break
                    
                    elif target_type == "exception":
                        # 変則の場合は条件にマッチするか確認
                        cond_key = f"*{period}/{day_en}" 
                        if var["conditions"] and cond_key in var["conditions"]:
                            if p_key in var["periods"]:
                                time_range = var["periods"][p_key]
                                break
                
                if not time_range:
                    continue

                start_hm = time_range["start"].replace(':', '') + "00"
                end_hm = time_range["end"].replace(':', '') + "00"

                target_weekday = day_offset_map.get(day_ja, 0)
                base_weekday = start_date.weekday()
                diff = (target_weekday - base_weekday + 7) % 7
                first_date = start_date + datetime.timedelta(days=diff)

                dtstart = first_date.strftime("%Y%m%d") + "T" + start_hm
                dtend = first_date.strftime("%Y%m%d") + "T" + end_hm
                
                lines.append("BEGIN:VEVENT")
                lines.append(f"SUMMARY:{course.title_ja}")
                lines.append(f"DTSTART:{dtstart}")
                lines.append(f"DTEND:{dtend}")
                lines.append(f"RRULE:FREQ=WEEKLY;UNTIL={end_date_str}Z")
                lines.append(f"LOCATION:{course.classroom}")
                lines.append(f"DESCRIPTION:Code: {course.no}\\nInstructor: {course.instructor}\\nMode: {course.mode}")
                lines.append("END:VEVENT")

        lines.append("END:VCALENDAR")
        
        try:
            with open(filename, 'w', encoding='utf-8', newline='\n') as f:
                f.write("\n".join(lines))
            print(f"\n保存しました: {filename}")
        except Exception as e:
            print(f"保存エラー: {e}")


    # --- 以下、既存のロジック (少し整理) ---

    def _is_course_valid(self, course: Course) -> bool:
        if course.no in self.excluded_exact_nos or course.subject in self.excluded_prefixes:
            return False
        is_major = course.subject in self.major_subject_codes
        if is_major:
            min_l = self.major_subjects_config.get('min_level', 0)
            max_l = self.major_subjects_config.get('max_level', 9999)
        else:
            min_l = self.other_subjects_config.get('min_level', 0)
            max_l = self.other_subjects_config.get('max_level', 9999)
        return min_l <= course.level <= max_l

    def _score_courses(self):
        priority_subjects = set(self.optimizer_settings.get('priority_subjects', []))
        level_priorities = self.optimizer_settings.get('level_priorities', {})
        for course in self.all_courses:
            score = 1
            if course.subject in priority_subjects: score += 10
            if course.subject in level_priorities:
                if course.level == level_priorities[course.subject]: score += 5
                elif abs(course.level - level_priorities[course.subject]) <= 100: score += 2
            self.course_scores[course.no] = score

    def _score_patterns(self):
        self.pattern_scores = {}
        for key, data in self.patterns.items():
            courses = [self.course_map[no] for no in data['courses'] if no in self.course_map and self._is_course_valid(self.course_map[no])]
            courses = self._prepare_candidates(courses)
            best = []
            for c in courses:
                if not self._check_conflict(best + [c]):
                    best.append(c)
            self.pattern_scores[key] = {
                "score": sum(self.course_scores.get(c.no, 0) for c in best),
                "courses": best
            }

    def _is_schedule_allowed(self, schedule_items: Set[Tuple[str, int, bool]], ignore_unavailable: bool = False,
                              allow_mandatory_override: bool = False) -> bool:
        off_days = set(self.constraints.get('off_days', []))
        # schedule_items contains (Day, Period, IsException)
        for day, period, _ in schedule_items:
            if day in off_days:
                return False
            if not ignore_unavailable:
                if (day, period) in self.unavailable_slots:
                    if allow_mandatory_override and (day, period) in self.mandatory_schedule:
                        continue
                    return False
        return True

    def _select_best_patterns(self) -> List[str]:
        if self._check_conflict(self.mandatory_courses):
            print("エラー: 必修科目が競合しています。")
            return None
        
        valid_patterns = []
        for key, data in self.pattern_scores.items():
            # パターンデータの schedule は [["月", 3], ...] 形式なので変換が必要
            # ただし patterns_json の schedule には * 情報がない。
            # パターン自体は「枠」なので * は関係ないが、照合用にセット化
            pat_sched = set()
            for item in self.patterns[key]['schedule']:
                if len(item) >= 2:
                    pat_sched.add((item[0], item[1], False)) # 仮にFalse

            # パターン自体の空きコマチェックは、変則フラグ無視で行う
            pat_sched_simple = {(d, p) for d, p, _ in pat_sched}
            
            # 不可コマチェック
            if not self._is_schedule_allowed(pat_sched, ignore_unavailable=False):
                # 不可コマに引っかかるが、必修があるならOKか？
                # 今回はパターン抽出の時点では厳しめに見る
                continue
                
            # 必修との競合チェック
            if not pat_sched_simple.isdisjoint(self.mandatory_schedule):
                continue
                
            valid_patterns.append((data['score'], key))
        
        valid_patterns.sort(key=lambda x: x[0], reverse=True)
        return [key for _, key in valid_patterns]

    def _build_initial_timetable(self, pattern_key: str) -> List[Course]:
        timetable = list(self.mandatory_courses)
        courses_from_pattern = self.pattern_scores[pattern_key]['courses']
        for course in courses_from_pattern:
            if sum(c.credits for c in timetable) + course.credits > self.max_credits:
                continue
            if not self._check_conflict(timetable + [course]):
                timetable.append(course)
        return timetable

    def _fill_remaining_credits(self, initial_timetable: List[Course]) -> List[List[Course]]:
        
        def greedy_fill(base_timetable: List[Course], ignore_unavailable: bool) -> Tuple[List[Course], List[List[Course]]]:
            current_timetable = list(base_timetable)
            current_credits = sum(c.credits for c in current_timetable)
            
            existing_nos = {c.no for c in current_timetable}
            candidates = [c for c in self.all_courses if c.no not in existing_nos and self._is_course_valid(c)]
            candidates = self._prepare_candidates(candidates)
            
            local_variations = []
            
            # 初期状態で条件を満たしている場合も候補に含める
            if self.min_credits <= current_credits <= self.max_credits:
                local_variations.append(list(current_timetable))

            for course in candidates:
                if not self._is_schedule_allowed(course.schedule, ignore_unavailable=ignore_unavailable): continue
                
                if current_credits + course.credits > self.max_credits:
                    continue

                if not self._check_conflict(current_timetable + [course]):
                    current_timetable.append(course)
                    current_credits += course.credits
                    
                    # 単位数条件を満たすたびにバリエーションとして記録
                    if self.min_credits <= current_credits <= self.max_credits:
                        local_variations.append(list(current_timetable))
            
            return current_timetable, local_variations

        # 1. Strict pass (空きコマ条件を厳守)
        final_strict, vars_strict = greedy_fill(initial_timetable, ignore_unavailable=False)
        
        if vars_strict:
            return vars_strict
        
        # 2. Fallback pass (空きコマ条件を緩和)
        # Strictパスで結果が出なかった場合、その最終状態から緩和パスを試す
        _, vars_loose = greedy_fill(final_strict, ignore_unavailable=True)
        return vars_loose

    # _fill_pass removed merged into greedy_fill internal function

    def _prepare_candidates(self, courses: List[Course]) -> List[Course]:
        temp_ratio = self.temperature / 100
        if self.desired_nos and temp_ratio == 0:
            courses = [c for c in courses if c.no in self.desired_nos]
        
        def score(c: Course):
            base = self.course_scores.get(c.no, 0)
            pref = (1 - temp_ratio) * (100 if c.no in self.desired_nos else 0)
            rand = temp_ratio * random.random() * 20
            return base + pref + rand
        
        return sorted(courses, key=score, reverse=True)

    @staticmethod
    def _check_conflict(timetable: List[Course]) -> bool:
        for i in range(len(timetable)):
            for j in range(i + 1, len(timetable)):
                if timetable[i].conflicts_with(timetable[j]):
                    return True
        return False

    def _display_results(self, candidates: List[List[Course]]):
        for idx, timetable in enumerate(candidates, 1):
            if not timetable: continue
            print("\n" + "="*50 + f"\n候補 #{idx}\n" + "="*50)
            print(f"合計単位数: {sum(c.credits for c in timetable)}")
            sorted_t = sorted(timetable, key=lambda c: (c.subject, c.no))
            for c in sorted_t:
                print(f"  - [{c.no}] {c.title_ja.ljust(20)} {c.schedule_str}")
                
                # 必修科目は入れ替え候補を表示しない
                if c.no in self.mandatory_nos:
                    continue

                # --- Valid Swap Candidates Detection ---
                # A swap candidate is a course that:
                # 1. Is not currently in the timetable
                # 2. Conflicts with the current course 'c' (occupies similar slot)
                # 3. Does NOT conflict with the rest of the timetable
                
                rest_of_schedule = [x for x in timetable if x.no != c.no]
                # To speed up, check if 'cand' conflicts with 'rest_of_schedule'
                # Pre-calculate occupied slots of rest
                # (Simple loop check is likely fast enough for small N)
                
                swaps = []
                # existing set for fast lookup
                existing_nos = {x.no for x in timetable}
                
                for cand in self.all_courses:
                    if cand.no == c.no: continue
                    if cand.no in existing_nos: continue
                    if not self._is_course_valid(cand): continue
                    
                    # Must conflict with 'c' (the valid alternative logic)
                    if cand.conflicts_with(c):
                        # But must fit with everything else
                        is_compatible = True
                        for r in rest_of_schedule:
                            if cand.conflicts_with(r):
                                is_compatible = False
                                break
                        
                        if is_compatible:
                            swaps.append(cand)

                if swaps:
                    # Sort by score or number?
                    swaps.sort(key=lambda x: x.no)
                    display_swaps = swaps[:5] # Limit to 5
                    swap_str = ", ".join([f"{s.no}({s.credits})" for s in display_swaps])
                    if len(swaps) > 5:
                        swap_str += "..."
                    print(f"    (入れ替え候補: {swap_str})")

            grid = defaultdict(dict)
            for c in timetable:
                for day, period, _ in c.schedule:
                    grid[day][period] = f"[{c.subject}]"
            
            days = ["月", "火", "水", "木", "金", "土"]
            print("\n" + "--- 時間割グリッド ---")
            header = " | " + " | ".join([f"{day:<6}" for day in days])
            print(header + "\n" + "-" * len(header))
            for p in range(1, 8):
                print(f"{p}限" + "".join([f"| {grid[day].get(p, '      '):<6}" for day in days]))
            print("\n")


# --- ヘルパー ---
# グローバル定数的に使う逆マップ
day_map_rev = {"M": "月", "TU": "火", "W": "水", "TH": "木", "F": "金", "SA": "土", "SU": "日"}

def load_courses_from_csv(filepath: str) -> List[Course]:
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            reader = csv.reader(f)
            next(reader)
            return [Course(no=r[0], lang=r[1], title_en=r[2], title_ja=r[3], schedule_str=r[4],
                           classroom=r[5], mode=r[6], instructor=r[7], credits=int(r[8]) if r[8].isdigit() else 0,
                           link=r[9] if len(r) > 9 else "") for r in reader if len(r) >= 9]
    except Exception as e:
        print(f"CSV読み込みエラー: {e}")
    return []

def load_json_file(filepath: str) -> Dict:
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            return json.load(f)
    except:
        return {}

def main():
    SETTINGS_PATH = 'user_settings.json'
    PERIOD_PATH = 'period_times.json'
    
    settings = load_json_file(SETTINGS_PATH)
    if not settings:
        print(f"設定ファイル({SETTINGS_PATH})が見つかりません。デフォルト値はありません。")
        return

    # ファイルパス取得
    csv_path = settings.get("file_paths", {}).get("courses_csv", "2025W_normalized.csv")
    pat_path = settings.get("file_paths", {}).get("patterns_json", "schedule_patterns.json")
    
    all_courses = load_courses_from_csv(csv_path)
    patterns = load_json_file(pat_path)
    period_data = load_json_file(PERIOD_PATH)
    
    if not period_data:
        print(f"警告: {PERIOD_PATH} が読み込めませんでした。カレンダー出力時に標準時間が不明になる可能性があります。")

    if all_courses and patterns:
        optimizer = PatternBasedOptimizer(all_courses, settings, patterns, period_data)
        optimizer.run()

if __name__ == '__main__':
    main()