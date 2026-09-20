"""Errors raised while loading and validating Checkgram configuration."""


class ConfigError(ValueError):
    """A user-actionable configuration error with a TOML path."""

    def __init__(self, path: str, message: str) -> None:
        self.path = path
        self.message = message
        super().__init__(f"{path}: {message}")


class AuthError(RuntimeError):
    """An authentication or session-storage error safe to show to an operator."""
