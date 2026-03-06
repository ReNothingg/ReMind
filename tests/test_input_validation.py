import pytest

from utils.input_validation import InputValidator, ValidationError, safe_dict_access


@pytest.mark.parametrize(
    ("raw_username", "expected"),
    [
        ("  valid_user  ", "valid_user"),
        ("user-123", "user-123"),
    ],
)
def test_validate_username_accepts_expected_values(raw_username, expected):
    assert InputValidator.validate_username(raw_username) == expected


@pytest.mark.parametrize(
    "raw_username",
    [
        "",
        "ab",
        "bad user",
        "_starts_with_underscore",
        "-starts-with-hyphen",
    ],
)
def test_validate_username_rejects_invalid_values(raw_username):
    with pytest.raises(ValidationError):
        InputValidator.validate_username(raw_username)


def test_validate_password_enforces_strength_rules():
    assert InputValidator.validate_password("StrongPass1!") is True

    with pytest.raises(ValidationError, match="non-empty string"):
        InputValidator.validate_password("")

    with pytest.raises(ValidationError, match="at least 8 characters"):
        InputValidator.validate_password("Ab1!")

    with pytest.raises(ValidationError, match="too long"):
        InputValidator.validate_password("A" * 257 + "1!")

    with pytest.raises(ValidationError, match="one digit"):
        InputValidator.validate_password("NoDigits!")

    with pytest.raises(ValidationError, match="one special character"):
        InputValidator.validate_password("NoSpecial123")


def test_validate_url_accepts_http_and_https():
    assert InputValidator.validate_url("https://example.com/path") == "https://example.com/path"
    assert InputValidator.validate_url("http://example.com") == "http://example.com"


@pytest.mark.parametrize(
    ("raw_url", "message"),
    [
        ("ftp://example.com", "URL scheme must be one of"),
        ("https:///missing-host", "missing host"),
    ],
)
def test_validate_url_rejects_invalid_values(raw_url, message):
    with pytest.raises(ValidationError, match=message):
        InputValidator.validate_url(raw_url)


def test_validate_json_checks_shape_size_and_required_keys():
    payload = {"message": "hello", "count": 1}
    assert InputValidator.validate_json(payload, expected_keys=["message"]) == payload
    assert InputValidator.validate_json(["a", "b"]) == ["a", "b"]

    with pytest.raises(ValidationError, match="JSON object or array"):
        InputValidator.validate_json("not-json")

    with pytest.raises(ValidationError, match="Missing required key"):
        InputValidator.validate_json({"present": True}, expected_keys=["missing"])

    with pytest.raises(ValidationError, match="too large"):
        InputValidator.validate_json({"blob": "x" * 50}, max_size=10)


def test_validate_text_covers_normal_and_rejected_inputs():
    assert InputValidator.validate_text("  plain text  ") == "plain text"
    assert (
        InputValidator.validate_text("Hello world <b>ok</b>", allow_html=True)
        == "Hello world <b>ok</b>"
    )

    with pytest.raises(ValidationError, match="non-empty string"):
        InputValidator.validate_text("")

    with pytest.raises(ValidationError, match="1-5 characters"):
        InputValidator.validate_text("too long", max_length=5)

    with pytest.raises(ValidationError, match="dangerous patterns"):
        InputValidator.validate_text("UNION SELECT password FROM users")

    with pytest.raises(ValidationError, match="too many special characters"):
        InputValidator.validate_text("!@#$%^&*()<>?/|}{")

    with pytest.raises(ValidationError, match="HTML tags are not allowed"):
        InputValidator.validate_text("<script>alert(1)</script>")


def test_validate_chat_message_integer_boolean_and_session_id():
    assert InputValidator.validate_chat_message(" hello ") == "hello"
    assert InputValidator.validate_integer("7", min_val=1, max_val=10) == 7
    assert InputValidator.validate_boolean(True) is True
    assert InputValidator.validate_boolean("yes") is True
    assert InputValidator.validate_boolean("off") is False
    assert InputValidator.validate_session_id("session_id_1234567890") == "session_id_1234567890"

    with pytest.raises(ValidationError, match="cannot be empty"):
        InputValidator.validate_chat_message("   ")

    with pytest.raises(ValidationError, match="too long"):
        InputValidator.validate_chat_message("x" * 11, max_length=10)

    with pytest.raises(ValidationError, match="integer"):
        InputValidator.validate_integer("not-a-number")

    with pytest.raises(ValidationError, match="at least 5"):
        InputValidator.validate_integer(3, min_val=5)

    with pytest.raises(ValidationError, match="at most 2"):
        InputValidator.validate_integer(3, max_val=2)

    with pytest.raises(ValidationError, match="boolean"):
        InputValidator.validate_boolean("maybe")

    with pytest.raises(ValidationError, match="Invalid session ID format"):
        InputValidator.validate_session_id("short")


def test_sanitize_output_and_safe_dict_access_wrap_errors():
    assert InputValidator.sanitize_output("<b>unsafe</b>") == "&lt;b&gt;unsafe&lt;/b&gt;"
    assert InputValidator.sanitize_output(123) == "123"
    assert safe_dict_access({"page": "4"}, "page", validator=InputValidator.validate_integer) == 4
    assert safe_dict_access({"missing": 1}, "page", default=9) == 9

    with pytest.raises(ValidationError, match="page: Value must be an integer"):
        safe_dict_access({"page": "x"}, "page", validator=InputValidator.validate_integer)

    class BrokenMapping:
        def get(self, *_args, **_kwargs):
            raise RuntimeError("boom")

    with pytest.raises(ValidationError, match="page: Invalid value"):
        safe_dict_access(BrokenMapping(), "page")
