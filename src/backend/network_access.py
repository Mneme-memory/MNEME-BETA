"""Network access policy for Mneme's local and Tailscale clients."""

from __future__ import annotations

import ipaddress
import json
import shutil
import subprocess
import threading
import time
from collections import OrderedDict
from pathlib import Path


TAILSCALE_V4 = ipaddress.ip_network("100.64.0.0/10")
TAILSCALE_V6 = ipaddress.ip_network("fd7a:115c:a1e0::/48")


class TailscaleAccessGate:
    """Allow loopback and identities verified by the local Tailscale daemon."""

    def __init__(self, positive_ttl=60.0, negative_ttl=3.0, max_entries=256):
        self.positive_ttl = positive_ttl
        self.negative_ttl = negative_ttl
        self.max_entries = max_entries
        self._cache = OrderedDict()
        self._lock = threading.Lock()

    @staticmethod
    def _normalize(address):
        try:
            ip = ipaddress.ip_address(address)
        except (TypeError, ValueError):
            return None
        if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
            return ip.ipv4_mapped
        return ip

    @staticmethod
    def _tailscale_executable():
        located = shutil.which("tailscale")
        if located:
            return located
        fallback = Path(r"C:\Program Files\Tailscale\tailscale.exe")
        return str(fallback) if fallback.is_file() else None

    def _cached(self, key):
        now = time.monotonic()
        with self._lock:
            item = self._cache.get(key)
            if not item:
                return None
            allowed, expires = item
            if expires <= now:
                del self._cache[key]
                return None
            self._cache.move_to_end(key)
            return allowed

    def _store(self, key, allowed):
        ttl = self.positive_ttl if allowed else self.negative_ttl
        with self._lock:
            self._cache[key] = (allowed, time.monotonic() + ttl)
            self._cache.move_to_end(key)
            while len(self._cache) > self.max_entries:
                self._cache.popitem(last=False)

    @staticmethod
    def _identity_contains_address(payload, address):
        node = payload.get("Node") if isinstance(payload, dict) else None
        if not isinstance(node, dict) or node.get("MachineAuthorized") is False:
            return False
        for value in node.get("Addresses", []):
            try:
                if ipaddress.ip_interface(value).ip == address:
                    return True
            except (TypeError, ValueError):
                continue
        return False

    def allows(self, remote_address):
        address = self._normalize(remote_address)
        if address is None:
            return False
        if address.is_loopback:
            return True
        if address not in TAILSCALE_V4 and address not in TAILSCALE_V6:
            return False

        key = str(address)
        cached = self._cached(key)
        if cached is not None:
            return cached

        executable = self._tailscale_executable()
        if not executable:
            self._store(key, False)
            return False
        try:
            result = subprocess.run(
                [executable, "whois", "--json", key],
                capture_output=True,
                text=True,
                timeout=1.0,
                check=False,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            payload = json.loads(result.stdout) if result.returncode == 0 else None
            allowed = self._identity_contains_address(payload, address)
        except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError):
            allowed = False

        self._store(key, allowed)
        return allowed

