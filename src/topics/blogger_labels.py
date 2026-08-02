from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from typing import Protocol

from src.topics.ids import canonical_url
from src.topics.models import ProposalStatus
from src.topics.store import TopicStore


class BloggerLabelClient(Protocol):
    def get_post(self, post_id: str) -> dict[str, Any]:
        ...

    def update_post_labels(
        self,
        post_id: str,
        labels: list[str],
        *,
        post: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        ...


def _read_rollback_payload(path: str) -> dict[str, Any]:
    selected = Path(path)
    if not selected.exists():
        raise ValueError("Prepared rollback payload is missing")
    try:
        payload = json.loads(selected.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Cannot read rollback payload {selected}: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError("Prepared rollback payload must be an object")
    return payload


def _read_label_snapshot(path: str) -> dict[str, Any]:
    selected = Path(path)
    if not selected.exists():
        raise ValueError("Immutable pre-change Blogger label snapshot is missing")
    try:
        payload = json.loads(selected.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(
            f"Cannot read pre-change Blogger label snapshot {selected}: {exc}"
        ) from exc
    if not isinstance(payload, dict):
        raise ValueError("Pre-change Blogger label snapshot must be an object")
    return payload


def _verified_post(
    client: BloggerLabelClient,
    post_id: str,
    expected_url: str,
) -> tuple[dict[str, Any], str]:
    post = client.get_post(post_id)
    returned_id = str(post.get("id") or post.get("blogger_post_id") or "")
    if returned_id != post_id:
        raise ValueError(f"Blogger GET returned the wrong post for {post_id}")
    returned_url = canonical_url(str(post.get("url") or ""))
    if not expected_url:
        raise ValueError(f"Expected canonical URL is missing for {post_id}")
    if returned_url != expected_url:
        raise ValueError(
            f"Blogger GET URL mismatch for {post_id}: "
            f"expected {expected_url}, found {returned_url}"
        )
    return post, returned_url


def _snapshot_posts_by_id(
    snapshot: dict[str, Any],
    affected: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    posts = snapshot.get("posts")
    if not isinstance(posts, list) or not posts:
        raise ValueError("Pre-change Blogger label snapshot has no posts")

    affected_by_id: dict[str, dict[str, Any]] = {}
    for item in affected:
        if not isinstance(item, dict):
            raise ValueError("Prepared rollback payload contains an invalid publication")
        post_id = str(item.get("blogger_post_id") or "")
        if not post_id or post_id in affected_by_id:
            raise ValueError(
                "Prepared rollback payload contains a missing/duplicate Blogger post ID"
            )
        affected_by_id[post_id] = item

    snapshot_by_id: dict[str, dict[str, Any]] = {}
    for item in posts:
        if not isinstance(item, dict):
            raise ValueError("Pre-change Blogger label snapshot contains an invalid post")
        post_id = str(item.get("blogger_post_id") or item.get("id") or "")
        if not post_id or post_id in snapshot_by_id:
            raise ValueError(
                "Pre-change Blogger label snapshot contains a missing/duplicate post ID"
            )
        labels = item.get("labels")
        if not isinstance(labels, list) or any(
            not isinstance(label, str) for label in labels
        ):
            raise ValueError(
                f"Pre-change Blogger label snapshot has invalid labels for {post_id}"
            )
        expected_url = canonical_url(str(affected_by_id.get(post_id, {}).get("url") or ""))
        snapshot_url = canonical_url(str(item.get("url") or ""))
        if not expected_url or snapshot_url != expected_url:
            raise ValueError(
                f"Pre-change Blogger label snapshot URL mismatch for {post_id}"
            )
        snapshot_by_id[post_id] = item

    if set(snapshot_by_id) != set(affected_by_id):
        raise ValueError(
            "Pre-change Blogger label snapshot post IDs do not match the rollback payload"
        )
    return snapshot_by_id


def _replace_one_label(
    labels: list[str],
    old_label: str,
    new_label: str,
) -> tuple[list[str], str]:
    current = [str(label) for label in labels if str(label)]
    if old_label not in current:
        if new_label in current:
            return current, "ALREADY_APPLIED"
        return current, "OLD_LABEL_MISSING"
    desired: list[str] = []
    for label in current:
        if label in {old_label, new_label}:
            if new_label not in desired:
                desired.append(new_label)
        else:
            desired.append(label)
    return desired, "UPDATE"


def sync_proposal_blogger_labels(
    store: TopicStore,
    site: str,
    proposal_id: str,
    client: BloggerLabelClient,
    *,
    apply: bool = False,
) -> dict[str, Any]:
    """GET every affected post first, then apply only approved old→new labels.

    The default is a read-only plan.  Retries are idempotent: posts that
    already carry the new label and no longer carry the old one are skipped.
    """

    proposal = store.get_monthly_proposal(site, proposal_id)
    if proposal is None:
        raise ValueError(f"Unknown proposal: {proposal_id}")
    if proposal.status is ProposalStatus.APPLIED and not proposal.publication_sync_pending:
        return {
            "site": site,
            "proposal_id": proposal_id,
            "dry_run": not apply,
            "success": True,
            "status": "ALREADY_SYNCED",
            "operations": [],
        }
    if (
        proposal.status is not ProposalStatus.APPROVED
        or not proposal.approved_by
        or not proposal.approved_at
        or not proposal.publication_sync_pending
    ):
        raise ValueError(
            "Blogger labels cannot be read or changed before explicit approval "
            "and pending-sync Registry application"
        )
    if (
        not proposal.snapshot_path
        or not Path(proposal.snapshot_path).exists()
        or not proposal.rollback_path
        or not Path(proposal.rollback_path).exists()
    ):
        raise ValueError(
            "Proposal snapshot and prepared rollback payload must exist before label sync"
        )
    rollback = _read_rollback_payload(proposal.rollback_path)
    if (
        rollback.get("proposal_id") != proposal_id
        or rollback.get("site") != site
        or rollback.get("snapshot_path") != proposal.snapshot_path
    ):
        raise ValueError("Prepared rollback payload identity mismatch")
    affected = rollback.get("affected_publications") or []
    if not isinstance(affected, list) or not affected:
        raise ValueError("Prepared rollback payload has no affected publications")

    seen_post_ids: set[str] = set()
    fetched_posts: list[dict[str, Any]] = []
    operations: list[dict[str, Any]] = []
    blocking_errors: list[str] = []
    for item in affected:
        post_id = str(item.get("blogger_post_id") or "")
        if not post_id or post_id in seen_post_ids:
            raise ValueError("Rollback payload contains a missing/duplicate Blogger post ID")
        seen_post_ids.add(post_id)
        expected_url = canonical_url(str(item.get("url") or ""))
        post, returned_url = _verified_post(client, post_id, expected_url)
        fetched_posts.append(post)
        old_label = str(item.get("old_label") or "")
        new_label = str(item.get("new_label") or "")
        desired, state = _replace_one_label(
            list(post.get("labels") or []),
            old_label,
            new_label,
        )
        if state == "OLD_LABEL_MISSING":
            blocking_errors.append(
                f"{post_id}: expected old label {old_label!r} is missing"
            )
        operations.append(
            {
                "topic_id": str(item.get("topic_id") or ""),
                "blogger_post_id": post_id,
                "canonical_url": returned_url,
                "old_label": old_label,
                "new_label": new_label,
                "labels_before": list(post.get("labels") or []),
                "labels_after": desired,
                "state": state,
            }
        )

    if not apply:
        return {
            "site": site,
            "proposal_id": proposal_id,
            "dry_run": True,
            "success": not blocking_errors,
            "status": "READY" if not blocking_errors else "BLOCKED",
            "blocking_errors": blocking_errors,
            "operations": operations,
        }

    if blocking_errors:
        message = "; ".join(blocking_errors)
        store.mark_proposal_publication_sync(
            site,
            proposal_id,
            success=False,
            error=message,
        )
        return {
            "site": site,
            "proposal_id": proposal_id,
            "dry_run": False,
            "success": False,
            "status": "BLOCKED",
            "blocking_errors": blocking_errors,
            "operations": operations,
        }

    store.prepare_proposal_label_sync_snapshot(
        site,
        proposal_id,
        fetched_posts,
    )
    post_by_id = {
        str(post.get("id") or post.get("blogger_post_id") or ""): post
        for post in fetched_posts
    }
    try:
        for operation in operations:
            if operation["state"] != "UPDATE":
                continue
            post_id = operation["blogger_post_id"]
            client.update_post_labels(
                post_id,
                operation["labels_after"],
                post=post_by_id[post_id],
            )
        for operation in operations:
            verified, _ = _verified_post(
                client,
                operation["blogger_post_id"],
                operation["canonical_url"],
            )
            actual_labels = list(verified.get("labels") or [])
            if actual_labels != operation["labels_after"]:
                raise RuntimeError(
                    f"{operation['blogger_post_id']}: Blogger label verification failed"
                )
    except Exception as exc:
        store.mark_proposal_publication_sync(
            site,
            proposal_id,
            success=False,
            error=str(exc),
        )
        return {
            "site": site,
            "proposal_id": proposal_id,
            "dry_run": False,
            "success": False,
            "status": "PENDING_RETRY",
            "error": str(exc),
            "operations": operations,
        }

    completed = store.mark_proposal_publication_sync(
        site,
        proposal_id,
        success=True,
    )
    return {
        "site": site,
        "proposal_id": proposal_id,
        "dry_run": False,
        "success": True,
        "status": completed.status.value,
        "operations": operations,
    }


def rollback_proposal_blogger_labels(
    store: TopicStore,
    site: str,
    proposal_id: str,
    client: BloggerLabelClient,
    *,
    apply: bool = False,
) -> dict[str, Any]:
    """Restore exact pre-change Blogger labels before rolling back the Registry.

    The default is a read-only plan.  Every affected post is fetched and its
    immutable ID and canonical URL are checked before any write.  A failed or
    partial Blogger update leaves the proposal APPLIED, so a retry can skip
    posts that already match the snapshot and finish the remaining restores.
    """

    proposal = store.get_monthly_proposal(site, proposal_id)
    if proposal is None:
        raise ValueError(f"Unknown proposal: {proposal_id}")
    if proposal.status is ProposalStatus.ROLLED_BACK:
        return {
            "site": site,
            "proposal_id": proposal_id,
            "dry_run": not apply,
            "success": True,
            "status": "ALREADY_ROLLED_BACK",
            "operations": [],
        }
    if proposal.status is not ProposalStatus.APPLIED:
        raise ValueError("Only an APPLIED proposal may restore Blogger labels")
    if proposal.publication_sync_pending:
        raise ValueError(
            "Pending forward Blogger label sync must be resolved before rollback"
        )
    if (
        not proposal.rollback_path
        or not Path(proposal.rollback_path).exists()
        or not proposal.label_sync_snapshot_path
        or not Path(proposal.label_sync_snapshot_path).exists()
    ):
        raise ValueError(
            "Prepared rollback payload and immutable pre-change Blogger label "
            "snapshot are required"
        )

    rollback = _read_rollback_payload(proposal.rollback_path)
    if (
        rollback.get("proposal_id") != proposal_id
        or rollback.get("site") != site
        or rollback.get("snapshot_path") != proposal.snapshot_path
    ):
        raise ValueError("Prepared rollback payload identity mismatch")
    affected = rollback.get("affected_publications")
    if not isinstance(affected, list) or not affected:
        raise ValueError("Prepared rollback payload has no affected publications")

    snapshot = _read_label_snapshot(proposal.label_sync_snapshot_path)
    if (
        snapshot.get("proposal_id") != proposal_id
        or snapshot.get("site") != site
    ):
        raise ValueError("Pre-change Blogger label snapshot identity mismatch")
    snapshot_by_id = _snapshot_posts_by_id(snapshot, affected)

    operations: list[dict[str, Any]] = []
    current_posts: dict[str, dict[str, Any]] = {}
    for item in affected:
        post_id = str(item.get("blogger_post_id") or "")
        expected_url = canonical_url(str(item.get("url") or ""))
        post, returned_url = _verified_post(client, post_id, expected_url)
        current_posts[post_id] = post
        labels_before = list(post.get("labels") or [])
        labels_after = list(snapshot_by_id[post_id]["labels"])
        operations.append(
            {
                "topic_id": str(item.get("topic_id") or ""),
                "blogger_post_id": post_id,
                "canonical_url": returned_url,
                "labels_before": labels_before,
                "labels_after": labels_after,
                "state": (
                    "ALREADY_RESTORED"
                    if labels_before == labels_after
                    else "RESTORE"
                ),
            }
        )

    if not apply:
        return {
            "site": site,
            "proposal_id": proposal_id,
            "dry_run": True,
            "success": True,
            "status": "READY",
            "operations": operations,
        }

    try:
        for operation in operations:
            if operation["state"] != "RESTORE":
                continue
            post_id = operation["blogger_post_id"]
            client.update_post_labels(
                post_id,
                operation["labels_after"],
                post=current_posts[post_id],
            )
        for operation in operations:
            verified, _ = _verified_post(
                client,
                operation["blogger_post_id"],
                operation["canonical_url"],
            )
            if list(verified.get("labels") or []) != operation["labels_after"]:
                raise RuntimeError(
                    f"{operation['blogger_post_id']}: "
                    "Blogger rollback label verification failed"
                )
    except Exception as exc:
        return {
            "site": site,
            "proposal_id": proposal_id,
            "dry_run": False,
            "success": False,
            "status": "PENDING_RETRY",
            "error": str(exc),
            "operations": operations,
        }

    try:
        rolled_back = store.rollback_monthly_proposal(site, proposal_id)
    except Exception as exc:
        return {
            "site": site,
            "proposal_id": proposal_id,
            "dry_run": False,
            "success": False,
            "status": "PENDING_REGISTRY_ROLLBACK",
            "error": str(exc),
            "operations": operations,
        }
    return {
        "site": site,
        "proposal_id": proposal_id,
        "dry_run": False,
        "success": True,
        "status": rolled_back.status.value,
        "operations": operations,
    }
