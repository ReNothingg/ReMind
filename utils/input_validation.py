import re
import json
from html import escape as html_escape
from urllib.parse import urlparse
from email_validator import validate_email, EmailNotValidError


class ValidationError(Exception):

    pass


class InputValidator:


    @staticmethod
    def validate_email(email):

        try:
            valid = validate_email(email)
            return valid.email
        except EmailNotValidError as e:
            raise ValidationError(f'Invalid email: {str(e)}')

    @staticmethod
    def validate_username(username, min_length=3, max_length=50):

        if not username or not isinstance(username, str):
            raise ValidationError('Username must be a non-empty string')

        username = username.strip()

        if len(username) < min_length or len(username) > max_length:
            raise ValidationError(f'Username must be {min_length}-{max_length} characters')
        if not re.match(r'^[a-zA-Z0-9_-]+$', username):
            raise ValidationError('Username can only contain letters, numbers, underscore, and hyphen')
        if username.startswith('_') or username.startswith('-'):
            raise ValidationError('Username cannot start with underscore or hyphen')

        return username

    @staticmethod
    def validate_password(password, min_length=8):

        if not password or not isinstance(password, str):
            raise ValidationError('Password must be a non-empty string')

        if len(password) < min_length:
            raise ValidationError(f'Password must be at least {min_length} characters')

        if len(password) > 256:
            raise ValidationError('Password is too long (max 256 characters)')
        if not re.search(r'\d', password):
            raise ValidationError('Password must contain at least one digit')

        if not re.search(r'[!@#$%^&*(),.?":{}|<>]', password):
            raise ValidationError('Password must contain at least one special character')

        return True

    @staticmethod
    def validate_url(url, allowed_schemes=None):

        if allowed_schemes is None:
            allowed_schemes = ['http', 'https']

        try:
            parsed = urlparse(url)
            if parsed.scheme not in allowed_schemes:
                raise ValidationError(f'URL scheme must be one of: {", ".join(allowed_schemes)}')
            if not parsed.netloc:
                raise ValidationError('Invalid URL: missing host')
            return url
        except Exception as e:
            raise ValidationError(f'Invalid URL: {str(e)}')

    @staticmethod
    def validate_json(data, expected_keys=None, max_size=1024*1024):

        if not isinstance(data, (dict, list)):
            raise ValidationError('Data must be a JSON object or array')
        json_str = json.dumps(data)
        if len(json_str) > max_size:
            raise ValidationError(f'JSON data too large (max {max_size} bytes)')
        if expected_keys and isinstance(data, dict):
            for key in expected_keys:
                if key not in data:
                    raise ValidationError(f'Missing required key: {key}')

        return data

    @staticmethod
    def validate_text(text, min_length=1, max_length=10000, allow_html=False):

        if not text or not isinstance(text, str):
            raise ValidationError('Text must be a non-empty string')

        text = text.strip()

        if len(text) < min_length or len(text) > max_length:
            raise ValidationError(f'Text must be {min_length}-{max_length} characters')
        dangerous_patterns = [
            r"'\s*or\s*'",
            r'"\s*or\s*"',
            r"union\s+select",
            r"drop\s+table",
            r"insert\s+into",
            r"update\s+",
            r"delete\s+from",
            r"exec\s*\(",
            r"execute\s*\(",
        ]

        text_lower = text.lower()
        for pattern in dangerous_patterns:
            if re.search(pattern, text_lower):
                raise ValidationError('Text contains potentially dangerous patterns')
        special_chars = sum(1 for c in text if not c.isalnum() and c not in ' \n\t\r.,!?-()[]{}:;"\'')
        if special_chars > len(text) * 0.3:  # More than 30% special chars
            raise ValidationError('Text contains too many special characters')

        if not allow_html and '<' in text and '>' in text:
            if re.search(r'<[^>]+>', text):
                raise ValidationError('HTML tags are not allowed')

        return text

    @staticmethod
    def validate_chat_message(message, max_length=32000):
        if not message or not isinstance(message, str):
            raise ValidationError('Message must be a non-empty string')

        message = message.strip()

        if len(message) > max_length:
            raise ValidationError(f'Message too long (max {max_length} characters)')

        if len(message) == 0:
            raise ValidationError('Message cannot be empty')

        return message

    @staticmethod
    def validate_integer(value, min_val=None, max_val=None):

        try:
            int_val = int(value)
        except (ValueError, TypeError):
            raise ValidationError('Value must be an integer')

        if min_val is not None and int_val < min_val:
            raise ValidationError(f'Value must be at least {min_val}')

        if max_val is not None and int_val > max_val:
            raise ValidationError(f'Value must be at most {max_val}')

        return int_val

    @staticmethod
    def validate_boolean(value):

        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            if value.lower() in ('true', '1', 'yes', 'on'):
                return True
            elif value.lower() in ('false', '0', 'no', 'off'):
                return False
        raise ValidationError('Value must be a boolean')

    @staticmethod
    def validate_session_id(session_id):

        if not session_id or not isinstance(session_id, str):
            raise ValidationError('Invalid session ID')
        if not re.match(r'^[a-zA-Z0-9_-]{20,200}$', session_id):
            raise ValidationError('Invalid session ID format')

        return session_id

    @staticmethod
    def sanitize_output(text):

        if not isinstance(text, str):
            return str(text)
        return html_escape(text)


def safe_dict_access(data, key, default=None, validator=None):

    try:
        value = data.get(key, default)
        if validator and value is not None:
            value = validator(value)
        return value
    except ValidationError as e:
        raise ValidationError(f'{key}: {str(e)}')
    except Exception as e:
        raise ValidationError(f'{key}: Invalid value')
