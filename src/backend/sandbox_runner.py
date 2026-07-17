"""Fail-closed Windows AppContainer execution backend for ``@run``."""

from __future__ import annotations

import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

try:
    from src.backend.config import get_mneme_home
except ModuleNotFoundError:
    from config import get_mneme_home


PROJECT_ROOT = Path(__file__).resolve().parents[2]
RUNNER_ROOT = PROJECT_ROOT / "src" / "native" / "mneme-runner"
SENSITIVE_KEY_PARTS = (
    "api_key", "apikey", "secret", "password", "credential",
    "access_token", "auth_token", "refresh_token",
)
BLOCKED_REPOSITORY_NAMES = {"config.json", ".env", ".env.local"}
UNTRACKED_RUNTIME_DIRS = {
    ".git", ".agents", ".claude", ".codex", ".codex-remote-attachments",
    ".pytest_cache", ".ruff_cache", "__pycache__", "backups", "build",
    "data", "exports", "logs", "node_modules", "temp", "venv", ".venv",
    "video-captures",
}


class SandboxUnavailable(RuntimeError):
    """Raised when the read-only sandbox cannot be established safely."""


@dataclass
class SandboxResult:
    stdout: str
    stderr: str
    return_code: int
    timed_out: bool = False


def _is_sensitive_key(key: str) -> bool:
    normalized = key.lower().replace("-", "_")
    return normalized == "api_keys" or any(part in normalized for part in SENSITIVE_KEY_PARTS)


def _redact_config(value: Any, key: str = "", sensitive_parent: bool = False) -> Any:
    sensitive = sensitive_parent or _is_sensitive_key(key)
    if isinstance(value, dict):
        return {item_key: _redact_config(item_value, item_key, sensitive)
                for item_key, item_value in value.items()}
    if isinstance(value, list):
        return [_redact_config(item, key, sensitive) for item in value]
    if sensitive and value:
        return "[REDACTED]"
    return value


def _collect_secret_values(value: Any, key: str = "", sensitive_parent: bool = False) -> set[str]:
    found = set()
    sensitive = sensitive_parent or _is_sensitive_key(key)
    if isinstance(value, dict):
        for item_key, item_value in value.items():
            found.update(_collect_secret_values(item_value, item_key, sensitive))
    elif isinstance(value, list):
        for item in value:
            found.update(_collect_secret_values(item, key, sensitive))
    elif sensitive:
        if isinstance(value, str) and len(value) >= 6:
            found.add(value)
    return found


def _scrub(text: str, secrets: set[str]) -> str:
    for secret in sorted(secrets, key=len, reverse=True):
        text = text.replace(secret, "[REDACTED]")
    return text


def _clean_stderr(text: str) -> str:
    """Remove the harmless AppContainer Python executable-resolution warning."""
    return re.sub(
        r"(?m)^Failed to find real location of .*pythonw?\.exe\s*$\n?",
        "",
        text,
    ).strip()


def _repository_files() -> list[Path]:
    """Return the distributable working tree without private/runtime state."""
    git_dir = PROJECT_ROOT / ".git"
    if git_dir.exists() and shutil.which("git"):
        try:
            result = subprocess.run(
                ["git", "ls-files", "-z"], cwd=PROJECT_ROOT,
                capture_output=True, check=True,
            )
        except (subprocess.CalledProcessError, OSError):
            result = None
        if result is not None:
            return [PROJECT_ROOT / os.fsdecode(item)
                    for item in result.stdout.split(b"\0") if item]

    files = []
    for directory, names, filenames in os.walk(PROJECT_ROOT):
        names[:] = [name for name in names if name not in UNTRACKED_RUNTIME_DIRS]
        base = Path(directory)
        for filename in filenames:
            if filename not in BLOCKED_REPOSITORY_NAMES and not filename.endswith(".pyc"):
                files.append(base / filename)
    return files


def _mirror_file(source: Path, target: Path, secrets: set[str]) -> None:
    """Hard-link one file into the mirror, copying scrubbed bytes if it holds a secret."""
    target.parent.mkdir(parents=True, exist_ok=True)
    source_bytes = source.read_bytes()
    scrubbed_bytes = source_bytes
    for secret in secrets:
        scrubbed_bytes = scrubbed_bytes.replace(
            secret.encode("utf-8"), b"[REDACTED]"
        )
    if scrubbed_bytes != source_bytes:
        target.write_bytes(scrubbed_bytes)
        return
    try:
        os.link(source, target)
    except OSError:
        shutil.copy2(source, target)


