# 履修最適化ツール (Course Registration Optimizer)

## 概要

このツールは、大学の授業データ（CSV）を元に、ユーザーが設定した制約（必修科目、単位数、空きコマなど）に基づいて最適な履修計画の候補を複数生成するコマンドラインツールです。
主にICU（国際基督教大学）の授業データ形式に対応するように設計されていますが、データ形式を合わせれば他大学でも応用可能です。

## 特徴

- **学期管理**: 春(S)・秋(A)・冬(W) の3学期をサポート。学期IDを指定するだけで、ファイルパスやデフォルト日程を自動解決します。
- **統合CLI**: `python src/main.py <command> <semester>` の形式で、初期化・前処理・最適化・出力を一元管理できます。
- **学期別設定**: 学期ごとに制約（必修科目、除外科目等）を個別管理。共通設定はグローバルファイルで一元管理します。
- **データ整形**: 複雑な形式の授業時間割CSVを、プログラムで扱いやすい標準的なCSV形式に変換します。
- **パターン抽出**: 共通する時間割パターン（例: 「月3, 水3, 金3」など）を自動抽出し、最適化のベースとして利用します。
- **高度な最適化**:
    - 必修科目、除外科目、優先科目の指定
    - 単位数の下限・上限設定
    - 全休曜日や不可コマ（アルバイトや部活など）の設定
    - 科目レベル（番台）によるフィルタリング
- **対話型編集**: 生成された候補を選択し、その場で科目の追加・削除を行って微調整できます。 `list` コマンドで追加・入れ替え可能な候補をツリー形式で確認可能です。
- **カレンダー出力**: 確定した時間割をiCalendar形式（.ics）で出力し、GoogleカレンダーやOutlookにインポート可能です。学期の開始日・終了日は学期種別から自動算出されます。
- **データバリデーション**: 正規化時に不正なCredits値、空Schedule、重複CourseNoを検出して警告します。
- **外部依存なし**: Pythonの標準ライブラリのみで動作するため、環境構築が容易です。

## 必要要件

- Python 3.8 以上
- 外部ライブラリのインストールは不要です。

## ファイル構成

```
.
├── src/                          # Pythonスクリプト
│   ├── main.py                   # 統合CLIエントリポイント
│   ├── semester.py               # 学期コンテキストモジュール
│   ├── normalize_courses.py
│   ├── discover_patterns.py
│   ├── convert_period.py
│   ├── optimize_courses.py
│   └── export_calendar.py
├── data/
│   ├── semesters/                # 学期別データ
│   │   ├── 2025W/
│   │   │   ├── raw.csv           # (入力) 大学からの元データ
│   │   │   ├── normalized.csv    # (生成) 正規化データ
│   │   │   └── patterns.json     # (生成) パターンデータ
│   │   └── 2026S/
│   │       └── ...
│   ├── period.csv                # (入力) 時間割定義 (学期横断共有)
│   └── period_times.json         # (生成) 時間割JSON
├── settings/
│   ├── global.json               # 共通設定 (全休曜日, 最適化パラメータ等)
│   └── 2025W.json                # 学期別設定 (必修科目, 除外科目等)
├── output/                       # 生成物
│   └── 2025W_schedule.ics
├── logs/                         # ログファイル
├── requirements.txt
└── README.md
```

## 使用方法 (統合CLI)

### Quick Start (新しい学期で始める場合)

```bash
# 1. 学期のセットアップ (raw CSV をコピー)
python src/main.py init 2026S --csv "path/to/downloaded.csv"

# 2. 設定ファイルを編集
#    settings/2026S.json を開き、必修科目や制約を設定

# 3. 前処理の一括実行
python src/main.py prepare 2026S

# 4. 最適化 (対話モード)
python src/main.py optimize 2026S

# 5. カレンダー出力 (非対話)
python src/main.py export 2026S --courses ELA060 PHY261
```

### コマンド一覧

#### `init` — 新規学期のセットアップ
```bash
python src/main.py init <semester> [--csv <path>]
```
- `data/semesters/<semester>/` ディレクトリを作成
- `settings/<semester>.json` に設定テンプレートを生成
- `--csv` を指定すると、raw CSVを自動コピー

#### `prepare` — 前処理パイプライン一括実行
```bash
python src/main.py prepare <semester>
```
normalize → discover patterns → convert period を順次実行します。

#### `optimize` — 最適化 (対話モード)
```bash
python src/main.py optimize <semester>
```
複数の候補を生成し、対話的に編集・保存できます。

#### `export` — カレンダー出力
```bash
python src/main.py export <semester> [--courses ...] [--output ...] [--start-date YYYY-MM-DD] [--end-date YYYY-MM-DD]
```

#### `list` — 学期一覧の表示
```bash
python src/main.py list
```

### 設定ファイル

**共通設定** (`settings/global.json`):
```json
{
    "constraints": {
        "off_days": ["土", "日"]
    },
    "optimizer_settings": {
        "temperature": 50,
        "max_candidates": 10
    },
    "semester_defaults": {
        "S": { "start_month": 4, "start_day": 7, "weeks": 10 },
        "A": { "start_month": 9, "start_day": 1, "weeks": 10 },
        "W": { "start_month": 12, "start_day": 1, "weeks": 10 }
    }
}
```

**学期別設定** (`settings/2025W.json`):
```json
{
    "constraints": {
        "mandatory_nos": ["ELA060", "PHY261"],
        "excluded_nos": ["HPE", "JLP"],
        "min_credits": 16,
        "max_credits": 18,
        "unavailable_slots": [
            {"day": "月", "period": 1},
            {"day": "金", "period": 5}
        ]
    },
    "optimizer_settings": {
        "priority_subjects": ["PHY"],
        "level_priorities": { "MTH": 200, "PHY": 200 }
    }
}
```

読み込み時は `global.json` をベースに、学期設定でオーバーライドされます。

### 対話モード操作

**候補選択画面:**
- `select <番号>`: 候補を選択して編集モードに入ります。
- `q`: 終了します。

**編集モード:**
- `add <科目番号>`: 科目を追加します（競合チェック付き）。
- `rm <科目番号>`: 科目を削除します。
- `list`: 追加可能な科目候補を表示します。
- `save`: 現在の時間割を `.ics` ファイルに出力します。学期の開始日・終了日は自動算出され、Enterで確定できます。
- `back`: 候補選択画面に戻ります。

### 個別スクリプトの実行 (上級)

各スクリプトは `--semester` オプションで単体実行も可能です:

```bash
python src/normalize_courses.py --semester 2026S
python src/discover_patterns.py --semester 2026S
python src/convert_period.py --input data/period.csv --output data/period_times.json
python src/optimize_courses.py 2026S
python src/export_calendar.py 2026S --courses ELA060 PHY261
```
保存しました: my_schedule.ics
```

## トラブルシューティング

- **「ファイルが見つかりません」**: ファイル名がデフォルトと一致しているか確認してください。
- **Windowsで文字化けする場合**: スクリプトはUTF-8エンコーディングを想定しています。
- **変則時間の適用**: `period.csv` 内で `*` が付いているコマや、`period_times.json` で定義された変則条件に合致するコマは、自動的に変則時間が適用されてカレンダーに出力されます。
