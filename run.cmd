@echo off
setlocal DisableDelayedExpansion
set "LF_PY=%LIGHTFRINGE_PYTHONW%"
if "%~1"=="" goto resolve
if /i not "%~1"=="-PythonPath" goto usage
if not "%~3"=="" goto usage
set "LF_PY=%~2"

:resolve
if not defined LF_PY goto usage
pushd "%~dp0" || exit /b 1
for %%I in ("%LF_PY%") do (
    set "LF_PY=%%~fI"
    set "LF_PREFIX=%%~dpI"
    set "LF_EXE=%%~nxI"
)
if /i not "%LF_EXE%"=="pythonw.exe" if /i not "%LF_EXE%"=="python.exe" goto invalid
if not exist "%LF_PY%" goto invalid
if exist "%LF_PY%\." goto invalid

set "PATH=%LF_PREFIX%;%LF_PREFIX%Library\bin;%SystemRoot%\System32;%SystemRoot%"
set "QT_PLUGIN_PATH="
set "QT_QPA_PLATFORM_PLUGIN_PATH="
set "PYTHONTZPATH="
set "OPENBLAS_NUM_THREADS=1"
start "" "%LF_PY%" -E -s -B -m lightfringe
set "LF_EXIT=%ERRORLEVEL%"
popd
exit /b %LF_EXIT%

:invalid
echo Expected a file path to pythonw.exe or python.exe. 1>&2
popd
exit /b 1

:usage
echo Set LIGHTFRINGE_PYTHONW or pass -PythonPath with the new A4 interpreter. See ../recovery/RECOVERY.md. 1>&2
exit /b 1
