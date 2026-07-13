from __future__ import annotations

import argparse
import json

from src.reporting.adsense_readiness import run


def main() -> None:
    parser = argparse.ArgumentParser(description="Check Blogger AdSense approval readiness.")
    parser.add_argument("--site", help="Site profile key.")
    parser.add_argument("--notify", action="store_true", help="Send Telegram only when attention is needed.")
    args = parser.parse_args()
    result = run(args.site, notify=args.notify)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
