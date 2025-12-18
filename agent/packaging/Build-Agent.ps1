[CmdletBinding()]
param(
    # Use a specific Python interpreter (defaults to `py -3.12` if available)
    [string]$Python = "",

    # If set, also produces a ready-to-ship zip bundle in agent/out
    [switch]$Bundle,

    # Clean build/dist/out before building
    [switch]$Clean
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

function Resolve-Python {
    param([string]$Py)

    if ($Py) {
        return (Get-Command $Py -ErrorAction Stop).Path
    }

    $py = Get-Command py -ErrorAction SilentlyContinue
    if ($py) {
        # Prefer Python 3.12 for our agent
        return "py -3.12"
    }

    $python = Get-Command python -ErrorAction SilentlyContinue
    if (-not $python) {
        throw "Python not found. Install Python 3.12+ or pass -Python <path>."
    }
    return $python.Path
}

function Invoke-Python {
    param(
        [Parameter(Mandatory)][string]$Py,
        [Parameter(Mandatory)][string[]]$Args
    )

    if ($Py -like "py *") {
        # When Resolve-Python returns "py -3.12"
        $parts = $Py.Split(" ", 2)
        $launcher = $parts[0]
        $ver = $parts[1]
        & $launcher $ver @Args
        return $LASTEXITCODE
    }

    & $Py @Args
    return $LASTEXITCODE
}

$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$agentRoot = Split-Path -Parent $here

Push-Location $agentRoot
try {
    if ($Clean) {
        foreach ($p in @("build", "dist", "out")) {
            if (Test-Path -LiteralPath $p) { Remove-Item -Recurse -Force -LiteralPath $p }
        }
    }

    $py = Resolve-Python -Py $Python
    Write-Host "[INFO] Using Python: $py"

    # Local build venv (kept in repo; ignore via .gitignore)
    $venvDir = Join-Path $agentRoot ".venv-build"
    $venvPy = Join-Path $venvDir "Scripts\python.exe"

    if (-not (Test-Path -LiteralPath $venvPy)) {
        Write-Host "[INFO] Creating build venv: $venvDir"
        $code = Invoke-Python -Py $py -Args @("-m", "venv", $venvDir)
        if ($code -ne 0) { throw "venv creation failed (exit $code)" }
    }

    Write-Host "[INFO] Installing build deps (pyinstaller + agent)"
    & $venvPy -m pip install --upgrade pip | Out-Null
    & $venvPy -m pip install --upgrade pyinstaller | Out-Null
    & $venvPy -m pip install -e . | Out-Null

    Write-Host "[INFO] Building with PyInstaller"
    & $venvPy -m PyInstaller --noconfirm --clean packaging/baseliner-agent.spec
    if ($LASTEXITCODE -ne 0) { throw "PyInstaller build failed (exit $LASTEXITCODE)" }

    $outExe = Join-Path $agentRoot "dist\baseliner-agent\baseliner-agent.exe"
    if (-not (Test-Path -LiteralPath $outExe)) {
        throw "Build succeeded but expected exe missing: $outExe"
    }

    Write-Host "[OK] Built: $outExe"

    if ($Bundle) {
        $outDir = Join-Path $agentRoot "out"
        New-Item -ItemType Directory -Force -Path $outDir | Out-Null

        $stage = Join-Path $outDir "bundle"
        if (Test-Path -LiteralPath $stage) { Remove-Item -Recurse -Force -LiteralPath $stage }
        New-Item -ItemType Directory -Force -Path $stage | Out-Null

        Copy-Item -Recurse -Force -LiteralPath (Join-Path $agentRoot "dist\baseliner-agent") -Destination (Join-Path $stage "baseliner-agent")
        Copy-Item -Force -LiteralPath (Join-Path $agentRoot "packaging\Install-BaselinerAgent.ps1") -Destination (Join-Path $stage "Install-BaselinerAgent.ps1")
        Copy-Item -Force -LiteralPath (Join-Path $agentRoot "packaging\Uninstall-BaselinerAgent.ps1") -Destination (Join-Path $stage "Uninstall-BaselinerAgent.ps1")
        Copy-Item -Force -LiteralPath (Join-Path $agentRoot "packaging\README.md") -Destination (Join-Path $stage "README.md")

        $zipPath = Join-Path $outDir "baseliner-agent-bundle.zip"
        if (Test-Path -LiteralPath $zipPath) { Remove-Item -Force -LiteralPath $zipPath }
        Compress-Archive -Path (Join-Path $stage "*") -DestinationPath $zipPath

        Write-Host "[OK] Bundle: $zipPath"
    }
}
finally {
    Pop-Location 
}
