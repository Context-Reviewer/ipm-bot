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
    "--app-package", $AppPackage,
    "--app-activity", $AppActivity,
    "--activate-ad-boost-tap", $ActivateAdBoostTap,
    "--claim-ark-reward-tap", $ClaimArkRewardTap,
    $RemoteSavePath
)

& $PythonExecutable @arguments
exit $LASTEXITCODE
