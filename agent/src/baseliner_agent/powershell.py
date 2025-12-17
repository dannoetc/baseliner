# agent/src/baseliner_agent/powershell.py
import base64
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
