"""Disabled FAERS live smoke placeholder; no medical-source request is authorized."""

import pytest

pytestmark = [
    pytest.mark.live_api,
    pytest.mark.skip(
        reason=(
            "FAERS live smoke requires a separate exact one-run Owner authorization; "
            "M1B-FAERS-003 is offline-only."
        )
    ),
]


def test_live_faers_requires_separate_owner_authorization() -> None:
    """Remain skipped until an exact identity/path/time-bound run is authorized."""
