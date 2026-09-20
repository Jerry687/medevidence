"""Closed catalog identities shared by source-neutral durable contracts."""

from typing import Final, Literal

CatalogVersion = Literal["m1a-concepts-v1", "m3.local-research-input.v1"]
M1A_CATALOG_HASH: Final = "sha256:eaffc3ee01ecd46a134578838b0304474642bf5e4a0c6e87302825d52be7682e"
LOCAL_RESEARCH_CATALOG_HASH: Final = (
    "sha256:60ad5de184b4ab9972ca6179e4df8fd0f56d8e6741852f48331b465772b0e4ba"
)


def validate_catalog_identity(version: str, content_hash: str) -> None:
    """Reject unknown catalogs and cross-version hash substitution."""
    if (version, content_hash) not in (
        ("m1a-concepts-v1", M1A_CATALOG_HASH),
        ("m3.local-research-input.v1", LOCAL_RESEARCH_CATALOG_HASH),
    ):
        raise ValueError("catalog version and content hash do not match an admitted identity")
