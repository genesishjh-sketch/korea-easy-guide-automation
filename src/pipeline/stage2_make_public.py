from __future__ import annotations

import argparse
import json
from pathlib import Path

from src.config import load_settings
from src.publishing.blogger import BloggerCredentialsError, BloggerPublisher


def run(post_id: str, result_path: Path | None = None) -> dict:
    settings = load_settings()
    publisher = BloggerPublisher(settings)
    result = publisher.publish_post(post_id)

    payload = {
        "draft": False,
        "blogger": {
            "id": result.get("id"),
            "url": result.get("url"),
            "selfLink": result.get("selfLink"),
            "status": result.get("status"),
            "published": result.get("published"),
            "updated": result.get("updated"),
        },
    }

    if result_path:
        result_path.parent.mkdir(parents=True, exist_ok=True)
        result_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    return payload


def main() -> None:
    parser = argparse.ArgumentParser(description="Stage 2: make an existing Blogger draft public.")
    parser.add_argument("--post-id", required=True, help="Blogger post ID to publish.")
    parser.add_argument("--result-path", help="Optional JSON path to save the publish result.")
    args = parser.parse_args()

    result_path = Path(args.result_path).expanduser().resolve() if args.result_path else None
    try:
        payload = run(args.post_id, result_path)
    except BloggerCredentialsError as exc:
        raise SystemExit(f"Blogger credential setup required: {exc}") from exc

    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