def _mirror_repository(destination: Path, redacted_config: dict, secrets: set[str]) -> None:
    """Create a fast hard-linked view, replacing the credential-bearing config."""
    destination.mkdir(parents=True)
    for source in _repository_files():
        if not source.is_file() or source.name in BLOCKED_REPOSITORY_NAMES:
            continue
        _mirror_file(source, destination / source.relative_to(PROJECT_ROOT), secrets)
    # The live instructions come from the Mneme home, which may sit outside
    # the repository tree — mirrored at the root where the AI expects them.
    live_instructions = get_mneme_home() / "system_instructions.txt"
    if live_instructions.is_file():
        _mirror_file(live_instructions, destination / "system_instructions.txt", secrets)
    (destination / "config.json").write_text(
        json.dumps(redacted_config, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8",
    )


def _runner_path() -> Path:
    machine = platform.machine().lower()
    architecture = "arm64" if machine in {"arm64", "aarch64"} else "x64"
    candidates = [
        RUNNER_ROOT / "bin" / architecture / "mneme-runner.exe",
        PROJECT_ROOT / "build" / "mneme-runner" / architecture / "mneme-runner.exe",
    ]
    # Windows 11 on ARM can execute x64 binaries. Prefer native ARM64, but keep
    # an emulated compatibility path until every release includes both builds.
    if architecture == "arm64":
        candidates.extend([
            RUNNER_ROOT / "bin" / "x64" / "mneme-runner.exe",
            PROJECT_ROOT / "build" / "mneme-runner" / "x64" / "mneme-runner.exe",
        ])
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    raise SandboxUnavailable(
        f"The {architecture} read-only runner is not installed. No code was executed."
    )


class AppContainerBackend:
    """Execute arbitrary Python with read-only inputs and disposable scratch."""

    def __init__(self, db_path, config, artifacts_path=None, attachments_path=None):
        self.db_path = Path(db_path)
        self.config = config
        self.artifacts_path = Path(artifacts_path) if artifacts_path else None
        self.attachments_path = Path(attachments_path) if attachments_path else None

    def execute(self, code: str, timeout_seconds=10, memory_mb=256,
                scratch_mb=64) -> SandboxResult:
        if os.name != "nt":
            raise SandboxUnavailable("The read-only @run sandbox currently requires Windows.")
        runner = _runner_path()
        secrets = _collect_secret_values(self.config)
        redacted_config = _redact_config(self.config)

        with tempfile.TemporaryDirectory(prefix="mneme-run-") as temporary:
            root = Path(temporary)
            input_root = root / "input"
            repository = input_root / "repo"
            scratch = root / "scratch"
            input_root.mkdir(parents=True)
            scratch.mkdir(parents=True)
            _mirror_repository(repository, redacted_config, secrets)
            redacted_config_path = repository / "config.json"
            script = input_root / "run.py"
            script.write_text(code, encoding="utf-8")
            stdout_path = scratch / "stdout.txt"
            stderr_path = scratch / "stderr.txt"

            db_uri = self.db_path.resolve().as_uri() + "?mode=ro"
            profile_dir = self.db_path.parent
            command = [
                str(runner),
                "--python", sys.executable,
                "--script", str(script),
                "--input-root", str(input_root),
                "--scratch", str(scratch),
                "--stdout", str(stdout_path),
                "--stderr", str(stderr_path),
                "--timeout-ms", str(int(timeout_seconds * 1000)),
                "--memory-mb", str(memory_mb),
                "--scratch-mb", str(scratch_mb),
                "--env", f"DB_PATH={db_uri}",
                "--env", f"REPO_PATH={repository}",
                "--env", f"CONFIG_PATH={redacted_config_path}",
                "--env", f"SRC_PATH={repository / 'src'}",
                "--env", f"ARTIFACTS_PATH={self.artifacts_path or ''}",
                "--env", f"ATTACHMENTS_PATH={self.attachments_path or ''}",
                "--env", f"SCRATCH_PATH={scratch}",
                "--read", str(profile_dir),
            ]
            for read_root in (self.artifacts_path, self.attachments_path):
                if (read_root and read_root.exists()
                        and profile_dir not in read_root.resolve().parents
                        and read_root.resolve() != profile_dir.resolve()):
                    command.extend(["--read", str(read_root)])

            try:
                process = subprocess.run(
                    command,
                    stdin=subprocess.DEVNULL,
                    capture_output=True,
                    text=True,
                    timeout=timeout_seconds + 5,
                    check=False,
                    close_fds=True,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
            except subprocess.TimeoutExpired as exc:
                raise SandboxUnavailable(
                    "The sandbox runner stopped responding. No unsandboxed fallback was used."
                ) from exc

            runner_error = _scrub(process.stderr.strip(), secrets)
            if 200 <= process.returncode <= 207:
                raise SandboxUnavailable(
                    f"The read-only sandbox could not start: {runner_error or 'unknown runner error'}"
                )
            stdout = _scrub(stdout_path.read_text(encoding="utf-8", errors="replace")
                            if stdout_path.exists() else "", secrets)
            stderr = _clean_stderr(_scrub(
                stderr_path.read_text(encoding="utf-8", errors="replace")
                if stderr_path.exists() else "", secrets
            ))
            return SandboxResult(
                stdout=stdout,
                stderr=stderr,
                return_code=process.returncode,
                timed_out=process.returncode == 124,
            )
