"""
Unit tests for tools.muscle.adapters.http_utils.redact_secrets.

Table-driven cases covering: Bearer tokens, GitHub PATs (ghp_*),
GitLab PATs (glpat_*), Authorization header lines, and token= query strings.
Each case asserts the original secret value is absent and a placeholder present.
"""

from __future__ import annotations

import pytest

from tools.muscle.adapters.http_utils import redact_secrets

REDACTED = "***REDACTED***"

# (description, input_text, secret_that_must_not_appear)
REDACT_CASES: list[tuple[str, str, str]] = [
    # --- Bearer tokens ---
    (
        "bearer_lowercase",
        "bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.payload.sig",
        "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.payload.sig",
    ),
    (
        "bearer_uppercase",
        "Authorization: Bearer ABCDEF1234567890abcdef",
        "ABCDEF1234567890abcdef",
    ),
    (
        "bearer_mixed_case",
        "BEARER MyS3cr3tT0ken12345",
        "MyS3cr3tT0ken12345",
    ),
    # --- GitHub PATs ---
    (
        "ghp_token",
        "token: ghp_abcdefghijklmnopqrstu",
        "ghp_abcdefghijklmnopqrstu",
    ),
    (
        "gho_token",
        "Authorization header value: gho_1234567890abcdefghij",
        "gho_1234567890abcdefghij",
    ),
    (
        "ghu_token",
        "ghu_AAAAAAAAAAAAAAAAAAAAAA extra context",
        "ghu_AAAAAAAAAAAAAAAAAAAAAA",
    ),
    (
        "ghs_token",
        "ghs_BBBBBBBBBBBBBBBBBBBBBB",
        "ghs_BBBBBBBBBBBBBBBBBBBBBB",
    ),
    (
        "ghr_token",
        "ghr_CCCCCCCCCCCCCCCCCCCCCC",
        "ghr_CCCCCCCCCCCCCCCCCCCCCC",
    ),
    # --- GitLab PATs ---
    (
        "glpat_token",
        "glpat_DDDDDDDDDDDDDDDDDDDDDD",
        "glpat_DDDDDDDDDDDDDDDDDDDDDD",
    ),
    (
        "glpat_in_url",
        "https://gitlab.com/api?private_token=glpat_EEEEEEEEEEEEEEEEEEEEEE",
        "glpat_EEEEEEEEEEEEEEEEEEEEEE",
    ),
    # --- Authorization header lines ---
    (
        "auth_header_bearer",
        "Authorization: Bearer sk-live-abcdef1234567890",
        "sk-live-abcdef1234567890",
    ),
    (
        "auth_header_token_param",
        "Authorization: token ghp_1111111111111111111111",
        "ghp_1111111111111111111111",
    ),
    # --- token= query strings ---
    (
        "token_query_param",
        "GET /api/endpoint?token=supersecretvalue123456",
        "supersecretvalue123456",
    ),
    (
        "api_key_param",
        "POST /api?api_key=myapikey1234567890abcd",
        "myapikey1234567890abcd",
    ),
    (
        "access_token_param",
        "access_token=verylongsecrettoken12345",
        "verylongsecrettoken12345",
    ),
    (
        "secret_param",
        "secret=mysecretvalue1234567890",
        "mysecretvalue1234567890",
    ),
    (
        "password_param",
        "password=mypassword12345678",
        "mypassword12345678",
    ),
]


@pytest.mark.parametrize("description,text,secret", REDACT_CASES, ids=[c[0] for c in REDACT_CASES])
def test_redact_secrets_removes_secret(description: str, text: str, secret: str) -> None:
    """redact_secrets must not leave the raw secret in the output."""
    result = redact_secrets(text)
    assert secret not in result, (
        f"[{description}] Secret '{secret}' still present in redacted output: {result!r}"
    )
    assert REDACTED in result, (
        f"[{description}] Placeholder '{REDACTED}' missing from output: {result!r}"
    )


def test_redact_secrets_none_input() -> None:
    """None input should return an empty string without raising."""
    assert redact_secrets(None) == ""


def test_redact_secrets_empty_string() -> None:
    """Empty string should pass through unchanged."""
    assert redact_secrets("") == ""


def test_redact_secrets_no_secret_unchanged() -> None:
    """Strings without secrets should not be modified."""
    plain = "This is a plain log message with no secrets."
    assert redact_secrets(plain) == plain


def test_redact_secrets_preserves_non_secret_prefix() -> None:
    """The non-secret prefix of a Bearer line is preserved."""
    text = "Authorization: Bearer secret1234567890abcdef"
    result = redact_secrets(text)
    assert "Authorization:" in result
    assert "Bearer" in result
    assert "secret1234567890abcdef" not in result


def test_redact_secrets_multiple_tokens_in_one_string() -> None:
    """All secrets in a multi-token string must be redacted."""
    text = (
        "ghp_AAAAAAAAAAAAAAAAAAAAAA and also bearer TOKEN1234567890abcdef "
        "and token=ANOTHERTOKEN12345678"
    )
    result = redact_secrets(text)
    assert "ghp_AAAAAAAAAAAAAAAAAAAAAA" not in result
    assert "TOKEN1234567890abcdef" not in result
    assert "ANOTHERTOKEN12345678" not in result
    assert result.count(REDACTED) >= 2
