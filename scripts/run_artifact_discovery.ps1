param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("census", "snapshot", "diff", "il2cpp-workspace", "il2cpp-input-report", "il2cpp-output-catalog", "il2cpp-name-hint-report", "il2cpp-assembly-priority-report", "il2cpp-manual-findings-report")]
    [string]$Command,

    [string]$PackageName = "com.TironiumTech.IdlePlanetMiner",
    [string]$AdbPath = "adb",
    [string]$AdbSerial,
    [string]$OutputRoot = "",
    [int]$HashMaxBytes = 8388608,
    [int]$CopyMaxBytes = 33554432,
    [int]$TextPreviewMaxBytes = 65536,
    [int]$TextDiffMaxBytes = 131072,
    [switch]$PullApk,
    [string]$BeforeSnapshotDir = "",
    [string]$AfterSnapshotDir = "",
    [string]$SnapshotDir = "",
    [string]$WorkspaceDir = "",
    [string]$InputReportDir = "",
    [string]$OutputDir = "",
    [string]$CatalogDir = "",
    [string]$NameHintReportDir = "",
    [string[]]$Term = @(),
    [string[]]$FindingPath = @(),
    [string[]]$FindingNote = @(),
    [string[]]$FindingSymbol = @(),
    [string[]]$FindingKind = @(),
    [string]$Analyst = "",
    [switch]$CaseSensitive,
    [string]$ToolName = "",
    [string]$ToolVersion = "",
    [string]$Notes = ""
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$pythonPath = Join-Path $repoRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $pythonPath)) {
    throw "Python interpreter not found: $pythonPath"
}

if ([string]::IsNullOrWhiteSpace($OutputRoot)) {
    $OutputRoot = Join-Path $repoRoot "data\artifacts"
}

