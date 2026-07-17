"""
Mneme System Tray — lightweight launcher for the Mneme server.

Sits in the Windows system tray with actions:
  - Start / Stop / Restart server
  - Open in browser
  - Quit

Usage:
    python scripts/tray.py
    pythonw scripts/tray.py   (no console window)
"""

import subprocess
import sys
import os
import shutil
import webbrowser
import json
import threading
import time
from urllib import request as urlrequest
from urllib.error import URLError
from pathlib import Path

import pystray
from PIL import Image

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parent.parent
TRAY_DIR = PROJECT_ROOT / "Logos" / "tray"

if sys.platform == "darwin":
    # macOS: template image — OS handles light/dark and active/inactive styling
    ICON_ONLINE_PATH = TRAY_DIR / "18-black.png"
    ICON_OFFLINE_PATH = TRAY_DIR / "18-black.png"  # macOS dims automatically
elif sys.platform == "win32":
    ICON_ONLINE_PATH = TRAY_DIR / "32.png"
    ICON_OFFLINE_PATH = TRAY_DIR / "32-grey.png"
else:
    # Linux
    ICON_ONLINE_PATH = TRAY_DIR / "22.png"
    ICON_OFFLINE_PATH = TRAY_DIR / "22-grey.png"

def _mneme_home():
    """
    Resolve the Mneme home directory (self-contained; no backend import).

    keep in sync with src/backend/config.get_mneme_home

    Resolution order: MNEME_HOME env override -> %LOCALAPPDATA%/Mneme if it
    already holds a config.json -> PROJECT_ROOT if IT holds a config.json
    (legacy layout) -> %LOCALAPPDATA%/Mneme (default for fresh installs).
    """
    env_home = os.environ.get("MNEME_HOME")
    if env_home:
        return Path(env_home)

    default_home = Path(os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")) / "Mneme"
    if (default_home / "config.json").exists():
        return default_home

    if (PROJECT_ROOT / "config.json").exists():
        return PROJECT_ROOT

    return default_home


MNEME_HOME = _mneme_home()
CONFIG_PATH = MNEME_HOME / "config.json"
SERVER_SCRIPT = PROJECT_ROOT / "src" / "backend" / "server.py"
FIRST_LAUNCH_MARKER = MNEME_HOME / "data" / ".launched"
SERVER_PID_FILE = MNEME_HOME / "data" / ".server.pid"
PYTHON_PATH_FILE = PROJECT_ROOT / "scripts" / ".python-path"

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

def get_port():
    try:
        with open(CONFIG_PATH, encoding="utf-8") as f:
            config = json.load(f)
        return config.get("system", {}).get("server_port", 8080)
    except Exception:
        return 8080

# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------

server_proc = None
tray_icon = None  # Global reference so the watchdog can update it
image_online = None
image_offline = None
_last_known_state = None  # Track state to avoid redundant icon updates


def server_running():
    return server_proc is not None and server_proc.poll() is None


def server_readiness():
    """Return stopped, starting, ready, or failed based on the process and HTTP status."""
    if not server_running():
        return "stopped"

    port = get_port()
    try:
        with urlrequest.urlopen(f"http://127.0.0.1:{port}/api/startup/status", timeout=0.6) as response:
            data = json.loads(response.read().decode("utf-8"))
        state = data.get("state")
        if state in ("ready", "failed"):
            return state
        return "starting"
    except (OSError, URLError, json.JSONDecodeError):
        return "starting"


def wait_for_server_ready(timeout=120):
    """Wait for the server to become app-ready, while leaving the tray responsive."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        state = server_readiness()
        sync_icon_state()
        if state in ("ready", "failed", "stopped"):
            return state
        time.sleep(0.5)
    return server_readiness()


# ---------------------------------------------------------------------------
# Icon switching
# ---------------------------------------------------------------------------

def sync_icon_state():
    """Update the tray icon to match the current server state.
    Called by the watchdog and after start/stop actions."""
    global _last_known_state
    if tray_icon is None:
        return

    state = server_readiness()
    if state == _last_known_state:
        return  # No change

    _last_known_state = state
    if state == "ready":
        tray_icon.icon = image_online
        tray_icon.title = "Mneme — running"
    elif state == "failed":
        tray_icon.icon = image_offline
        tray_icon.title = "Mneme — startup failed"
    elif state == "starting":
        tray_icon.icon = image_offline
        tray_icon.title = "Mneme — starting..."
    else:
        tray_icon.icon = image_offline
        tray_icon.title = "Mneme — stopped"
    tray_icon.update_menu()


# ---------------------------------------------------------------------------
# Orphan cleanup — kill leftover server from a previous crash
# ---------------------------------------------------------------------------

def kill_orphaned_server():
    """If a PID file exists from a previous run, kill that process."""
    if not SERVER_PID_FILE.exists():
        return
    try:
        pid = int(SERVER_PID_FILE.read_text().strip())
        # Check if it's actually a python process running our server
        if sys.platform == "win32":
            import ctypes
            kernel32 = ctypes.windll.kernel32
            handle = kernel32.OpenProcess(0x0001, False, pid)  # PROCESS_TERMINATE
            if handle:
                kernel32.TerminateProcess(handle, 1)
                kernel32.CloseHandle(handle)
        else:
            import signal
            os.kill(pid, signal.SIGTERM)
    except (ValueError, OSError, ProcessLookupError):
        pass  # Process already gone
    finally:
        SERVER_PID_FILE.unlink(missing_ok=True)


def write_pid_file(pid):
    SERVER_PID_FILE.parent.mkdir(parents=True, exist_ok=True)
    SERVER_PID_FILE.write_text(str(pid), encoding="utf-8")


def clear_pid_file():
    SERVER_PID_FILE.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# Job object (Windows) — auto-kill server if tray process dies
# ---------------------------------------------------------------------------

_job_handle = None

def setup_job_object():
    """Create a Windows Job Object that kills child processes when the tray exits."""
    global _job_handle
    if sys.platform != "win32":
        return

    try:
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.windll.kernel32

        # CreateJobObjectW(lpJobAttributes, lpName)
        _job_handle = kernel32.CreateJobObjectW(None, None)
        if not _job_handle:
            return

        # Configure job to kill children on close
        # JOBOBJECT_EXTENDED_LIMIT_INFORMATION
        class JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
            _fields_ = [
                ("PerProcessUserTimeLimit", ctypes.c_int64),
                ("PerJobUserTimeLimit", ctypes.c_int64),
                ("LimitFlags", wintypes.DWORD),
                ("MinimumWorkingSetSize", ctypes.c_size_t),
                ("MaximumWorkingSetSize", ctypes.c_size_t),
                ("ActiveProcessLimit", wintypes.DWORD),
                ("Affinity", ctypes.POINTER(ctypes.c_ulong)),
                ("PriorityClass", wintypes.DWORD),
                ("SchedulingClass", wintypes.DWORD),
            ]

        class IO_COUNTERS(ctypes.Structure):
            _fields_ = [
                ("ReadOperationCount", ctypes.c_uint64),
                ("WriteOperationCount", ctypes.c_uint64),
                ("OtherOperationCount", ctypes.c_uint64),
                ("ReadTransferCount", ctypes.c_uint64),
                ("WriteTransferCount", ctypes.c_uint64),
                ("OtherTransferCount", ctypes.c_uint64),
            ]

        class JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
            _fields_ = [
                ("BasicLimitInformation", JOBOBJECT_BASIC_LIMIT_INFORMATION),
                ("IoInfo", IO_COUNTERS),
                ("ProcessMemoryLimit", ctypes.c_size_t),
                ("JobMemoryLimit", ctypes.c_size_t),
                ("PeakProcessMemoryUsed", ctypes.c_size_t),
                ("PeakJobMemoryUsed", ctypes.c_size_t),
            ]

        info = JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
        # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x2000
        info.BasicLimitInformation.LimitFlags = 0x2000

        # SetInformationJobObject(hJob, JobObjectExtendedLimitInformation, &info, sizeof)
        kernel32.SetInformationJobObject(
            _job_handle,
            9,  # JobObjectExtendedLimitInformation
            ctypes.byref(info),
            ctypes.sizeof(info),
        )
    except Exception:
        _job_handle = None


def assign_to_job(proc):
    """Add a process to the job object so it dies when the tray dies."""
    if _job_handle is None or sys.platform != "win32":
        return
    try:
        import ctypes
        kernel32 = ctypes.windll.kernel32
        # PROCESS_SET_QUOTA | PROCESS_TERMINATE
        handle = kernel32.OpenProcess(0x0100 | 0x0001, False, proc.pid)
        if handle:
            kernel32.AssignProcessToJobObject(_job_handle, handle)
            kernel32.CloseHandle(handle)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Server process management
# ---------------------------------------------------------------------------

def start_server(icon=None, item=None):
    global server_proc
    if server_running():
        return

    env = os.environ.copy()
    env["PYTHONUTF8"] = "1"

    popen_kwargs = dict(
        cwd=str(PROJECT_ROOT),
        env=env,
    )
    # CREATE_NO_WINDOW is Windows-only — suppresses console on pythonw
    if sys.platform == "win32":
        popen_kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW

    # Prefer the interpreter resolved by the installer so dependencies and
    # runtime are tied together even if PATH changes after installation.
    python_exe = None
    if PYTHON_PATH_FILE.exists():
        recorded = PYTHON_PATH_FILE.read_text(encoding="utf-8").strip()
        if recorded and Path(recorded).exists():
            python_exe = recorded

    if not python_exe:
        # Use 'python' explicitly — sys.executable may be 'pythonw' which
        # suppresses stdout/stderr and can cause the server to crash on print()
        python_exe = shutil.which("python") or sys.executable

    server_proc = subprocess.Popen(
        [python_exe, str(SERVER_SCRIPT)],
        **popen_kwargs,
    )

    # Track the server PID and tie it to the tray's lifecycle
    write_pid_file(server_proc.pid)
    assign_to_job(server_proc)

    sync_icon_state()
    state = wait_for_server_ready()

    if state == "ready" and tray_icon:
        tray_icon.notify("Mneme is ready. Catch-up memory work may continue in the background.", "Mneme")
    elif state == "failed" and tray_icon:
        tray_icon.notify("Mneme startup failed", "Mneme")
    elif state == "starting" and tray_icon:
        tray_icon.notify("Mneme is still starting", "Mneme")
    elif tray_icon:
        tray_icon.notify("Mneme server failed to start", "Mneme")


def stop_server(icon=None, item=None):
    global server_proc
    if not server_running():
        return
    server_proc.terminate()
    try:
        server_proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        server_proc.kill()
    server_proc = None
    clear_pid_file()
    sync_icon_state()
    if tray_icon:
        tray_icon.notify("Mneme server stopped", "Mneme")


def restart_server(icon=None, item=None):
    stop_server()
    start_server()


# ---------------------------------------------------------------------------
# First launch
# ---------------------------------------------------------------------------

def is_first_launch():
    return not FIRST_LAUNCH_MARKER.exists()


def mark_launched():
    FIRST_LAUNCH_MARKER.parent.mkdir(parents=True, exist_ok=True)
    FIRST_LAUNCH_MARKER.write_text("launched", encoding="utf-8")


# ---------------------------------------------------------------------------
# Menu actions
# ---------------------------------------------------------------------------

def open_browser(icon=None, item=None):
    port = get_port()
    webbrowser.open(f"http://localhost:{port}")


def quit_app(icon, item):
    stop_server()
    clear_pid_file()
    icon.stop()


def server_status_text(item):
    state = server_readiness()
    if state == "ready":
        return "Server: running"
    if state == "starting":
        return "Server: starting"
    if state == "failed":
        return "Server: startup failed"
    return "Server: stopped"


# ---------------------------------------------------------------------------
# Watchdog — monitors server health, updates icon if process dies
# ---------------------------------------------------------------------------

def watchdog():
    """Periodically check if the server process is still alive."""
    while True:
        time.sleep(3)
        sync_icon_state()


# ---------------------------------------------------------------------------
# Build tray
# ---------------------------------------------------------------------------

def on_tray_ready(icon):
    """Called once the tray icon is visible and ready to show notifications."""
    global tray_icon
    tray_icon = icon
    icon.visible = True

    def _startup():
        first_launch = is_first_launch()
        start_server()
        if first_launch:
            time.sleep(0.5)
            icon.notify(
                "Mneme is running! Right-click the tray icon for options.",
                "Welcome to Mneme",
            )
            mark_launched()

    threading.Thread(target=_startup, daemon=True).start()
    threading.Thread(target=watchdog, daemon=True).start()


def main():
    global image_online, image_offline

    # Clean up any orphaned server from a previous crash
    kill_orphaned_server()

    # Set up job object so server dies if tray is force-closed
    setup_job_object()

    image_online = Image.open(ICON_ONLINE_PATH)
    image_offline = Image.open(ICON_OFFLINE_PATH)

    menu = pystray.Menu(
        pystray.MenuItem(server_status_text, None, enabled=False),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Start server", start_server, enabled=lambda item: not server_running()),
        pystray.MenuItem("Stop server", stop_server, enabled=lambda item: server_running()),
        pystray.MenuItem("Restart server", restart_server, enabled=lambda item: server_running()),
        pystray.MenuItem("Open in browser", open_browser),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Quit", quit_app),
    )

    # Start with offline icon — on_tray_ready will switch after server starts
    icon = pystray.Icon("mneme", image_offline, "Mneme — starting...", menu)
    icon.run(setup=on_tray_ready)


if __name__ == "__main__":
    main()
