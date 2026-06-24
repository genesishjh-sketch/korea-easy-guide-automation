from __future__ import annotations

import argparse
from datetime import date
from datetime import datetime
import json
from pathlib import Path
import traceback

from src.config import ROOT_DIR
from src.config import load_settings
from src.notifications.telegram import NotificationClient
from src.pipeline.stage1_generate import run as run_stage1
from src.pipeline.stage2_publish import run as run_stage2
from src.quality.hades import HadesQualityGate


def used_keywords(site: str | None = None) -> set[str]:
    settings = load_settings(site)
    values = set()
    for path in Path(settings.generated_output_dir).glob("*/*/metadata.json"):
        try:
            metadata = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        candidate = metadata.get("candidate", {})
        keyword = candidate.get("keyword")
        if keyword:
            values.add(keyword.lower())
    return values


def choose_seed(explicit_seed: str | None = None, site: str | None = None) -> str:
    settings = load_settings(site)
    if explicit_seed:
        return explicit_seed
    seed_path = Path(settings.seed_file)
    if not seed_path.is_absolute():
        seed_path = ROOT_DIR / seed_path
    seeds = json.loads(seed_path.read_text(encoding="utf-8"))
    if settings.app_env.lower() == "production":
        return choose_seed_for_date(seeds, settings.automation_start_date, date.today())
    used = used_keywords(site)
    for seed in seeds:
        if seed.lower() not in used:
            return seed
    return seeds[0]


def choose_seed_for_date(seeds: list[str], start_date: str, today: date) -> str:
    if not seeds:
        raise ValueError("Seed file must contain at least one topic seed.")
    try:
        start = datetime.strptime(start_date, "%Y-%m-%d").date()
    except ValueError:
        start = today
    index = max(0, (today - start).days) % len(seeds)
    return seeds[index]


def run(seed: str | None = None, site: str | None = None, publish_mode: str = "draft") -> dict[str, str]:
    selected_seed = choose_seed(seed, site)
    try:
        article_dir = run_stage1(selected_seed, site)
        if publish_mode == "validate":
            result_path = run_validation(article_dir, site)
        else:
            result_path = run_stage2(article_dir=article_dir, mode=publish_mode, site=site)
        result = {
            "seed": selected_seed,
            "article_dir": str(article_dir),
            "publish_result": str(result_path),
            "site": load_settings(site).site_key,
            "mode": publish_mode,
        }
        notify_daily_completion(result)
        return result
    except Exception as exc:
        notify_daily_failure(selected_seed, exc, site)
        raise


def run_validation(article_dir: Path, site: str | None = None) -> Path:
    settings = load_settings(site)
    report = HadesQualityGate(settings.content_domain).review_article_dir(article_dir)
    report_path = article_dir / "quality_report.json"
    report_path.write_text(json.dumps(report.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
    result_path = article_dir / "validation_result.json"
    result_path.write_text(
        json.dumps(
            {
                "mode": "validate",
                "published": False,
                "passed": report.passed,
                "score": report.score,
                "min_score": report.min_score,
                "issues": [issue.__dict__ for issue in report.issues],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    if not report.passed:
        issues = "; ".join(f"{issue.code}: {issue.message}" for issue in report.issues)
        raise ValueError(f"Hades validation failed with score {report.score}/{report.min_score}: {issues}")
    return result_path


def notify_daily_completion(result: dict[str, str]) -> None:
    settings = load_settings(result.get("site"))
    NotificationClient(settings).send(build_daily_success_message(result))


def notify_daily_failure(seed: str, exc: Exception, site: str | None = None) -> None:
    settings = load_settings(site)
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
    settings = load_settings(result.get("site"))
    article_dir = Path(result["article_dir"])
    metadata = read_json(article_dir / "metadata.json")
    publish_result = read_json(Path(result["publish_result"]))
    quality_report = read_json(article_dir / "quality_report.json")
    mode = result.get("mode", "draft")

    article = metadata.get("article", {})
    blogger = publish_result.get("blogger", {})
    draft = publish_result.get("draft", True)
    quality_score = quality_report.get("score", "n/a")
    quality_passed = quality_report.get("passed", False)
    issues = quality_report.get("issues", [])
    if mode == "validate":
        status = "검증 완료"
    else:
        status = "초안 업로드 완료" if draft else "공개 발행 완료"
    blogger_status = blogger.get("status") or "unknown"
    blogger_url = blogger.get("url") or "발행 없음"

    lines = [
        "[Posting Bot] 매일 아침 포스팅 결과 보고",
        "",
        f"- 블로그: {settings.site_name}",
        f"- 사이트: {settings.site_url}",
        f"- 실행모드: {mode}",
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
            "- 검증 모드면 Blogger에는 글이 생성되지 않습니다.",
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
    parser.add_argument("--site", help="Site profile key, for example: easy_pc_fix_guide")
    parser.add_argument("--mode", choices=["validate", "draft", "publish"], default="draft")
    args = parser.parse_args()
    result = run(args.seed, args.site, args.mode)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
