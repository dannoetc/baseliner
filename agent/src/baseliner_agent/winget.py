import re
import subprocess
from dataclasses import dataclass
from typing import Optional


@dataclass
class WingetResult:
    exit_code: int
    stdout: str
    stderr: str


def _run(args: list[str], timeout_s: int = 900) -> WingetResult:
    p = subprocess.run(args, capture_output=True, text=True, timeout=timeout_s, shell=False)
    return WingetResult(exit_code=p.returncode, stdout=p.stdout or "", stderr=p.stderr or "")


def list_package(package_id: str) -> WingetResult:
    return _run(["winget", "list", "--id", package_id, "--exact"])


def install_package(package_id: str) -> WingetResult:
    return _run([
        "winget", "install",
        "--id", package_id,
        "--exact",
        "--silent",
        "--accept-package-agreements",
        "--accept-source-agreements",
    ])


def upgrade_package(package_id: str) -> WingetResult:
    return _run([
        "winget", "upgrade",
        "--id", package_id,
        "--exact",
        "--silent",
        "--accept-package-agreements",
        "--accept-source-agreements",
    ])


def installed_from_list_output(stdout: str, package_id: str) -> bool:
    pid = package_id.lower()
    return any(pid in (ln or "").lower() for ln in stdout.splitlines())


def parse_version_from_list_output(stdout: str, package_id: str) -> Optional[str]:
    for ln in stdout.splitlines():
        if package_id.lower() in (ln or "").lower():
            tokens = re.split(r"\s{2,}", ln.strip())
            if len(tokens) >= 3:
                v = tokens[2].strip()
                return v or None
    return None
