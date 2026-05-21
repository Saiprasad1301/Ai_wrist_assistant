@echo off
REM Set provider keys as environment variables before running this service.
REM Example:
REM   set GEMINI_API_KEY=your_key_here
REM   set POLLINATIONS_API_KEY=your_key_here
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0start-gemini-intent.ps1"
