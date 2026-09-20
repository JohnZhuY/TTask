from pathlib import Path

from .qt_gui import run


def main() -> int:
    data_dir = Path.home() / ".ttask"
    data_dir.mkdir(parents=True, exist_ok=True)
    return run(data_dir / "ttask.db")


if __name__ == "__main__":
    raise SystemExit(main())
