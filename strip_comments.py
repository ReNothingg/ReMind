import tokenize
from pathlib import Path
from io import BytesIO
import shutil

ROOT = Path.cwd()          # где запустил — оттуда чистим всё
BACKUP = ROOT / "_backup"  # общий бэкап


def strip_comments(code: str) -> str:
    result = []
    tokens = tokenize.tokenize(BytesIO(code.encode()).readline)

    for tok in tokens:
        if tok.type == tokenize.COMMENT:
            continue
        if tok.type == tokenize.STRING and tok.start[1] == 0:
            continue

        result.append(tok.string)

    return "".join(result)


def main():
    if not BACKUP.exists():
        shutil.copytree(ROOT, BACKUP, dirs_exist_ok=True)

    for path in ROOT.rglob("*.py"):
        if BACKUP in path.parents:
            continue

        text = path.read_text(encoding="utf-8")
        cleaned = strip_comments(text)
        path.write_text(cleaned, encoding="utf-8")

        print("cleaned:", path)

    print("\nГотово. Бэкап лежит в:", BACKUP)


if __name__ == "__main__":
    main()
