from __future__ import annotations

import argparse

from src.config import load_settings
from src.reporting.weekly import WeeklyReporter


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate a weekly automation report.")
    parser.parse_args()
    settings = load_settings()
    path = WeeklyReporter(settings).generate()
    print(path)


if __name__ == "__main__":
    main()
