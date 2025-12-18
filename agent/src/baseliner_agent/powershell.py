"""PowerShell execution helpers for the Windows agent.

MVP constraints:
  - always non-interactive
  - bounded execution (timeouts)
  - best-effort process tree termination on timeout
  - return 124 on timeout (matches curl/wget convention)
"""

import base64
import os
import shutil
import subprocess
from dataclasses import dataclass
from typing import Sequence


@dataclass
class PowerShellResult:
    exit_code: int
    stdout: str
    stderr: str
    engine: str  # "pwsh" or "powershell"


def pick_powershell() -> str:
    if shutil.which("pwsh"):
        return "pwsh"
    if shutil.which("powershell"):
        return "powershell"
    raise RuntimeError("No PowerShell host found (pwsh.exe or powershell.exe).")


def _encode_command(script: str) -> str:
    # PowerShell expects UTF-16LE for EncodedCommand
    raw = script.encode("utf-16le")
    return base64.b64encode(raw).decode("ascii")


def _kill_process_tree(pid: int) -> None:
    """Best-effort kill of a process tree on Windows."""
    try:
        subprocess.run(
            ["taskkill", "/PID", str(pid), "/T", "/F"],
            capture_output=True,
            text=True,
            timeout=10,
            shell=False,
        )
    except Exception:
        return


def _run(args: Sequence[str], *, timeout_s: int) -> tuple[int, str, str]:
    """Run a command with timeout; on timeout kill the process tree."""
    try:
        p = subprocess.Popen(
            list(args),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            shell=False,
        )
    except FileNotFoundError as e:
        return 127, "", str(e)

    try:
        out, err = p.communicate(timeout=timeout_s)
        return p.returncode or 0, out or "", err or ""
    except subprocess.TimeoutExpired:
        _kill_process_tree(p.pid)
        try:
            p.kill()
        except Exception:
            pass

        # Drain pipes best-effort
        try:
            out, err = p.communicate(timeout=2)
        except Exception:
            out, err = "", ""

        msg = f"timeout after {timeout_s}s; killed process tree pid={p.pid}"
        err_full = (err or "")
        err_full = (err_full + "\n" + msg) if err_full else msg
        return 124, out or "", err_full


def run_ps(script: str, timeout_s: int = 300) -> PowerShellResult:
    """
    Runs a PowerShell script safely via -EncodedCommand.
    Preserves exit code; returns 124 on timeout.
    """
    engine = pick_powershell()

    args = [
        engine,
        "-NoProfile",
        "-NonInteractive",
        "-ExecutionPolicy",
        "Bypass",
        "-EncodedCommand",
        _encode_command(script),
    ]

    code, out, err = _run(args, timeout_s=timeout_s)
    return PowerShellResult(exit_code=code, stdout=out, stderr=err, engine=engine)


def run_ps_file(path: str, *, timeout_s: int = 300, args: Sequence[str] | None = None) -> PowerShellResult:
    """Run a PowerShell script file via -File.

    Returns:
      - exit_code from the script
      - 124 on timeout
      - 127 if the path doesn't exist
    """
    p = (path or "").strip().strip('"')
    if not p:
        return PowerShellResult(exit_code=127, stdout="", stderr="empty path", engine="powershell")

    if not os.path.exists(p):
        return PowerShellResult(exit_code=127, stdout="", stderr=f"file not found: {p}", engine="powershell")

    engine = pick_powershell()

    argv = [
        engine,
        "-NoProfile",
        "-NonInteractive",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        p,
    ]
    if args:
        argv.extend([str(a) for a in args])

    code, out, err = _run(argv, timeout_s=timeout_s)
    return PowerShellResult(exit_code=code, stdout=out, stderr=err, engine=engine)
