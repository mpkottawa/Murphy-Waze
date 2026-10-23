@echo off
set "review_python=%~dp000database\Tools\.worker\Scripts\python.exe"
if not exist "%review_python%" set "review_python=python"
"%review_python%" "%~dp000database\Tools\setup_local_review.py"
pause
