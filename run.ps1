[CmdletBinding()]
param([string]$PythonPath = $env:LIGHTFRINGE_PYTHONW)

$ErrorActionPreference = 'Stop'
if ([string]::IsNullOrWhiteSpace($PythonPath)) {
    throw 'Set LIGHTFRINGE_PYTHONW or pass -PythonPath with the new A4 interpreter. See ../recovery/RECOVERY.md.'
}

Push-Location -LiteralPath $PSScriptRoot
try {
    $interpreter = Get-Item -LiteralPath $PythonPath
} finally {
    Pop-Location
}
if ($interpreter -isnot [System.IO.FileInfo] -or $interpreter.Name -notin @('pythonw.exe', 'python.exe')) {
    throw "Expected a path to pythonw.exe or python.exe. Received: $PythonPath"
}

$prefix = $interpreter.DirectoryName
$launch = New-Object System.Diagnostics.ProcessStartInfo
$launch.FileName = $interpreter.FullName
$launch.Arguments = '-E -s -B -m lightfringe'
$launch.WorkingDirectory = $PSScriptRoot
$launch.UseShellExecute = $false
$launch.EnvironmentVariables['PATH'] = @(
    $prefix
    (Join-Path $prefix 'Library\bin')
    (Join-Path $env:SystemRoot 'System32')
    $env:SystemRoot
) -join ';'
foreach ($name in @('QT_PLUGIN_PATH', 'QT_QPA_PLATFORM_PLUGIN_PATH', 'PYTHONTZPATH')) {
    $launch.EnvironmentVariables.Remove($name)
}
$launch.EnvironmentVariables['OPENBLAS_NUM_THREADS'] = '1'
[System.Diagnostics.Process]::Start($launch) | Out-Null
