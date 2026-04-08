"""
OptiCourse 統合CLIエントリポイント

Usage:
    python src/main.py init <semester> [--csv <path>]
    python src/main.py prepare <semester>
    python src/main.py optimize <semester>
    python src/main.py export <semester> [--courses ...] [--output ...]
    python src/main.py list
"""

import argparse
import shutil
import sys
from pathlib import Path

# src/ をモジュール検索パスに追加
sys.path.insert(0, str(Path(__file__).resolve().parent))

from semester import SemesterContext, list_semesters, detect_latest_semester, load_merged_settings


def cmd_init(args):
    """新規学期のセットアップ"""
    ctx = SemesterContext(args.semester)

    # ディレクトリ作成
    ctx.semester_dir.mkdir(parents=True, exist_ok=True)
    print(f"学期ディレクトリを作成しました: {ctx.semester_dir}")

    # raw CSV のコピー
    if args.csv:
        src = Path(args.csv)
        if not src.exists():
            print(f"エラー: ファイルが見つかりません: {src}", file=sys.stderr)
            sys.exit(1)
        dest = ctx.raw_csv_path
        shutil.copy2(src, dest)
        print(f"CSVをコピーしました: {src} → {dest}")
    else:
        if not ctx.raw_csv_path.exists():
            print(f"ヒント: raw CSVを配置してください → {ctx.raw_csv_path}")

    # 設定テンプレートの生成
    if not ctx.settings_path.exists():
        ctx.settings_path.parent.mkdir(parents=True, exist_ok=True)
        template = """{
    "constraints": {
        "mandatory_nos": [],
        "excluded_nos": [],
        "desired_nos": [],
        "min_credits": 14,
        "max_credits": 18,
        "unavailable_slots": []
    },
    "optimizer_settings": {
        "priority_subjects": [],
        "level_priorities": {},
        "course_level_constraints": {
            "major_subjects": {
                "codes": [],
                "min_level": 0,
                "max_level": 9999
            },
            "other_subjects": {
                "min_level": 0,
                "max_level": 9999
            }
        }
    }
}
"""
        ctx.settings_path.write_text(template, encoding="utf-8")
        print(f"設定テンプレートを作成しました: {ctx.settings_path}")
        print(f"  → 必修科目や制約を編集してください。")
    else:
        print(f"設定ファイルは既に存在します: {ctx.settings_path}")

    print(f"\n次のステップ:")
    if not args.csv and not ctx.raw_csv_path.exists():
        print(f"  1. raw CSVを配置: {ctx.raw_csv_path}")
        print(f"  2. 設定を編集: {ctx.settings_path}")
        print(f"  3. python src/main.py prepare {args.semester}")
    else:
        print(f"  1. 設定を編集: {ctx.settings_path}")
        print(f"  2. python src/main.py prepare {args.semester}")


def cmd_prepare(args):
    """前処理パイプラインの一括実行: normalize → discover → convert_period"""
    ctx = SemesterContext(args.semester)

    if not ctx.raw_csv_path.exists():
        print(f"エラー: raw CSVが見つかりません: {ctx.raw_csv_path}", file=sys.stderr)
        print(f"先に 'python src/main.py init {args.semester} --csv <path>' を実行してください。")
        sys.exit(1)

    # Step 1: normalize
    print(f"[1/3] 正規化: {ctx.raw_csv_path} → {ctx.normalized_csv_path}")
    from normalize_courses import normalize
    warnings = normalize(ctx.raw_csv_path, ctx.normalized_csv_path)
    if warnings:
        print(f"  ⚠ {len(warnings)} 件の警告:")
        for w in warnings:
            print(f"    - {w}")
    print(f"  完了: {ctx.normalized_csv_path}")

    # Step 2: discover patterns
    print(f"\n[2/3] パターン抽出: {ctx.normalized_csv_path} → {ctx.patterns_json_path}")
    from discover_patterns import discover_and_save_patterns
    discover_and_save_patterns(str(ctx.normalized_csv_path), str(ctx.patterns_json_path))

    # Step 3: convert period (学期横断共有 — 未生成の場合のみ)
    period_json = ctx.period_times_json_path()
    period_csv = ctx.period_csv_path()
    if not period_json.exists():
        if not period_csv.exists():
            print(f"\n[3/3] スキップ: {period_csv} が見つかりません（初回は手動で配置してください）")
        else:
            print(f"\n[3/3] 時間割JSON変換: {period_csv} → {period_json}")
            from convert_period import convert_csv_to_json
            convert_csv_to_json(str(period_csv), str(period_json))
    else:
        print(f"\n[3/3] スキップ: {period_json} は既に存在します")

    print(f"\n前処理が完了しました。")
    print(f"次のステップ: python src/main.py optimize {args.semester}")


