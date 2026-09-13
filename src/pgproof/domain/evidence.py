"""Evidence contract.

The four labels in `docs/PRODUCT_SPEC.md` section 7 are the product's central
trust boundary, so they are a closed enum here and changing them requires an ADR
per `docs/ARCHITECTURE.md` section 16.
"""

from __future__ import annotations

from pgproof.domain.primitives import Contract, NonEmptyText, Sha256, SnakeCaseEnum
from pgproof.domain.sources import SourceRef


class EvidenceKind(SnakeCaseEnum):
    """What a statement is allowed to claim."""

    OBSERVED = "observed"
    USER_CONFIRMED = "user_confirmed"
    INFERRED = "inferred"
    VERIFIED_IN_FIXTURE = "verified_in_fixture"


class EvidenceRef(Contract):
    """An immutable citation.

    `verified_in_fixture` never means production behaviour; the fixture boundary
    travels with the claim in `fixture_scale` so a consumer cannot drop it.
    """

    id: NonEmptyText
    kind: EvidenceKind
    summary: NonEmptyText
    source: SourceRef | None = None
    content_hash: Sha256 | None = None
    fixture_scale: NonEmptyText | None = None


class EvidenceGraph(Contract):
    """Every citation the analysis produced, addressable by id."""

    refs: tuple[EvidenceRef, ...] = ()

    @property
    def ids(self) -> frozenset[str]:
        return frozenset(ref.id for ref in self.refs)
