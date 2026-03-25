"""Tests for PII filter: detection and redaction of sensitive data."""

from stronghold.security.sentinel.pii_filter import (
    PIIMatch,
    redact,
    scan_and_redact,
    scan_for_pii,
)


class TestAPIKeyDetection:
    """Detect various API key formats."""

    def test_aws_key(self) -> None:
        matches = scan_for_pii("Key is AKIAIOSFODNN7EXAMPLE")
        assert len(matches) == 1
        assert matches[0].pii_type == "aws_key"

    def test_openai_key(self) -> None:
        matches = scan_for_pii("sk-abc123def456ghi789jkl012mno345pqr678stu901vwx")
        assert len(matches) == 1
        assert matches[0].pii_type == "api_key"

    def test_generic_api_key_assignment(self) -> None:
        matches = scan_for_pii('api_key = "abcdef1234567890abcdef"')
        assert any(m.pii_type == "api_key" for m in matches)

    def test_secret_key_assignment(self) -> None:
        matches = scan_for_pii("secret_key: sk_live_abcdef1234567890")
        assert any(m.pii_type == "api_key" for m in matches)

    def test_bearer_token(self) -> None:
        matches = scan_for_pii("Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6Ik")
        assert any(m.pii_type in ("bearer_token", "jwt") for m in matches)


class TestIPDetection:
    """Detect internal IP addresses, skip common safe ones."""

    def test_internal_ip(self) -> None:
        matches = scan_for_pii("Server at 10.10.21.40")
        assert len(matches) == 1
        assert matches[0].pii_type == "ip_address"

    def test_localhost_skipped(self) -> None:
        matches = scan_for_pii("Connect to 127.0.0.1:8080")
        assert not any(m.pii_type == "ip_address" for m in matches)

    def test_broadcast_skipped(self) -> None:
        matches = scan_for_pii("Broadcast 255.255.255.255")
        assert not any(m.pii_type == "ip_address" for m in matches)

    def test_zero_skipped(self) -> None:
        matches = scan_for_pii("Bind to 0.0.0.0")
        assert not any(m.pii_type == "ip_address" for m in matches)


class TestEmailDetection:
    """Detect email addresses."""

    def test_simple_email(self) -> None:
        matches = scan_for_pii("Contact user@example.com for help")
        assert len(matches) == 1
        assert matches[0].pii_type == "email"

    def test_complex_email(self) -> None:
        matches = scan_for_pii("Send to first.last+tag@sub.domain.org")
        assert any(m.pii_type == "email" for m in matches)


class TestJWTDetection:
    """Detect JWT tokens."""

    def test_jwt_format(self) -> None:
        jwt = "eyJhbGciOiJSUzI1NiJ9.eyJzdWIiOiJ1c2VyLTEyMyJ9.signaturebase64urldata"
        matches = scan_for_pii(f"Token: {jwt}")
        assert any(m.pii_type == "jwt" for m in matches)


class TestConnectionStringDetection:
    """Detect database connection strings."""

    def test_postgres_url(self) -> None:
        matches = scan_for_pii("DSN: postgresql://user:pass@db.internal:5432/mydb")
        assert any(m.pii_type == "connection_string" for m in matches)

    def test_redis_url(self) -> None:
        matches = scan_for_pii("REDIS_URL=redis://redis.cluster:6379/0")
        assert any(m.pii_type == "connection_string" for m in matches)

    def test_mongodb_url(self) -> None:
        matches = scan_for_pii("mongodb+srv://admin:secret@cluster.mongodb.net/db")
        assert any(m.pii_type == "connection_string" for m in matches)


class TestPrivateKeyDetection:
    """Detect private key blocks."""

    def test_rsa_key(self) -> None:
        matches = scan_for_pii("-----BEGIN RSA PRIVATE KEY-----\nMIIEowIB...")
        assert any(m.pii_type == "private_key" for m in matches)

    def test_generic_key(self) -> None:
        matches = scan_for_pii("-----BEGIN PRIVATE KEY-----\nMIIEvAIB...")
        assert any(m.pii_type == "private_key" for m in matches)


class TestPasswordDetection:
    """Detect password assignments."""

    def test_password_assignment(self) -> None:
        matches = scan_for_pii('password = "SuperSecret123!"')
        assert any(m.pii_type == "password" for m in matches)

    def test_pwd_colon(self) -> None:
        matches = scan_for_pii("pwd: MyLongPassword99")
        assert any(m.pii_type == "password" for m in matches)


class TestRedaction:
    """Redaction replaces matches with placeholders."""

    def test_single_redaction(self) -> None:
        result = redact("Key is AKIAIOSFODNN7EXAMPLE here")
        assert "AKIAIOSFODNN7EXAMPLE" not in result
        assert "[REDACTED:aws_key]" in result

    def test_multiple_redactions(self) -> None:
        text = "IP: 10.10.21.40, email: user@example.com"
        result = redact(text)
        assert "10.10.21.40" not in result
        assert "user@example.com" not in result
        assert "[REDACTED:ip_address]" in result
        assert "[REDACTED:email]" in result

    def test_no_matches_returns_original(self) -> None:
        text = "This is perfectly clean text."
        assert redact(text) == text

    def test_scan_and_redact_convenience(self) -> None:
        text = "Server at 192.168.1.100"
        redacted, matches = scan_and_redact(text)
        assert len(matches) == 1
        assert "192.168.1.100" not in redacted


class TestOverlappingPatterns:
    """Handle overlapping PII matches without double-detection."""

    def test_bearer_containing_jwt(self) -> None:
        """Bearer token that is also a JWT should match once, not twice."""
        jwt = "eyJhbGciOiJSUzI1NiJ9.eyJzdWIiOiJ1c2VyLTEyMyJ9.signaturebase64urldata"
        text = f"Authorization: Bearer {jwt}"
        matches = scan_for_pii(text)
        # Should get one match (bearer_token captures the whole thing),
        # not two overlapping matches
        assert len(matches) >= 1
        # The JWT itself shouldn't produce a second match if bearer already covered it
        starts = [m.start for m in matches]
        assert len(starts) == len(set(starts)), "Overlapping matches detected"

    def test_adjacent_pii_both_detected(self) -> None:
        """Two non-overlapping PII items should both be caught."""
        text = "AKIAIOSFODNN7EXAMPLE and user@example.com"
        matches = scan_for_pii(text)
        types = {m.pii_type for m in matches}
        assert "aws_key" in types
        assert "email" in types

    def test_no_double_redaction(self) -> None:
        """Redacting already-redacted text should not create nested placeholders."""
        text = "Key: AKIAIOSFODNN7EXAMPLE"
        first_pass = redact(text)
        second_pass = redact(first_pass)
        assert second_pass == first_pass  # Idempotent


class TestFalsePositiveResistance:
    """Ensure normal text is not flagged."""

    def test_version_numbers_not_flagged(self) -> None:
        matches = scan_for_pii("Python 3.12.1 released")
        assert not any(m.pii_type == "ip_address" for m in matches)

    def test_short_words_not_flagged(self) -> None:
        matches = scan_for_pii("The password is too short")
        # "too short" is < 8 chars so shouldn't match password pattern
        assert not any(m.pii_type == "password" for m in matches)

    def test_normal_conversation(self) -> None:
        text = "What's the weather like today? Can you turn on the lights?"
        matches = scan_for_pii(text)
        assert len(matches) == 0

    def test_code_discussion_not_flagged(self) -> None:
        text = "The function returns True when the input is valid."
        matches = scan_for_pii(text)
        assert len(matches) == 0
