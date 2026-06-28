#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

from app_factory import create_app
from utils.feedback import export_feedback_dataset


def main() -> int:
    parser = argparse.ArgumentParser(description="Export AI response feedback as JSONL.")
    parser.add_argument("output", help="Destination JSONL file path.")
    args = parser.parse_args()

    output_path = Path(args.output).expanduser().resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)

    app = create_app()
    with app.app_context():
        row_count = export_feedback_dataset(str(output_path))

    print(f"Exported {row_count} feedback rows to {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
