"""Local and SSH-backed command / file transport."""

from __future__ import annotations

import os
import shlex
import subprocess
import tempfile
from pathlib import Path
from typing import Any


class LocalTransport:
    """Run probes on the local host."""

    kind = "local"

    def run(self, argv: list[str], timeout: float = 5.0) -> tuple[str, str, int]:
        try:
            r = subprocess.run(
                argv,
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
            )
            return r.stdout, r.stderr, r.returncode
        except subprocess.TimeoutExpired:
            return "", "timeout", 124
        except OSError as e:
            return "", str(e), 127

    def read_text(self, path: str) -> str | None:
        try:
            return Path(path).read_text(encoding="utf-8", errors="replace")
        except OSError:
            return None

    def http_base_strata(self) -> str:
        from inftop.strata import DEFAULT_STRATA_URL

        return DEFAULT_STRATA_URL


    def http_base_ollama(self) -> str:
        return "http://127.0.0.1:11434"

    def sysfs_drm(self) -> str:
        return "/sys/class/drm"

    def close(self) -> None:
        pass


class SSHTransport:
    """Run every probe over one persistent `ssh` ControlMaster connection."""

    kind = "ssh"

    def __init__(self, host: str = "gpu-box") -> None:
        self.host = host
        self._ctrl = str(
            Path(tempfile.gettempdir()) / f"inftop-ssh-{os.getpid()}-{host}.sock"
        )
        self._base = [
            "ssh",
            "-o",
            "ControlMaster=auto",
            "-o",
            f"ControlPath={self._ctrl}",
            "-o",
            "ControlPersist=60",
            "-o",
            "BatchMode=yes",
            "-o",
            "ConnectTimeout=5",
            host,
        ]
        # Establish master
        self.run(["true"], timeout=15.0)

    def run(self, argv: list[str], timeout: float = 5.0) -> tuple[str, str, int]:
        remote = " ".join(shlex.quote(a) for a in argv)
        try:
            r = subprocess.run(
                self._base + [remote],
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
            )
            return r.stdout, r.stderr, r.returncode
        except subprocess.TimeoutExpired:
            return "", "timeout", 124
        except OSError as e:
            return "", str(e), 127

    def read_text(self, path: str) -> str | None:
        out, _, code = self.run(["cat", path], timeout=3.0)
        if code != 0:
            return None
        return out

    def http_base_strata(self) -> str:
        # Reach Strata via remote curl at the LAN bind (not 127.0.0.1).
        from inftop.strata import DEFAULT_STRATA_URL

        return f"ssh://{self.host}/{DEFAULT_STRATA_URL}"

    def http_base_ollama(self) -> str:
        return f"ssh://{self.host}/http://127.0.0.1:11434"

    def sysfs_drm(self) -> str:
        return "/sys/class/drm"

    def remote_http_get(self, url: str, headers: dict[str, str] | None = None) -> tuple[Any | None, str | None]:
        """GET JSON via remote curl (used when base is ssh://...)."""
        import json

        hdrs = []
        for k, v in (headers or {}).items():
            hdrs.extend(["-H", f"{k}: {v}"])
        # Strip ssh://host/ prefix if present
        real = url
        if url.startswith("ssh://"):
            # ssh://gpu-box/http://127.0.0.1:8080/health
            parts = url.split("/", 3)
            real = parts[3] if len(parts) > 3 else url
        cmd = ["curl", "-sS", "--max-time", "2", *hdrs, real]
        out, err, code = self.run(cmd, timeout=5.0)
        if code != 0:
            return None, err.strip() or f"curl exit {code}"
        try:
            return (json.loads(out) if out.strip() else {}), None
        except json.JSONDecodeError as e:
            return None, str(e)

    def close(self) -> None:
        try:
            subprocess.run(
                [
                    "ssh",
                    "-o",
                    f"ControlPath={self._ctrl}",
                    "-O",
                    "exit",
                    self.host,
                ],
                capture_output=True,
                timeout=3,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            pass
        try:
            Path(self._ctrl).unlink(missing_ok=True)
        except OSError:
            pass


def make_transport(remote: str | None) -> LocalTransport | SSHTransport:
    if remote:
        return SSHTransport(remote)
    return LocalTransport()
