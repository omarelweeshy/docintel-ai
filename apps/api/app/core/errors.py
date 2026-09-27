class AppError(Exception):
    def __init__(self, code: str, message: str, status: int = 400) -> None:
        self.code = code
        self.message = message
        self.status = status
        super().__init__(message)


class ProviderError(AppError):
    def __init__(self, message: str = "AI provider unavailable. Check configuration and retry."):
        super().__init__("provider_unavailable", message, 503)


class ParseError(AppError):
    def __init__(self, message: str):
        super().__init__("parse_failed", message, 422)
