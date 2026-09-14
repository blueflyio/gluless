"""Generate the canonical IR JSON Schema from `gluless.models`.

`models.py` is authored; `api/contract.schema.json` is generated. There is
exactly one definition, so the two cannot drift — and
`tests/test_ir_schema.py` fails if the checked-in file stops matching.

    python -m gluless.schema            # print to stdout
    python -m gluless.schema --write    # rewrite api/contract.schema.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict

from gluless.models import SCHEMA_ID, Contract

#: Repo-relative location of the generated schema. Kept next to api/openapi.yaml
#: because it is a language-neutral artifact, not a Python one: the Go and
#: TypeScript SDKs consume this file, not models.py.
SCHEMA_RELPATH = "api/contract.schema.json"


def build_schema() -> Dict[str, Any]:
    """Return the canonical JSON Schema for a GluLess Contract IR document."""
    schema = Contract.model_json_schema(mode="serialization")
    # Pydantic emits the draft 2020-12 dialect.
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": SCHEMA_ID,
        **schema,
    }


def schema_path() -> Path:
    """Absolute path to the checked-in schema, located from this file."""
    # gluless/schema.py -> gluless -> python -> sdk -> <repo root>
    return Path(__file__).resolve().parents[3] / SCHEMA_RELPATH


def render() -> str:
    return json.dumps(build_schema(), indent=2, sort_keys=True) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="gluless.schema", description=__doc__)
    parser.add_argument("--write", action="store_true", help=f"rewrite {SCHEMA_RELPATH}")
    parser.add_argument("--check", action="store_true", help="exit non-zero if the checked-in schema is stale")
    args = parser.parse_args(argv)

    text = render()
    target = schema_path()

    if args.write:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
        print(f"wrote {target}")
        return 0
    if args.check:
        if not target.exists():
            print(f"missing {target}; run: python -m gluless.schema --write", file=sys.stderr)
            return 1
        if target.read_text(encoding="utf-8") != text:
            print(f"{target} is stale; run: python -m gluless.schema --write", file=sys.stderr)
            return 1
        print(f"{target} is current")
        return 0

    sys.stdout.write(text)
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI entry
    raise SystemExit(main())
