from __future__ import annotations

import argparse
import json
from pathlib import Path
import traceback

from src.config import ROOT_DIR
from src.config import load_settings
from src.notifications.telegram import NotificationClient
from src.pipeline.stage1_generate import run as run_stage1
from src.pipeline.stage2_publish import run as run_stage2


def used_keywords() -> set[str]:
    values = set()
    for path in (ROOT_DIR / "data" / "generated").glob("*/*/metadata.json"):
        try:
            metadata = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        candidate = metadata.get("candidate", {})
        keyword = candidate.get("keyword")
        if keyword:
            values.add(keyword.lower())
    return values


def choose_seed(explicit_seed: str | None = None) -> str:
    if explicit_seed:
        return explicit_seed
    seeds = json.loads((ROOT_DIR / "data" / "seeds" / "topic_seeds.json").read_text(encoding="utf-8"))
    used = used_keywords()
    for seed in seeds:
        if seed.lower() not in used:
            return seed
    return seeds[0]


def run(seed: str | None = None) -> dict[str, str]:
    selected_seed = choose_seed(seed)
    try:
        article_dir = run_stage1(selected_seed)
        result_path = run_stage2(article_dir=article_dir, mode="draft")
        result = {
            "seed": selected_seed,
            "article_dir": str(article_dir),
            "publish_result": str(result_path),
        }
        notify_daily_completion(result)
        return result
    except Exception as exc:
        notify_daily_failure(selected_seed, exc)
        raise


def notify_daily_completion(result: dict[str, str]) -> None:
    settings = load_settings()
    NotificationClient(settings).send(build_daily_success_message(result))


def notify_daily_failure(seed: str, exc: Exception) -> None:
    settings = load_settings()
    error = "".join(traceback.format_exception_only(type(exc), exc)).strip()
    NotificationClient(settings).send(
        "\n".join(
            [
                "[Posting Bot] 일일 포스팅 실패",
                "",
                f"- 블로그: {settings.site_name}",
                f"- 사이트: {settings.site_url}",
                f"- 주제 시드: {seed}",
                f"- 오류: {error}",
                "",
                "조치 필요:",
                "- 품질검수 실패면 글/이미지/출처를 보강해야 합니다.",
                "- Blogger 인증 실패면 OAuth 토큰을 갱신해야 합니다.",
                "- 이미지 누락이면 Codex 이미지 생성 후 다시 실행해야 합니다.",
            ]
        )
    )


def build_daily_success_message(result: dict[str, str]) -> str:
    settings = load_settings()
    article_dir = Path(result["article_dir"])
    metadata = read_json(article_dir / "metadata.json")
    publish_result = read_json(Path(result["publish_result"]))
    quality_report = read_json(article_dir / "quality_report.json")

    article = metadata.get("article", {})
    blogger = publish_result.get("blogger", {})
    draft = publish_result.get("draft", True)
    quality_score = quality_report.get("score", "n/a")
    quality_passed = quality_report.get("passed", False)
    issues = quality_report.get("issues", [])
    status = "초안 업로드 완료" if draft else "공개 발행 완료"
    blogger_status = blogger.get("status") or "unknown"
    blogger_url = blogger.get("url") or "URL 없음"

    lines = [
        "[Posting Bot] 매일 아침 포스팅 결과 보고",
        "",
        f"- 블로그: {settings.site_name}",
        f"- 사이트: {settings.site_url}",
        f"- 상태: {status}",
        f"- Blogger 상태: {blogger_status}",
        f"- 제목: {article.get('title', '제목 없음')}",
        f"- 카테고리: {article.get('category', '미분류')}",
        f"- 주제 시드: {result['seed']}",
        f"- 품질점수: {quality_score}/100",
        f"- 품질통과: {'예' if quality_passed else '아니오'}",
        f"- URL: {blogger_url}",
        f"- 생성 폴더: {result['article_dir']}",
    ]

    if issues:
        lines.extend(["", "품질 이슈:"])
        for issue in issues[:5]:
            lines.append(f"- {issue.get('code')}: {issue.get('message')}")

    lines.extend(
        [
            "",
            "다음 확인:",
            "- 공개 발행 전이면 이미지/링크/본문 품질을 최종 확인하세요.",
            "- 공개 발행 후에는 Search Console 색인 요청과 Analytics 수집 여부를 확인하세요.",
        ]
    )
    return "\n".join(lines)


def read_json(path: Path) -> dict:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> None:
    parser = argparse.ArgumentParser(description="Daily pipeline: collect, generate, and upload a Blogger draft.")
    parser.add_argument("--seed", help="Optional explicit topic seed")
    args = parser.parse_args()
    result = run(args.seed)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