def cmd_optimize(args):
    """最適化（対話モード）"""
    ctx = SemesterContext(args.semester)

    if not ctx.normalized_csv_path.exists():
        print(f"エラー: 正規化CSVが見つかりません: {ctx.normalized_csv_path}", file=sys.stderr)
        print(f"先に 'python src/main.py prepare {args.semester}' を実行してください。")
        sys.exit(1)

    # optimize_courses.py の main() に学期IDを渡す
    # sys.argvを書き換えてargparseに渡す
    sys.argv = ['optimize_courses.py', args.semester]
    from optimize_courses import main as optimize_main
    optimize_main()


def cmd_export(args):
    """カレンダー出力"""
    export_args = ['export_calendar.py', args.semester]
    if args.courses:
        export_args += ['--courses'] + args.courses
    if args.output:
        export_args += ['--output', args.output]
    if args.start_date:
        export_args += ['--start-date', args.start_date]
    if args.end_date:
        export_args += ['--end-date', args.end_date]

    sys.argv = export_args
    from export_calendar import main as export_main
    export_main()


def cmd_list(args):
    """学期一覧の表示"""
    semesters = list_semesters()
    if not semesters:
        print("登録されている学期はありません。")
        print(f"'python src/main.py init <semester>' で新規学期を作成できます。")
        return

    latest = detect_latest_semester()
    print("登録されている学期:")
    for sid in semesters:
        ctx = SemesterContext(sid)
        marker = " ← 最新" if sid == latest else ""
        has_raw = "✓" if ctx.raw_csv_path.exists() else "✗"
        has_norm = "✓" if ctx.normalized_csv_path.exists() else "✗"
        has_pat = "✓" if ctx.patterns_json_path.exists() else "✗"
        has_settings = "✓" if ctx.settings_path.exists() else "✗"
        print(f"  {sid} ({ctx.term_name}){marker}")
        print(f"    raw: {has_raw}  normalized: {has_norm}  patterns: {has_pat}  settings: {has_settings}")


def build_parser():
    parser = argparse.ArgumentParser(
        prog="opticourse",
        description="OptiCourse — 履修最適化ツール",
    )
    subparsers = parser.add_subparsers(dest="command", help="サブコマンド")

    # init
    p_init = subparsers.add_parser("init", help="新規学期のセットアップ")
    p_init.add_argument("semester", help="学期ID (例: 2026S)")
    p_init.add_argument("--csv", help="raw CSVファイルのパス")
    p_init.set_defaults(func=cmd_init)

    # prepare
    p_prep = subparsers.add_parser("prepare", help="前処理パイプライン一括実行")
    p_prep.add_argument("semester", help="学期ID (例: 2026S)")
    p_prep.set_defaults(func=cmd_prepare)

    # optimize
    p_opt = subparsers.add_parser("optimize", help="最適化（対話モード）")
    p_opt.add_argument("semester", help="学期ID (例: 2026S)")
    p_opt.set_defaults(func=cmd_optimize)

    # export
    p_exp = subparsers.add_parser("export", help="カレンダー出力")
    p_exp.add_argument("semester", help="学期ID (例: 2026S)")
    p_exp.add_argument("--courses", nargs='+', help="科目番号リスト")
    p_exp.add_argument("--output", help="出力ファイル名")
    p_exp.add_argument("--start-date", help="開始日 (YYYY-MM-DD)")
    p_exp.add_argument("--end-date", help="終了日 (YYYY-MM-DD)")
    p_exp.set_defaults(func=cmd_export)

    # list
    p_list = subparsers.add_parser("list", help="学期一覧の表示")
    p_list.set_defaults(func=cmd_list)

    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(0)

    args.func(args)


if __name__ == "__main__":
    main()
