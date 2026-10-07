$ErrorActionPreference = 'Stop'
$projectPath = Split-Path $PSScriptRoot -Parent
$launcherPath = Join-Path $projectPath 'tools\open_admin.ps1'
$windowsPowerShell = Join-Path $env:WINDIR 'System32\WindowsPowerShell\v1.0\powershell.exe'
$testPort = 61994
$statePath = Join-Path $projectPath ('artifacts\admin-tunnel\connection-' + $testPort + '.json')
if (Test-Path -LiteralPath $statePath) { throw 'Reserved test port has a state file; choose another test port.' }

# Same -File invocation used by the shortcut. Close on an unused port cannot
# start SSH, stop an existing tunnel, contact the server or show a GUI dialog.
$ErrorActionPreference = 'Continue'
$result = & $windowsPowerShell -NoProfile -ExecutionPolicy Bypass -File $launcherPath `
    -Action Close -LocalPort $testPort -Diagnostic 2>&1 | Out-String
$code = $LASTEXITCODE
$ErrorActionPreference = 'Stop'
if ($code -ne 0) { throw ('Shortcut -File parameter initialization failed (exit ' + $code + '): ' + $result) }
Write-Output 'Windows PowerShell 5.1 shortcut default-parameter regression: PASS'
