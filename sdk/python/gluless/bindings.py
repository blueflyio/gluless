"""Utility -> ExecutableBinding resolution and HTTP execution.

Security posture:
  * Path parameters are percent-encoded (no traversal via "../").
  * Only declared body properties are sent; path/query inputs never leak into a body.
  * Headers (auth) come from the resolver, sourced by the caller from an external
    secret provider. Header values are never included in results, evidence or errors.
  * Every request has a timeout.
"""
import json
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from gluless.models import Utility

DEFAULT_TIMEOUT_SECONDS = 30.0


@dataclass
class ExecutableBinding:
    server: str
    method: str
    path: str
    parameters: List[Dict[str, Any]] = field(default_factory=list)
    request_body: Optional[Dict[str, Any]] = None
    responses: Dict[str, Any] = field(default_factory=dict)
    headers: Dict[str, str] = field(default_factory=dict)
    timeout: float = DEFAULT_TIMEOUT_SECONDS

    def build_request(self, inputs: Dict[str, Any]) -> urllib.request.Request:
        path_names = {p["name"] for p in self.parameters if p.get("in") == "path"}
        query_names = {p["name"] for p in self.parameters if p.get("in") == "query"}

        missing = [n for n in path_names if n not in inputs]
        if missing:
            raise ValueError(f"Missing path parameter(s) {missing} for {self.method} {self.path}")

        url_path = self.path
        query: Dict[str, str] = {}
        for name, val in inputs.items():
            if name in path_names:
                url_path = url_path.replace("{" + name + "}", urllib.parse.quote(str(val), safe=""))
            elif name in query_names:
                query[name] = str(val)

        url = self.server.rstrip("/") + url_path
        if query:
            url += "?" + urllib.parse.urlencode(query)

        headers = dict(self.headers)
        data: Optional[bytes] = None
        if self.method.upper() in ("POST", "PUT", "PATCH"):
            headers["Content-Type"] = "application/json"
            if isinstance(self.request_body, dict) and isinstance(self.request_body.get("properties"), dict):
                payload = {k: inputs[k] for k in self.request_body["properties"] if k in inputs}
            else:
                payload = {k: v for k, v in inputs.items() if k not in path_names and k not in query_names}
            data = json.dumps(payload).encode("utf-8")
        return urllib.request.Request(url, data=data, headers=headers, method=self.method.upper())

    def execute(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        try:
            req = self.build_request(inputs)
        except ValueError as e:
            return {"status_code": 0, "body": {}, "error": str(e)}
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as response:
                return {"status_code": response.status, "body": _parse_body(response.read())}
        except urllib.error.HTTPError as e:
            return {"status_code": e.code, "body": _parse_body(e.read()), "error": f"HTTP {e.code}: {e.reason}"}
        except urllib.error.URLError as e:
            return {"status_code": 0, "body": {}, "error": f"transport error: {e.reason}"}
        except TimeoutError:
            return {"status_code": 0, "body": {}, "error": f"timeout after {self.timeout}s"}
        except OSError as e:
            return {"status_code": 0, "body": {}, "error": f"transport error: {e.__class__.__name__}"}


def _parse_body(raw: bytes) -> Any:
    text = raw.decode("utf-8", errors="replace")
    if not text:
        return None
    try:
        return json.loads(text)
    except ValueError:
        return text


class UtilityResolver:
    """
    Resolves a semantic Utility to an ExecutableBinding.

    server_url: full base URL including any path prefix (http://host:8000/v0).
                If omitted, the first server declared by the Utility's source
                document is used.
    headers:    static headers to send on every request (auth tokens sourced by
                the caller from an external secret provider, e.g. 1Password).
    """

    def __init__(
        self,
        server_url: Optional[str] = None,
        headers: Optional[Dict[str, str]] = None,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
    ):
        self.server_url = server_url.rstrip("/") if server_url else None
        self.headers = dict(headers or {})
        self.timeout = timeout

    def resolve(self, utility: Utility) -> ExecutableBinding:
        t = utility.transport
        server = self.server_url or (t.servers[0] if t.servers else None)
        if not server:
            raise ValueError(f"No server URL for utility {utility.id}: pass server_url or declare servers in the source")
        return ExecutableBinding(
            server=server,
            method=t.method,
            path=t.path,
            parameters=t.parameters,
            request_body=t.request_body,
            responses=t.responses,
            headers=self.headers,
            timeout=self.timeout,
        )
