@echo off
setlocal
cd /d "%~dp0"
set "LF_A4_PY=F:\DevProjects\_Envs\LightFringe\A4-R1\Scripts\pythonw.exe"
if not exist "%LF_A4_PY%" (
  echo LightFringe A4 runtime is missing. See docs\LF-P0-A4-FORMAL-IMPORT.md.
  pause
  exit /b 1
)
set "OPENBLAS_NUM_THREADS=1"
start "" "%LF_A4_PY%" -E -s -B -m lightfringe
endlocal
