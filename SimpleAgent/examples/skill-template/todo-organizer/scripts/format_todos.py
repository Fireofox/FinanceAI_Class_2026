"""Format task arguments as a Markdown checklist using only the standard library."""

import argparse
import sys


def nonempty_text(value: str) -> str:
    """Keep each task or title on a single line."""
    text = " ".join(value.split())
    if not text:
        raise argparse.ArgumentTypeError("must not be empty or whitespace")
    return text


def main() -> None:
    parser = argparse.ArgumentParser(description="Format tasks as a Markdown checklist.")
    parser.add_argument("--title", type=nonempty_text, default="待辦事項", help="Checklist title")
    parser.add_argument("tasks", type=nonempty_text, nargs="+", help="One or more task descriptions")
    args = parser.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    print(f"# {args.title}\n")
    for task in args.tasks:
        print(f"- [ ] {task}")


if __name__ == "__main__":
    main()
