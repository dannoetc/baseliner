from __future__ import annotations

import ctypes
import json
import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass
class WingetResult:
    exit_code: int
    stdout: str
    stderr: str


_WINGET_PATH: str | None = None

_DEFAULT_MSSTORE_REGION = "US"

_WINGET_LIST_NO_MATCH = 0x8A150014
_WINGET_LIST_NO_MATCH_TEXT = "No installed package found matching input criteria."

# winget show: "No package found matching input criteria."
_WINGET_SHOW_NO_MATCH_RE = re.compile(
    r"(no package found matching input criteria|found no package matching input criteria|no package found)",
    re.IGNORECASE,
)

# Prefer these sources for preflight. We try winget first (fast/quiet), then msstore.
_PREFLIGHT_SOURCES: list[str] = ["winget", "msstore"]


def configure_winget(path: str | None) -> None:
    global _WINGET_PATH
    path = (path or "").strip()
    _WINGET_PATH = path or None


def _is_system_context() -> bool:
    u = (os.environ.get("USERNAME") or "").lower()
    dom = (os.environ.get("USERDOMAIN") or "").lower()
    prof = (os.environ.get("USERPROFILE") or "").lower()
    if u == "system":
        return True
    if dom in ("nt authority",) and u == "system":
        return True
    if "systemprofile" in prof:
        return True
    return False


def _looks_like_user_windowsapps_alias(p: Path) -> bool:
    s = str(p).lower().replace("/", "\\")
    return "\\appdata\\local\\microsoft\\windowsapps\\winget.exe" in s and "\\users\\" in s


def _parse_version_tuple(s: str) -> tuple[int, ...]:
    out: list[int] = []
    for part in s.split("."):
        try:
            out.append(int(part))
        except Exception:
            out.append(0)
    return tuple(out)


def _candidate_version_from_path(p: Path) -> tuple[int, ...]:
    parent = p.parent.name
    m = re.search(r"Microsoft\.DesktopAppInstaller_(\d+(?:\.\d+)+)_", parent)
    if not m:
        return (0,)
    return _parse_version_tuple(m.group(1))


def _resolve_winget_via_appx_powershell() -> Optional[str]:
    try:
        cmd = [
            "powershell.exe",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-Command",
            (
                "$p = Get-AppxPackage -AllUsers Microsoft.DesktopAppInstaller "
                "| Sort-Object Version -Descending | Select-Object -First 1; "
                "if ($p -and $p.InstallLocation) { "
                "  $w = Join-Path $p.InstallLocation 'winget.exe'; "
                "  if (Test-Path $w) { Write-Output $w } "
                "}"
            ),
        ]
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=30, shell=False)
        out = (p.stdout or "").strip()
        if out and Path(out).exists():
            return out
    except Exception:
        pass
    return None


def resolve_winget() -> str:
    if _WINGET_PATH:
        p = Path(_WINGET_PATH)
        if _is_system_context() and _looks_like_user_windowsapps_alias(p):
            pass
        else:
            if p.exists():
                return str(p)
            raise RuntimeError(f"Configured winget_path does not exist: {_WINGET_PATH}")

    found = shutil.which("winget")
    if found:
        return found

    candidates: list[Path] = []

    local_appdata = os.environ.get("LOCALAPPDATA")
    if local_appdata:
        candidates.append(Path(local_appdata) / "Microsoft" / "WindowsApps" / "winget.exe")

    program_files = os.environ.get("ProgramFiles") or r"C:\Program Files"
    windowsapps = Path(program_files) / "WindowsApps"
    try:
        if windowsapps.exists():
            patterns = [
                "Microsoft.DesktopAppInstaller_*_x64__8wekyb3d8bbwe/winget.exe",
                "Microsoft.DesktopAppInstaller_*_neutral__8wekyb3d8bbwe/winget.exe",
                "Microsoft.DesktopAppInstaller_*__8wekyb3d8bbwe/winget.exe",
            ]
            for pat in patterns:
                candidates.extend(windowsapps.glob(pat))
    except Exception:
        pass

    candidates = [p for p in candidates if p and p.exists()]

    if candidates:
        candidates.sort(key=_candidate_version_from_path, reverse=True)
        return str(candidates[0])

    ps = _resolve_winget_via_appx_powershell()
    if ps:
        return ps

    raise RuntimeError(
        "winget.exe not found/usable in this context. "
        "If running as SYSTEM, ensure DesktopAppInstaller (winget) is installed/provisioned "
        "and set winget_path to the real package winget.exe (not the per-user WindowsApps alias)."
    )


# ----------------------------
# Output cleanup + msstore geo
# ----------------------------

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
_SPINNER_LINE_RE = re.compile(r"^\s*[-\\|/]\s*$")
_PROGRESS_HINT_RE = re.compile(r"MB\s*/\s*MB|KB\s*/\s*MB|KB\s*/\s*KB", re.IGNORECASE)
_BLOCK_CHARS_RE = re.compile(r"[█▓▒░]+")
_GARBLED_BLOCK_RE = re.compile(r"(?:Γû[êÆ]){3,}", re.IGNORECASE)

