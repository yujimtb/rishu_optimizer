import csv
import json
import re
import sys

# Windows環境での文字化け対策
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')

def parse_time_range(time_str):
    """ '8:45-10:00' -> {'start': '08:45', 'end': '10:00'} """
    if not time_str or '-' not in time_str:
        return None
    try:
        start, end = time_str.split('-')
        return {
            "start": start.strip().zfill(5), # 8:45 -> 08:45
            "end": end.strip().zfill(5)
        }
    except:
        return None

def parse_condition_string(cond_str):
    """ '*4/M, *5/TH' -> ['*4/M', '*5/TH'] """
    if not cond_str or cond_str == "標準":
        return None
    # カンマで分割してリスト化
    conditions = []
    parts = cond_str.split(',')
    for p in parts:
        p = p.strip()
        if p:
            conditions.append(p)
    return conditions

def convert_csv_to_json(csv_path, output_path):
    result = {
        "schedule_types": {} # regular, christian_week, etc.
    }

    try:
        with open(csv_path, 'r', encoding='utf-8') as f:
            reader = list(csv.reader(f))
            
            # ヘッダー解析
            # Row 0: [, 平常, 平常, キリスト教週間, キリスト教週間]
            # Row 1: [, 標準, "*4/M...", 標準, "*4/M..."]
            
            # 列ごとのメタデータを構築
            col_meta = {}
            main_categories = reader[0]
            sub_categories = reader[1]
            
            for col_idx in range(1, len(main_categories)):
                main_cat = main_categories[col_idx].strip()
                sub_cat = sub_categories[col_idx].strip()
                
                if not main_cat: continue
                
                # キー名の正規化 (平常 -> regular, キリスト教週間 -> christian_week)
                cat_key = "regular" if "平常" in main_cat else "christian_week" if "キリスト教" in main_cat else main_cat
                
                if cat_key not in result["schedule_types"]:
                    result["schedule_types"][cat_key] = {
                        "name": main_cat,
                        "variations": []
                    }
                
                variation_info = {
                    "type": "standard" if sub_cat == "標準" else "exception",
                    "conditions": parse_condition_string(sub_cat),
                    "periods": {}
                }
                
                # col_metaにこのバリエーションへの参照を保存
                col_meta[col_idx] = variation_info
                result["schedule_types"][cat_key]["variations"].append(variation_info)

            # データ行解析
            # Row 2~: [第1時限, 8:45-10:00, , 8:45-9:50, ...]
            for row in reader[2:]:
                if not row: continue
                
                row_label = row[0].strip()
                # "第1時限" -> 1, "昼休" -> "lunch"
                period_key = None
                match = re.search(r'(\d+)', row_label)
                if match:
                    period_key = match.group(1)
                elif "昼" in row_label:
                    period_key = "lunch"
                else:
                    period_key = row_label # fallback
                
                for col_idx in range(1, len(row)):
                    if col_idx in col_meta and col_idx < len(row):
                        time_val = parse_time_range(row[col_idx])
                        if time_val:
                            col_meta[col_idx]["periods"][period_key] = time_val

        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(result, f, ensure_ascii=False, indent=4)
            
        print(f"変換完了: '{output_path}' を生成しました。")
        return True

    except Exception as e:
        print(f"エラーが発生しました: {e}")
        return False

if __name__ == "__main__":
    convert_csv_to_json('data/period.csv', 'data/period_times.json')
