# agent/src/baseliner_agent/powershell.py
import base64
import shutil
import subprocess
from dataclasses import dataclass


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


def run_ps(script: str, timeout_s: int = 300) -> PowerShellResult:
    """
    Runs a PowerShell script safely via -EncodedCommand.
    Preserves exit code.
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

    p = subprocess.run(
        args,
        capture_output=True,
        text=True,
        timeout=timeout_s,
        shell=False,
    )

    return PowerShellResult(
        exit_code=p.returncode,
        stdout=p.stdout or "",
        stderr=p.stderr or "",
        engine=engine,
    )
