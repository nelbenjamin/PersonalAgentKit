from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


GOAL_TYPES = {"build", "dispatch", "fix", "genesis", "integrate", "retrospective", "review", "spike", "tend"}
REFLECTION_REQUIRED_GOAL_TYPES = {"build", "fix", "review", "tend", "retrospective"}
REFLECTION_POLICY_VERSION = "2026-03-11"


def classify_goal_type_from_slug(slug: str) -> str:
    normalized_slug = Path(slug).stem.lower()
    normalized_slug = re.sub(r"^\d+[-_]+", "", normalized_slug)
    tokens = [token for token in re.split(r"[-_]+", normalized_slug) if token]
    if not tokens:
        return "build"

    first_token = tokens[0]
    last_token = tokens[-1]

    if first_token == "integrate":
        return "integrate"
    if first_token == "retrospective":
        return "retrospective"
    if first_token == "tend":
        return "tend"
    if first_token == "genesis":
        return "genesis"
    if first_token == "dispatch":
        return "dispatch"
    if first_token == "review":
        return "review"
    if first_token == "spike" or last_token == "spike":
        return "spike"
    if first_token == "fix":
        return "fix"
    return "build"


def goal_type_from_goal_file(goal_file: str | None) -> str:
    if not goal_file:
        return "build"
    return classify_goal_type_from_slug(Path(goal_file).stem)


def reflection_required_for_goal_type(goal_type: str, *, status: str | None = None) -> bool:
    return status == "success" and goal_type in REFLECTION_REQUIRED_GOAL_TYPES


def normalize_status(status: Any) -> Any:
    if status == "completed":
        return "success"
    if status == "failed":
        return "failure"
    return status


def load_meta(run_dir: Path) -> dict[str, Any] | None:
    meta_path = run_dir / "meta.json"
    if not meta_path.exists():
        return None
    try:
        return json.loads(meta_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def goal_type_from_run_dir(run_dir: Path) -> str:
    meta = load_meta(run_dir)
    if isinstance(meta, dict):
        goal_type = meta.get("goal_type")
        if goal_type in GOAL_TYPES:
            return goal_type
        goal_file = meta.get("goal_file")
        if isinstance(goal_file, str) and goal_file:
            return goal_type_from_goal_file(goal_file)
    return classify_goal_type_from_slug(run_dir.name)


def reflection_contract_from_meta(meta: dict[str, Any]) -> tuple[bool, str]:
    explicit = meta.get("requires_reflection")
    if isinstance(explicit, bool):
        return explicit, "explicit"
    return False, "legacy-unspecified"


def reflection_required_for_run(run_dir: Path, status: str | None) -> bool:
    meta = load_meta(run_dir)
    if isinstance(meta, dict):
        explicit, _ = reflection_contract_from_meta(meta)
        return explicit and normalize_status(status) == "success"
    return False


def reflection_policy_summary() -> str:
    required = ", ".join(sorted(REFLECTION_REQUIRED_GOAL_TYPES))
    return (
        f"Reflection contract ({REFLECTION_POLICY_VERSION}): successful {required} runs must write reflection.md. "
        "genesis, dispatch, integrate, and spike runs are exempt unless a future contract marks them otherwise. "
        "Legacy runs without requires_reflection are historical records with unspecified reflection obligations."
    )
