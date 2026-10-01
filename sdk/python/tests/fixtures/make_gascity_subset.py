"""Regenerate gascity-openapi.subset.json from the pinned upstream document.

Upstream: gastownhall/gascity docs/reference/schema/openapi.json
The subset keeps the document skeleton plus the paths listed in KEEP, which
cover every identity collision the importer must handle, the city/session
hierarchy, and the top-level health surface. Run:

    python tests/fixtures/make_gascity_subset.py
"""
import hashlib
import json
import sys
import urllib.request
from pathlib import Path

UPSTREAM_COMMIT = "02e058598391329b7927405351ff62af89c44feb"  # 2026-09-30
UPSTREAM_URL = (
    "https://raw.githubusercontent.com/gastownhall/gascity/"
    f"{UPSTREAM_COMMIT}/docs/reference/schema/openapi.json"
)
KEEP = [
    "/health",
    "/v0/cities",
    "/v0/city",
    "/v0/city/{cityName}",
    "/v0/city/{cityName}/sessions",
    "/v0/city/{cityName}/session/{id}",
    "/v0/city/{cityName}/session/{id}/kill",
    "/v0/city/{cityName}/agent/{base}",
    "/v0/city/{cityName}/agent/{dir}/{base}",
    "/v0/city/{cityName}/agent/{base}/output",
    "/v0/city/{cityName}/agent/{dir}/{base}/output",
    "/v0/city/{cityName}/agent/{base}/output/stream",
    "/v0/city/{cityName}/agent/{dir}/{base}/output/stream",
    "/v0/city/{cityName}/agent/{base}/{action}",
    "/v0/city/{cityName}/agent/{dir}/{base}/{action}",
    "/v0/city/{cityName}/patches/agent/{base}",
    "/v0/city/{cityName}/patches/agent/{dir}/{base}",
]  # /v0/events is excluded on purpose: it drags in ~200 event payload schemas


def _refs(node, out):
    if isinstance(node, dict):
        ref = node.get("$ref")
        if isinstance(ref, str) and ref.startswith("#/components/"):
            out.add(tuple(ref.split("/")[2:4]))
        for v in node.values():
            _refs(v, out)
    elif isinstance(node, list):
        for v in node:
            _refs(v, out)


def _referenced_components(paths, components):
    """Keep only components reachable from the kept paths (transitively)."""
    wanted, frontier = set(), set()
    _refs(paths, frontier)
    while frontier - wanted:
        wanted |= frontier
        frontier = set()
        for section, name in wanted:
            _refs(components.get(section, {}).get(name), frontier)
    kept = {}
    for section, name in sorted(wanted):
        if name in components.get(section, {}):
            kept.setdefault(section, {})[name] = components[section][name]
    return kept


def main() -> int:
    raw = urllib.request.urlopen(UPSTREAM_URL, timeout=60).read()
    doc = json.loads(raw)
    subset = {k: v for k, v in doc.items() if k not in ("paths", "components")}
    subset["paths"] = {p: doc["paths"][p] for p in KEEP if p in doc["paths"]}
    subset["components"] = _referenced_components(subset["paths"], doc.get("components", {}))
    subset["x-gluless-fixture"] = {
        "upstream": "gastownhall/gascity docs/reference/schema/openapi.json",
        "upstream_commit": UPSTREAM_COMMIT,
        "upstream_sha256": hashlib.sha256(raw).hexdigest(),
        "paths_kept": len(subset["paths"]),
        "paths_upstream": len(doc["paths"]),
    }
    out = Path(__file__).with_name("gascity-openapi.subset.json")
    out.write_text(json.dumps(subset, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    print(f"wrote {out} ({out.stat().st_size} bytes, {len(subset['paths'])}/{len(doc['paths'])} paths)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
