"""Извлекает параметры (input schema) из страницы документации Higgsfield."""

import re
import sys
import urllib.request

url = sys.argv[1]
req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
with urllib.request.urlopen(req, timeout=45) as resp:
    raw = resp.read().decode("utf-8", "replace")

text = re.sub(r"(?is)<(script|style|noscript)[^>]*>.*?</\1>", " ", raw)
text = re.sub(r"(?s)<[^>]+>", "\n", text)
text = re.sub(r"&quot;", '"', text).replace("&amp;", "&").replace("&#x27;", "'")
lines = [ln.strip() for ln in text.splitlines() if ln.strip()]

try:
    start = next(i for i, ln in enumerate(lines) if ln.startswith("Input schema"))
except StopIteration:
    start = 0
end = len(lines)
for i in range(start, len(lines)):
    if lines[i].startswith("Response") or lines[i].startswith("Complete JSON"):
        end = i
        break

chunk = lines[start:end]
budget = 9000
out = []
used = 0
for ln in chunk:
    if used + len(ln) > budget:
        break
    out.append(ln)
    used += len(ln) + 1
print("SCHEMA|" + " | ".join(out))
