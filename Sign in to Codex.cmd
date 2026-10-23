@echo off
pushd "%~dp000database\Tools"
".venv\Scripts\python.exe" -c "from cloud_workflow import connect; connect().wait()"
popd
pause
