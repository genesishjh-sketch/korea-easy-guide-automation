from __future__ import annotations

import argparse
from datetime import datetime
from datetime import timezone
import fcntl
import hashlib
import json
import logging
import mimetypes
import os
from pathlib import Path
import re
import urllib.error
import urllib.request

from bs4 import BeautifulSoup

from src.config import ROOT_DIR, load_settings
from src.publishing.blogger import BloggerCredentialsError, BloggerPublisher
from src.quality.hades import HadesQualityGate
from src.quality.originality import MAX_BODY_SIMILARITY
from src.quality.originality import MAX_REPEATED_TITLE_ENDING
from src.quality.originality import REWRITE_BODY_SIMILARITY
from src.quality.originality import closest_match
from src.quality.originality import generic_title_ending
from src.quality.originality import repeated_title_ending_count


logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
LOGGER = logging.getLogger("stage2")
RAW_IMAGE_BASE_URL = os.getenv(
    "RAW_IMAGE_BASE_URL",
    "https://raw.githubusercontent.com/genesishjh-sketch/korea-easy-guide-automation/main",
)
REUSABLE_IMAGE_PATH_PARTS = (
    "/src/images/ai_assets/korea/",
    "/src/images/ai_assets/windows/",
)
ALLOWED_UNIQUE_IMAGE_PATH_PART = "/src/images/ai_assets/hosted/"
PUBLISH_ATTEMPT_TTL_SECONDS = int(
    os.getenv("TOPIC_PUBLISH_ATTEMPT_TTL_SECONDS", "1800")
)


class PublicationReconciliationRequired(RuntimeError):
    """A Blogger mutation may have happened and must never be retried as an insert."""

    reconciliation_only = True


class PublishAttemptBlocked(PublicationReconciliationRequired):
    pass


class BloggerOutcomeUnknown(PublicationReconciliationRequired):
    pass


class PublishReceiptPersisted(PublicationReconciliationRequired):
    pass


def latest_article_dir(site: str | None = None) -> Path:
    settings = load_settings(site)
    generated_root = Path(settings.generated_output_dir)
    candidates = [
        path
        for path in generated_root.glob("*/*")
        if path.is_dir() and (path / "article.html").exists() and (path / "metadata.json").exists()
    ]
    if not candidates:
        raise FileNotFoundError("No generated article directories found. Run stage1 first.")
    return max(candidates, key=lambda path: path.stat().st_mtime)


def load_article(article_dir: Path, site: str | None = None) -> tuple[str, str, list[str]]:
    metadata = json.loads((article_dir / "metadata.json").read_text(encoding="utf-8"))
    article = metadata["article"]
    title = article["title"]
    labels = article.get("tags", [])
    validate_required_images(article_dir)
    validate_quality(article_dir, site)
    html = (article_dir / "article.html").read_text(encoding="utf-8")
    html = rewrite_local_image_paths(html, article_dir)
    validate_public_image_urls_reachable(html)
    validate_fresh_public_images(html, site)
    return title, html, labels


