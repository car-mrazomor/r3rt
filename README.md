# r3rt

A small requests-style HTTP client: a Python wrapper (cffi) around a libcurl C library.

## Build the C library

Requires libcurl (preinstalled on macOS; `apt install libcurl4-openssl-dev` on Debian/Ubuntu).

```sh
# macOS
cc -shared -fPIC -o src/r3rt/_lib/librequest.dylib lib/http_request.c -lcurl

# Linux
cc -shared -fPIC -o src/r3rt/_lib/librequest.so lib/http_request.c -lcurl

# Windows (MinGW, with curl installed)
gcc -shared -o src/r3rt/_lib/librequest.dll lib/http_request.c -lcurl
```

## Install

Either copy the `src/r3rt/` folder next to your code, or:

```sh
uv pip install /path/to/my-own-requests
```

## Usage

```python
import r3rt

r = r3rt.get("https://httpbin.org/get", params={"q": 1}, headers={"X-A": "b"})
r = r3rt.post(url, data={"k": "v"})                 # form
r = r3rt.post(url, json={"k": "v"})                 # JSON
r = r3rt.post(url, files={"f": open("a.jpg", "rb")})  # multipart
r = r3rt.put(url, data="raw")
r = r3rt.delete(url, auth=("user", "pass"), cookies={"c": "v"})

r.status_code, r.ok, r.headers, r.cookies, r.text, r.content, r.json()
r.raise_for_status()

with r3rt.Session() as s:  # keeps headers, cookies, auth
    s.get(url)
```

Not supported: `HEAD`, timeouts, request bodies containing NUL bytes.
