import csv
import json
from collections import defaultdict
import os

def discover_and_save_patterns(csv_path: str, output_path: str):
    """
    CSVファイルから授業データを読み込み、ユニークな時間割パターンを抽出して、
    各パターンに属する授業科目のリストをJSONファイルに保存する。

    出力形式:
    {
        "3/TU,2/TH,3/TH": {
            "schedule": [["火", 3], ["木", 2], ["木", 3]],
            "courses": ["GEH012", "ANOTHER_COURSE_NO"]
        },
        ...
    }
    """
    patterns = defaultdict(lambda: defaultdict(list))
    
    day_map = {"M": "月", "TU": "火", "W": "水", "TH": "木", "F": "金", "SA": "土", "SU": "日"}

    print(f"'{csv_path}' から時間割パターンの抽出を開始します...")

    try:
        with open(csv_path, 'r', encoding='utf-8') as f:
            reader = csv.reader(f)
            next(reader)  # ヘッダーをスキップ

            for row in reader:
                if len(row) < 5:
                    continue
                
                course_no = row[0]
                schedule_str = row[4]

                # パターンキーとして元の時間割文字列を使用
                pattern_key = schedule_str
                
                # パターンにコース番号を追加
                patterns[pattern_key]["courses"].append(course_no)

    except FileNotFoundError:
        print(f"エラー: ファイルが見つかりません: {csv_path}")
        return
    except Exception as e:
        print(f"CSV読み込み中にエラーが発生しました: {e}")
        return

    # パースされたスケジュール情報を各パターンに追加
    final_patterns = {}
    for key, value in patterns.items():
        parsed_schedule = []
        # schedule_str のパースロジック (optimize_courses.pyから)
        try:
            parts = key.split(',')
            valid_pattern = True
            for part in parts:
                if '/' in part:
                    period, day_abbr = part.strip().split('/')
                    day = day_map.get(day_abbr.upper())
                    if day and period.isdigit():
                        parsed_schedule.append([day, int(period)])
                    else: # 解析できない場合は無効なパターン
                        valid_pattern = False
                        break
                else: # スラッシュがない場合も無効
                    valid_pattern = False
                    break
            
            if valid_pattern:
                final_patterns[key] = {
                    "schedule": parsed_schedule,
                    "courses": value["courses"]
                }
        except (ValueError, IndexError):
            # 解析エラーが起きるパターンは無視
            continue

    try:
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(final_patterns, f, ensure_ascii=False, indent=4)
        print(f"'{output_path}' に {len(final_patterns)} 件のユニークなパターンを保存しました。")
    except Exception as e:
        print(f"JSONファイルへの書き込み中にエラーが発生しました: {e}")


if __name__ == '__main__':
    # このスクリプトが存在するディレクトリを基準にする
    base_dir = os.path.dirname(os.path.abspath(__file__))
    
    CSV_FILE_PATH = os.path.join(base_dir, '2025W_normalized.csv')
    OUTPUT_JSON_PATH = os.path.join(base_dir, 'schedule_patterns.json')
    
    discover_and_save_patterns(CSV_FILE_PATH, OUTPUT_JSON_PATH)
