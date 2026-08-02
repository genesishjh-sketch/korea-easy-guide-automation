from __future__ import annotations

import argparse
from collections import Counter
from types import SimpleNamespace
import json
import logging
from pathlib import Path
from typing import Any, Mapping

from src.collectors.google import GoogleSuggestSeedEnricher
from src.collectors.reddit import RedditSeedEnricher
from src.config import ROOT_DIR, load_settings
from src.content.generator import EnglishArticleGenerator
from src.content.topic_scoring import build_candidate
from src.content.windows_generator import WindowsArticleGenerator
from src.images.ai_library import install_korea_ai_assets
from src.images.ai_library import install_windows_ai_assets
from src.images.ai_plan import build_article_image_plan
from src.images.local_svg import create_korea_svg_assets
from src.storage.article_store import ArticleStore


logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
LOGGER = logging.getLogger("stage1")

# Backwards-compatible patch/import points for existing callers and tests.
RedditCollector = RedditSeedEnricher
GoogleSuggestCollector = GoogleSuggestSeedEnricher

EVIDENCE_OBSERVED_QUESTION = "OBSERVED_QUESTION"
EVIDENCE_FIRST_PARTY_QUERY = "FIRST_PARTY_QUERY"
EVIDENCE_QUERY_PLAN = "QUERY_PLAN"
EVIDENCE_FALLBACK_TEMPLATE = "FALLBACK_TEMPLATE"
EVIDENCE_SEARCH_SUGGESTION = "SEARCH_SUGGESTION"
EVIDENCE_TYPES = {
    EVIDENCE_OBSERVED_QUESTION,
    EVIDENCE_FIRST_PARTY_QUERY,
    EVIDENCE_SEARCH_SUGGESTION,
    EVIDENCE_QUERY_PLAN,
    EVIDENCE_FALLBACK_TEMPLATE,
}
ELIGIBLE_EVIDENCE_TYPES = {
    EVIDENCE_OBSERVED_QUESTION,
    EVIDENCE_FIRST_PARTY_QUERY,
}
RESEARCH_REPORT_SCHEMA_VERSION = 2
NUMERIC_RESEARCH_FIELDS = (
    "live_reddit_signal_count",
    "reddit_oauth_signal_count",
    "reddit_public_json_signal_count",
    "reddit_google_site_search_signal_count",
    "fallback_reddit_signal_count",
    "google_suggest_signal_count",
    "google_suggest_live_signal_count",
    "google_suggest_fallback_signal_count",
    "observed_evidence_count",
    "observed_question_count",
    "first_party_query_count",
    "verified_public_page_signal_count",
    "query_plan_count",
    "fallback_evidence_count",
    "search_suggestion_count",
    "demand_eligible_signal_count",
    "stability_eligible_signal_count",
    "ready_eligible_signal_count",
    "cadence_eligible_signal_count",
)
NUMERIC_RESEARCH_MAP_FIELDS = (
    "signal_source_counts",
    "reddit_collection_method_counts",
    "google_suggest_method_counts",
    "evidence_type_counts",
)
TOPIC_CONTEXT_FIELDS = (
    "topic_id",
    "cluster_id",
    "category_id",
    "action",
    "topic_action",
    "revision",
    "topic_revision",
    "claim_run_id",
    "editor_brief",
    "reader_questions",
    "difference_from_existing",
    "existing_post_refs",
)


def load_seed(default_seed: str | None, settings) -> str:
    if default_seed:
        return default_seed
    seeds_path = Path(settings.seed_file)
    if not seeds_path.is_absolute():
        seeds_path = ROOT_DIR / seeds_path
    seeds = json.loads(seeds_path.read_text(encoding="utf-8"))
    return seeds[0]


