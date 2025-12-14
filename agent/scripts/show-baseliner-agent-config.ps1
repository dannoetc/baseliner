param(
    [string]$RepoRoot = "C:\Users\Administrator\Documents\GitHub\baseliner",
    [string]$ConfigPath = "C:\ProgramData\Baseliner\agent.toml"
)

$ErrorActionPreference = "Stop"

$agentDir = Join-Path $RepoRoot "agent"
$venvPython = Join-Path $agentDir ".venv\Scripts\python.exe"

if (-not (Test-Path $venvPython)) {
    throw "Python venv not found at: $venvPython"
}

& $venvPython -m baseliner_agent --config $ConfigPath config show
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
