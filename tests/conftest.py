"""Make the repository root importable so `evaluation` resolves in tests.

`medevidence` ships from `src/` and is installed by uv. The `evaluation`
package is a repository-level analysis tool rather than part of the
distribution, so it is not installed and needs the root on `sys.path`.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# The installed distribution stays authoritative. `src` is added only when
# `medevidence` is not importable, so packaging problems are not masked.
try:  # pragma: no cover - environment dependent
    import medevidence  # noqa: F401
except ImportError:  # pragma: no cover - environment dependent
    src = ROOT / "src"
    if str(src) not in sys.path:
        sys.path.insert(0, str(src))
