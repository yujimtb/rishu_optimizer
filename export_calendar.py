import csv
import json
import argparse
import datetime
import sys
import re
from pathlib import Path
from typing import Dict, List, Tuple, Optional

# Windows環境での文字化け対策
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')

# 曜日マップ
DAY_MAP_JA_TO_EN = {"月": "MO", "火": "TU", "水": "WE", "木": "TH", "金": "FR", "土": "SA", "日": "SU"}
DAY_MAP_EN_KEY = {"M": "月", "TU": "火", "W": "水", "TH": "木", "F": "金", "SA": "土", "SU": "日"}

def load_period_times(csv_path: str) -> Dict[int, Tuple[str, str]]:
    """
    period.csv から時限ごとの開始・終了時刻を読み込む。
    形式: {1: ("084500", "100000"), ...}
    """
    period_map = {}
    try:
        with open(csv_path, 'r', encoding='utf-8') as f:
            reader = csv.reader(f)
            # ヘッダー処理: 1行目と2行目はスキップ、または内容確認
            # 今回は固定フォーマットとして3行目以降のデータ列(col 1)を見る
            # col 0: "第1時限", col 1: "8:45-10:00"
            
            rows = list(reader)
            start_row_idx = 0
            for i, row in enumerate(rows):
                if row and "第1時限" in row[0]:
                    start_row_idx = i
                    break
            
            for row in rows[start_row_idx:]:
                if not row or len(row) < 2: continue
                
                label = row[0].strip()
                time_range = row[1].strip() # "8:45-10:00"
                
                # "第N時限" から数字を抽出
                match = re.search(r'(\d+)', label)
                if match and time_range:
                    p_num = int(match.group(1))
                    
                    # 時間パース "8:45-10:00"
                    times = time_range.split('-')
                    if len(times) == 2:
                        start_str = times[0].strip().replace(':', '') + "00" # 0845 -> 084500
                        end_str = times[1].strip().replace(':', '') + "00"
                        
                        # 0埋め (845 -> 0845)
                        if len(start_str) == 5: start_str = "0" + start_str
                        if len(end_str) == 5: end_str = "0" + end_str
                        
                        period_map[p_num] = (start_str, end_str)
                        
    except Exception as e:
        print(f"警告: {csv_path} の読み込みに失敗しました: {e}")
        # フォールバック用のデフォルト時間（ICU標準時限を想定）
        return {
            1: ("085000", "100000"), 2: ("101000", "112000"), 3: ("113000", "124000"),
            4: ("135000", "150000"), 5: ("151000", "162000"), 6: ("163000", "174000"),
            7: ("175000", "190000")
        }
    return period_map

def get_course_info(normalized_csv: str, target_nos: List[str]) -> List[Dict]:
    """指定されたコース番号の情報をCSVから取得"""
    courses = []
    target_set = set(target_nos)
    
    try:
        with open(normalized_csv, 'r', encoding='utf-8') as f:
            reader = csv.reader(f)
            header = next(reader) # skip header
            
            for row in reader:
                if len(row) < 6: continue
                c_no = row[0]
                if c_no in target_set:
                    courses.append({
                        "no": c_no,
                        "title": row[2] + " " + row[3], # EN + JA
                        "schedule": row[4], # "3/M,2/TH" format
                        "classroom": row[5],
                        "instructor": row[7]
                    })
    except Exception as e:
        print(f"エラー: 授業データの読み込み失敗: {e}")
        
    return courses

def parse_schedule_string(sched_str: str) -> List[Tuple[str, int]]:
    """ "3/M, 2/TH" -> [("月", 3), ("木", 2)] """
    # normalize_courses.py と同等のロジック
    slots = []
    # 記号除去
    clean = re.sub(r'[\\*()]', '', sched_str)
    parts = clean.split(',')
    for p in parts:
        if '/' in p:
            try:
                period_s, day_abbr = p.strip().split('/')
                day_key = day_abbr.strip().upper()
                if day_key in DAY_MAP_EN_KEY:
                    slots.append((DAY_MAP_EN_KEY[day_key], int(period_s)))
            except:
                pass
    return slots

