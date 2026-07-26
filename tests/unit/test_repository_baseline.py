"""Unit checks for the approved repository toolchain baseline."""

import sys

import medevidence


def test_exact_python_runtime() -> None:
    """The local and CI runtime must use the approved Python patch."""
    assert sys.version_info[:3] == (3, 12, 13)


def test_package_metadata_is_importable() -> None:
    """The source-layout package must be installed by the locked bootstrap."""
    assert medevidence.__version__ == "0.0.0"