_MSSTORE_GEO_ERROR_RE = re.compile(
    r"msstore.*requires.*2-letter geographic region", re.IGNORECASE | re.DOTALL
)

_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
_GetUserGeoName = getattr(_kernel32, "GetUserGeoName", None)
_SetUserGeoName = getattr(_kernel32, "SetUserGeoName", None)

if _GetUserGeoName:
    _GetUserGeoName.argtypes = [ctypes.c_wchar_p, ctypes.c_int]
    _GetUserGeoName.restype = ctypes.c_int

if _SetUserGeoName:
    _SetUserGeoName.argtypes = [ctypes.c_wchar_p]
    _SetUserGeoName.restype = ctypes.c_int  # BOOL


def _decode(b: bytes) -> str:
    if not b:
        return ""
    try:
        return b.decode("utf-8", errors="replace")
    except Exception:
        try:
            return b.decode("utf-16-le", errors="replace")
        except Exception:
            return b.decode(errors="replace")


def _clean_output(text: str) -> str:
    if not text:
        return ""

    text = _ANSI_RE.sub("", text)

    out: list[str] = []
    for raw in text.splitlines():
        line = (raw or "").rstrip()

        if not line:
            out.append("")
            continue

        if _SPINNER_LINE_RE.match(line):
            continue

        if _PROGRESS_HINT_RE.search(line) and (_BLOCK_CHARS_RE.search(line) or _GARBLED_BLOCK_RE.search(line)):
            continue

        if (_BLOCK_CHARS_RE.search(line) or _GARBLED_BLOCK_RE.search(line)) and len(line) > 40:
            continue

        out.append(line)

    collapsed: list[str] = []
    for ln in out:
        if ln == "" and collapsed and collapsed[-1] == "":
            continue
        collapsed.append(ln)

    return "\n".join(collapsed).strip()


def _get_user_geo_name() -> Optional[str]:
    try:
        if not _GetUserGeoName:
            return None
        buf = ctypes.create_unicode_buffer(16)
        n = _GetUserGeoName(buf, len(buf))
        if n and buf.value:
            v = buf.value.strip().upper()
            if len(v) == 2:
                return v
    except Exception:
        pass
    return None


def _set_user_geo_name(code2: str) -> bool:
    try:
        if not _SetUserGeoName:
            return False
        code2 = (code2 or "").strip().upper()
        if len(code2) != 2:
            return False
        return bool(_SetUserGeoName(code2))
    except Exception:
        return False


def _ensure_msstore_region() -> None:
    current = _get_user_geo_name()
    if current and len(current) == 2:
        return

    desired = (os.environ.get("BASELINER_MSSTORE_REGION") or "").strip().upper()
    if not desired:
        desired = _DEFAULT_MSSTORE_REGION

    _set_user_geo_name(desired)


def _ensure_winget_settings_best_effort() -> None:
    try:
        local_appdata = os.environ.get("LOCALAPPDATA")
        if not local_appdata:
            return

        settings_path = (
            Path(local_appdata)
            / "Packages"
            / "Microsoft.DesktopAppInstaller_8wekyb3d8bbwe"
            / "LocalState"
            / "settings.json"
        )
        settings_path.parent.mkdir(parents=True, exist_ok=True)

        settings: dict = {}
        if settings_path.exists():
            try:
                settings = json.loads(settings_path.read_text(encoding="utf-8"))
                if not isinstance(settings, dict):
                    settings = {}
            except Exception:
                settings = {}

        changed = False
        src = settings.get("source")
        if not isinstance(src, dict):
            src = {}
        if src.get("autoUpdateIntervalInMinutes") != 0:
            src["autoUpdateIntervalInMinutes"] = 0
            settings["source"] = src
            changed = True

        if changed:
            settings_path.write_text(json.dumps(settings, indent=2) + "\n", encoding="utf-8")
    except Exception:
        return


def _run(args: list[str], timeout_s: int = 900) -> WingetResult:
    if args and args[0].lower() == "winget":
        args = [resolve_winget(), *args[1:]]

    _ensure_winget_settings_best_effort()

    try:
        p = subprocess.run(args, capture_output=True, text=False, timeout=timeout_s, shell=False)
        stdout = _clean_output(_decode(p.stdout or b""))
        stderr = _clean_output(_decode(p.stderr or b""))
        return WingetResult(exit_code=p.returncode, stdout=stdout, stderr=stderr)
    except OSError as e:
        return WingetResult(
            exit_code=1,
            stdout="",
            stderr=f"oserror running winget (winerror={getattr(e, 'winerror', None)}): {e}",
        )


def _is_list_no_match(r: WingetResult) -> bool:
    if r.exit_code == _WINGET_LIST_NO_MATCH:
        return True
    if _WINGET_LIST_NO_MATCH_TEXT.lower() in (r.stdout or "").lower():
        return True
    return False