def create_ics_content(courses: List[Dict], period_times: Dict[int, Tuple[str, str]], start_date: datetime.date) -> str:
    """iCalendar形式の文字列を生成"""
    
    # 学期開始日（月曜日）を基準にする
    # start_date が月曜でない場合、直前の月曜に戻すか、そのまま使うか。
    # ここでは「指定された日付以降の最初の該当曜日」を計算する
    
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//OptiCourse//Course Scheduler//EN",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH"
    ]
    
    day_offset_map = {"月": 0, "火": 1, "水": 2, "木": 3, "金": 4, "土": 5, "日": 6}
    
    # 基準日が何曜日か (0=Mon, 6=Sun)
    base_weekday = start_date.weekday()
    
    # 学期終了日（仮: 開始から10週間後）
    term_end = start_date + datetime.timedelta(weeks=10)
    end_date_str = term_end.strftime("%Y%m%dT235959")
    
    for course in courses:
        slots = parse_schedule_string(course['schedule'])
        for day_ja, period in slots:
            if period not in period_times:
                continue
                
            start_time_str, end_time_str = period_times[period]
            
            # 最初の授業日を計算
            target_weekday = day_offset_map.get(day_ja, 0)
            days_diff = (target_weekday - base_weekday + 7) % 7
            first_date = start_date + datetime.timedelta(days=days_diff)
            
            dtstart = first_date.strftime("%Y%m%d") + "T" + start_time_str
            dtend = first_date.strftime("%Y%m%d") + "T" + end_time_str
            
            description = f"Course No: {course['no']}\\nInstructor: {course['instructor']}\\nSchedule: {course['schedule']}"
            
            lines.append("BEGIN:VEVENT")
            lines.append(f"SUMMARY:{course['title']}")
            lines.append(f"DTSTART:{dtstart}")
            lines.append(f"DTEND:{dtend}")
            # 毎週繰り返し (RRULE)
            lines.append(f"RRULE:FREQ=WEEKLY;UNTIL={end_date_str}Z")
            lines.append(f"LOCATION:{course['classroom']}")
            lines.append(f"DESCRIPTION:{description}")
            lines.append("END:VEVENT")

    lines.append("END:VCALENDAR")
    return "\n".join(lines)

def main():
    parser = argparse.ArgumentParser(description="Generate iCalendar (.ics) file from course list.")
    parser.add_argument("--courses", nargs='+', help="List of course numbers to export (e.g. ELA060 PHY261)")
    parser.add_argument("--output", default="my_schedule.ics", help="Output filename")
    parser.add_argument("--start-date", help="Term start date (YYYY-MM-DD). Default: next Monday")
    
    args = parser.parse_args()
    
    # 設定読み込み
    settings = {}
    try:
        with open('user_settings.json', 'r', encoding='utf-8') as f:
            settings = json.load(f)
    except:
        pass
        
    # 対象科目の決定
    target_nos = []
    if args.courses:
        target_nos = args.courses
    else:
        # 設定ファイルから mandatory_nos を取得
        target_nos = settings.get('constraints', {}).get('mandatory_nos', [])
        
    if not target_nos:
        print("エラー: エクスポートする科目が指定されていません。")
        print("引数で指定するか (--courses AAA101 BBB202)、user_settings.json の mandatory_nos に設定してください。")
        return

    # 開始日の決定
    if args.start_date:
        try:
            start_date = datetime.datetime.strptime(args.start_date, "%Y-%m-%d").date()
        except ValueError:
            print("日付形式エラー: YYYY-MM-DD で指定してください")
            return
    else:
        # デフォルト: 今日の次の月曜日
        today = datetime.date.today()
        start_date = today + datetime.timedelta(days=(7 - today.weekday()))
        print(f"開始日が指定されていないため、次の月曜日 ({start_date}) を基準にします。")

    print(f"対象科目: {', '.join(target_nos)}")
    print("データ読み込み中...")
    
    period_times = load_period_times('period.csv')
    course_data = get_course_info('2025W_normalized.csv', target_nos)
    
    if not course_data:
        print("警告: 指定された科目のデータが見つかりませんでした。")
        return
        
    print(f"{len(course_data)} 件の授業データが見つかりました。ICSファイルを生成します...")
    
    ics_content = create_ics_content(course_data, period_times, start_date)
    
    with open(args.output, 'w', encoding='utf-8', newline='\n') as f:
        f.write(ics_content)
        
    print(f"完了: '{args.output}' が作成されました。カレンダーアプリにインポートできます。")

if __name__ == "__main__":
    main()
