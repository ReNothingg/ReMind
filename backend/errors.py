from dataclasses import dataclass
from typing import Any, Optional


@dataclass
class ApiError(Exception):
    message: str
    status: int = 400
    code: str = "bad_request"
    extra: Optional[dict[str, Any]] = None
