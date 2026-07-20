# Mneme read-only runner

Native Windows AppContainer host for `@run`. The helper receives an already
sanitized input tree, grants its AppContainer identity read access to that tree
and the selected Python runtime, grants write access only to disposable scratch
storage, launches one child process with no network capabilities, and captures
stdout/stderr.

The backend must fail closed if the helper is missing or returns a sandbox setup
error. It must never fall back to an ordinary Python subprocess.

Granting access leaves a persistent read/execute ACE for the
`Mneme.ReadOnlyRunner` AppContainer SID on the Python install directory, the
profile directory, and the artifacts/attachments roots. The helper skips the
grant when a covering ACE already exists, so only the first run on a machine
pays the ACL propagation cost. Granting fails (exit 204) when the invoking user
cannot modify the target's DACL — typically a system-wide Python install; use a
per-user Python instead.

Build precompiled x64 and ARM64 helpers from a Visual Studio developer machine:

```powershell
.\build.ps1 -Architecture all
```

End users do not build this component. Release archives include prebuilt
binaries under `bin/x64` and, once the native ARM64 release build is enabled,
`bin/arm64`. The backend prefers the native machine architecture; Windows 11
ARM can use the x64 helper through its built-in emulation as a compatibility
path until the native ARM64 binary has been validated on hardware.
