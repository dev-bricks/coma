# -*- coding: utf-8 -*-
"""Gemeinsame Testhilfen.

**Kein Test dieser Suite startet einen echten Prozess.** ``subprocess`` wird
ueberall ersetzt; das ist keine Bequemlichkeit, sondern Absicht: Ein Test, der
``claude`` startet, kostet Tokens, braucht Netz und wird beim ersten Ausfall
abgeschaltet.
"""
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from coma import JobBoard


@pytest.fixture
def fake_run():
    """Fabrik fuer einen Ersatz von ``subprocess.run``.

    Der Ersatz merkt sich die Aufrufe unter ``.calls``, damit ein Test die
    tatsaechlich uebergebene Argumentliste pruefen kann.
    """

    def factory(*, returncode=0, stdout="", stderr="", raises=None, log_text=None):
        def runner(cmd, **kwargs):
            runner.calls.append({"cmd": list(cmd), "kwargs": kwargs})
            if raises is not None:
                raise raises
            handle = kwargs.get("stdout")
            if log_text is not None and hasattr(handle, "write"):
                handle.write(log_text.encode("utf-8"))
            elif hasattr(handle, "write") and stdout:
                handle.write(stdout.encode("utf-8"))
            if kwargs.get("capture_output"):
                return SimpleNamespace(
                    returncode=returncode, stdout=stdout, stderr=stderr
                )
            return SimpleNamespace(returncode=returncode, stdout=None, stderr=None)

        runner.calls = []
        return runner

    return factory


@pytest.fixture
def fake_popen():
    """Fabrik fuer einen Ersatz von ``subprocess.Popen``."""

    class FakePopen:
        instances: list["FakePopen"] = []

        def __init__(self, cmd, **kwargs):
            self.cmd = list(cmd)
            self.kwargs = kwargs
            self.pid = 4242
            self._codes: list = []
            self.terminated = False
            FakePopen.instances.append(self)

        def program(self, *codes):
            self._codes = list(codes)
            return self

        def poll(self):
            if not self._codes:
                return None
            value = self._codes.pop(0)
            if value is None:
                return None
            self._returncode = value
            return value

        def wait(self, timeout=None):
            while self._codes:
                value = self._codes.pop(0)
                if value is not None:
                    return value
            raise subprocess.TimeoutExpired(cmd=self.cmd, timeout=timeout)

        def terminate(self):
            self.terminated = True
            self._codes = [-15]

        def kill(self):  # pragma: no cover - Notausgang
            self.terminated = True
            self._codes = [-9]

    FakePopen.instances = []
    return FakePopen


@pytest.fixture
def board(tmp_path: Path) -> JobBoard:
    """Ein leeres Jobverzeichnis mit IN/ OUT/ DONE/."""
    board = JobBoard(tmp_path / "_agentjobs")
    board.ensure_dirs()
    return board


@pytest.fixture
def job(board: JobBoard):
    """Ein eingereichter Auftrag namens ``testjob``."""
    return board.submit("testjob", "# Auftrag\n\nSchreibe eine Zeile.\n")
