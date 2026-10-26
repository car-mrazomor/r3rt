import json as _json
import os
from urllib.parse import urlencode, urlsplit, urlunsplit

from ._ffi import ffi, lib
from .exceptions import ConnectionError, R3RTError
from .models import CaseInsensitiveDict, Response


# Methods that should always carry a body (empty if none given) so curl
# sends "Content-Length: 0" instead of nothing.
_BODY_METHODS = {"POST", "PUT", "PATCH"}

# Sent with every request; any header passed by the caller overrides these
# (keys are case-insensitive), and extra headers are simply added.
DEFAULT_HEADERS = {
    "User-Agent": "r3rt/0.1.0",
    "Accept": "*/*",
}


def _items(obj):
    """Accept a dict or a list of (key, value) pairs."""
    if obj is None:
        return []
    if isinstance(obj, dict):
        return list(obj.items())
    return list(obj)


def _to_bytes(value) -> bytes:
    if isinstance(value, bytes):
        return value
    if isinstance(value, (bytearray, memoryview)):
        return bytes(value)
    return str(value).encode()


def _build_url(url: str, params) -> str:
    params = _items(params)
    if not params:
        return url
    scheme, netloc, path, query, fragment = urlsplit(url)
    extra = urlencode(params, doseq=True)
    query = f"{query}&{extra}" if query else extra
    return urlunsplit((scheme, netloc, path, query, fragment))


def _read_file(field, value):
    """Normalise a `files` entry into (filename, bytes)."""
    if isinstance(value, tuple):
        filename, content = value[0], value[1]
    else:
        filename, content = None, value

    if hasattr(content, "read"):
        if filename is None:
            filename = os.path.basename(getattr(content, "name", "")) or None
        content = content.read()

    return filename or field, _to_bytes(content)


class _PreparedRequest(object):
    """Holds all cffi buffers for one call, so they stay alive until it returns."""

    def __init__(self, method, url, params, data, json, files, headers, cookies, auth):
        self.method = method.upper()
        self.url = _build_url(url, params)
        self.headers = CaseInsensitiveDict(DEFAULT_HEADERS)
        self.headers.update(headers or {})
        self._keep = []

        self.c_method = self._cstr(self.method)
        self.c_url = self._cstr(self.url)
        self.c_post_data = ffi.NULL
        self.c_files = ffi.NULL
        self.files_count = 0

        self._prepare_body(data, json, files)
        self._prepare_headers()
        self._prepare_cookies(cookies)
        self._prepare_auth(auth)

    def _cstr(self, value):
        if value is None:
            return ffi.NULL
        buf = ffi.new("char[]", _to_bytes(value))
        self._keep.append(buf)
        return buf

    def _prepare_body(self, data, json, files):
        if json is not None and (data is not None or files):
            raise ValueError("json cannot be combined with data or files")

        if files:
            self._prepare_files(data, files)
            return

        body = None
        if json is not None:
            body = _json.dumps(json).encode()
            self.headers.setdefault("Content-Type", "application/json")
        elif isinstance(data, (dict, list, tuple)):
            body = urlencode(_items(data), doseq=True).encode()
            self.headers.setdefault("Content-Type", "application/x-www-form-urlencoded")
        elif data is not None:
            body = _to_bytes(data)

        if body is None and self.method in _BODY_METHODS:
            body = b""

        if body is not None:
            if b"\0" in body:
                raise ValueError("request body cannot contain NUL bytes (it is sent as a C string)")
            self.c_post_data = self._cstr(body)

    def _prepare_files(self, data, files):
        if data is not None and not isinstance(data, (dict, list, tuple)):
            raise ValueError("data must be a dict or list of pairs when sending files")

        parts = []
        # Plain form fields go along as multipart parts without a filename,
        # because the C side ignores post_data once files are present.
        for k, v in _items(data):
            parts.append((k, None, _to_bytes(v)))
        for k, v in _items(files):
            filename, content = _read_file(k, v)
            parts.append((k, filename, content))

        self.c_files = ffi.new("UploadFile[]", len(parts))
        self._keep.append(self.c_files)
        for i, (field, filename, content) in enumerate(parts):
            buf = ffi.new("char[]", content)
            self._keep.append(buf)
            self.c_files[i].file_data = buf
            self.c_files[i].file_size = len(content)
            self.c_files[i].field_name = self._cstr(field)
            self.c_files[i].filename = self._cstr(filename)
        self.files_count = len(parts)

    def _prepare_headers(self):
        hdrs = [self._cstr(f"{k}: {v}") for k, v in self.headers.items()]
        self.c_headers = ffi.new("const char *[]", hdrs) if hdrs else ffi.NULL
        self._keep.append(self.c_headers)
        self.headers_count = len(hdrs)

    def _prepare_cookies(self, cookies):
        cookies = _items(cookies)
        self.c_cookies = self._cstr("; ".join(f"{k}={v}" for k, v in cookies)) if cookies else ffi.NULL

    def _prepare_auth(self, auth):
        if auth is None:
            self.c_auth = ffi.NULL
        elif isinstance(auth, (tuple, list)):
            user, passwd = auth
            self.c_auth = self._cstr(f"{user}:{passwd}")
        else:
            self.c_auth = self._cstr(auth)


