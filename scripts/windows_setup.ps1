[CmdletBinding()]
param(
    [ValidateSet("fast", "standard")]
    [string]$Tier = "fast",

    [switch]$Update,
    [switch]$PreviewOnly,

    [ValidateSet("auto", "with-usage", "without-usage")]
    [string]$Usage = "auto",

    [string]$CodexHome = "",
    [string]$HomePath = ""
)

$ErrorActionPreference = "Stop"
$KitRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$Setup = Join-Path $KitRoot "scripts\setup.py"

function Resolve-Python311 {
    $Candidates = @(
        @{ Name = "py"; Prefix = @("-3") },
        @{ Name = "python"; Prefix = @() },
        @{ Name = "python3"; Prefix = @() }
    )
    foreach ($Candidate in $Candidates) {
        $Command = Get-Command $Candidate.Name -ErrorAction SilentlyContinue
        if ($null -eq $Command) {
            continue
        }
        $CandidatePrefix = @($Candidate.Prefix)
        try {
            & $Command.Source @CandidatePrefix -c "import sys; raise SystemExit(sys.version_info < (3, 11))" 2>$null
        }
        catch {
            continue
        }
        if ($LASTEXITCODE -eq 0) {
            return @{
                Exe = $Command.Source
                Prefix = @($Candidate.Prefix)
            }
        }
    }
    throw "Python 3.11 or newer is required. Install Python, then rerun this command."
}

$Python = Resolve-Python311
$PythonPrefix = @($Python.Prefix)
$SetupArgs = @($Setup, "--usage", $Usage)
if ($PSBoundParameters.ContainsKey("Tier") -or -not $Update) {
    $SetupArgs += @("--tier", $Tier)
}
if ($CodexHome) {
    $SetupArgs += @("--codex-home", $CodexHome)
}
if ($HomePath) {
    $SetupArgs += @("--home", $HomePath)
}
if ($Update) {
    $SetupArgs += "--update"
}
if ($PreviewOnly) {
    $SetupArgs += "--preview-only"
}

$env:PYTHONDONTWRITEBYTECODE = "1"
& $Python.Exe @PythonPrefix @SetupArgs
if ($LASTEXITCODE -ne 0) {
    throw "Setup stopped safely. Review the reported conflict, requirement, or recovery path."
}
