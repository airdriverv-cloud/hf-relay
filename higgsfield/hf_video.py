#!/usr/bin/env python3
"""Higgsfield AI — генерация видео через официальный HTTP API.

Проверено по спецификации платформы:
  POST https://platform.higgsfield.ai/<app-path>
  заголовки: hf-api-key + hf-secret  (либо Authorization: Key key:secret)
  ответ: {"status":"queued","request_id":"req_...","status_url":...,"cancel_url":...}
  опрос: GET status_url  -> status: queued | in_progress | completed | failed | nsfw | canceled
  результат: в completed-JSON лежит ссылка на .mp4

Ключи берутся здесь: https://cloud.higgsfield.ai/api-keys
Переменные окружения: HF_API_KEY и HF_SECRET (или HF_KEY="key:secret").

ВНИМАНИЕ: platform.higgsfield.ai недоступен из сетей РФ (блокировка по SNI на уровне
провайдера). Нужен VPN/прокси; проверка — `python hf_video.py --check`.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

BASE = "https://platform.higgsfield.ai"
TIMEOUT = 60
POLL_EVERY = 5
POLL_LIMIT = 240  # 20 минут

# Прокси для обхода блокировки, например socks5h://127.0.0.1:10999
PROXY = os.getenv("HF_PROXY") or None

# Проверенные пути приложений (app path в терминах API)
MODELS = {
    "sora2-pro-t2v": "sora-2/text-to-video/pro",
    "kling25-turbo-t2v": "kling-video/v2.5-turbo/pro/text-to-video",
    "kling21-master-t2v": "kling-video/v2.1/master/text-to-video",
    "kling25-turbo-i2v": "kling-video/v2.5-turbo/pro/image-to-video",
    "kling21-master-i2v": "kling-video/v2.1/master/image-to-video",
    "kling21-pro-i2v": "kling-video/v2.1/pro/image-to-video",
    "kling21-std-i2v": "kling-video/v2.1/standard/image-to-video",
    "dop-standard": "higgsfield-ai/dop/standard",
    "dop-turbo": "higgsfield-ai/dop/turbo",
}


def credentials() -> tuple[str, str]:
    key = os.getenv("HF_API_KEY")
    secret = os.getenv("HF_SECRET") or os.getenv("HF_API_SECRET")
    if key and secret:
        return key, secret
    joined = os.getenv("HF_KEY", "")
    if ":" in joined:
        k, s = joined.split(":", 1)
        return k, s
    sys.exit(
        "Нет ключей. Задайте HF_API_KEY и HF_SECRET "
        "(ключи: https://cloud.higgsfield.ai/api-keys)."
    )


def request(method: str, url: str, payload: dict | None = None) -> dict:
    key, secret = credentials()
    headers = {
        "hf-api-key": key,
        "hf-secret": secret,
        "Accept": "application/json",
        "Content-Type": "application/json",
        "User-Agent": "hf-video-script/1.0",
    }
    data = json.dumps(payload).encode("utf-8") if payload is not None else None

    try:
        import httpx
    except ImportError:
        return _request_urllib(method, url, data, headers)

    try:
        with httpx.Client(proxy=PROXY, timeout=TIMEOUT) as client:
            resp = client.request(method, url, content=data, headers=headers)
    except Exception as e:  # noqa: BLE001
        sys.exit(f"Сеть недоступна ({e}). Нужен рабочий VPN/прокси — см. HF_PROXY / --proxy.")
    if resp.status_code >= 400:
        sys.exit(f"HTTP {resp.status_code} на {method} {url}: {resp.text[:800]}")
    return resp.json() if resp.content else {}


def _request_urllib(method, url, data, headers) -> dict:
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            body = resp.read()
            return json.loads(body) if body else {}
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")[:800]
        sys.exit(f"HTTP {e.code} на {method} {url}: {detail}")
    except urllib.error.URLError as e:
        sys.exit(
            f"Сеть недоступна ({e.reason}). Скорее всего блокировка higgsfield.ai — "
            "включите VPN/прокси и повторите."
        )


def find_video_url(obj) -> str | None:
    """Ищем в JSON первую ссылку, похожую на видео."""
    if isinstance(obj, str):
        low = obj.lower().split("?")[0]
        if low.endswith((".mp4", ".mov", ".webm")):
            return obj
        return None
    if isinstance(obj, list):
        for item in obj:
            found = find_video_url(item)
            if found:
                return found
        return None
    if isinstance(obj, dict):
        # сначала пробуем осмысленные ключи
        for key in ("video", "url", "raw_url", "result_url"):
            if key in obj:
                found = find_video_url(obj[key])
                if found:
                    return found
        for value in obj.values():
            found = find_video_url(value)
            if found:
                return found
    return None


def submit(app_path: str, payload: dict) -> dict:
    return request("POST", f"{BASE}/{app_path.lstrip('/')}", payload)


def wait(request_id: str, status_url: str, verbose: bool = True) -> dict:
    status_url = status_url or f"{BASE}/requests/{request_id}"
    last = None
    for _ in range(POLL_LIMIT):
        data = request("GET", status_url)
        status = data.get("status", "?")
        if verbose and status != last:
            print(f"  статус: {status}", flush=True)
            last = status
        if status == "completed":
            return data
        if status in ("failed", "nsfw", "canceled"):
            sys.exit(f"Генерация не удалась: {status}\n{json.dumps(data, ensure_ascii=False)[:600]}")
        time.sleep(POLL_EVERY)
    sys.exit(f"Таймаут: за {POLL_LIMIT * POLL_EVERY // 60} мин статус не стал completed")


def download(url: str, dest: Path) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        import httpx

        with httpx.Client(proxy=PROXY, timeout=300, follow_redirects=True) as client:
            with client.stream("GET", url) as resp:
                resp.raise_for_status()
                with open(dest, "wb") as fh:
                    for chunk in resp.iter_bytes(1 << 20):
                        fh.write(chunk)
    except ImportError:
        with urllib.request.urlopen(url, timeout=300) as resp, open(dest, "wb") as fh:
            while chunk := resp.read(1 << 20):
                fh.write(chunk)
    return dest


def check() -> int:
    """Быстрая проверка: есть ли сеть до API (без ключей)."""
    for host in ("platform.higgsfield.ai", "cloud.higgsfield.ai"):
        url = f"https://{host}/"
        t0 = time.time()
        try:
            urllib.request.urlopen(url, timeout=8)
            print(f"{host}: доступен ({time.time() - t0:.1f} c)")
        except urllib.error.HTTPError as e:
            print(f"{host}: доступен, HTTP {e.code} ({time.time() - t0:.1f} c)")
        except Exception as e:
            print(f"{host}: НЕДОСТУПЕН — {type(e).__name__}: {e}")
    print("если оба НЕДОСТУПНЫ — нужен VPN/прокси")
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description="Генерация видео через Higgsfield API")
    p.add_argument("--check", action="store_true", help="только проверить сетевой доступ")
    p.add_argument("--model", default="kling25-turbo-t2v", help=f"{', '.join(MODELS)} или полный путь")
    p.add_argument("--prompt", help="текстовый промпт")
    p.add_argument("--image", help="URL изображения для image-to-video")
    p.add_argument("--duration", type=int, help="длительность, сек")
    p.add_argument("--aspect", help="например 16:9 или 9:16")
    p.add_argument("--negative", help="negative prompt")
    p.add_argument("--params", help="JSON с параметрами (переопределяет флаги)")
    p.add_argument(
        "--proxy",
        help="прокси, например socks5h://127.0.0.1:10999 (по умолчанию из HF_PROXY)",
    )
    p.add_argument("--out", default="out/video.mp4", help="куда скачать mp4")
    p.add_argument("--wait", action="store_true", default=True, help="дождаться и скачать")
    p.add_argument("--no-download", action="store_true", help="только дождаться, без файла")
    a = p.parse_args()

    global PROXY
    if a.proxy:
        PROXY = a.proxy

    if a.check:
        return check()

    credentials()  # падаем сразу, до печати параметров и сетевых попыток

    app_path = MODELS.get(a.model, a.model)
    payload: dict = {}
    if a.prompt:
        payload["prompt"] = a.prompt
    if a.image:
        payload["image_url"] = a.image
    if a.duration:
        payload["duration"] = a.duration
    if a.aspect:
        payload["aspect_ratio"] = a.aspect
    if a.negative:
        payload["negative_prompt"] = a.negative
    if a.params:
        payload.update(json.loads(a.params))
    if not payload.get("prompt"):
        p.error("нужен --prompt (для image-to-video — хотя бы короткий)")
    print(f"Модель: {app_path}")
    print(f"Параметры: {json.dumps(payload, ensure_ascii=False)}")
    created = submit(app_path, payload)
    rid = created.get("request_id")
    print(f"Запрос создан: {rid}")
    if not rid:
        print(json.dumps(created, ensure_ascii=False, indent=2))
        return 1

    result = wait(rid, created.get("status_url", ""))
    url = find_video_url(result)
    out_path = Path(a.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    meta = {
        "model": app_path,
        "payload": payload,
        "request_id": rid,
        "video_url": url,
        "result": result,
    }
    (out_path.parent / "result.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(result, ensure_ascii=False, indent=2)[:1500])
    if not url:
        sys.exit("В ответе не нашлась ссылка на видео — смотрите JSON выше")
    print(f"Видео: {url}")
    if not a.no_download:
        path = download(url, Path(a.out))
        print(f"Сохранено: {path.resolve()} ({path.stat().st_size / 1e6:.1f} МБ)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
