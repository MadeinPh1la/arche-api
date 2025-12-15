# src/arche_api/domain/services/statement_ledger_delta_engine.py
# Copyright (c)
# SPDX-License-Identifier: MIT
"""Statement ledger delta engine.

Purpose:
    Provide deterministic, testable helpers to compute restatement deltas
    between successive normalized statement versions for a given identity
    tuple. This sits on top of canonical normalized payloads and the
    :mod:`edgar_restatement_delta` helpers.

Responsibilities:
    * Build a restatement "ledger" for a sequence of statement versions.
    * Compute a single restatement delta between two chosen versions.
    * Enforce minimal invariants around version ordering and availability.

Design:
    * Pure domain module – no logging, IO, or HTTP concerns.
    * Uses :class:`CanonicalStatementPayload` and :class:`RestatementDelta`
      as the primary value objects.
    * Surfaces domain-level errors via :class:`EdgarMappingError` and
      :class:`EdgarIngestionError`.

Layer:
    domain/services
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence

from arche_api.domain.entities.canonical_statement_payload import (
    CanonicalStatementPayload,
)
from arche_api.domain.entities.edgar_restatement_delta import (
    RestatementDelta,
    compute_restatement_delta,
)
from arche_api.domain.entities.edgar_statement_version import EdgarStatementVersion
from arche_api.domain.enums.canonical_statement_metric import CanonicalStatementMetric
from arche_api.domain.exceptions.edgar import EdgarIngestionError, EdgarMappingError


def _normalized_sorted_versions(
    versions: Sequence[EdgarStatementVersion],
) -> list[EdgarStatementVersion]:
    """Return versions with normalized payloads, sorted by version_sequence ASC."""
    normalized_versions = [v for v in versions if v.normalized_payload is not None]
    return sorted(normalized_versions, key=lambda v: v.version_sequence)


def _find_version_index(
    versions: Sequence[EdgarStatementVersion],
    target_sequence: int,
) -> int:
    """Locate the index of a version by version_sequence or raise EdgarMappingError."""
    for idx, v in enumerate(versions):
        if v.version_sequence == target_sequence:
            return idx

    raise EdgarMappingError(
        "Requested version_sequence not found for restatement delta.",
        details={"version_sequence": target_sequence},
    )


def _resolve_version_indices(
    *,
    versions: Sequence[EdgarStatementVersion],
    from_version_sequence: int | None,
    to_version_sequence: int | None,
) -> tuple[int, int]:
    """Resolve from/to indices for a restatement delta selection.

    Selection rules:
        * When both from_version_sequence and to_version_sequence are provided,
          those exact versions are used (and must be ordered correctly).
        * When only to_version_sequence is provided, the "from" version is the
          nearest earlier normalized version.
        * When only from_version_sequence is provided, the "to" version is the
          nearest later normalized version.
        * When neither is provided, the delta is computed between the two
          latest normalized versions.
    """
    count = len(versions)
    if count < 2:
        raise EdgarIngestionError(
            "At least two normalized statement versions are required to compute a restatement delta.",
        )

    # Both explicit
    if from_version_sequence is not None and to_version_sequence is not None:
        from_idx = _find_version_index(versions, from_version_sequence)
        to_idx = _find_version_index(versions, to_version_sequence)
        if from_idx >= to_idx:
            raise EdgarMappingError(
                "from_version_sequence must precede to_version_sequence for restatement delta.",
                details={
                    "from_version_sequence": from_version_sequence,
                    "to_version_sequence": to_version_sequence,
                },
            )
        return from_idx, to_idx

    # Only `to`
    if to_version_sequence is not None:
        to_idx = _find_version_index(versions, to_version_sequence)
        if to_idx == 0:
            raise EdgarMappingError(
                "No earlier normalized version available for requested to_version_sequence.",
                details={"to_version_sequence": to_version_sequence},
            )
        return to_idx - 1, to_idx

    # Only `from`
    if from_version_sequence is not None:
        from_idx = _find_version_index(versions, from_version_sequence)
        if from_idx >= count - 1:
            raise EdgarMappingError(
                "No later normalized version available for requested from_version_sequence.",
                details={"from_version_sequence": from_version_sequence},
            )
        return from_idx, from_idx + 1

    # Neither provided → latest pair
    to_idx = count - 1
    from_idx = to_idx - 1
    return from_idx, to_idx


def build_restatement_ledger(
    *,
    versions: Sequence[EdgarStatementVersion],
    metrics: Iterable[CanonicalStatementMetric] | None = None,
) -> list[RestatementDelta]:
    """Build a restatement ledger from a sequence of statement versions.

    The ledger is defined as the list of consecutive restatement deltas between
    successive normalized versions for the same (cik, statement_type,
    accounting_standard, statement_date, fiscal_year, fiscal_period, currency)
    identity.

    Behavior:
        * Versions lacking a ``normalized_payload`` are ignored.
        * Remaining versions are ordered by ``version_sequence`` ascending.
        * For each adjacent pair (v_n, v_n+1), a :class:`RestatementDelta`
          is produced via :func:`compute_restatement_delta`.
        * Identity mismatches between payloads are surfaced as
          :class:`EdgarMappingError` from :func:`compute_restatement_delta`.

    Args:
        versions:
            Sequence of :class:`EdgarStatementVersion` instances, typically
            returned from the EDGAR statements repository.
        metrics:
            Optional iterable of :class:`CanonicalStatementMetric` to restrict
            the delta computation to a subset of metrics. When ``None``,
            all intersecting metrics are considered.

    Returns:
        Ordered list of :class:`RestatementDelta` instances. If fewer than two
        versions expose a normalized payload, the ledger is empty.
    """
    sorted_versions = _normalized_sorted_versions(versions)
    if len(sorted_versions) < 2:
        return []

    metric_filter: Iterable[CanonicalStatementMetric] | None = (
        None if metrics is None else tuple(metrics)
    )

    deltas: list[RestatementDelta] = []

    for idx in range(len(sorted_versions) - 1):
        from_version = sorted_versions[idx]
        to_version = sorted_versions[idx + 1]

        # mypy: normalized_payload is guaranteed non-None for sorted_versions.
        from_payload: CanonicalStatementPayload = from_version.normalized_payload  # type: ignore[assignment]
        to_payload: CanonicalStatementPayload = to_version.normalized_payload  # type: ignore[assignment]

        delta = compute_restatement_delta(
            from_payload=from_payload,
            to_payload=to_payload,
            metrics=metric_filter,
        )
        deltas.append(delta)

    return deltas


def compute_restatement_delta_between_versions(
    *,
    versions: Sequence[EdgarStatementVersion],
    from_version_sequence: int | None = None,
    to_version_sequence: int | None = None,
    metrics: Iterable[CanonicalStatementMetric] | None = None,
) -> RestatementDelta:
    """Compute a restatement delta between two chosen statement versions.

    Selection rules:

        * When both ``from_version_sequence`` and ``to_version_sequence`` are
          provided, those exact versions are used.
        * When only ``to_version_sequence`` is provided, the "from" version
          is the nearest earlier normalized version.
        * When only ``from_version_sequence`` is provided, the "to" version
          is the nearest later normalized version.
        * When neither is provided, the delta is computed between the two
          latest normalized versions.

    All selection is performed on versions that have a non-None
    ``normalized_payload``. Identity mismatches between payloads are surfaced
    as :class:`EdgarMappingError` from :func:`compute_restatement_delta`.

    Args:
        versions:
            Sequence of :class:`EdgarStatementVersion` instances, typically
            returned from the EDGAR statements repository.
        from_version_sequence:
            Optional lower-bound version sequence (inclusive).
        to_version_sequence:
            Optional upper-bound version sequence (inclusive).
        metrics:
            Optional iterable of :class:`CanonicalStatementMetric` to restrict
            the delta computation to a subset of metrics. When ``None``,
            all intersecting metrics are considered.

    Returns:
        A single :class:`RestatementDelta` instance representing the
        restatement delta between the selected versions.

    Raises:
        EdgarIngestionError:
            If fewer than two normalized versions exist for the identity.
        EdgarMappingError:
            If the requested version sequences cannot be resolved, or the
            chosen pair does not have a valid ordering.
    """
    sorted_versions = _normalized_sorted_versions(versions)
    from_idx, to_idx = _resolve_version_indices(
        versions=sorted_versions,
        from_version_sequence=from_version_sequence,
        to_version_sequence=to_version_sequence,
    )

    from_version = sorted_versions[from_idx]
    to_version = sorted_versions[to_idx]

    from_payload: CanonicalStatementPayload = from_version.normalized_payload  # type: ignore[assignment]
    to_payload: CanonicalStatementPayload = to_version.normalized_payload  # type: ignore[assignment]

    metric_filter: Iterable[CanonicalStatementMetric] | None = (
        None if metrics is None else tuple(metrics)
    )

    return compute_restatement_delta(
        from_payload=from_payload,
        to_payload=to_payload,
        metrics=metric_filter,
    )
