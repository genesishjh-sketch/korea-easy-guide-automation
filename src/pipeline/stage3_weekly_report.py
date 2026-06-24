from __future__ import annotations

import argparse

from src.config import load_settings
from src.notifications.telegram import NotificationClient
from src.reporting.weekly import WeeklyReporter


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate a weekly automation report.")
    parser.parse_args()
    settings = load_settings()
    path = WeeklyReporter(settings).generate()
    NotificationClient(settings).send(path.read_text(encoding="utf-8"))
    print(path)


if __name__ == "__main__":
    main()