def _maybe_fix_msstore_geo_and_retry(result: WingetResult, retry_args: list[str]) -> WingetResult:
    combined = f"{result.stdout}\n{result.stderr}"
    if _MSSTORE_GEO_ERROR_RE.search(combined):
        _ensure_msstore_region()
        return _run(retry_args)
    return result


def list_package(package_id: str, *, source: str | None = "winget") -> WingetResult:
    """
    Detect installed packages.

    Default behavior pins to source=winget and scope=machine (quiet + matches our install).
    If source is None, omit --source (use winget default).
    """
    args = [
        "winget",
        "list",
        "--id",
        package_id,
        "--exact",
        "--scope",
        "machine",
        "--accept-source-agreements",
        "--disable-interactivity",
    ]
    if source:
        args.extend(["--source", source])

    r = _run(args)
    r = _maybe_fix_msstore_geo_and_retry(r, args)

    if _is_list_no_match(r):
        return WingetResult(exit_code=0, stdout=r.stdout, stderr=r.stderr)
    return r



def show_package(package_id: str, *, source: Optional[str] = "winget") -> WingetResult:
    args = [
        "winget",
        "show",
        "--id",
        package_id,
        "--exact",
        "--accept-source-agreements",
        "--disable-interactivity",
    ]
    if source:
        args.extend(["--source", source])

    r = _run(args)
    r = _maybe_fix_msstore_geo_and_retry(r, args)
    return r


def package_id_exists_ex(package_id: str) -> tuple[bool, Optional[str], WingetResult]:
    last: WingetResult | None = None

    for src in _PREFLIGHT_SOURCES:
        r = show_package(package_id, source=src)
        last = r
        combined = f"{r.stdout}\n{r.stderr}".strip()

        if _WINGET_SHOW_NO_MATCH_RE.search(combined):
            continue

        if r.exit_code == 0:
            return (True, src, r)

        return (False, src, r)

    if last is None:
        last = WingetResult(exit_code=1, stdout="", stderr="preflight not executed")
    return (False, None, last)


def package_id_exists(package_id: str) -> tuple[bool, WingetResult]:
    exists, _src, r = package_id_exists_ex(package_id)
    return (exists, r)


def install_package(
    package_id: str,
    *,
    source: str | None = None,
    version: str | None = None,
    force: bool = False,
) -> WingetResult:
    args = [
        "winget",
        "install",
        "--id",
        package_id,
        "--exact",
        "--silent",
        "--disable-interactivity",
        "--scope",
        "machine",
        "--accept-package-agreements",
        "--accept-source-agreements",
    ]
    if version:
        args.extend(["--version", version])
    if force:
        args.append("--force")
    if source:
        args.extend(["--source", source])
    res = _run(args)
    return _maybe_fix_msstore_geo_and_retry(res, args)



def upgrade_package(package_id: str, *, source: str | None = None) -> WingetResult:
    args = [
        "winget",
        "upgrade",
        "--id",
        package_id,
        "--exact",
        "--silent",
        "--disable-interactivity",
        "--scope",
        "machine",
        "--accept-package-agreements",
        "--accept-source-agreements",
    ]
    if source:
        args.extend(["--source", source])
    res = _run(args)
    return _maybe_fix_msstore_geo_and_retry(res, args)


def uninstall_package(package_id: str, *, source: str | None = None) -> WingetResult:
    args = [
        "winget",
        "uninstall",
        "--id",
        package_id,
        "--exact",
        "--silent",
        "--disable-interactivity",
        "--scope",
        "machine",
        "--accept-source-agreements",
    ]
    if source:
        args.extend(["--source", source])
    res = _run(args)
    return _maybe_fix_msstore_geo_and_retry(res, args)


def _find_id_token_and_version(stdout: str, package_id: str) -> tuple[bool, Optional[str]]:
    pid = (package_id or "").strip().lower()
    if not pid:
        return (False, None)

    id_re = re.compile(rf"(?<!\S){re.escape(pid)}(?!\S)", re.IGNORECASE)

    for ln in (stdout or "").splitlines():
        s = (ln or "").strip()
        if not s:
            continue
        lower = s.lower()
        if lower.startswith("name") or lower.startswith("id ") or set(s) <= {"-"}:
            continue

        if not id_re.search(s):
            continue

        toks = s.split()
        idx = None
        for i, t in enumerate(toks):
            if t.lower() == pid:
                idx = i
                break
        if idx is None:
            return (True, None)

        ver = toks[idx + 1] if idx + 1 < len(toks) else None
        return (True, ver)

    return (False, None)


def installed_from_list_output(stdout: str, package_id: str) -> bool:
    found, _ = _find_id_token_and_version(stdout, package_id)
    return found


def parse_version_from_list_output(stdout: str, package_id: str) -> Optional[str]:
    _, ver = _find_id_token_and_version(stdout, package_id)
    return ver
