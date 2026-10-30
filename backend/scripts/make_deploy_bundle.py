"""Pack exactly what the server needs to build the image (an allowlist, not the whole project) into one .tar.gz, and refuse
to write it if any file is an env/secret file or contains something that looks like an API key or private key.

    .\\.venv\\Scripts\\python.exe scripts\\make_deploy_bundle.py --out D:\\smartplate-deploy.tar.gz

Never included: .env / .env.bak / any *.env except deploy/smartplate.env.example, backups, databases, datasets outside
deploy/reference_data, node_modules, build output, tests. Run scripts/prepare_deploy_data.py first.
"""
from __future__ import annotations

import argparse
import re
import sys
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
INCLUDE = ["Dockerfile", ".dockerignore", "deploy/docker-compose.yml", "deploy/Caddyfile", "deploy/smartplate.env.example",
           "deploy/reference_data", "backend/requirements-deploy.txt", "backend/app", "backend/models/production/food_classifier",
           "backend/models/production/freshness", "frontend", "docs/DEPLOYMENT.md"]
SKIP_DIRS = {"node_modules", "dist", "__pycache__", ".vite", "tests"}
SKIP_FILE = re.compile(r"(^\.env($|\.)|\.env$|\.bak$|\.pyc$|\.log$|\.db(-wal|-shm)?$)", re.I)
SECRET = re.compile(rb"sk-(proj-)?[A-Za-z0-9_-]{20,}|AIza[0-9A-Za-z_-]{30,}|-----BEGIN [A-Z ]*PRIVATE KEY-----")
ALLOWED_ENV = {"deploy/smartplate.env.example"}


def files() -> list[Path]:
    out = []
    for item in INCLUDE:
        p = ROOT / item
        if not p.exists():
            raise SystemExit(f"missing: {item} (run scripts/prepare_deploy_data.py for deploy/reference_data)")
        for f in ([p] if p.is_file() else sorted(p.rglob("*"))):
            rel = f.relative_to(ROOT).as_posix()
            if f.is_dir() or any(part in SKIP_DIRS for part in f.relative_to(ROOT).parts[:-1]):
                continue
            if SKIP_FILE.search(f.name) and rel not in ALLOWED_ENV:
                continue
            out.append(f)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True, type=Path)
    args = ap.parse_args()
    chosen = files()
    flagged = [f.relative_to(ROOT).as_posix() for f in chosen if f.suffix.lower() not in (".keras", ".npz", ".png", ".ico")
               and SECRET.search(f.read_bytes())]
    if flagged:
        print("REFUSED: these files look like they contain a key (values not shown):", *flagged, sep="\n  ")
        return 1
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(args.out, "w:gz") as tar:
        for f in chosen:
            tar.add(f, arcname=f"smartplate/{f.relative_to(ROOT).as_posix()}", recursive=False)
    size = sum(f.stat().st_size for f in chosen)
    print(f"{len(chosen)} files, {size / 1e6:.1f} MB uncompressed -> {args.out} ({args.out.stat().st_size / 1e6:.1f} MB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
