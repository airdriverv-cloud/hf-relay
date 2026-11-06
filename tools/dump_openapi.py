"""Скачивает OpenAPI-спеку Higgsfield в out/openapi.json (для локального разбора)."""

import json
import os
import urllib.request

SPEC = "https://docs.higgsfield.ai/docs/openapi.json"

with urllib.request.urlopen(SPEC, timeout=60) as resp:
    raw = resp.read()

data = json.loads(raw)
os.makedirs("out", exist_ok=True)
with open(os.path.join("out", "openapi.json"), "wb") as fh:
    fh.write(raw)
print(f"INFO|сохранено {len(raw)} байт, путей: {len(data.get('paths', {}))}")
