"""Count task arguments using only the Python standard library."""

import argparse
import sys


def nonempty_task(value: str) -> str:
    if not value.strip():
        raise argparse.ArgumentTypeError("task must not be empty or whitespace")
    return value


def main() -> None:
    parser = argparse.ArgumentParser(description="Count the provided tasks.")
    parser.add_argument("tasks", type=nonempty_task, nargs="+", help="One or more task descriptions")
    args = parser.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    print(f"待辦事項數量：{len(args.tasks)}")


if __name__ == "__main__":
    main()
