"""Печатает компактный список эндпоинтов генерации из OpenAPI-спеки Higgsfield."""

import json
import urllib.request

SPEC = "https://docs.higgsfield.ai/docs/openapi.json"

with urllib.request.urlopen(SPEC, timeout=60) as resp:
    spec = json.load(resp)

paths = spec.get("paths", {})
print(f"INFO|всего путей: {len(paths)}")

rows = []
for path, ops in sorted(paths.items()):
    for method, op in ops.items():
        if method.lower() != "post":
            continue
        summary = (op.get("summary") or "").strip()
        rows.append((path, summary))

for path, summary in rows:
    print(f"EP|{path}|{summary[:90]}")

print(f"INFO|POST-эндпоинтов: {len(rows)}")
