"""Immutable M1A ingestion contracts and storage."""

from .artifacts import (
    CapturedAcquisition,
    RawResponseObservation,
    SnapshotManifest,
    capture_acquisition,
    replay_manifest,
    response_observation,
)
from .contracts import (
    M1A_CANONICAL_JSON_V1,
    M1A_CONSTRAINED_V1,
    AcquisitionIntent,
    AcquisitionRegistrationEnvelope,
    ArtifactLink,
    RunIntent,
    RunRegistrationEnvelope,
    with_computed_identity,
)

__all__ = [
    "M1A_CANONICAL_JSON_V1",
    "M1A_CONSTRAINED_V1",
    "AcquisitionIntent",
    "AcquisitionRegistrationEnvelope",
    "ArtifactLink",
    "CapturedAcquisition",
    "RawResponseObservation",
    "RunIntent",
    "RunRegistrationEnvelope",
    "SnapshotManifest",
    "capture_acquisition",
    "replay_manifest",
    "response_observation",
    "with_computed_identity",
]
