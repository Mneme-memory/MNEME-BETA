"""
Power management — optionally keep the PC awake for as long as Mneme is
running, so mobile clients (Tailscale) stay able to reach it.

Windows-only for now. Uses SetThreadExecutionState with ES_SYSTEM_REQUIRED
(no ES_DISPLAY_REQUIRED — the screen is still allowed to turn off, only
system sleep is suppressed).

GOTCHA: SetThreadExecutionState is a per-thread flag maintained by Windows —
it only has effect for as long as the calling thread is alive, and it resets
the moment that thread exits. It must therefore be called from a dedicated,
long-lived daemon thread (not a request handler thread, which exits after
each request). This module spawns exactly one such thread and coordinates
it with an Event: the thread sets the "stay awake" flag, blocks on the
Event, and clears the flag when signaled to release.
"""

import ctypes
import platform
import threading

ES_CONTINUOUS = 0x80000000
ES_SYSTEM_REQUIRED = 0x00000001

_lock = threading.Lock()
_release_event = None
_worker_thread = None
_active = False
_warned_non_windows = False


def _worker(release_event):
    """Runs on a dedicated daemon thread for the lifetime of the lock."""
    kernel32 = ctypes.windll.kernel32
    kernel32.SetThreadExecutionState(ES_CONTINUOUS | ES_SYSTEM_REQUIRED)
    try:
        release_event.wait()
    finally:
        # Clear the flag before the thread exits so Windows stops treating
        # this thread as a reason to stay awake.
        kernel32.SetThreadExecutionState(ES_CONTINUOUS)


def is_supported():
    return platform.system() == "Windows"


def is_active():
    with _lock:
        return _active


def acquire():
    """Start keeping the system awake. Safe to call repeatedly (no-op if
    already active)."""
    global _release_event, _worker_thread, _active, _warned_non_windows

    if not is_supported():
        if not _warned_non_windows:
            print("[PowerManagement] keep_pc_awake is only supported on Windows; ignoring.")
            _warned_non_windows = True
        return

    with _lock:
        if _active:
            return
        _release_event = threading.Event()
        _worker_thread = threading.Thread(
            target=_worker, args=(_release_event,), daemon=True,
            name="PowerManagementKeepAwake",
        )
        _worker_thread.start()
        _active = True
        print("[PowerManagement] System sleep suppressed (display may still turn off).")


def release():
    """Stop keeping the system awake. Safe to call repeatedly (no-op if
    already inactive)."""
    global _release_event, _worker_thread, _active

    with _lock:
        if not _active:
            return
        _release_event.set()
        _worker_thread = None
        _release_event = None
        _active = False
        print("[PowerManagement] System sleep no longer suppressed.")


def apply_setting(enabled):
    """Engage or release the lock to match a boolean config/setting value."""
    if enabled:
        acquire()
    else:
        release()