def run(
    seed: str | None = None,
    site: str | None = None,
    topic_context: Mapping[str, Any] | None = None,
) -> Path:
    settings = load_settings(site)
    keyword = load_seed(seed, settings)
    LOGGER.info("Collecting signals for keyword: %s", keyword)
    reddit = RedditSeedEnricher(
        settings.reddit_user_agent,
        client_id=settings.reddit_client_id,
        client_secret=settings.reddit_client_secret,
        subreddits=settings.reddit_subreddits,
    )
    google = GoogleSuggestSeedEnricher()
    reddit_signals = reddit.collect(keyword, limit=6)
    google_signals = google.collect(keyword, limit=8)
    signals = reddit_signals + google_signals

    demand_signals = [signal for signal in signals if is_eligible_evidence(signal)]
    candidate = build_candidate(keyword, demand_signals, settings.content_domain)
    candidate.signals = signals
    apply_topic_context(candidate, topic_context)
    LOGGER.info("Selected topic category=%s score=%s", candidate.category, candidate.score)

    generator = WindowsArticleGenerator(settings) if settings.content_domain == "windows_help" else EnglishArticleGenerator(settings)
    provisional_plan = build_article_image_plan(candidate, f"{keyword} guide")
    provisional_article = generator.generate(
        candidate,
        provisional_plan.hero_asset(),
        provisional_plan.inline_assets(),
    )
    image_plan = build_article_image_plan(candidate, provisional_article.title)
    article = generator.generate(candidate, image_plan.hero_asset(), image_plan.inline_assets())

    store = ArticleStore(Path(settings.generated_output_dir))
    output_dir = store.save(article, candidate)
    (output_dir / "image_plan.json").write_text(
        json.dumps(image_plan.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    if settings.content_domain == "windows_help":
        install_windows_ai_assets(output_dir, article.title, keyword)
    elif settings.content_domain == "korea_travel":
        install_korea_ai_assets(output_dir, article.title, keyword)
    elif image_plan.images[0].filename.endswith(".svg"):
        create_korea_svg_assets(output_dir, article.title, keyword)
    article = apply_high_quality_korea_post_if_available(output_dir, article, settings.content_domain)
    research_report = build_research_report(
        settings,
        keyword,
        article,
        signals,
        reddit.diagnostics,
        google.diagnostics,
        candidate=candidate,
    )
    (output_dir / "research_report.json").write_text(
        json.dumps(research_report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    LOGGER.info("Saved article to %s", output_dir)
    return output_dir


def apply_high_quality_korea_post_if_available(output_dir: Path, article, content_domain: str):
    if content_domain == "windows_help":
        return article
    from src.pipeline.stage2_apply_high_quality_posts import run as apply_high_quality_posts

    if not apply_high_quality_posts(output_dir):
        return article
    metadata = json.loads((output_dir / "metadata.json").read_text(encoding="utf-8"))
    return SimpleNamespace(**metadata["article"])


def apply_topic_context(candidate, topic_context: Mapping[str, Any] | None) -> None:
    if not topic_context:
        return
    for field_name in TOPIC_CONTEXT_FIELDS:
        if field_name in {"action", "topic_action", "revision", "topic_revision"}:
            continue
        if field_name not in topic_context or not hasattr(candidate, field_name):
            continue
        value = topic_context[field_name]
        setattr(candidate, field_name, value)
    action = topic_context.get("topic_action", topic_context.get("action"))
    if action is not None:
        candidate.action = str(action)
        candidate.topic_action = str(action)
    revision = topic_context.get("topic_revision", topic_context.get("revision"))
    if revision is not None:
        if isinstance(revision, bool) or not isinstance(revision, int) or revision < 0:
            raise ValueError("topic_context.topic_revision must be a non-negative integer")
        candidate.revision = revision
        candidate.topic_revision = revision
    if "difference" in topic_context and not topic_context.get("difference_from_existing"):
        candidate.difference_from_existing = str(topic_context["difference"])


def signal_evidence_type(signal) -> str:
    explicit = str((signal.metadata or {}).get("evidence_type") or "").strip().upper()
    if explicit:
        if explicit not in EVIDENCE_TYPES:
            raise ValueError(f"unsupported evidence_type: {explicit}")
        if explicit == EVIDENCE_OBSERVED_QUESTION and not is_verified_observed_question(signal):
            raise ValueError(
                "OBSERVED_QUESTION requires OAuth provenance or verified_by_codex=true "
                "with an actual source item id and canonical public page URL"
            )
        return explicit
    method = str((signal.metadata or {}).get("collection_method") or "").strip().casefold()
    if signal.source == "reddit" and method == "oauth":
        return EVIDENCE_OBSERVED_QUESTION
    if signal.source == "reddit":
        return EVIDENCE_QUERY_PLAN
    if signal.source == "reddit_search":
        return EVIDENCE_QUERY_PLAN
    if signal.source == "reddit_fallback":
        return EVIDENCE_FALLBACK_TEMPLATE
    if signal.source == "google_suggest":
        return (
            EVIDENCE_SEARCH_SUGGESTION
            if method == "live"
            else EVIDENCE_FALLBACK_TEMPLATE
        )
    if signal.source == "search_console":
        return EVIDENCE_FIRST_PARTY_QUERY
    raise ValueError(f"signal source requires an explicit evidence_type: {signal.source}")


def evidence_weight(evidence_type: str) -> float:
    return 1.0 if evidence_type in ELIGIBLE_EVIDENCE_TYPES else 0.0


def is_eligible_evidence(signal) -> bool:
    return signal_evidence_type(signal) in ELIGIBLE_EVIDENCE_TYPES


def is_verified_observed_question(signal) -> bool:
    metadata = signal.metadata or {}
    method = str(metadata.get("collection_method") or "").strip().casefold()
    if signal.source == "reddit" and method == "oauth":
        return True
    item_id = str(
        metadata.get("source_item_id")
        or metadata.get("reddit_item_id")
        or metadata.get("external_id")
        or ""
    ).strip()
    canonical_url = str(metadata.get("canonical_public_page_url") or signal.url or "").strip()
    return bool(metadata.get("verified_by_codex") is True and item_id and canonical_url)


def signal_evidence_rows(signals: list) -> list[dict]:
    rows = []
    for signal in signals:
        evidence_type = signal_evidence_type(signal)
        weight = evidence_weight(evidence_type)
        rows.append(
            {
                "source": str(signal.source),
                "title": str(signal.title),
                "url": str(signal.url or ""),
                "collection_method": str((signal.metadata or {}).get("collection_method") or "unknown"),
                "evidence_type": evidence_type,
                "collector_role": str((signal.metadata or {}).get("collector_role") or "seed_enricher"),
                "query_expansion_only": evidence_type in {
                    EVIDENCE_QUERY_PLAN,
                    EVIDENCE_FALLBACK_TEMPLATE,
                    EVIDENCE_SEARCH_SUGGESTION,
                },
                "source_item_id": str(
                    (signal.metadata or {}).get("source_item_id")
                    or (signal.metadata or {}).get("reddit_item_id")
                    or ""
                ),
                "canonical_public_page_url": str(
                    (signal.metadata or {}).get("canonical_public_page_url")
                    or signal.url
                    or ""
                ),
                "verified_by_codex": bool((signal.metadata or {}).get("verified_by_codex")),
                "signal_score": float(signal.score),
                "demand_weight": weight,
                "stability_weight": weight,
                "ready_weight": weight,
                "cadence_weight": weight,
            }
        )
    return rows


def build_research_report(
    settings,
    keyword: str,
    article,
    signals: list,
    reddit_diagnostics: dict | None = None,
    google_diagnostics: dict | None = None,
    candidate=None,
) -> dict:
    signal_queries = [signal.title for signal in signals[:4] if signal.title]
    evidence_rows = signal_evidence_rows(signals)
    evidence_aggregates = derive_research_evidence_aggregates(evidence_rows)
    queries = [keyword, f"{keyword} official", f"{keyword} beginner fix", *signal_queries]
    if settings.content_domain == "windows_help":
        queries.extend(
            [
                f"{keyword} Microsoft Support",
                f"{keyword} Microsoft Learn",
                f"{keyword} Windows release health",
            ]
        )
    sources = [
        {
            "name": source.get("name", ""),
            "url": source.get("url", ""),
            "type": "official_or_platform",
        }
        for source in article.sources
    ]
    context_reader_questions = list(getattr(candidate, "reader_questions", []) or [])
    if context_reader_questions:
        reader_questions = context_reader_questions
    elif settings.content_domain == "windows_help":
        reader_questions = [
            f"What does {keyword} mean?",
            f"How do I fix {keyword} safely?",
            f"Should beginners try advanced fixes for {keyword}?",
            f"Can {keyword} cause data loss?",
            f"When should I get help for {keyword}?",
        ]
    else:
        reader_questions = [
            f"What is the easiest way to handle {keyword} in Korea?",
            f"What should foreign visitors prepare before using {keyword}?",
            f"What official links should I check for {keyword}?",
            f"What can go wrong with {keyword} during a Korea trip?",
            f"What backup option should I keep for {keyword}?",
        ]

    topic_context = {
        field_name: getattr(candidate, field_name)
        for field_name in TOPIC_CONTEXT_FIELDS
        if candidate is not None and hasattr(candidate, field_name)
    }
    report = {
        "schema_version": RESEARCH_REPORT_SCHEMA_VERSION,
        "collector_role": "seed_enricher",
        "site": settings.site_key,
        "content_domain": settings.content_domain,
        "seed_keyword": keyword,
        "topic": article.title,
        "queries": list(dict.fromkeys(queries))[:10],
        "sources": sources,
        "reader_questions": reader_questions,
        "topic_context": topic_context,
        "signal_evidence": evidence_rows,
        **evidence_aggregates,
        "reddit_collection_diagnostics": reddit_diagnostics or {},
        "google_suggest_diagnostics": google_diagnostics or {},
        "evidence_policy": {
            EVIDENCE_OBSERVED_QUESTION: "OAuth question or Codex-verified canonical public question; eligible for demand, stability, READY, and cadence evidence.",
            EVIDENCE_FIRST_PARTY_QUERY: "First-party Search Console query evidence; eligible for demand, stability, READY, and cadence evidence.",
            EVIDENCE_QUERY_PLAN: "Synthetic search plan only; all evidence weights are zero.",
            EVIDENCE_FALLBACK_TEMPLATE: "Local fallback template only; all evidence weights are zero.",
            EVIDENCE_SEARCH_SUGGESTION: "Live autocomplete phrasing expansion only; all evidence weights are zero.",
        },
        "notes": [
            "The collectors are seed enrichers; they do not discover, approve, or schedule topics.",
            "Only OBSERVED_QUESTION and FIRST_PARTY_QUERY count as demand, stability, READY, or cadence evidence.",
            "Unauthenticated Reddit public_json results remain QUERY_PLAN until a canonical public page is verified by Codex.",
            "QUERY_PLAN, FALLBACK_TEMPLATE, and SEARCH_SUGGESTION records are query expansion only and have zero evidence weight.",
            "Official/platform sources are used for publishing validation.",
        ],
    }
    validate_research_report(report)
    return report


def _integer_count_map(values: Mapping) -> dict[str, int]:
    return {str(key): int(value) for key, value in sorted(values.items())}


def derive_research_evidence_aggregates(
    signal_evidence: list[Mapping[str, Any]],
) -> dict[str, Any]:
    """Derive every evidence aggregate from the auditable row set."""

    source_counts: Counter[str] = Counter()
    reddit_method_counts: Counter[str] = Counter()
    google_method_counts: Counter[str] = Counter()
    evidence_type_counts: Counter[str] = Counter()
    observed_question_count = 0
    observed_reddit_count = 0
    first_party_query_count = 0
    reddit_oauth_count = 0
    reddit_public_json_count = 0
    reddit_google_site_search_count = 0
    fallback_reddit_count = 0
    google_suggest_count = 0
    google_suggest_live_count = 0
    google_suggest_fallback_count = 0
    verified_public_page_count = 0

    for row in signal_evidence:
        source = str(row.get("source") or "")
        method = str(row.get("collection_method") or "").strip().casefold()
        evidence_type = str(row.get("evidence_type") or "").strip().upper()
        source_counts[source] += 1
        evidence_type_counts[evidence_type] += 1

        if source in {"reddit", "reddit_search", "reddit_fallback"}:
            reddit_method_counts[method] += 1
        if source == "google_suggest":
            google_method_counts[method] += 1
            google_suggest_count += 1
            if method == "live":
                google_suggest_live_count += 1
            elif method in {"fallback", "fallback_template"}:
                google_suggest_fallback_count += 1

        if evidence_type == EVIDENCE_OBSERVED_QUESTION:
            observed_question_count += 1
            if source == "reddit":
                observed_reddit_count += 1
                if method == "oauth":
                    reddit_oauth_count += 1
            if method != "oauth" and row.get("verified_by_codex") is True:
                verified_public_page_count += 1
        elif evidence_type == EVIDENCE_FIRST_PARTY_QUERY:
            first_party_query_count += 1

        if source == "reddit" and method == "public_json":
            reddit_public_json_count += 1
        if source == "reddit_search" and method == "google_site_search":
            reddit_google_site_search_count += 1
        if (
            source == "reddit_fallback"
            and evidence_type == EVIDENCE_FALLBACK_TEMPLATE
        ):
            fallback_reddit_count += 1

    eligible_count = observed_question_count + first_party_query_count
    return {
        "live_reddit_signal_count": observed_reddit_count,
        "reddit_oauth_signal_count": reddit_oauth_count,
        "reddit_public_json_signal_count": reddit_public_json_count,
        "reddit_google_site_search_signal_count": reddit_google_site_search_count,
        "fallback_reddit_signal_count": fallback_reddit_count,
        "google_suggest_signal_count": google_suggest_count,
        "google_suggest_live_signal_count": google_suggest_live_count,
        "google_suggest_fallback_signal_count": google_suggest_fallback_count,
        "observed_evidence_count": observed_question_count,
        "observed_question_count": observed_question_count,
        "first_party_query_count": first_party_query_count,
        "verified_public_page_signal_count": verified_public_page_count,
        "query_plan_count": int(
            evidence_type_counts.get(EVIDENCE_QUERY_PLAN, 0)
        ),
        "fallback_evidence_count": int(
            evidence_type_counts.get(EVIDENCE_FALLBACK_TEMPLATE, 0)
        ),
        "search_suggestion_count": int(
            evidence_type_counts.get(EVIDENCE_SEARCH_SUGGESTION, 0)
        ),
        "demand_eligible_signal_count": eligible_count,
        "stability_eligible_signal_count": eligible_count,
        "ready_eligible_signal_count": eligible_count,
        "cadence_eligible_signal_count": eligible_count,
        "signal_source_counts": _integer_count_map(source_counts),
        "reddit_collection_method_counts": _integer_count_map(
            reddit_method_counts
        ),
        "google_suggest_method_counts": _integer_count_map(google_method_counts),
        "evidence_type_counts": _integer_count_map(evidence_type_counts),
    }


def validate_research_report(report: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(report, Mapping):
        raise ValueError("research_report must be an object")
    if report.get("schema_version") != RESEARCH_REPORT_SCHEMA_VERSION:
        raise ValueError(f"research_report.schema_version must be {RESEARCH_REPORT_SCHEMA_VERSION}")
    for field_name in NUMERIC_RESEARCH_FIELDS:
        _validate_non_negative_integer(report.get(field_name), field_name)
    for map_name in NUMERIC_RESEARCH_MAP_FIELDS:
        values = report.get(map_name)
        if not isinstance(values, Mapping):
            raise ValueError(f"research_report.{map_name} must be an object of numeric counts")
        for key, value in values.items():
            _validate_non_negative_integer(value, f"{map_name}.{key}")
    signal_evidence = report.get("signal_evidence")
    if not isinstance(signal_evidence, list):
        raise ValueError("research_report.signal_evidence must be an array")
    for index, row in enumerate(signal_evidence):
        if not isinstance(row, Mapping):
            raise ValueError(f"research_report.signal_evidence[{index}] must be an object")
        score = row.get("signal_score")
        if isinstance(score, bool) or not isinstance(score, (int, float)):
            raise ValueError(f"signal_evidence[{index}].signal_score must be numeric")
        evidence_type = str(row.get("evidence_type") or "")
        if evidence_type not in EVIDENCE_TYPES:
            raise ValueError(
                f"signal_evidence[{index}].evidence_type must be one of {sorted(EVIDENCE_TYPES)}"
            )
        source = str(row.get("source") or "").strip()
        collection_method = str(
            row.get("collection_method") or ""
        ).strip().casefold()
        if evidence_type == EVIDENCE_OBSERVED_QUESTION:
            has_identity = bool(
                row.get("source_item_id")
                and row.get("canonical_public_page_url")
            )
            is_oauth = (
                source == "reddit"
                and collection_method == "oauth"
                and has_identity
            )
            is_verified_page = bool(
                row.get("verified_by_codex") is True
                and has_identity
            )
            if not (is_oauth or is_verified_page):
                raise ValueError(
                    f"signal_evidence[{index}] OBSERVED_QUESTION lacks verified provenance"
                )
        if (
            evidence_type == EVIDENCE_FIRST_PARTY_QUERY
            and source != "search_console"
        ):
            raise ValueError(
                f"signal_evidence[{index}] FIRST_PARTY_QUERY must come from Search Console"
            )
        expected_weight = evidence_weight(str(evidence_type))
        for weight_name in ("demand_weight", "stability_weight", "ready_weight", "cadence_weight"):
            value = row.get(weight_name)
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError(f"signal_evidence[{index}].{weight_name} must be numeric")
            if float(value) != expected_weight:
                raise ValueError(
                    f"signal_evidence[{index}].{weight_name} must be {expected_weight} for {evidence_type}"
                )
    derived = derive_research_evidence_aggregates(signal_evidence)
    for field_name in NUMERIC_RESEARCH_FIELDS:
        if report.get(field_name) != derived[field_name]:
            raise ValueError(
                f"research_report.{field_name} does not match signal_evidence "
                f"(expected {derived[field_name]})"
            )
    for map_name in NUMERIC_RESEARCH_MAP_FIELDS:
        if dict(report.get(map_name) or {}) != derived[map_name]:
            raise ValueError(
                f"research_report.{map_name} does not match signal_evidence"
            )
    return derived


def _validate_non_negative_integer(value: Any, field_name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"research_report.{field_name} must be a non-negative integer")


def main() -> None:
    parser = argparse.ArgumentParser(description="Stage 1: collect signals, generate article, save outputs.")
    parser.add_argument("--seed", help="Topic seed keyword, for example: 'incheon airport to seoul'")
    parser.add_argument("--site", help="Site profile key, for example: easy_pc_fix_guide")
    args = parser.parse_args()
    output_dir = run(args.seed, args.site)
    print(output_dir)


if __name__ == "__main__":
    main()
