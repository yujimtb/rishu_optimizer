import argparse
import csv
import sys
from pathlib import Path


def split_lines(cell: str) -> list[str]:
    """Split a CSV cell that may contain embedded newlines; drop empty lines."""
    return [line.strip() for line in cell.splitlines() if line.strip()]


def parse_title_block(cell: str) -> tuple[str, str, str, str]:
    """
    Column 5 holds multiple lines:
      1st: title (EN)
      2nd: title (JA) if present
      3rd+: schedule lines and optionally classroom lines
    A line can contain period/day tokens (e.g., '3/M') and room tokens (e.g., 'H-101').
    """
    lines = split_lines(cell)
    title_en = lines[0] if lines else ""
    title_ja = lines[1] if len(lines) > 1 else ""

    schedule_parts: list[str] = []
    classroom_parts: list[str] = []

    for line in lines[2:]:
        tokens = [tok.strip() for tok in line.split(",") if tok.strip()]
        period_tokens = [tok for tok in tokens if "/" in tok]
        room_tokens = [tok for tok in tokens if "/" not in tok]
        if period_tokens:
            schedule_parts.append(",".join(period_tokens))
        if room_tokens:
            classroom_parts.append(",".join(room_tokens))

    schedule = " ; ".join(schedule_parts)
    classroom = " ; ".join(classroom_parts)
    return title_en, title_ja, schedule, classroom


def parse_mode(cell: str) -> tuple[str, str]:
    """
    Column 6 header is 'Enrollment limit\\nMode of instruction'.
    We keep only mode; enrollment is ignored.
    """
    lines = split_lines(cell)
    if not lines:
        return "", ""
    if len(lines) == 1:
        return "", lines[0]
    return lines[0], lines[-1]


def parse_credits_links(cell: str) -> tuple[str, str]:
    """
    Column 8 header is 'Credits\\nLinks ...'.
    First non-empty line is credits; the rest are links concatenated.
    """
    lines = split_lines(cell)
    if not lines:
        return "", ""
    credits = lines[0]
    links = " | ".join(lines[1:]) if len(lines) > 1 else ""
    return credits, links


def normalize(input_path: Path, output_path: Path) -> list[str]:
    """正規化CSVを生成し、警告メッセージのリストを返す。"""
    warnings: list[str] = []
    seen_nos: set[str] = set()

    with input_path.open(encoding="utf-8-sig", newline="") as f_in, output_path.open(
        "w", encoding="utf-8", newline=""
    ) as f_out:
        reader = csv.reader(f_in)
        writer = csv.writer(f_out)

        writer.writerow(
            [
                "CourseNo",
                "Language",
                "TitleEN",
                "TitleJA",
                "Schedule",
                "Classroom",
                "Mode",
                "Instructor",
                "Credits",
                "Links",
            ]
        )

        for row in reader:
            # Skip empty rows
            if not any(row):
                continue
            # Expect at least 8 columns per original format
            if len(row) < 8:
                continue

            course_no = row[1].strip()
            if not course_no or course_no.lower() == "course no.":
                continue
            language = row[2].strip()
            title_en, title_ja, schedule, classroom = parse_title_block(row[4])
            _, mode = parse_mode(row[5])
            instructor = row[6].strip()
            credits, links = parse_credits_links(row[7])

            # バリデーション
            if course_no in seen_nos:
                warnings.append(f"重複CourseNo: {course_no}")
            seen_nos.add(course_no)

            try:
                credits_int = int(credits)
                if credits_int < 0:
                    warnings.append(f"負のCredits: {course_no} ({credits})")
            except ValueError:
                if credits:
                    warnings.append(f"不正なCredits値: {course_no} ({credits})")

            if not schedule:
                warnings.append(f"Scheduleが空: {course_no}")

            writer.writerow(
                [
                    course_no,
                    language,
                    title_en,
                    title_ja,
                    schedule,
                    classroom,
                    mode,
                    instructor,
                    credits,
                    links,
                ]
            )

    return warnings


def main() -> None:
    parser = argparse.ArgumentParser(description="Normalize course CSV.")
    parser.add_argument(
        "--semester",
        help="Semester ID (e.g. 2026S). Resolves paths automatically.",
    )
    parser.add_argument(
        "--input",
        help="path to original CSV (overrides --semester)",
    )
    parser.add_argument(
        "--output",
        help="path to write normalized CSV (overrides --semester)",
    )
    args = parser.parse_args()

    if args.semester:
        from semester import SemesterContext
        ctx = SemesterContext(args.semester)
        input_path = Path(args.input) if args.input else ctx.raw_csv_path
        output_path = Path(args.output) if args.output else ctx.normalized_csv_path
    elif args.input:
        input_path = Path(args.input)
        output_path = Path(args.output) if args.output else input_path.with_name(
            input_path.stem.split(" ")[0] + "_normalized.csv"
        )
    else:
        print("エラー: --semester または --input を指定してください。", file=sys.stderr)
        sys.exit(1)

    if not input_path.exists():
        print(f"エラー: 入力ファイルが見つかりません: {input_path}", file=sys.stderr)
        sys.exit(1)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    warnings = normalize(input_path, output_path)

    if warnings:
        print(f"\n⚠ {len(warnings)} 件の警告:")
        for w in warnings:
            print(f"  - {w}")

    print(f"\n正規化完了: {output_path}")


if __name__ == "__main__":
    main()
