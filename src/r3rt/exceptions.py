class R3RTError(Exception):
    """Base class for every r3rt error."""


class ConnectionError(R3RTError):
    """The request failed inside libcurl (DNS, connect, TLS, ...)."""


class HTTPError(R3RTError):
    """Raised by Response.raise_for_status() for 4xx/5xx responses."""

    def __init__(self, message: str, response=None):
        super().__init__(message)
        self.response = response