$arguments = @("-m", "ipm_bot.artifacts", $Command)
if ($Command -eq "diff") {
    if ([string]::IsNullOrWhiteSpace($BeforeSnapshotDir)) {
        throw "-BeforeSnapshotDir is required for diff."
    }
    if ([string]::IsNullOrWhiteSpace($AfterSnapshotDir)) {
        throw "-AfterSnapshotDir is required for diff."
    }
    $arguments += @($BeforeSnapshotDir, $AfterSnapshotDir)
    $arguments += @("--output-root", $OutputRoot)
    $arguments += @("--text-diff-max-bytes", $TextDiffMaxBytes)
} elseif ($Command -eq "il2cpp-workspace") {
    if ([string]::IsNullOrWhiteSpace($SnapshotDir)) {
        throw "-SnapshotDir is required for il2cpp-workspace."
    }
    $arguments += @("--snapshot", $SnapshotDir)
    $arguments += @("--output-root", $OutputRoot)
} elseif ($Command -eq "il2cpp-input-report") {
    if ([string]::IsNullOrWhiteSpace($WorkspaceDir)) {
        throw "-WorkspaceDir is required for il2cpp-input-report."
    }
    $arguments += @("--workspace", $WorkspaceDir)
    $arguments += @("--output-root", $OutputRoot)
    if (-not [string]::IsNullOrWhiteSpace($Notes)) {
        $arguments += @("--notes", $Notes)
    }
} elseif ($Command -eq "il2cpp-output-catalog") {
    if ([string]::IsNullOrWhiteSpace($OutputDir)) {
        throw "-OutputDir is required for il2cpp-output-catalog."
    }
    if ([string]::IsNullOrWhiteSpace($InputReportDir) -and [string]::IsNullOrWhiteSpace($WorkspaceDir)) {
        throw "Either -InputReportDir or -WorkspaceDir is required for il2cpp-output-catalog."
    }
    if (-not [string]::IsNullOrWhiteSpace($InputReportDir) -and -not [string]::IsNullOrWhiteSpace($WorkspaceDir)) {
        throw "Specify only one of -InputReportDir or -WorkspaceDir for il2cpp-output-catalog."
    }
    $arguments += @("--output-dir", $OutputDir)
    if (-not [string]::IsNullOrWhiteSpace($InputReportDir)) {
        $arguments += @("--input-report", $InputReportDir)
    } else {
        $arguments += @("--workspace", $WorkspaceDir)
    }
    $arguments += @("--output-root", $OutputRoot)
    if (-not [string]::IsNullOrWhiteSpace($ToolName)) {
        $arguments += @("--tool-name", $ToolName)
    }
    if (-not [string]::IsNullOrWhiteSpace($ToolVersion)) {
        $arguments += @("--tool-version", $ToolVersion)
    }
    if (-not [string]::IsNullOrWhiteSpace($Notes)) {
        $arguments += @("--notes", $Notes)
    }
} elseif ($Command -eq "il2cpp-name-hint-report") {
    if ([string]::IsNullOrWhiteSpace($CatalogDir)) {
        throw "-CatalogDir is required for il2cpp-name-hint-report."
    }
    if ($Term.Count -eq 0) {
        throw "At least one -Term is required for il2cpp-name-hint-report."
    }
    $arguments += @("--catalog", $CatalogDir)
    foreach ($termValue in $Term) {
        if (-not [string]::IsNullOrWhiteSpace($termValue)) {
            $arguments += @("--term", $termValue)
        }
    }
    if ($CaseSensitive.IsPresent) {
        $arguments += "--case-sensitive"
    }
    $arguments += @("--output-root", $OutputRoot)
    if (-not [string]::IsNullOrWhiteSpace($Notes)) {
        $arguments += @("--notes", $Notes)
    }
} elseif ($Command -eq "il2cpp-assembly-priority-report") {
    if ([string]::IsNullOrWhiteSpace($CatalogDir)) {
        throw "-CatalogDir is required for il2cpp-assembly-priority-report."
    }
    $arguments += @("--catalog", $CatalogDir)
    $arguments += @("--output-root", $OutputRoot)
    if (-not [string]::IsNullOrWhiteSpace($Notes)) {
        $arguments += @("--notes", $Notes)
    }
} elseif ($Command -eq "il2cpp-manual-findings-report") {
    if ([string]::IsNullOrWhiteSpace($CatalogDir) -and [string]::IsNullOrWhiteSpace($NameHintReportDir)) {
        throw "Either -CatalogDir or -NameHintReportDir is required for il2cpp-manual-findings-report."
    }
    if (-not [string]::IsNullOrWhiteSpace($CatalogDir) -and -not [string]::IsNullOrWhiteSpace($NameHintReportDir)) {
        throw "Specify only one of -CatalogDir or -NameHintReportDir for il2cpp-manual-findings-report."
    }
    if ($FindingPath.Count -eq 0 -or $FindingNote.Count -eq 0) {
        throw "At least one -FindingPath and one matching -FindingNote are required for il2cpp-manual-findings-report."
    }
    if ($FindingPath.Count -ne $FindingNote.Count) {
        throw "-FindingPath and -FindingNote must have the same number of entries."
    }
    if ($FindingSymbol.Count -gt 0 -and $FindingSymbol.Count -ne $FindingPath.Count) {
        throw "-FindingSymbol must be omitted or have the same number of entries as -FindingPath."
    }
    if ($FindingKind.Count -gt 0 -and $FindingKind.Count -ne $FindingPath.Count) {
        throw "-FindingKind must be omitted or have the same number of entries as -FindingPath."
    }
    if (-not [string]::IsNullOrWhiteSpace($CatalogDir)) {
        $arguments += @("--catalog", $CatalogDir)
    } else {
        $arguments += @("--name-hint-report", $NameHintReportDir)
    }
    foreach ($findingPathValue in $FindingPath) {
        $arguments += @("--finding-path", $findingPathValue)
    }
    foreach ($findingNoteValue in $FindingNote) {
        $arguments += @("--finding-note", $findingNoteValue)
    }
    foreach ($findingSymbolValue in $FindingSymbol) {
        $arguments += @("--finding-symbol", $findingSymbolValue)
    }
    foreach ($findingKindValue in $FindingKind) {
        $arguments += @("--finding-kind", $findingKindValue)
    }
    if (-not [string]::IsNullOrWhiteSpace($Analyst)) {
        $arguments += @("--analyst", $Analyst)
    }
    if (-not [string]::IsNullOrWhiteSpace($Notes)) {
        $arguments += @("--notes", $Notes)
    }
    $arguments += @("--output-root", $OutputRoot)
} else {
    $arguments += @("--package-name", $PackageName)
    $arguments += @("--output-root", $OutputRoot)
    $arguments += @("--adb-path", $AdbPath)
    if (-not [string]::IsNullOrWhiteSpace($AdbSerial)) {
        $arguments += @("--adb-serial", $AdbSerial)
    }
    $arguments += @("--hash-max-bytes", $HashMaxBytes)
    $arguments += @("--copy-max-bytes", $CopyMaxBytes)
    $arguments += @("--text-preview-max-bytes", $TextPreviewMaxBytes)
    if ($PullApk.IsPresent) {
        $arguments += "--pull-apk"
    }
}

& $pythonPath @arguments
exit $LASTEXITCODE
