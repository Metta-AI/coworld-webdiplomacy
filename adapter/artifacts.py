"""Local atomic writes and HTTP artifact transfer."""

import os
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import Request, url2pathname, urlopen


def local_path(uri):
    parsed = urlparse(uri)
    if parsed.scheme != "file":
        raise ValueError(f"Expected a file artifact URI: {uri}")
    return Path(url2pathname(parsed.path))


def read_artifact(uri):
    if urlparse(uri).scheme in ("http", "https"):
        with urlopen(Request(uri), timeout=30) as response:
            return response.read()
    return local_path(uri).read_bytes()


def write_artifact(uri, data, method_env):
    if urlparse(uri).scheme in ("http", "https"):
        method = os.environ.get(method_env, "PUT").upper()
        if method not in ("POST", "PUT"):
            raise ValueError(f"{method_env} must be PUT or POST")
        request = Request(uri, data=data, method=method, headers={"Content-Type": "application/json"})
        with urlopen(request, timeout=60):
            return
    target = local_path(uri)
    temporary = target.with_name(target.name + ".tmp")
    temporary.write_bytes(data)
    temporary.replace(target)
