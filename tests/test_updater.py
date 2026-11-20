"""Selbst-Update: Archiv einspielen, Version merken."""
import io
import tarfile

from jarvis import store, updater


def _archive(files: dict) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for name, content in files.items():
            data = content.encode()
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return buf.getvalue()


def test_apply_replaces_only_package(tmp_path):
    target = tmp_path / "jarvis"
    target.mkdir()
    (target / "alt.py").write_text("alt")
    (target / "brain.py").write_text("alte version")
    arc = _archive({"repo-abc/jarvis/__init__.py": "", "repo-abc/jarvis/brain.py": "neue version",
                    "repo-abc/jarvis/static/app.html": "<html>", "repo-abc/install.sh": "nicht kopieren"})
    assert updater.apply(arc, target) == 3
    assert (target / "brain.py").read_text() == "neue version"
    assert (target / "static" / "app.html").exists() and (target / "alt.py").exists()
    assert not (tmp_path / "install.sh").exists()


def test_rejects_archive_without_package(tmp_path):
    try:
        updater.apply(_archive({"repo/README.md": "x"}), tmp_path)
    except RuntimeError:
        return
    raise AssertionError("ungültiges Archiv akzeptiert")


def test_update_flow(monkeypatch, tmp_path):
    monkeypatch.setattr(updater, "latest_sha", lambda: "a" * 40)
    monkeypatch.setattr(updater, "download", lambda sha: _archive({"r/jarvis/__init__.py": ""}))
    monkeypatch.setattr(updater, "PKG_DIR", tmp_path)
    monkeypatch.setattr(updater.apply, "__defaults__", (tmp_path,))
    r = updater.update(restart=False)
    assert r["status"] == "aktualisiert" and updater.installed_sha() == "a" * 40
    assert updater.update(restart=False)["status"] == "aktuell"


def test_day_round_rotates_and_runs(monkeypatch):
    from datetime import datetime
    from jarvis import autopilot, config
    calls = []
    monkeypatch.setattr(autopilot.pipeline, "run", lambda **kw: calls.append(kw["web_focuses"]) or {"A": 0, "B": 0})
    a = autopilot.day_round(datetime(2026, 11, 20, 10))["fokus"]
    b = autopilot.day_round(datetime(2026, 11, 20, 12))["fokus"]
    assert len(a) == 4 and a != b and calls[0] == a
    assert "Autopilot" not in config.__name__  # sanity
    from jarvis import agent
    assert "alle 2 Stunden" in agent.OWNER_SYSTEM and "cron" in agent.OWNER_SYSTEM
