"""Selbst-Update: Jarvis holt neue Versionen von GitHub und startet sich neu.

Ablauf: Neuesten Stand des Branches prüfen → Quellcode-Archiv laden → nur den Ordner
`jarvis/` ersetzen → Prozess beenden. Docker startet den Container automatisch neu
(restart: unless-stopped), und die Dateien im Container bleiben dabei erhalten.
"""
from __future__ import annotations

import io
import logging
import os
import shutil
import tarfile
import tempfile
import threading
import time
from pathlib import Path

import requests

from . import store

log = logging.getLogger("jarvis.update")

REPO = os.environ.get("JARVIS_UPDATE_REPO", "cemal-canmalkoc-cmd/jarvis-")
BRANCH = os.environ.get("JARVIS_UPDATE_BRANCH", "claude/magical-pascal-95tllp")
PKG_DIR = Path(__file__).resolve().parent


def latest_sha() -> str:
    r = requests.get(f"https://api.github.com/repos/{REPO}/commits/{BRANCH}",
                     headers={"Accept": "application/vnd.github+json"}, timeout=20)
    r.raise_for_status()
    return r.json()["sha"]


def installed_sha() -> str | None:
    return store.get_state(store.connect(), "installed_sha")


def download(sha: str) -> bytes:
    r = requests.get(f"https://codeload.github.com/{REPO}/tar.gz/{sha}", timeout=120)
    r.raise_for_status()
    return r.content


def apply(archive: bytes, target: Path = PKG_DIR) -> int:
    """Ersetzt die Dateien in `target` durch den Ordner jarvis/ aus dem Archiv. Gibt die Anzahl Dateien zurück."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        with tarfile.open(fileobj=io.BytesIO(archive), mode="r:gz") as tar:
            members = []
            for m in tar.getmembers():
                parts = Path(m.name).parts
                if len(parts) >= 2 and parts[1] == "jarvis" and (m.isfile() or m.isdir()):
                    m.name = str(Path(*parts[1:]))
                    members.append(m)
            if not any(m.name == "jarvis/__init__.py" for m in members):
                raise RuntimeError("Archiv enthält kein gültiges jarvis-Paket")
            tar.extractall(tmp_path, members=members, filter="data")
        new_pkg = tmp_path / "jarvis"
        count = sum(1 for p in new_pkg.rglob("*") if p.is_file())
        shutil.copytree(new_pkg, target, dirs_exist_ok=True)
    return count


def _restart_later(delay: float = 2.0) -> None:
    def _go():
        time.sleep(delay)
        log.info("Neustart für Update …")
        os._exit(0)
    threading.Thread(target=_go, daemon=True).start()


def update(force: bool = False, restart: bool = True) -> dict:
    sha = latest_sha()
    current = installed_sha()
    if sha == current and not force:
        return {"status": "aktuell", "version": sha[:7]}
    files = apply(download(sha))
    store.set_state(store.connect(), "installed_sha", sha)
    if restart:
        _restart_later()
    return {"status": "aktualisiert", "version": sha[:7], "dateien": files,
            "info": "Jarvis startet in wenigen Sekunden neu."}
