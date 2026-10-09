from __future__ import annotations


class ProviderRequestError(RuntimeError):
    """Expose a stable error code without the provider's response body."""

    def __init__(self, code: str, status: int = 503):
        super().__init__(code)
        self.code = code
        self.status = status
