"""Скачивает бинарный файл (видео) по URL с раннера GitHub и кладёт в out/."""

import os
import sys
import urllib.request

url = sys.argv[1]
name = sys.argv[2] if len(sys.argv) > 2 else "file.bin"

os.makedirs("out", exist_ok=True)
dst = os.path.join("out", name)
req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
with urllib.request.urlopen(req, timeout=300) as resp, open(dst, "wb") as fh:
    total = 0
    while True:
        chunk = resp.read(1 << 20)
        if not chunk:
            break
        fh.write(chunk)
        total += len(chunk)
print(f"DOWNLOADED|{dst}|{total}")
