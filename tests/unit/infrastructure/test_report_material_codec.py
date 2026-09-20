"""Closed, reproducible report material JSON without dynamic class loading."""

from __future__ import annotations

import json
import os
import subprocess
import sys

import pytest
from tests.unit.tools.test_report_document import _passed, _provenance

from medevidence.infrastructure.report_material_codec import (
    ReportMaterialError,
    decode_provenance,
    decode_report_request,
    encode_provenance,
    encode_report_request,
)


def test_request_and_provenance_rebuild_exact_typed_values() -> None:
    request, _ = _passed()
    request_json = encode_report_request(request)
    provenance = _provenance(request)
    provenance_json = encode_provenance(provenance)
    assert decode_report_request(request_json) == request
    assert decode_provenance(provenance_json) == provenance
    assert encode_report_request(decode_report_request(request_json)) == request_json
    assert encode_provenance(decode_provenance(provenance_json)) == provenance_json


def test_duplicate_extra_coerced_and_oversize_request_json_fail_closed() -> None:
    request, _ = _passed()
    raw = encode_report_request(request)
    payload = json.loads(raw)
    with pytest.raises(ReportMaterialError, match="duplicate"):
        decode_report_request('{"run_id":"first","run_id":"second"}')
    with pytest.raises(ReportMaterialError, match="canonical typed"):
        decode_report_request(json.dumps({**payload, "unexpected": "value"}))
    payload["scope"]["max_pages"] = "1"
    with pytest.raises(ReportMaterialError, match="typed schema"):
        decode_report_request(json.dumps(payload))
    with pytest.raises(ReportMaterialError, match="byte bound"):
        decode_report_request(" " * 16_777_217)


def test_unordered_evidence_permissions_have_stable_cross_process_json() -> None:
    script = (
        "from tests.unit.tools.test_report_document import _passed; "
        "from medevidence.infrastructure.report_material_codec import encode_report_request; "
        "from medevidence.domain import sha256_digest; "
        "request,_=_passed(); print(sha256_digest(encode_report_request(request)))"
    )
    digests = []
    for seed in ("1", "2", "991"):
        env = {**os.environ, "PYTHONHASHSEED": seed, "UV_OFFLINE": "1"}
        result = subprocess.run(
            [sys.executable, "-c", script],
            env=env,
            capture_output=True,
            text=True,
            timeout=20,
            check=True,
        )
        digests.append(result.stdout.strip())
    assert len(set(digests)) == 1
