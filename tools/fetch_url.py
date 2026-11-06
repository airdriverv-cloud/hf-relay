"""Загрузка URL с зарубежного раннера: печатает текст строками с префиксом FETCH|."""

import json
import re
import sys
import urllib.request

url = sys.argv[1]
req = urllib.request.Request(
    url,
    headers={
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
        "Accept": "*/*",
    },
)
with urllib.request.urlopen(req, timeout=45) as resp:
    ctype = resp.headers.get("Content-Type", "")
    raw = resp.read().decode("utf-8", "replace")

if "json" in ctype:
    try:
        text = json.dumps(json.loads(raw), ensure_ascii=False, indent=1)
    except Exception:
        text = raw
else:
    text = re.sub(r"(?is)<(script|style|noscript)[^>]*>.*?</\1>", " ", raw)
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    text = re.sub(r"&nbsp;?", " ", text)
    text = re.sub(r"\s+", " ", text)

limit = 20000
chunk = 200
for i in range(0, min(len(text), limit), chunk):
    print("FETCH|" + text[i : i + chunk].replace("|", "/"))
