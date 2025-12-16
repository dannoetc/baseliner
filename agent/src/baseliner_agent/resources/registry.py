from __future__ import annotations

from baseliner_agent.engine import ResourceHandler

from .script_powershell import PowerShellScriptHandler
from .winget_package import WingetPackageHandler


def default_handlers() -> dict[str, ResourceHandler]:
    """Default engine handlers supported by the MVP agent."""
    winget = WingetPackageHandler()
    ps = PowerShellScriptHandler()
    return {
        winget.resource_type: winget,
        ps.resource_type: ps,
    }