def validate_quality(article_dir: Path, site: str | None = None) -> None:
    settings = load_settings(site)
    report = HadesQualityGate(settings.content_domain).review_article_dir(article_dir)
    report_path = article_dir / "quality_report.json"
    report_path.write_text(json.dumps(report.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
    if not report.passed:
        issues = "; ".join(f"{issue.code}: {issue.message}" for issue in report.issues)
        raise ValueError(f"Hades quality gate failed with score {report.score}/{report.min_score}: {issues}")


def validate_required_images(article_dir: Path) -> None:
    image_plan_path = article_dir / "image_plan.json"
    if not image_plan_path.exists():
        raise FileNotFoundError("image_plan.json is required before Blogger publishing.")

    image_plan = json.loads(image_plan_path.read_text(encoding="utf-8"))
    if not image_plan.get("strict", False):
        raise ValueError("image_plan.json must set strict=true before Blogger publishing.")

    required_images = [image for image in image_plan.get("images", []) if image.get("required", True)]
    if len(required_images) < 2:
        raise ValueError("At least two required image assets are needed before Blogger publishing.")

    invalid_urls = []
    missing = []
    invalid_extensions = []
    for image in required_images:
        url = image.get("url") or f"assets/{image.get('filename', '')}"
        if not url.startswith("assets/"):
            invalid_urls.append(url)
            continue
        if Path(url).suffix.lower() == ".svg":
            invalid_extensions.append(url)
            continue
        if not (article_dir / url).exists():
            missing.append(url)

    if invalid_urls:
        joined = ", ".join(invalid_urls)
        raise ValueError(f"Required image assets must be local assets/ files: {joined}.")

    if invalid_extensions:
        joined = ", ".join(invalid_extensions)
        raise ValueError(f"Public publishing requires fresh raster JPG/PNG/WebP images, not SVG fallback assets: {joined}.")

    if missing:
        joined = ", ".join(missing)
        raise FileNotFoundError(
            f"Required Codex-generated image assets are missing: {joined}. "
            "Generate the images from image_plan.json and save them before publishing."
        )


def rewrite_local_image_paths(html: str, article_dir: Path) -> str:
    """Replace local image assets with stable raw GitHub URLs so Blogger lists stay lightweight."""
    soup = BeautifulSoup(html, "html.parser")
    for img in soup.find_all("img"):
        src = img.get("src", "")
        if src.startswith("assets/"):
            asset_path = article_dir / src
            if not asset_path.exists():
                img.decompose()
                continue
            mime_type = mimetypes.guess_type(asset_path.name)[0]
            if mime_type not in {"image/png", "image/jpeg", "image/webp"}:
                img.decompose()
                continue
            img["src"] = raw_image_url_for_asset(asset_path)
            img["loading"] = "lazy"
    return str(soup)


def raw_image_url_for_asset(asset_path: Path) -> str:
    library_path = find_matching_ai_asset(asset_path)
    if library_path is None:
        raise FileNotFoundError(
            f"Image asset is not available in src/images/ai_assets for lightweight Blogger publishing: {asset_path}. "
            "Copy the generated image into the image asset library or provide a stable external image URL."
        )
    relative = library_path.relative_to(ROOT_DIR).as_posix()
    validate_library_image_is_publishable(relative)
    return f"{RAW_IMAGE_BASE_URL.rstrip('/')}/{relative}"


def validate_library_image_is_publishable(relative_path: str) -> None:
    normalized = f"/{relative_path}"
    if ALLOWED_UNIQUE_IMAGE_PATH_PART in normalized:
        return
    if any(part in normalized for part in REUSABLE_IMAGE_PATH_PARTS):
        raise ValueError(
            "Reusable image library assets cannot be used for public publishing: "
            f"{relative_path}. Generate fresh article-specific Codex images and store them under src/images/ai_assets/hosted/."
        )


def validate_fresh_public_images(html: str, site: str | None = None) -> None:
    settings = load_settings(site)
    new_urls = set(image_urls_from_html(html))
    if not new_urls:
        raise ValueError("Public publishing requires image URLs after local image rewrite.")
    embedded = sorted(url for url in new_urls if url.startswith("data:image"))
    if embedded:
        raise ValueError(
            "Public publishing must not embed base64 data:image assets. "
            "Use article-specific hosted assets under src/images/ai_assets/hosted/ instead."
        )
    used_urls = public_image_urls(settings.site_url)
    reused = sorted(new_urls & used_urls)
    if reused:
        raise ValueError(
            "Fresh article-specific images are required; these image URLs are already used by published posts: "
            + ", ".join(reused[:5])
        )


def validate_public_image_urls_reachable(html: str) -> None:
    """Fail before publishing if Blogger would receive broken external image URLs."""
    broken: list[str] = []
    for url in image_urls_from_html(html):
        if not url.startswith(("http://", "https://")):
            continue
        try:
            status, content_type = public_image_url_status(url)
        except Exception as exc:
            broken.append(f"{url} ({exc})")
            continue
        if status >= 400:
            broken.append(f"{url} (HTTP {status})")
            continue
        if content_type and not content_type.lower().startswith("image/"):
            broken.append(f"{url} ({content_type})")
    if broken:
        raise ValueError(
            "Public publishing requires reachable image URLs before Blogger upload. "
            "Commit/push hosted image assets or replace the image URLs first: "
            + "; ".join(broken[:5])
        )


def public_image_url_status(url: str) -> tuple[int, str]:
    request = urllib.request.Request(url, method="HEAD", headers={"User-Agent": "korea-blog-automation/1.0"})
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            return response.getcode(), response.headers.get("Content-Type", "")
    except urllib.error.HTTPError as exc:
        if exc.code != 405:
            return exc.code, exc.headers.get("Content-Type", "")
    request = urllib.request.Request(url, headers={"User-Agent": "korea-blog-automation/1.0"})
    with urllib.request.urlopen(request, timeout=15) as response:
        return response.getcode(), response.headers.get("Content-Type", "")


def public_image_urls(site_url: str) -> set[str]:
    payload = public_feed_payload(site_url)

    urls: set[str] = set()
    for entry in payload.get("feed", {}).get("entry", []):
        content = entry.get("content", {}).get("$t", "")
        urls.update(image_urls_from_html(content))
    return urls


def public_feed_payload(site_url: str) -> dict:
    feed_url = f"{site_url.rstrip('/')}/feeds/posts/default?alt=json&max-results=100"
    try:
        with urllib.request.urlopen(feed_url, timeout=20) as response:
            return json.load(response)
    except Exception as exc:
        raise RuntimeError(f"Could not check the published Blogger feed: {exc}") from exc


def public_posts(site_url: str) -> list[dict[str, str]]:
    payload = public_feed_payload(site_url)
    posts = []
    for entry in payload.get("feed", {}).get("entry", []):
        url = next(
            (link.get("href", "") for link in entry.get("link", []) if link.get("rel") == "alternate"),
            "",
        )
        posts.append(
            {
                "title": entry.get("title", {}).get("$t", ""),
                "url": url,
                "content_html": (entry.get("content") or entry.get("summary") or {}).get("$t", ""),
            }
        )
    return posts


def validate_live_originality(
    title: str,
    html: str,
    site: str | None = None,
    *,
    exclude_url: str = "",
) -> None:
    settings = load_settings(site)
    posts = [post for post in public_posts(settings.site_url) if post.get("url", "").rstrip("/") != exclude_url.rstrip("/")]
    match = closest_match(html, posts)
    if match and match.similarity >= MAX_BODY_SIMILARITY:
        raise ValueError(
            "Hades originality gate failed: article body is too similar to an existing post "
            f"({match.similarity:.1%}, {match.title}, {match.url}). Rewrite the topic-specific structure and guidance before publishing."
        )
    if match and match.similarity >= REWRITE_BODY_SIMILARITY:
        raise ValueError(
            "Hades originality rewrite gate failed: article body is approaching an existing post "
            f"({match.similarity:.1%}, {match.title}, {match.url}). Restructure the article around its unique reader decision before publishing."
        )

    ending = generic_title_ending(title)
    repeated = repeated_title_ending_count(title, [str(post.get("title") or "") for post in posts])
    if ending and repeated >= MAX_REPEATED_TITLE_ENDING:
        raise ValueError(
            "Hades title-pattern gate failed: "
            f"the ending '{ending}' already appears in {repeated} published titles. Use a title shaped around this article's actual decision or symptom."
        )


def image_urls_from_html(html: str) -> list[str]:
    soup = BeautifulSoup(html, "html.parser")
    urls = [img.get("src", "").strip() for img in soup.find_all("img") if img.get("src")]
    if urls:
        return urls
    return [match.group(1).strip() for match in re.finditer(r"<img\b[^>]*\bsrc=[\"']([^\"']+)[\"']", html, flags=re.I)]


def find_matching_ai_asset(asset_path: Path) -> Path | None:
    digest = sha256_file(asset_path)
    for candidate in (ROOT_DIR / "src" / "images" / "ai_assets").rglob("*"):
        if candidate.is_file() and candidate.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp", ".svg"}:
            if sha256_file(candidate) == digest:
                return candidate
    return None


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save_publish_result(
    article_dir: Path,
    result: dict,
    draft: bool,
    topic_context: dict | None = None,
    *,
    topic_registry_sync: dict | None = None,
    publish_attempt: dict | None = None,
) -> Path:
    context = topic_context or load_topic_context(article_dir)
    result_path = article_dir / "blogger_publish_result.json"
    result_path.write_text(
        json.dumps(
            {
                "draft": draft,
                "topic_id": context.get("topic_id", ""),
                "cluster_id": context.get("cluster_id", ""),
                "category_id": context.get("category_id", ""),
                "action": context.get("action", "NEW_POST"),
                "topic_action": context.get("topic_action", context.get("action", "NEW_POST")),
                "revision": context.get("revision", 0),
                "topic_revision": context.get("topic_revision", context.get("revision", 0)),
                "claim_run_id": context.get("claim_run_id", ""),
                "publish_attempt_id": (
                    (publish_attempt or {}).get("attempt_id")
                    or context.get("publish_attempt_id", "")
                ),
                "topic_registry_sync": topic_registry_sync or {"status": "not_applicable"},
                "blogger": {
                    "id": result.get("id"),
                    "url": result.get("url"),
                    "selfLink": result.get("selfLink"),
                    "status": result.get("status"),
                    "published": result.get("published"),
                    "updated": result.get("updated"),
                },
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return result_path


def load_topic_context(article_dir: Path) -> dict:
    try:
        metadata = json.loads((article_dir / "metadata.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    candidate = metadata.get("candidate") or {}
    return {
        "topic_id": str(candidate.get("topic_id") or ""),
        "cluster_id": str(candidate.get("cluster_id") or ""),
        "category_id": str(candidate.get("category_id") or ""),
        "action": str(candidate.get("action") or candidate.get("topic_action") or "NEW_POST").upper(),
        "topic_action": str(candidate.get("topic_action") or candidate.get("action") or "NEW_POST").upper(),
        "revision": candidate.get("revision") or candidate.get("topic_revision") or 0,
        "topic_revision": candidate.get("topic_revision") or candidate.get("revision") or 0,
        "claim_run_id": str(candidate.get("claim_run_id") or ""),
    }


def parse_topic_revision(topic_context: dict) -> int:
    raw = (
        topic_context.get("revision")
        if topic_context.get("revision") is not None
        else topic_context.get("topic_revision")
    )
    if isinstance(raw, bool):
        raise ValueError("Topic revision must be a positive integer; booleans are invalid.")
    if isinstance(raw, int):
        revision = raw
    elif isinstance(raw, str) and raw.strip().isdigit():
        revision = int(raw.strip())
    else:
        raise ValueError("Topic revision must be a positive integer before publishing.")
    if revision <= 0:
        raise ValueError("Topic revision must be greater than zero before publishing.")
    return revision


def ensure_topic_id_marker(html: str, topic_id: str) -> str:
    selected_topic_id = str(topic_id or "").strip()
    if not selected_topic_id:
        return html
    soup = BeautifulSoup(html, "html.parser")
    for tagged in soup.find_all(attrs={"data-topic-id": True}):
        del tagged.attrs["data-topic-id"]
    marker = soup.new_tag("span")
    marker["data-topic-id"] = selected_topic_id
    marker["hidden"] = ""
    marker["aria-hidden"] = "true"
    marker["role"] = "presentation"
    root = soup.find("article") or soup.body
    if root is not None:
        root.insert(0, marker)
    else:
        soup.insert(0, marker)
    return str(soup)


def existing_topic_publication(article_dir: Path, site: str | None = None) -> dict | None:
    settings = load_settings(site)
    context = load_topic_context(article_dir)
    topic_id = context.get("topic_id", "")
    if not topic_id:
        return None

    try:
        from src.topics.store import TopicStore

        record = TopicStore().get_topic(settings.site_key, topic_id)
    except Exception:
        record = None
    if record is not None:
        publications = getattr(record, "publications", None)
        if publications is None and isinstance(record, dict):
            publications = record.get("publications") or record.get("publication_refs")
        for publication in publications or []:
            payload = publication if isinstance(publication, dict) else {
                "blogger_post_id": getattr(publication, "blogger_post_id", ""),
                "url": getattr(publication, "url", ""),
                "title": getattr(publication, "title", ""),
                "status": getattr(publication, "status", ""),
                "published_at": getattr(publication, "published_at", ""),
                "updated_at": getattr(publication, "updated_at", ""),
            }
            if payload.get("blogger_post_id") or payload.get("url"):
                return payload

    for metadata_path in Path(settings.generated_output_dir).glob("*/*/metadata.json"):
        try:
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        other_candidate = metadata.get("candidate") or {}
        if str(other_candidate.get("topic_id") or "") != topic_id:
            continue
        result_path = metadata_path.parent / "blogger_publish_result.json"
        if not result_path.exists():
            continue
        try:
            result = json.loads(result_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        blogger = result.get("blogger") or {}
        if result.get("draft") or result.get("skipped"):
            continue
        if blogger.get("id") or blogger.get("url"):
            return {
                "blogger_post_id": blogger.get("id", ""),
                "url": blogger.get("url", ""),
                "title": (metadata.get("article") or {}).get("title", ""),
                "status": blogger.get("status", ""),
                "published_at": blogger.get("published", ""),
                "updated_at": blogger.get("updated", ""),
            }
    return None


def validate_topic_ready(article_dir: Path, site: str | None = None) -> dict:
    settings = load_settings(site)
    context = load_topic_context(article_dir)
    topic_id = context.get("topic_id", "")
    if not topic_id:
        return context
    generated_revision = parse_topic_revision(context)
    if context.get("action", "NEW_POST") != "NEW_POST":
        raise ValueError(
            f"Topic {topic_id} is a maintenance action ({context.get('action')}); "
            "it must use the maintenance update flow instead of creating a new Blogger post."
        )
    try:
        from src.topics.models import TopicAction
        from src.topics.models import TopicStatus
        from src.topics.store import TopicStore

        record = TopicStore().get_topic(settings.site_key, topic_id)
    except Exception as exc:
        raise ValueError(
            f"Topic registry revalidation failed for {topic_id}; publishing is held."
        ) from exc
    if record is None:
        raise ValueError(f"Topic {topic_id} no longer exists in the registry; publishing is held.")
    status = getattr(record, "status", "")
    action = getattr(record, "action", "")
    status_value = status.value if hasattr(status, "value") else str(status)
    action_value = action.value if hasattr(action, "value") else str(action)
    allowed_statuses = {
        TopicStatus.CLAIMED.value,
        TopicStatus.GENERATED.value,
    }
    if status_value.upper() not in allowed_statuses:
        raise ValueError(
            f"Topic {topic_id} is {status_value or 'UNKNOWN'}, not CLAIMED/GENERATED; publishing is held."
        )
    if action_value.upper() != TopicAction.NEW_POST.value:
        raise ValueError(
            f"Topic {topic_id} action changed to {action_value or 'UNKNOWN'}; publishing is held."
        )
    try:
        current_revision = int(getattr(record, "revision", 0) or 0)
    except (TypeError, ValueError):
        raise ValueError(
            f"Topic {topic_id} has an invalid Registry revision; publishing is held."
        )
    if current_revision <= 0 or generated_revision != current_revision:
        raise ValueError(
            f"Topic {topic_id} revision changed from {generated_revision} to {current_revision}; "
            "regenerate from the current editor brief before publishing."
        )
    generated_claim = str(context.get("claim_run_id") or "")
    current_claim = str(getattr(record, "claim_run_id", "") or "")
    if not generated_claim or generated_claim != current_claim:
        raise ValueError(
            f"Topic {topic_id} claim ownership does not match the generated article; publishing is held."
        )
    return context


def save_duplicate_topic_result(
    article_dir: Path,
    publication: dict,
    topic_context: dict,
) -> Path:
    result_path = article_dir / "duplicate_topic_publish_result.json"
    result_path.write_text(
        json.dumps(
            {
                "draft": False,
                "skipped": True,
                "reason": "duplicate_topic_id",
                "topic_id": topic_context.get("topic_id", ""),
                "cluster_id": topic_context.get("cluster_id", ""),
                "category_id": topic_context.get("category_id", ""),
                "action": topic_context.get("action", "NEW_POST"),
                "topic_action": topic_context.get("topic_action", topic_context.get("action", "NEW_POST")),
                "revision": topic_context.get("revision", 0),
                "topic_revision": topic_context.get("topic_revision", topic_context.get("revision", 0)),
                "claim_run_id": topic_context.get("claim_run_id", ""),
                "blogger": {
                    "id": publication.get("blogger_post_id") or publication.get("post_id"),
                    "url": publication.get("url"),
                    "selfLink": None,
                    "status": "SKIPPED_DUPLICATE",
                    "published": publication.get("published_at") or publication.get("published"),
                    "updated": publication.get("updated_at") or publication.get("updated"),
                },
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return result_path


def begin_topic_publish_attempt(site: str, topic_context: dict) -> dict | None:
    topic_id = str(topic_context.get("topic_id") or "")
    if not topic_id:
        return None
    revision = parse_topic_revision(topic_context)
    run_id = str(topic_context.get("claim_run_id") or "")
    if not run_id:
        raise ValueError(f"Topic {topic_id} has no active claim_run_id; publishing is held.")
    try:
        from src.topics.store import TopicStore

        store = TopicStore()
        begin = getattr(store, "begin_publish_attempt", None)
        if not callable(begin):
            raise RuntimeError("TopicStore publish-attempt CAS API is unavailable")
        attempt = begin(
            site,
            topic_id,
            run_id=run_id,
            expected_revision=revision,
            lease_seconds=PUBLISH_ATTEMPT_TTL_SECONDS,
        )
    except PublishAttemptBlocked:
        raise
    except Exception as exc:
        raise PublishAttemptBlocked(
            f"Could not acquire the one-time Blogger insert lease for {topic_id}: {exc}"
        ) from exc
    if not isinstance(attempt, dict) or not attempt.get("acquired"):
        attempt_id = str((attempt or {}).get("attempt_id") or "")
        status = str((attempt or {}).get("status") or "UNKNOWN")
        raise PublishAttemptBlocked(
            f"Topic {topic_id} already has publish attempt {attempt_id or 'unknown'} "
            f"in {status}; reconcile Blogger instead of inserting again."
        )
    return attempt


def mark_topic_insert_started(site: str, topic_context: dict, attempt: dict | None) -> dict | None:
    if attempt is None:
        return None
    topic_id = str(topic_context.get("topic_id") or "")
    attempt_id = str(attempt.get("attempt_id") or "")
    try:
        from src.topics.store import TopicStore

        updated = TopicStore().mark_publish_insert_started(
            site,
            topic_id,
            attempt_id=attempt_id,
            run_id=str(topic_context.get("claim_run_id") or ""),
        )
    except Exception as exc:
        raise PublishAttemptBlocked(
            f"Could not durably mark Blogger insert start for {topic_id}: {exc}"
        ) from exc
    return updated if isinstance(updated, dict) else attempt


def mark_topic_publish_unknown(
    site: str,
    topic_context: dict,
    attempt: dict | None,
    error: str,
) -> None:
    if attempt is None:
        return
    try:
        from src.topics.store import TopicStore

        TopicStore().mark_publish_attempt_unknown(
            site,
            str(topic_context.get("topic_id") or ""),
            attempt_id=str(attempt.get("attempt_id") or ""),
            run_id=str(topic_context.get("claim_run_id") or ""),
            error=error[:2000],
        )
    except Exception as mark_error:
        LOGGER.error(
            "Could not persist unknown Blogger outcome for topic_id=%s attempt_id=%s: %s",
            topic_context.get("topic_id"),
            attempt.get("attempt_id"),
            mark_error,
        )


def record_topic_publication(
    site: str,
    topic_context: dict,
    title: str,
    result: dict,
    *,
    draft: bool,
) -> dict:
    topic_id = str(topic_context.get("topic_id") or "")
    if not topic_id or draft or not (result.get("id") or result.get("url")):
        return {"status": "not_applicable"}
    publication_data = {
        "blogger_post_id": str(result.get("id") or ""),
        "url": str(result.get("url") or ""),
        "title": title,
        "status": str(result.get("status") or ""),
        "published_at": str(result.get("published") or ""),
        "updated_at": str(result.get("updated") or ""),
        "last_verified_at": "",
    }
    attempt_id = str(topic_context.get("publish_attempt_id") or "")
    try:
        from src.topics.models import PublicationRef
        from src.topics.store import TopicStore

        store = TopicStore()
        publication = PublicationRef.from_dict(publication_data)
    except Exception as exc:
        return enqueue_local_publication_sync(
            site,
            topic_id,
            publication_data,
            error=f"TopicStore unavailable: {exc}",
            attempt_id=attempt_id,
            topic_revision=topic_context.get("revision"),
            run_id=str(topic_context.get("claim_run_id") or ""),
        )

    try:
        expected_revision = parse_topic_revision(topic_context)
        if attempt_id:
            record_receipt = getattr(store, "record_publish_receipt", None)
            if not callable(record_receipt):
                raise RuntimeError("TopicStore publish-receipt API is unavailable")
            record_receipt(
                site,
                topic_id,
                attempt_id=attempt_id,
                publication=publication,
                expected_revision=expected_revision,
                run_id=str(topic_context.get("claim_run_id") or ""),
            )
        else:
            store.record_publication(
                site,
                topic_id,
                publication,
                expected_revision=expected_revision,
                run_id=str(topic_context.get("claim_run_id") or ""),
            )
        return {
            "status": "recorded_live_unverified",
            "durable": True,
            "attempt_id": attempt_id,
        }
    except Exception as record_error:
        try:
            enqueue_receipt = getattr(store, "enqueue_publish_receipt", None)
            attempt_marked_unknown = False
            if attempt_id and callable(enqueue_receipt):
                enqueue_receipt(
                    site,
                    topic_id,
                    attempt_id=attempt_id,
                    publication=publication,
                    error=str(record_error),
                )
                attempt_marked_unknown = True
            else:
                store.enqueue_publication_sync(
                    site,
                    topic_id,
                    publication,
                    error=str(record_error),
                )
            if attempt_id and not attempt_marked_unknown:
                try:
                    store.mark_publish_attempt_unknown(
                        site,
                        topic_id,
                        attempt_id=attempt_id,
                        run_id=str(topic_context.get("claim_run_id") or ""),
                        error=f"receipt queued: {record_error}",
                    )
                except Exception:
                    pass
            LOGGER.warning(
                "Blogger post is live but topic publication sync was queued: topic_id=%s post_id=%s error=%s",
                topic_id,
                publication.blogger_post_id,
                record_error,
            )
            return {
                "status": "queued",
                "error": str(record_error),
                "durable": True,
                "attempt_id": attempt_id,
            }
        except Exception as outbox_error:
            return enqueue_local_publication_sync(
                site,
                topic_id,
                publication_data,
                error=f"record={record_error}; store_outbox={outbox_error}",
                attempt_id=attempt_id,
                topic_revision=topic_context.get("revision"),
                run_id=str(topic_context.get("claim_run_id") or ""),
            )


def enqueue_local_publication_sync(
    site: str,
    topic_id: str,
    publication: dict,
    *,
    error: str,
    attempt_id: str = "",
    topic_revision: object = None,
    run_id: str = "",
    attempt_kind: str = "INSERT",
    action: str = "",
) -> dict:
    path = local_publication_outbox_path()
    payload = {
        "schema_version": 2,
        "site": site,
        "topic_id": topic_id,
        "attempt_id": attempt_id,
        "attempt_kind": str(attempt_kind or "INSERT").strip().upper(),
        "action": str(action or "").strip().upper(),
        "topic_revision": topic_revision,
        "run_id": run_id,
        "publication": publication,
        "error": error,
        "created_at": datetime.now(tz=timezone.utc).isoformat(),
        "idempotency_key": (
            f"{site}:{topic_id}:{attempt_id}:"
            f"{publication.get('blogger_post_id') or publication.get('url')}"
        ),
    }
    try:
        durable_jsonl_append(path, payload)
        LOGGER.warning(
            "Blogger post is live but registry sync is pending in durable outbox %s: topic_id=%s error=%s",
            path,
            topic_id,
            error,
        )
        return {
            "status": "local_outbox",
            "path": str(path),
            "error": error,
            "durable": True,
            "attempt_id": attempt_id,
        }
    except Exception as outbox_error:
        LOGGER.error(
            "Blogger post is live and topic registry sync/outbox both failed: topic_id=%s error=%s outbox_error=%s",
            topic_id,
            error,
            outbox_error,
        )
        return {
            "status": "error",
            "error": f"{error}; local_outbox={outbox_error}",
            "durable": False,
            "attempt_id": attempt_id,
        }


def local_publication_outbox_path(path: str | Path | None = None) -> Path:
    if path is not None:
        return Path(path).expanduser()
    configured = os.getenv("TOPIC_PUBLICATION_OUTBOX", "").strip()
    return (
        Path(configured).expanduser()
        if configured
        else ROOT_DIR / "data" / "topics" / "publication_sync_pending.jsonl"
    )


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(
        str(path),
        os.O_RDONLY | getattr(os, "O_DIRECTORY", 0),
    )
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def durable_jsonl_append(path: Path, payload: dict) -> bool:
    """Append one idempotent JSONL record under a process lock and fsync it."""

    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.with_name(f".{path.name}.lock")
    with lock_path.open("a+b") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        try:
            existing_keys: set[str] = set()
            if path.exists():
                with path.open("rb") as existing:
                    for raw_line in existing:
                        try:
                            item = json.loads(raw_line.decode("utf-8"))
                        except (UnicodeDecodeError, ValueError):
                            continue
                        existing_keys.add(
                            str(item.get("idempotency_key") or "")
                        )
            appended = payload.get("idempotency_key") not in existing_keys
            created = not path.exists()
            with path.open("a+b") as handle:
                if appended:
                    handle.seek(0, os.SEEK_END)
                    if handle.tell():
                        handle.seek(-1, os.SEEK_END)
                        if handle.read(1) != b"\n":
                            handle.seek(0, os.SEEK_END)
                            handle.write(b"\n")
                    handle.seek(0, os.SEEK_END)
                    handle.write(
                        json.dumps(
                            payload,
                            ensure_ascii=False,
                            separators=(",", ":"),
                        ).encode("utf-8")
                        + b"\n"
                    )
                handle.flush()
                os.fsync(handle.fileno())
            if created:
                _fsync_directory(path.parent)
            return appended
        finally:
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


def replay_local_publication_outbox(
    store,
    site: str,
    *,
    path: str | Path | None = None,
    consume: bool = True,
) -> dict:
    """Move durable local fallback receipts into the Registry outbox."""

    selected_path = local_publication_outbox_path(path)
    if not selected_path.exists():
        return {
            "path": str(selected_path),
            "found": 0,
            "imported": 0,
            "remaining": 0,
            "errors": [],
        }
    lock_path = selected_path.with_name(f".{selected_path.name}.lock")
    imported_keys: set[str] = set()
    errors: list[dict] = []
    parsed_lines: list[tuple[bytes, dict | None]] = []
    with lock_path.open("a+b") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        try:
            for raw_line in selected_path.read_bytes().splitlines(keepends=True):
                try:
                    item = json.loads(raw_line.decode("utf-8"))
                except (UnicodeDecodeError, ValueError) as exc:
                    parsed_lines.append((raw_line, None))
                    errors.append({"error": f"invalid_jsonl:{exc}"})
                    continue
                parsed_lines.append((raw_line, item))
                if str(item.get("site") or "") != site:
                    continue
                topic_id = str(item.get("topic_id") or "")
                publication = dict(item.get("publication") or {})
                idempotency_key = str(item.get("idempotency_key") or "")
                try:
                    attempt_id = str(item.get("attempt_id") or "")
                    attempt_kind = str(
                        item.get("attempt_kind") or "INSERT"
                    ).strip().upper()
                    run_id = str(item.get("run_id") or "")
                    raw_revision = item.get("topic_revision")
                    revision = (
                        int(raw_revision)
                        if (
                            not isinstance(raw_revision, bool)
                            and str(raw_revision or "").isdigit()
                            and int(raw_revision) > 0
                        )
                        else 0
                    )
                    receipt_recorded = False
                    if (
                        attempt_id
                        and revision
                        and run_id
                        and attempt_kind == "UPDATE"
                        and callable(
                            getattr(store, "record_update_receipt", None)
                        )
                    ):
                        try:
                            store.record_update_receipt(
                                site,
                                topic_id,
                                attempt_id=attempt_id,
                                publication=publication,
                                expected_revision=revision,
                                run_id=run_id,
                            )
                            receipt_recorded = True
                        except Exception:
                            store.enqueue_update_receipt(
                                site,
                                topic_id,
                                attempt_id=attempt_id,
                                publication=publication,
                                run_id=run_id,
                                error=str(item.get("error") or ""),
                            )
                    elif (
                        attempt_id
                        and revision
                        and run_id
                        and callable(
                            getattr(store, "record_publish_receipt", None)
                        )
                    ):
                        try:
                            store.record_publish_receipt(
                                site,
                                topic_id,
                                attempt_id=attempt_id,
                                publication=publication,
                                expected_revision=revision,
                                run_id=run_id,
                            )
                            receipt_recorded = True
                        except Exception:
                            store.enqueue_publish_receipt(
                                site,
                                topic_id,
                                attempt_id=attempt_id,
                                publication=publication,
                                error=str(item.get("error") or ""),
                            )
                    elif (
                        attempt_id
                        and attempt_kind == "UPDATE"
                        and run_id
                        and callable(
                            getattr(store, "enqueue_update_receipt", None)
                        )
                    ):
                        store.enqueue_update_receipt(
                            site,
                            topic_id,
                            attempt_id=attempt_id,
                            publication=publication,
                            run_id=run_id,
                            error=str(item.get("error") or ""),
                        )
                    elif attempt_id and callable(
                        getattr(store, "enqueue_publish_receipt", None)
                    ):
                        store.enqueue_publish_receipt(
                            site,
                            topic_id,
                            attempt_id=attempt_id,
                            publication=publication,
                            error=str(item.get("error") or ""),
                        )
                    else:
                        entry = store.enqueue_publication_sync(
                            site,
                            topic_id,
                            publication,
                            error=str(item.get("error") or ""),
                        )
                        store.mark_publication_outbox_stage(
                            site,
                            str(entry.get("outbox_id") or ""),
                            "blogger",
                            success=True,
                        )
                    if receipt_recorded:
                        entry = store.enqueue_publication_sync(
                            site,
                            topic_id,
                            publication,
                            error="Sheet synchronization pending after local receipt replay",
                        )
                        for stage in ("blogger", "registry"):
                            store.mark_publication_outbox_stage(
                                site,
                                str(entry.get("outbox_id") or ""),
                                stage,
                                success=True,
                            )
                    imported_keys.add(idempotency_key)
                except Exception as exc:
                    errors.append(
                        {
                            "idempotency_key": idempotency_key,
                            "topic_id": topic_id,
                            "error": str(exc),
                        }
                    )

            if consume and imported_keys:
                remaining_lines = []
                for raw_line, item in parsed_lines:
                    if (
                        isinstance(item, dict)
                        and str(item.get("site") or "") == site
                        and str(item.get("idempotency_key") or "")
                        in imported_keys
                    ):
                        continue
                    remaining_lines.append(raw_line)
                temp_path = selected_path.with_name(
                    f".{selected_path.name}.{os.getpid()}.tmp"
                )
                try:
                    with temp_path.open("wb") as handle:
                        handle.writelines(remaining_lines)
                        handle.flush()
                        os.fsync(handle.fileno())
                    os.replace(temp_path, selected_path)
                    _fsync_directory(selected_path.parent)
                finally:
                    if temp_path.exists():
                        temp_path.unlink()
        finally:
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
    remaining = sum(
        1
        for _, item in parsed_lines
        if not (
            isinstance(item, dict)
            and str(item.get("site") or "") == site
            and str(item.get("idempotency_key") or "") in imported_keys
        )
    )
    return {
        "path": str(selected_path),
        "found": sum(
            1
            for _, item in parsed_lines
            if isinstance(item, dict)
            and str(item.get("site") or "") == site
        ),
        "imported": len(imported_keys),
        "remaining": remaining,
        "errors": errors,
    }


def attach_topic_registry_sync(result_path: Path, sync_result: dict) -> None:
    try:
        payload = json.loads(result_path.read_text(encoding="utf-8"))
        payload["topic_registry_sync"] = sync_result
        result_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except (OSError, ValueError) as exc:
        LOGGER.error("Could not persist topic registry sync status to %s: %s", result_path, exc)


def run(article_dir: Path | None, mode: str | None, site: str | None = None) -> Path:
    settings = load_settings(site)
    selected_dir = article_dir or latest_article_dir(site)
    publish_mode = mode or settings.blogger_publish_mode
    draft = publish_mode != "publish"
    topic_context = load_topic_context(selected_dir)
    if topic_context.get("topic_id") and topic_context.get("action", "NEW_POST") != "NEW_POST":
        raise ValueError(
            f"Topic {topic_context.get('topic_id')} is a maintenance action "
            f"({topic_context.get('action')}); it must use the maintenance update flow."
        )
    if not draft:
        publication = existing_topic_publication(selected_dir, site)
        if publication:
            result_path = save_duplicate_topic_result(selected_dir, publication, topic_context)
            LOGGER.info(
                "Skipped duplicate topic_id=%s; existing publication=%s",
                topic_context.get("topic_id"),
                publication.get("url"),
            )
            return result_path
    topic_context = validate_topic_ready(selected_dir, site)

    title, html, labels = load_article(selected_dir, site)
    html = ensure_topic_id_marker(html, str(topic_context.get("topic_id") or ""))
    validate_live_originality(title, html, site)
    publisher = BloggerPublisher(settings)
    attempt = None
    if not draft and topic_context.get("topic_id"):
        attempt = begin_topic_publish_attempt(settings.site_key, topic_context)
        attempt = mark_topic_insert_started(
            settings.site_key,
            topic_context,
            attempt,
        )
        topic_context = {
            **topic_context,
            "publish_attempt_id": str((attempt or {}).get("attempt_id") or ""),
        }
    LOGGER.info("Publishing to Blogger blog_id=%s draft=%s title=%s", settings.blogger_blog_id, draft, title)
    try:
        result = publisher.publish(title=title, html=html, labels=labels, draft=draft)
    except Exception as exc:
        if attempt is not None:
            mark_topic_publish_unknown(
                settings.site_key,
                topic_context,
                attempt,
                str(exc),
            )
            raise BloggerOutcomeUnknown(
                f"Blogger insert outcome is unknown for topic "
                f"{topic_context.get('topic_id')} attempt "
                f"{attempt.get('attempt_id')}; reconcile before any retry."
            ) from exc
        raise
    sync_result = record_topic_publication(
        settings.site_key,
        topic_context,
        title,
        result,
        draft=draft,
    )
    if (
        not draft
        and topic_context.get("topic_id")
        and not bool(sync_result.get("durable"))
    ):
        mark_topic_publish_unknown(
            settings.site_key,
            topic_context,
            attempt,
            str(sync_result.get("error") or "publication receipt was not durable"),
        )
        raise BloggerOutcomeUnknown(
            f"Blogger returned a post for topic {topic_context.get('topic_id')}, "
            "but neither Registry nor the receipt outbox was durable. Reconcile before retry."
        )
    try:
        result_path = save_publish_result(
            selected_dir,
            result,
            draft,
            topic_context,
            topic_registry_sync=sync_result,
            publish_attempt=attempt,
        )
    except Exception as exc:
        if (
            not draft
            and topic_context.get("topic_id")
            and bool(sync_result.get("durable"))
            and (result.get("id") or result.get("url"))
        ):
            raise PublishReceiptPersisted(
                f"Blogger receipt for topic {topic_context.get('topic_id') or 'legacy'} "
                "was persisted before the local result write failed; reconcile, do not reinsert."
            ) from exc
        raise
    LOGGER.info("Saved publish result to %s", result_path)
    return result_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Stage 2: publish a generated article to Blogger.")
    parser.add_argument("--article-dir", help="Generated article directory. Defaults to latest generated article.")
    parser.add_argument("--mode", choices=["draft", "publish"], help="Blogger publishing mode. Default: BLOGGER_PUBLISH_MODE")
    parser.add_argument("--site", help="Site profile key, for example: easy_pc_fix_guide")
    args = parser.parse_args()

    article_dir = Path(args.article_dir).expanduser().resolve() if args.article_dir else None
    try:
        result_path = run(article_dir, args.mode, args.site)
    except BloggerCredentialsError as exc:
        raise SystemExit(f"Blogger credential setup required: {exc}") from exc
    print(result_path)


if __name__ == "__main__":
    main()
