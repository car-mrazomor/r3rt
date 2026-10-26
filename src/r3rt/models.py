import json as _json
from http import HTTPStatus
from collections.abc import MutableMapping

from .exceptions import HTTPError


class CaseInsensitiveDict(MutableMapping):
    """Dict with case-insensitive keys, used for HTTP headers."""

    def __init__(self, data=None, **kwargs):
        self._store: dict = {}
        self.update(data or {}, **kwargs)

    def __setitem__(self, key, value):
        self._store[key.lower()] = (key, value)

    def __getitem__(self, key):
        return self._store[key.lower()][1]

    def __delitem__(self, key):
        del self._store[key.lower()]

    def __iter__(self):
        return (key for key, _ in self._store.values())

    def __len__(self):
        return len(self._store)

    def __repr__(self):
        return repr(dict(self.items()))


class Response(object):
    def __init__(self, url: str, status_code: int, content: bytes, raw_headers: str, cookies: dict):
        self.url = url
        self.status_code = status_code
        self.content = content
        self.raw_headers = raw_headers
        self.cookies = cookies
        self.reason = ""
        self.headers = CaseInsensitiveDict()
        self._parse_headers(raw_headers)

    def _parse_headers(self, raw: str):
        # With redirects / "100 Continue" libcurl hands us several header
        # blocks back to back; only the last one belongs to this response.
        blocks = [b for b in raw.replace("\r\n", "\n").split("\n\n") if b.strip()]
        if not blocks:
            return

        status_line, *lines = blocks[-1].split("\n")
        parts = status_line.split(" ", 2)
        if len(parts) == 3:
            self.reason = parts[2].strip()
        if not self.reason:
            # HTTP/2 status lines carry no reason phrase.
            try:
                self.reason = HTTPStatus(self.status_code).phrase
            except ValueError:
                pass

        for line in lines:
            if ":" not in line:
                continue
            k, v = line.split(":", 1)
            k, v = k.strip(), v.strip()
            if k in self.headers:
                self.headers[k] = f"{self.headers[k]}, {v}"
            else:
                self.headers[k] = v

    @property
    def encoding(self) -> str:
        content_type = self.headers.get("content-type", "")
        for param in content_type.split(";")[1:]:
            k, _, v = param.strip().partition("=")
            if k.lower() == "charset" and v:
                return v.strip("\"'")
        return "utf-8"

    @property
    def text(self) -> str:
        try:
            return self.content.decode(self.encoding, errors="replace")
        except LookupError:
            return self.content.decode("utf-8", errors="replace")

    def json(self, **kwargs):
        return _json.loads(self.content, **kwargs)

    @property
    def ok(self) -> bool:
        return self.status_code < 400

    def raise_for_status(self):
        if 400 <= self.status_code < 500:
            kind = "Client Error"
        elif 500 <= self.status_code < 600:
            kind = "Server Error"
        else:
            return
        raise HTTPError(f"{self.status_code} {kind}: {self.reason} for url: {self.url}", response=self)

    def __bool__(self):
        return self.ok

    def __repr__(self):
        return f"<Response [{self.status_code}]>"
