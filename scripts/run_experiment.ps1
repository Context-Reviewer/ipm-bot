[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$AdbSerial,

    [Parameter(Mandatory = $true)]
    [string]$RemoteSavePath,

    [Parameter(Mandatory = $true)]
    [string]$AppPackage,

    [Parameter(Mandatory = $true)]
    [string]$AppActivity,

    [Parameter(Mandatory = $true)]
    [string]$ActivateAdBoostTap,

    [Parameter(Mandatory = $true)]
    [string]$ClaimArkRewardTap,

    [string]$PreparedSavePath = "C:\dev\ipm-bot\data\runs\current\playerInfo.dat",
    [double]$TimeoutSeconds = 30,
    [double]$PollIntervalSeconds = 2,
    [string]$ActionOverride = "",
    [double]$SaveRepullIntervalSeconds = 1.0,
    [switch]$ManualObservationMode,
    [double]$ManualObservationWindowSeconds = 20.0,
    [double]$ManualObservationProbeIntervalSeconds = 1.0,
    [double]$ArkAdWaitSeconds = 20.0,
    [double]$ArkSkipCloseWaitSeconds = 1.0,
    [double]$ArkReturnWaitSeconds = 3.0,
    [int]$ArkEscAttempts = 1,
    [double]$ArkEscIntervalSeconds = 1.0,
    [int]$ArkPostWatchProbeCount = 0,
    [double]$ArkPostWatchProbeIntervalSeconds = 2.0,
    [int]$ArkPostWatchUiDumpMaxTextLength = 240,
    [string]$PythonExecutable = "python",
    [string]$AdbPath = "adb"
)

$arguments = @(
    "-m", "ipm_bot.experiment",
    "--save-source", "adb-pull",
    "--actuator", "adb",
    "--adb-path", $AdbPath,
    "--adb-serial", $AdbSerial,
    "--prepared-save-path", $PreparedSavePath,
    "--timeout-seconds", $TimeoutSeconds.ToString(),
    "--poll-interval-seconds", $PollIntervalSeconds.ToString(),
    "--save-repull-interval-seconds", $SaveRepullIntervalSeconds.ToString(),
    "--manual-observation-window-seconds", $ManualObservationWindowSeconds.ToString(),
    "--manual-observation-probe-interval-seconds", $ManualObservationProbeIntervalSeconds.ToString(),
    "--app-package", $AppPackage,
    "--app-activity", $AppActivity,
    "--activate-ad-boost-tap", $ActivateAdBoostTap,
    "--claim-ark-reward-tap", $ClaimArkRewardTap,
    "--ark-ad-wait-seconds", $ArkAdWaitSeconds.ToString(),
    "--ark-skip-close-wait-seconds", $ArkSkipCloseWaitSeconds.ToString(),
    "--ark-return-wait-seconds", $ArkReturnWaitSeconds.ToString(),
    "--ark-esc-attempts", $ArkEscAttempts.ToString(),
    "--ark-esc-interval-seconds", $ArkEscIntervalSeconds.ToString(),
    "--ark-post-watch-probe-count", $ArkPostWatchProbeCount.ToString(),
    "--ark-post-watch-probe-interval-seconds", $ArkPostWatchProbeIntervalSeconds.ToString(),
    "--ark-post-watch-ui-dump-max-text-length", $ArkPostWatchUiDumpMaxTextLength.ToString(),
    $RemoteSavePath
)

if ($ActionOverride -ne "") {
    $arguments += @("--action-override", $ActionOverride)
}
if ($ManualObservationMode) {
    $arguments += "--manual-observation-mode"
}

& $PythonExecutable @arguments
exit $LASTEXITCODE