def _parse_cookie_list(node) -> dict:
    """Turn libcurl's Netscape-format cookie list into {name: value}."""
    cookies = {}
    while node != ffi.NULL:
        line = ffi.string(node.data).decode(errors="replace")
        fields = line.split("\t")
        if len(fields) >= 7:
            cookies[fields[5]] = fields[6]
        node = node.next
    return cookies


def _perform(prep: _PreparedRequest) -> Response:
    c_resp = lib.http_request(
        prep.c_method, prep.c_url, prep.c_post_data, prep.c_cookies,
        prep.c_headers, prep.headers_count, prep.c_auth,
        prep.c_files, prep.files_count,
    )
    if c_resp == ffi.NULL:
        raise R3RTError("out of memory while creating the response")

    try:
        if c_resp.err_msg != ffi.NULL:
            msg = ffi.string(c_resp.err_msg).decode(errors="replace")
            raise ConnectionError(f"{msg} ({prep.method} {prep.url})")

        content = bytes(ffi.buffer(c_resp.body, c_resp.size)) if c_resp.body != ffi.NULL else b""
        raw_headers = (
            bytes(ffi.buffer(c_resp.headers, c_resp.header_size)).decode("iso-8859-1")
            if c_resp.headers != ffi.NULL else ""
        )
        return Response(
            url=prep.url,
            status_code=int(c_resp.status_code),
            content=content,
            raw_headers=raw_headers,
            cookies=_parse_cookie_list(c_resp.cookies),
        )
    finally:
        lib.free_response(c_resp)


def request(method: str, url: str, params=None, data=None, json=None, files=None,
            headers=None, cookies=None, auth=None) -> Response:
    """Send an HTTP request.

    params  -- dict / list of pairs, appended to the URL query string
    data    -- dict / list of pairs (form-encoded) or str / bytes (sent raw)
    json    -- any JSON-serialisable object; sets Content-Type: application/json
    files   -- {field: file_obj | bytes | (filename, file_obj_or_bytes)}, sent as multipart
    headers -- dict of request headers
    cookies -- dict of cookies to send
    auth    -- (user, password) tuple or "user:password"
    """
    if method.upper() == "HEAD":
        # libcurl would wait for a body that never comes, and the C lib
        # does not set CURLOPT_NOBODY.
        raise NotImplementedError("HEAD is not supported by the underlying C library")
    prep = _PreparedRequest(method, url, params, data, json, files, headers, cookies, auth)
    return _perform(prep)


def get(url, params=None, **kwargs) -> Response:
    return request("GET", url, params=params, **kwargs)


def options(url, **kwargs) -> Response:
    return request("OPTIONS", url, **kwargs)


def post(url, data=None, json=None, **kwargs) -> Response:
    return request("POST", url, data=data, json=json, **kwargs)


def put(url, data=None, **kwargs) -> Response:
    return request("PUT", url, data=data, **kwargs)


def patch(url, data=None, **kwargs) -> Response:
    return request("PATCH", url, data=data, **kwargs)


def delete(url, **kwargs) -> Response:
    return request("DELETE", url, **kwargs)


class Session(object):
    """Keeps headers, cookies and auth across requests."""

    def __init__(self):
        self.headers = CaseInsensitiveDict()
        self.cookies: dict = {}
        self.auth = None

    def request(self, method, url, headers=None, cookies=None, auth=None, **kwargs) -> Response:
        merged_headers = CaseInsensitiveDict(self.headers)
        merged_headers.update(headers or {})
        merged_cookies = {**self.cookies, **dict(_items(cookies))}

        resp = request(method, url, headers=merged_headers, cookies=merged_cookies or None,
                       auth=auth if auth is not None else self.auth, **kwargs)
        self.cookies.update(resp.cookies)
        return resp

    def get(self, url, params=None, **kwargs):
        return self.request("GET", url, params=params, **kwargs)

    def options(self, url, **kwargs):
        return self.request("OPTIONS", url, **kwargs)

    def post(self, url, data=None, json=None, **kwargs):
        return self.request("POST", url, data=data, json=json, **kwargs)

    def put(self, url, data=None, **kwargs):
        return self.request("PUT", url, data=data, **kwargs)

    def patch(self, url, data=None, **kwargs):
        return self.request("PATCH", url, data=data, **kwargs)

    def delete(self, url, **kwargs):
        return self.request("DELETE", url, **kwargs)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        pass
