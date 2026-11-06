#!/usr/bin/env python3
"""Higgsfield через GitHub Actions (обход блокировки домена в РФ).

Логика: локально собираем JSON, запускаем workflow в приватном репозитории,
раннер GitHub (зарубежный IP) вызывает platform.higgsfield.ai, забирает mp4
артефактом, мы скачиваем его локально.

Использование:
  python hf_remote.py --check
  python hf_remote.py --model kling25-turbo-t2v --prompt "..." --duration 5 --aspect 16:9
  python hf_remote.py --model sora2-pro-t2v --params '{"prompt":"...","duration":8,"resolution":"1080p"}'

Требуется установленный и залогиненный `gh` (GitHub CLI).
Секреты HF_API_KEY / HF_SECRET должны лежать в настройках репозитория.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
import uuid
from pathlib import Path

REPO = "airdriverv-cloud/hf-relay"
WORKFLOW = "generate.yml"
ARTIFACT = "hf-output"

# консоль Windows по умолчанию в cp1251 — не даём ей падать на логах
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def gh(*args: str, capture: bool = True) -> str:
    cmd = ["gh", *args]
    res = subprocess.run(cmd, capture_output=capture, text=True, encoding="utf-8", errors="replace")
    if res.returncode != 0:
        tail = (res.stderr or res.stdout or "").strip()[-800:]
        raise SystemExit(f"gh {' '.join(args)} → код {res.returncode}\n{tail}")
    return res.stdout


def dispatch(tag: str, mode: str, model: str, payload: str, outfile: str, url: str = "") -> None:
    gh(
        "workflow", "run", WORKFLOW,
        "--repo", REPO,
        "-f", f"mode={mode}",
        "-f", f"tag={tag}",
        "-f", f"model={model}",
        "-f", f"payload={payload}",
        "-f", f"out={outfile}",
        "-f", f"url={url}",
    )


def find_run(tag: str, timeout: float = 90) -> int:
    """Ищем run по имени hf-<tag>."""
    name = f"hf-{tag}"
    deadline = time.time() + timeout
    while time.time() < deadline:
        raw = gh("run", "list", "--repo", REPO, "--limit", "15",
                 "--json", "databaseId,name,status,createdAt")
        for run in json.loads(raw or "[]"):
            if run.get("name") == name:
                return int(run["databaseId"])
        time.sleep(5)
    raise SystemExit("Не нашёл запуск workflow (hf-<tag>) за %.0f с" % timeout)


def wait_run(run_id: int, timeout: float = 2400) -> str:
    deadline = time.time() + timeout
    while time.time() < deadline:
        raw = gh("run", "view", str(run_id), "--repo", REPO,
                 "--json", "status,conclusion")
        data = json.loads(raw or "{}")
        status = data.get("status")
        if status == "completed":
            return data.get("conclusion") or "unknown"
        time.sleep(10)
    raise SystemExit(f"Раннер не закончил за {timeout / 60:.0f} мин")


def load_keys(path: Path) -> dict[str, str]:
    """Читает ключи из файла вида KEY=VALUE и/или из окружения.

    Понимает оба формата: пара HF_API_KEY + HF_SECRET и одиночный HF_KEY.
    """
    import os

    values: dict[str, str] = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8-sig").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            values[k.strip()] = v.strip().strip('"').strip("'")
    for k in ("HF_KEY", "HF_API_KEY", "HF_SECRET", "HF_API_SECRET"):
        if os.getenv(k):
            values.setdefault(k, os.environ[k])

    if values.get("HF_API_SECRET"):
        values.setdefault("HF_SECRET", values["HF_API_SECRET"])
    if values.get("HF_API_KEY"):
        if not values.get("HF_SECRET"):
            raise SystemExit("Есть HF_API_KEY, но нет HF_SECRET — пришлите оба значения.")
        return {"HF_API_KEY": values["HF_API_KEY"], "HF_SECRET": values["HF_SECRET"]}
    if values.get("HF_SECRET") and not values.get("HF_API_KEY"):
        raise SystemExit("Есть HF_SECRET, но нет HF_API_KEY — пришлите оба значения.")
    if values.get("HF_KEY"):
        return {"HF_KEY": values["HF_KEY"]}
    raise SystemExit(
        f"Не нашёл ключи. Ожидаю файл {path} со строкой HF_KEY=... "
        "(или парой HF_API_KEY=... / HF_SECRET=...)."
    )


def install_keys(path: Path) -> int:
    values = load_keys(path)
    for name, value in values.items():
        gh("secret", "set", name, "--repo", REPO, "--body", value)
        print(f"secret {name}: записан ({len(value)} симв.)")
    print(gh("secret", "list", "--repo", REPO))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Генерация видео через Higgsfield из GitHub Actions")
    ap.add_argument("--check", action="store_true", help="прогнать проверку сети на раннере")
    ap.add_argument("--fetch", metavar="URL", help="скачать страницу через раннер (обход блокировки)")
    ap.add_argument("--schema", metavar="URL", help="вытащить input schema модели со страницы документации")
    ap.add_argument("--endpoints", action="store_true", help="список POST-эндпоинтов API из OpenAPI")
    ap.add_argument("--openapi", action="store_true", help="скачать openapi.json в out/openapi")
    ap.add_argument("--install-keys", action="store_true", help="залить ключи из keys.env в secrets репозитория")
    ap.add_argument("--keys-file", default="keys.env", help="файл с HF_API_KEY/HF_SECRET")
    ap.add_argument("--model", default="kling25-turbo-t2v", help="алиас или полный app path")
    ap.add_argument("--prompt")
    ap.add_argument("--image", help="URL изображения (image-to-video)")
    ap.add_argument("--duration", type=int)
    ap.add_argument("--aspect")
    ap.add_argument("--negative")
    ap.add_argument("--params", help="JSON с аргументами (переопределяет флаги)")
    ap.add_argument("--out", default="video.mp4", help="имя файла внутри артефакта")
    ap.add_argument("--dir", default="out", help="куда скачать локально")
    ap.add_argument("--tag", help="метка запуска (по умолчанию случайная)")
    ap.add_argument("--keep-tag", action="store_true", help="не удалять старые артефакты")
    a = ap.parse_args()

    tag = (a.tag or uuid.uuid4().hex[:8]).replace("-", "")[:12]

    if a.install_keys:
        return install_keys(Path(a.keys_file))

    if a.endpoints:
        print(f"запрашиваю список эндпоинтов, tag={tag}")
        dispatch(tag, "endpoints", a.model, '{"prompt":"x"}', a.out)
        run_id = find_run(tag)
        conclusion = wait_run(run_id)
        if conclusion != "success":
            print(gh("run", "view", str(run_id), "--repo", REPO, "--log-failed"))
            raise SystemExit(f"Запуск завершился: {conclusion}")
        for line in gh("run", "view", str(run_id), "--repo", REPO, "--log").splitlines():
            if "EP|" in line:
                print(line.split("EP|", 1)[1].split("\t")[0])
            elif "INFO|" in line:
                print(line.split("INFO|", 1)[1].split("\t")[0])
        return 0

    if a.openapi:
        print(f"скачиваю openapi.json через раннер, tag={tag}")
        dispatch(tag, "openapi", a.model, '{"prompt":"x"}', a.out)
        run_id = find_run(tag)
        conclusion = wait_run(run_id)
        if conclusion != "success":
            print(gh("run", "view", str(run_id), "--repo", REPO, "--log-failed"))
            raise SystemExit(f"Запуск завершился: {conclusion}")
        dest = Path(a.dir) / "openapi"
        dest.mkdir(parents=True, exist_ok=True)
        gh("run", "download", str(run_id), "--repo", REPO, "-n", ARTIFACT, "-D", str(dest))
        for f in sorted(dest.rglob("openapi.json")):
            print(f"{f.resolve()} ({f.stat().st_size / 1024:.0f} КБ)")
        return 0

    if a.schema:
        print(f"схема {a.schema} через раннер, tag={tag}")
        dispatch(tag, "schema", a.model, '{"prompt":"x"}', a.out, a.schema)
        run_id = find_run(tag)
        conclusion = wait_run(run_id)
        if conclusion != "success":
            print(gh("run", "view", str(run_id), "--repo", REPO, "--log-failed"))
            raise SystemExit(f"Запуск завершился: {conclusion}")
        text = "".join(
            line.split("SCHEMA|", 1)[1]
            for line in gh("run", "view", str(run_id), "--repo", REPO, "--log").splitlines()
            if "SCHEMA|" in line
        )
        print(text.replace(" | ", "\n"))
        return 0

    if a.fetch:
        print(f"fetch {a.fetch} через раннер, tag={tag}")
        dispatch(tag, "fetch", a.model, '{"prompt":"fetch"}', a.out, a.fetch)
        run_id = find_run(tag)
        conclusion = wait_run(run_id)
        if conclusion != "success":
            print(gh("run", "view", str(run_id), "--repo", REPO, "--log-failed"))
            raise SystemExit(f"Запуск завершился: {conclusion}")
        text = "".join(
            line.split("FETCH|", 1)[1]
            for line in gh("run", "view", str(run_id), "--repo", REPO, "--log").splitlines()
            if "FETCH|" in line
        )
        print(text)
        return 0

    if a.check:
        print(f"Запускаю проверку сети на раннере, tag={tag}")
        dispatch(tag, "check", a.model, '{"prompt":"check"}', a.out)
        run_id = find_run(tag)
        print(f"run: https://github.com/{REPO}/actions/runs/{run_id}")
        conclusion = wait_run(run_id)
        log = gh("run", "view", str(run_id), "--repo", REPO, "--log")
        keys = ("HTTP", "недоступ", "НЕДОСТУП", "доступен", "ipify", "проверк", "Проверк")
        for line in log.splitlines():
            if any(k in line for k in keys) or "HTTP" in line:
                print(line.replace("\ufeff", "").strip()[:300])
        print("итог:", conclusion)
        # проверяем и скачивание артефакта
        dest = Path(a.dir) / f"check-{tag}"
        try:
            gh("run", "download", str(run_id), "--repo", REPO, "-n", ARTIFACT, "-D", str(dest))
            files = sorted(p for p in dest.rglob("*") if p.is_file())
            print("артефакт скачан:", ", ".join(f.name for f in files) or "пусто")
        except SystemExit as e:
            print("артефакт не скачался:", e)
        return 0 if conclusion == "success" else 1

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
        ap.error("нужен --prompt")

    print(f"tag={tag} модель={a.model}")
    print("параметры:", json.dumps(payload, ensure_ascii=False))
    dispatch(tag, "generate", a.model, json.dumps(payload, ensure_ascii=False), a.out)
    run_id = find_run(tag)
    print(f"run: https://github.com/{REPO}/actions/runs/{run_id}")
    print("жду завершения (обычно 1–4 мин)...")

    conclusion = wait_run(run_id)
    if conclusion != "success":
        print(gh("run", "view", str(run_id), "--repo", REPO, "--log-failed"))
        raise SystemExit(f"Запуск завершился: {conclusion}")

    dest = Path(a.dir) / tag
    dest.mkdir(parents=True, exist_ok=True)
    gh("run", "download", str(run_id), "--repo", REPO, "-n", ARTIFACT, "-D", str(dest))
    files = sorted(p for p in dest.rglob("*") if p.is_file())
    for f in files:
        print(f"  {f}  ({f.stat().st_size / 1e6:.2f} МБ)")

    result_file = dest / "result.json"
    if result_file.exists():
        meta = json.loads(result_file.read_text(encoding="utf-8"))
        print("request_id:", meta.get("request_id"))
        print("video_url :", meta.get("video_url"))

    video = next((p for p in files if p.suffix.lower() in {".mp4", ".mov", ".webm"}), None)
    if video:
        print(f"\nГОТОВО: {video.resolve()}")
    else:
        print("\nВидео не найдено в артефакте — смотрите result.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
