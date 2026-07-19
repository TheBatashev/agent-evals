"""Validate portable JSONL datasets used by the agent-evals skill."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any


ALLOWED_RISKS = frozenset({"critical", "high", "medium", "low"})
ALLOWED_SUITES = frozenset(
    {
        "capability",
        "regression",
        "safety",
        "production",
        "judge-calibration",
        "benchmark",
    }
)
REQUIRED_FIELDS = frozenset({"id", "suite", "risk", "input", "expected", "metadata"})
REQUIRED_METADATA_FIELDS = frozenset({"owner", "dataset_version", "source"})


@dataclass(frozen=True)
class ValidationIssue:
    """Represent one actionable validation issue."""

    line: int
    message: str

    def render(self) -> str:
        """Return a stable CLI representation."""

        return f"line {self.line}: {self.message}"


class EvalDatasetValidator:
    """Validate dataset structure without retaining mutable global state."""

    def validate(self, path: Path) -> list[ValidationIssue]:
        """Validate a JSONL dataset.

        Args:
            path: Dataset file path.

        Returns:
            A list of validation issues. An empty list means success.
        """

        issues: list[ValidationIssue] = []
        seen_ids: dict[str, int] = {}

        with path.open("r", encoding="utf-8-sig") as dataset_file:
            for line_number, raw_line in enumerate(dataset_file, start=1):
                if not raw_line.strip():
                    continue

                case = self._parse_case(raw_line, line_number, issues)
                if case is None:
                    continue

                issues.extend(self._validate_case(case, line_number, seen_ids))

        if not seen_ids and not issues:
            issues.append(ValidationIssue(line=0, message="dataset contains no cases"))

        return issues

    @staticmethod
    def _parse_case(
        raw_line: str,
        line_number: int,
        issues: list[ValidationIssue],
    ) -> dict[str, Any] | None:
        try:
            value = json.loads(raw_line)
        except json.JSONDecodeError as error:
            issues.append(
                ValidationIssue(
                    line=line_number,
                    message=f"invalid JSON: {error.msg} at column {error.colno}",
                )
            )
            return None

        if not isinstance(value, dict):
            issues.append(ValidationIssue(line=line_number, message="case must be a JSON object"))
            return None

        return value

    def _validate_case(
        self,
        case: dict[str, Any],
        line_number: int,
        seen_ids: dict[str, int],
    ) -> list[ValidationIssue]:
        issues: list[ValidationIssue] = []
        missing = REQUIRED_FIELDS - case.keys()
        if missing:
            issues.append(
                ValidationIssue(
                    line=line_number,
                    message=f"missing required fields: {', '.join(sorted(missing))}",
                )
            )

        case_id = case.get("id")
        if not isinstance(case_id, str) or not case_id.strip():
            issues.append(ValidationIssue(line=line_number, message="id must be a non-empty string"))
        elif case_id in seen_ids:
            issues.append(
                ValidationIssue(
                    line=line_number,
                    message=f"duplicate id '{case_id}' first seen on line {seen_ids[case_id]}",
                )
            )
        else:
            seen_ids[case_id] = line_number

        suite = case.get("suite")
        if suite not in ALLOWED_SUITES:
            issues.append(
                ValidationIssue(
                    line=line_number,
                    message=f"suite must be one of {sorted(ALLOWED_SUITES)}",
                )
            )

        risk = case.get("risk")
        if risk not in ALLOWED_RISKS:
            issues.append(
                ValidationIssue(
                    line=line_number,
                    message=f"risk must be one of {sorted(ALLOWED_RISKS)}",
                )
            )

        for field_name in ("input", "expected", "metadata"):
            if field_name in case and not isinstance(case[field_name], dict):
                issues.append(
                    ValidationIssue(
                        line=line_number,
                        message=f"{field_name} must be a JSON object",
                    )
                )

        metadata = case.get("metadata")
        if isinstance(metadata, dict):
            missing_metadata = REQUIRED_METADATA_FIELDS - metadata.keys()
            if missing_metadata:
                issues.append(
                    ValidationIssue(
                        line=line_number,
                        message=(
                            "metadata missing required fields: "
                            f"{', '.join(sorted(missing_metadata))}"
                        ),
                    )
                )

        if case.get("risk") == "critical":
            expected = case.get("expected")
            if isinstance(expected, dict) and not self._has_hard_expectation(expected):
                issues.append(
                    ValidationIssue(
                        line=line_number,
                        message=(
                            "critical case needs outcome, forbidden_tools, "
                            "or deterministic_assertions"
                        ),
                    )
                )

        return issues

    @staticmethod
    def _has_hard_expectation(expected: dict[str, Any]) -> bool:
        hard_fields = ("outcome", "forbidden_tools", "deterministic_assertions")
        return any(field in expected and expected[field] not in (None, [], {}) for field in hard_fields)


def parse_args(argv: list[str]) -> argparse.Namespace:
    """Parse command-line arguments."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dataset", type=Path, help="Path to a JSONL eval dataset")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Run validation and return a process exit code."""

    args = parse_args(argv if argv is not None else sys.argv[1:])
    if not args.dataset.is_file():
        print(f"ERROR: dataset not found: {args.dataset}", file=sys.stderr)
        return 2

    issues = EvalDatasetValidator().validate(args.dataset)
    if issues:
        print(f"INVALID: {args.dataset}", file=sys.stderr)
        for issue in issues:
            print(f"- {issue.render()}", file=sys.stderr)
        return 1

    print(f"VALID: {args.dataset}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

