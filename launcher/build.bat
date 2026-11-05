@echo off
rem Builds "Signal Pipeline.exe" (the launcher) into the project root with the
rem C# compiler that ships with Windows (.NET Framework 4).
cd /d "%~dp0"
set "CSC=%WINDIR%\Microsoft.NET\Framework64\v4.0.30319\csc.exe"
if not exist "%CSC%" set "CSC=%WINDIR%\Microsoft.NET\Framework\v4.0.30319\csc.exe"
"%CSC%" /nologo /target:winexe /win32icon:..\src\signal_pipeline\ui\assets\icon.ico /out:"..\Signal Pipeline.exe" launcher.cs
if errorlevel 1 (echo Build failed & exit /b 1)
echo Built: "%~dp0..\Signal Pipeline.exe"
