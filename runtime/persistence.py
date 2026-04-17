from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

RESEARCH_ROOT = Path("RESEARCH")


# ---------------------------------------------------------------------------
# Path traversal guard
# ---------------------------------------------------------------------------

def _assert_within_research(path: Path) -> None:
    """Raise ValueError if path resolves outside RESEARCH_ROOT.

    Guards against LLM-generated slugs or filenames that contain `..` sequences
    or absolute path components that would escape the artifact directory.
    """
    try:
        path.resolve().relative_to(RESEARCH_ROOT.resolve())
    except ValueError:
        raise ValueError(f"Path traversal blocked: {path!r} escapes RESEARCH_ROOT")


# ---------------------------------------------------------------------------
# Tool 4 — Artifact Persistence
# ---------------------------------------------------------------------------

def get_slug_root(slug: str) -> Path:
    root = RESEARCH_ROOT / slug
    _assert_within_research(root)
    return root


def persist_artifact(
    slug: str,
    filename: str,
    content: Any,
    *,
    subdir: str | None = None,
) -> str:
    """
    LLM-callable artifact persistence tool.

    Writes LLM-authored content to RESEARCH/<slug>/<filename>.
    The LLM decides what to write; this function only writes it.

    Args:
        slug:     Session slug derived from the research question.
        filename: Target filename (e.g. "intent.json", "final_answer.json").
        content:  Dict/list → written as JSON. str → written as-is (Markdown etc.).
        subdir:   Optional subdirectory under the slug root (e.g. "rounds").

    Returns:
        The absolute path string where the file was written.
    """
    root = get_slug_root(slug)
    if subdir:
        root = root / subdir

    path = root / filename
    _assert_within_research(path)  # validate final path (covers subdir + filename)

    root.mkdir(parents=True, exist_ok=True)

    if isinstance(content, (dict, list)):
        path.write_text(json.dumps(content, ensure_ascii=False, indent=2), encoding="utf-8")
    else:
        path.write_text(str(content), encoding="utf-8")

    return str(path)


def persist_manifest(slug: str, metadata: dict[str, Any]) -> str:
    """Write or update the session manifest."""
    manifest = {
        "slug": slug,
        "created_at": metadata.get("created_at", time.time()),
        "updated_at": time.time(),
        **metadata,
    }
    return persist_artifact(slug, "manifest.json", manifest)


def append_execution_log(slug: str, log_entry: dict[str, Any]) -> str:
    """
    Append a runtime execution event to execution_log.json.

    The file uses an object wrapper so metadata can grow without changing the
    top-level shape later.
    """
    existing = read_artifact(slug, "execution_log.json")
    if not isinstance(existing, dict):
        existing = {
            "version": 1,
            "entries": [],
        }

    entries = existing.get("entries")
    if not isinstance(entries, list):
        entries = []

    entries.append(log_entry)
    existing["entries"] = entries
    existing["updated_at"] = time.time()
    return persist_artifact(slug, "execution_log.json", existing)


def read_execution_log(slug: str) -> dict[str, Any]:
    """
    Read execution_log.json using the stable wrapper shape.

    Returns an empty log wrapper when the file does not exist yet.
    """
    existing = read_artifact(slug, "execution_log.json")
    if isinstance(existing, dict) and isinstance(existing.get("entries"), list):
        return existing
    return {
        "version": 1,
        "entries": [],
    }


def persist_round_bundle(
    slug: str,
    round_id: str,
    contract: dict[str, Any],
    executed_queries: list[dict[str, Any]],
    evaluation: dict[str, Any],
) -> str:
    """Persist the round bundle contract used by the shared docs."""
    bundle = {
        "contract": contract,
        "executed_queries": executed_queries,
        "evaluation": evaluation,
    }
    return persist_artifact(slug, f"{round_id}.json", bundle, subdir="rounds")


def read_round_bundle(slug: str, round_id: str) -> dict[str, Any] | None:
    """Read one persisted round bundle by round id."""
    bundle = read_artifact(slug, f"{round_id}.json", subdir="rounds")
    return bundle if isinstance(bundle, dict) else None


def list_round_bundles(slug: str) -> list[dict[str, Any]]:
    """Return all persisted round bundles sorted by round id filename."""
    root = get_slug_root(slug) / "rounds"
    _assert_within_research(root)
    if not root.exists():
        return []

    bundles: list[dict[str, Any]] = []
    for path in sorted(root.glob("*.json")):
        _assert_within_research(path)
        try:
            content = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(content, dict):
            bundles.append(content)
    return bundles


def load_session_evidence(slug: str) -> dict[str, Any]:
    """
    Aggregate the stable artifacts needed by evaluator/final-answer consumers.

    This keeps upper layers on explicit persisted evidence rather than implicit
    in-memory side channels.
    """
    return {
        "intent": read_artifact(slug, "intent.json"),
        "intent_sidecar": read_artifact(slug, "intent_sidecar.json"),
        "environment_scan": read_artifact(slug, "environment_scan.json"),
        "plan": read_artifact(slug, "plan.json"),
        "execution_log": read_execution_log(slug),
        "round_bundles": list_round_bundles(slug),
        "final_answer": read_artifact(slug, "final_answer.json"),
        "domain_pack_suggestions": read_artifact(slug, "domain_pack_suggestions.json"),
        "manifest": read_artifact(slug, "manifest.json"),
    }


def list_artifacts(slug: str) -> list[str]:
    """Return relative paths of all artifacts written so far for this slug."""
    root = get_slug_root(slug)  # slug already validated
    if not root.exists():
        return []
    return sorted(str(p.relative_to(root)) for p in root.rglob("*") if p.is_file())


def read_artifact(slug: str, filename: str, *, subdir: str | None = None) -> Any:
    """
    Read a previously written artifact back as parsed JSON (or raw string).
    Useful for loading prior rounds during a multi-round investigation.
    """
    root = get_slug_root(slug)
    if subdir:
        root = root / subdir

    path = root / filename
    _assert_within_research(path)  # validate final path

    if not path.exists():
        return None
    text = path.read_text(encoding="utf-8")
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return text
