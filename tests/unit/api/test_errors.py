"""Closed versioned error-envelope tests."""

from medevidence.api.errors import ERROR_SPECS, ApiErrorCode, error_response

REQUEST_ID = "request:00000000-0000-4000-8000-000000000001"


def test_every_error_code_uses_only_its_fixed_message_and_retryability() -> None:
    assert set(ERROR_SPECS) == set(ApiErrorCode)
    for code, (status, retryable, message) in ERROR_SPECS.items():
        response = error_response(code, REQUEST_ID)
        assert status in {422, 500, 502, 503, 504}
        assert response.error.code is code
        assert response.error.retryable is retryable
        assert response.error.message == message
        assert response.error.request_id == REQUEST_ID
        assert response.error.field_paths == ()


def test_field_paths_are_sorted_and_unique() -> None:
    response = error_response(
        ApiErrorCode.INVALID_REQUEST,
        REQUEST_ID,
        ("/z", "/a", "/z"),
    )
    assert response.error.field_paths == ("/a", "/z")
