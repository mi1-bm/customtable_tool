@echo off
cd /d %~dp0

rem ===== settings =====
set LIST=table_url.txt
rem source default.json
set SRC=
rem output
set DST=
rem ====================

set PY=python
where python >nul 2>nul || set PY=py
%PY% update_tables.py "%LIST%" "%SRC%" "%DST%"
pause
