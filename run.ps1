$ErrorActionPreference = 'Stop'
$pythonPath = 'F:\DevProjects\_Envs\LightFringe\A4-R1\Scripts\pythonw.exe'
if (-not (Test-Path -LiteralPath $pythonPath)) { throw 'LightFringe A4 runtime is missing. See docs/LF-P0-A4-FORMAL-IMPORT.md.' }
$launch = New-Object System.Diagnostics.ProcessStartInfo
$launch.FileName = $pythonPath
$launch.Arguments = '-E -s -B -m lightfringe'
$launch.WorkingDirectory = $PSScriptRoot
$launch.UseShellExecute = $false
$launch.EnvironmentVariables['OPENBLAS_NUM_THREADS'] = '1'
[System.Diagnostics.Process]::Start($launch) | Out-Null
