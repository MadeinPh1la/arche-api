# src/stacklion_api/domain/value_objects/value_objects.py
"""Principal and other Value Objects (Domain Layer).

Purpose:
    Represent core domain value objects in a transport-agnostic, domain-friendly
    form. These objects are intentionally small and immutable, and they do not
    embed any adapter or infrastructure concerns (e.g., HTTP, JWT, DB).

Design:
    - Value Object semantics: immutable, hashable, equality by value.
    - Validation via Pydantic v2 for Principal; simple dataclass for lightweight
      identity tuples.
    - Interoperability: simple fields that map cleanly from common IdP claims
      or statement identity tuples.

Layer:
    domain/value_objects
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

__all__ = ["Principal"]


class Principal(BaseModel):
    """Authenticated actor value object.

    This value object is used across domain/application layers to represent the
    current actor. It is designed to be independent of the transport or identity
    provider used to authenticate the request.

    Attributes:
        subject: Stable external identifier for the actor (e.g., user or service ID).
        email: Optional email address of the actor, if known and applicable.
        roles: Normalized, duplicate-free list of role names (strings).
    """

    model_config = ConfigDict(
        title="Principal",
        frozen=True,  # value-object semantics (immutable instances)
        extra="forbid",  # no undeclared fields
        populate_by_name=True,
        str_strip_whitespace=True,
        json_schema_extra={
            "description": (
                "Authenticated actor (human or service) represented as a " "domain value object."
            ),
            "examples": [
                {
                    "subject": "user_2a9f3c",
                    "email": "analyst@example.com",
                    "roles": ["ANALYST", "READONLY"],
                }
            ],
        },
    )

    subject: str | None = Field(
        default=None,
        description="Stable external identifier for the actor (e.g., user or service account ID).",
        min_length=1,
    )
    email: str | None = Field(
        default=None,
        description="Primary email address for the actor, when applicable.",
    )
    roles: list[str] = Field(
        default_factory=list,
        description="Normalized, duplicate-free list of role names assigned to the actor.",
        examples=[["ADMIN", "TRADER"]],
    )

    # -------------------------------------------------------------------------
    # Validators
    # -------------------------------------------------------------------------
    @field_validator("roles", mode="before")
    @classmethod
    def _normalize_roles(cls, v: Any) -> list[str]:
        """Normalize roles input to a deduplicated list of strings.

        - Accepts None, a single string, or an iterable of strings.
        - Preserves original case (no lower/upper transforms).
        - Removes duplicates while preserving the first-seen order.

        Args:
            v: Raw value provided for the `roles` field.

        Returns:
            List[str]: Deduplicated list of role names.

        Raises:
            TypeError: If the provided value cannot be coerced to a list of strings.
        """
        if v is None or v == "":
            return []
        if isinstance(v, str):
            return [v]

        try:
            dedup: list[str] = []
            seen: set[str] = set()
            for item in v:
                s = str(item)
                if s not in seen:
                    seen.add(s)
                    dedup.append(s)
            return dedup
        except Exception as exc:  # pragma: no cover - defensive
            raise TypeError("roles must be a string or iterable of strings") from exc

    # -------------------------------------------------------------------------
    # Convenience
    # -------------------------------------------------------------------------
    @property
    def is_authenticated(self) -> bool:
        """Return True if the principal has a non-empty `subject`.

        Returns:
            bool: True when `subject` is present; otherwise False.
        """
        return bool(self.subject)

    @classmethod
    def from_claims(cls, claims: dict[str, Any]) -> Principal:
        """Create a Principal from IdP claims (e.g., JWT).

        This helper extracts common keys without binding the domain model to a
        particular identity provider. Unknown claim fields are ignored.

        Extraction rules:
            - subject: `sub`
            - email: `email` or `primary_email`
            - roles: `roles` or `org_roles`

        Args:
            claims: Mapping of claims as decoded from an identity token.

        Returns:
            Principal: Constructed value object based on the provided claims.
        """
        subject = claims.get("sub")
        email = claims.get("email") or claims.get("primary_email")
        roles = claims.get("roles") or claims.get("org_roles") or []
        return cls(subject=subject, email=email, roles=roles)
