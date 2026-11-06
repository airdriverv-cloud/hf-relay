"""Печатает входную схему модели из страницы документации Higgsfield."""

import re
import sys
import urllib.request

url = sys.argv[1]
req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
with urllib.request.urlopen(req, timeout=45) as resp:
    raw = resp.read().decode("utf-8", "replace")

# содержимое страницы живёт в JSON-потоке next.js; забираем сырой текст
text = raw.replace("\\n", "\n").replace('\\"', '"')
text = re.sub(r"(?is)<(script|style|noscript)[^>]*>.*?</\1>", " ", text)
text = re.sub(r"(?s)<[^>]+>", "\n", text)
text = text.replace("&quot;", '"').replace("&amp;", "&").replace("&#x27;", "'")

lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
start = next((i for i, ln in enumerate(lines) if ln == "Input schema"), 0)
end = next((i for i in range(start + 1, len(lines)) if lines[i].startswith("Complete JSON")), len(lines))

chunk = " | ".join(lines[start:end])
chunk = chunk.replace("|", "/")
for i in range(0, min(len(chunk), 12000), 180):
    print("SCHEMA|" + chunk[i:i + 180])
