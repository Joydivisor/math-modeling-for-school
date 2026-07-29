$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot
Push-Location $projectRoot
try {
    python -m src.data.validate_metadata
    python -m unittest discover -s tests -v
    git diff --check
}
finally {
    Pop-Location
}
