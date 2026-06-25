from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Mapping
from urllib.parse import urlparse

from eval_readiness.config import (
    ReadinessConfig,
    ResolvedReadiness,
    load_readiness_config,
    resolve_readiness,
)


@dataclass(frozen=True)
class StartDecision:
    queued: bool
    reason: str
    detail: str
    instance_id: str = ""
    data_url: str = ""
    hf_path: str = ""
    hf_dataset: str = ""
    language_label: str = ""


def evaluate_start(
    *,
    eval_type: str,
    pr_state: str,
    labels: list[str],
    eval_item: Mapping[str, Any] | None,
    dataset_item: Mapping[str, Any] | None,
    readiness_config: ReadinessConfig,
) -> StartDecision:
    if eval_item is None:
        return StartDecision(False, "missing_eval_item", "Source PR was not found in the eval project")

    fields = _fields(eval_item)
    status = fields.get("Status")
    verification = fields.get("Verification")
    if status != "Prepare for Eval":
        return StartDecision(
            False,
            "invalid_public_status",
            f"Expected public Status=Prepare for Eval, found {status or '<empty>'}",
        )
    if verification != "Generated":
        return StartDecision(
            False,
            "invalid_public_verification",
            f"Expected public Verification=Generated, found {verification or '<empty>'}",
        )

    if pr_state.upper() != "CLOSED":
        return StartDecision(False, "source_pr_not_closed", f"Expected closed source PR, found state {pr_state}")

    if dataset_item is None:
        return StartDecision(False, "missing_dataset_item", "Source PR was not found in Dataset Metadata project")

    data_url = _fields(dataset_item).get("Data") or ""
    if not data_url:
        return StartDecision(False, "missing_dataset_data", "Dataset Metadata project item has no Data URL")

    instance_id = parse_instance_id(data_url)
    if not instance_id:
        return StartDecision(False, "invalid_dataset_data", f"Could not parse instance id from Data URL: {data_url}")

    resolved = resolve_readiness(readiness_config, eval_type, labels)
    if not isinstance(resolved, ResolvedReadiness):
        return StartDecision(False, resolved.reason, resolved.detail, instance_id=instance_id, data_url=data_url)

    return StartDecision(
        queued=True,
        reason="queued",
        detail="Eval-readiness start guards passed",
        instance_id=instance_id,
        data_url=data_url,
        hf_path=resolved.hf_path,
        hf_dataset=resolved.profile.hf_dataset,
        language_label=resolved.language.label,
    )


def parse_instance_id(data_url: str) -> str:
    parsed = urlparse(data_url)
    path = parsed.path if parsed.scheme else data_url
    filename = PurePosixPath(path).name
    if not filename.endswith(".json"):
        return ""
    return filename.removesuffix(".json")


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate datapoint eval-readiness start guards")
    parser.add_argument("--eval-type", required=True)
    parser.add_argument("--pr-state", required=True)
    parser.add_argument("--labels-file", type=Path, required=True)
    parser.add_argument("--eval-item-file", type=Path, required=True)
    parser.add_argument("--dataset-item-file", type=Path, required=True)
    parser.add_argument("--readiness-config", type=Path, default=Path(".github/config/eval-readiness.json"))
    parser.add_argument("--github-output", type=Path, default=None)
    args = parser.parse_args()

    decision = evaluate_start(
        eval_type=args.eval_type,
        pr_state=args.pr_state,
        labels=_read_json(args.labels_file),
        eval_item=_read_optional_object(args.eval_item_file),
        dataset_item=_read_optional_object(args.dataset_item_file),
        readiness_config=load_readiness_config(args.readiness_config),
    )
    outputs = {
        "queued": "true" if decision.queued else "false",
        "reason": decision.reason,
        "detail": decision.detail,
        "instance_id": decision.instance_id,
        "data_url": decision.data_url,
        "hf_path": decision.hf_path,
        "hf_dataset": decision.hf_dataset,
        "language_label": decision.language_label,
    }
    print(json.dumps(outputs, sort_keys=True))
    if args.github_output is not None:
        _write_github_output(args.github_output, outputs)
    return 0


def _fields(item: Mapping[str, Any]) -> Mapping[str, str]:
    fields = item.get("fields")
    return fields if isinstance(fields, Mapping) else {}


def _read_optional_object(path: Path) -> Mapping[str, Any] | None:
    raw = _read_json(path)
    if raw is None:
        return None
    if not isinstance(raw, Mapping):
        raise ValueError(f"{path}: expected JSON object or null")
    return raw


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text())


def _write_github_output(path: Path, outputs: Mapping[str, str]) -> None:
    with path.open("a") as output:
        for key, value in outputs.items():
            print(f"{key}={value}", file=output)


if __name__ == "__main__":
    raise SystemExit(main())
