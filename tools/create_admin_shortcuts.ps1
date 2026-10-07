$ErrorActionPreference = 'Stop'
$projectPath = Split-Path $PSScriptRoot -Parent
$launcher = Join-Path $PSScriptRoot 'open_admin.ps1'
$powershellPath = Join-Path $env:WINDIR 'System32\WindowsPowerShell\v1.0\powershell.exe'
$shortcutShell = New-Object -ComObject WScript.Shell
foreach ($entry in @(
    @{Name='打开管理后台.lnk'; Action='Open'; Description='建立或复用 SSH 转发，打开星知航私有后台'},
    @{Name='关闭后台连接.lnk'; Action='Close'; Description='仅关闭此入口建立的本机 SSH 转发'}
)) {
    $shortcutPath = Join-Path $projectPath $entry.Name
    $shortcut = $shortcutShell.CreateShortcut($shortcutPath)
    $shortcut.TargetPath = $powershellPath
    $shortcut.Arguments = '-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "' + $launcher + '" -Action ' + $entry.Action
    $shortcut.WorkingDirectory = $projectPath
    $shortcut.WindowStyle = 7
    $shortcut.Description = $entry.Description
    $shortcut.IconLocation = $powershellPath + ',0'
    $shortcut.Save()
    $saved = $shortcutShell.CreateShortcut($shortcutPath)
    if ($saved.TargetPath -ne $powershellPath -or $saved.Arguments -ne $shortcut.Arguments) {
        throw '快捷方式读回校验失败。'
    }
    Write-Output $shortcutPath
}
