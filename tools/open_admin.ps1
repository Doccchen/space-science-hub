[CmdletBinding()]
param(
    [ValidateSet('Open', 'Close')][string]$Action = 'Open',
    [string]$ServerAddress = '8.137.164.100',
    [string]$Username = 'root',
    [ValidateRange(1024, 65535)][int]$LocalPort = 18080,
    [ValidateRange(1, 65535)][int]$RemotePort = 8090,
    [string]$KeyPath = (Join-Path (Split-Path (Split-Path $PSScriptRoot -Parent) -Parent) 'GPT.pem')
)

# Local launcher only: no credentials copied, server commands or configuration changes.
$ErrorActionPreference = 'Stop'
$projectPath = Split-Path $PSScriptRoot -Parent
$stateDirectory = Join-Path $projectPath 'artifacts\admin-tunnel'
$statePath = Join-Path $stateDirectory ('connection-' + $LocalPort + '.json')
$stderrPath = Join-Path $stateDirectory ('ssh-' + $LocalPort + '.stderr.log')
$stdoutPath = Join-Path $stateDirectory ('ssh-' + $LocalPort + '.stdout.log')
$adminUrl = 'http://127.0.0.1:' + $LocalPort
$forwarding = '127.0.0.1:' + $LocalPort + ':127.0.0.1:' + $RemotePort
$sshProcess = $null
$mutex = $null
$locked = $false

function Show-Notice([string]$Text) {
    Add-Type -AssemblyName System.Windows.Forms
    [void][System.Windows.Forms.MessageBox]::Show($Text, '星知航 · 管理后台')
}

function Test-AdminPage {
    try {
        # GET only; no login, cookies, model calls or secrets.
        $response = Invoke-WebRequest -Uri ($adminUrl + '/') -UseBasicParsing -TimeoutSec 2
        return ($response.StatusCode -eq 200 -and $response.Content.Contains('id="login-form"') -and
            $response.Content.Contains('id="nav-resources"') -and $response.Content.Contains('id="nav-ai"'))
    }
    catch { return $false }
}

function Get-ManagedProcess {
    if (-not (Test-Path -LiteralPath $statePath -PathType Leaf)) { return $null }
    try {
        $record = Get-Content -LiteralPath $statePath -Raw | ConvertFrom-Json
        if ($record.Server -ne $ServerAddress -or $record.Username -ne $Username -or
            $record.Forwarding -ne $forwarding) { return $null }
        $process = Get-Process -Id ([int]$record.ProcessId) -ErrorAction Stop
        if ($process.ProcessName -ne 'ssh' -or
            $process.StartTime.ToUniversalTime().ToString('o') -ne $record.StartTime) { return $null }
        $details = Get-CimInstance Win32_Process -Filter ('ProcessId=' + $process.Id)
        if (-not $details.CommandLine.Contains($forwarding) -or
            -not $details.CommandLine.Contains($Username + '@' + $ServerAddress)) { return $null }
        return $process
    }
    catch { return $null }
}

try {
    $mutex = New-Object System.Threading.Mutex($false, ('Local\StarKnowledgeAdmin-' + $LocalPort))
    try { $locked = $mutex.WaitOne(20000) }
    catch [System.Threading.AbandonedMutexException] { $locked = $true }
    if (-not $locked) { throw '后台入口正在建立连接，请稍后再打开。' }

    $managed = Get-ManagedProcess
    if ($Action -eq 'Close') {
        if ($managed) {
            Stop-Process -Id $managed.Id -Force
            Show-Notice '本入口建立的 SSH 转发已关闭。服务器网站和后台服务继续运行。'
        }
        else {
            Show-Notice '本入口没有运行中的连接。若是手动开启的 SSH 窗口，请关闭原窗口。'
        }
        exit
    }

    if (Test-AdminPage) {
        # Reuse an existing tunnel, including one opened manually; never terminate it.
        Start-Process -FilePath $adminUrl
        exit
    }
    if ($managed) {
        Stop-Process -Id $managed.Id -Force
        Start-Sleep -Milliseconds 300
    }
    if (Get-NetTCPConnection -LocalPort $LocalPort -State Listen -ErrorAction SilentlyContinue) {
        throw ('本机端口 ' + $LocalPort + ' 被其他连接占用，且未能读取新版管理后台。请先检查原 SSH 窗口。')
    }
    if (-not (Test-Path -LiteralPath $KeyPath -PathType Leaf)) {
        throw ('未找到 SSH 密钥文件：' + $KeyPath)
    }
    $sshExecutable = (Get-Command ssh.exe -ErrorAction Stop).Source
    [void](New-Item -ItemType Directory -Path $stateDirectory -Force)
    # BatchMode prevents invisible password prompts. Host-key trust is never bypassed.
    $arguments = @('-N', '-T', '-L', $forwarding,
        '-o', 'BatchMode=yes', '-o', 'StrictHostKeyChecking=yes', '-o', 'ConnectTimeout=10',
        '-o', 'ExitOnForwardFailure=yes', '-o', 'ServerAliveInterval=30', '-o', 'ServerAliveCountMax=3',
        '-i', ('"' + $KeyPath + '"'), ($Username + '@' + $ServerAddress))
    $sshProcess = Start-Process -FilePath $sshExecutable -ArgumentList $arguments -WindowStyle Hidden -PassThru `
        -RedirectStandardError $stderrPath -RedirectStandardOutput $stdoutPath
    $record = @{ProcessId=$sshProcess.Id; StartTime=$sshProcess.StartTime.ToUniversalTime().ToString('o');
        Server=$ServerAddress; Username=$Username; Forwarding=$forwarding}
    $record | ConvertTo-Json | Set-Content -LiteralPath $statePath -Encoding UTF8

    $deadline = (Get-Date).AddSeconds(20)
    do {
        if ($sshProcess.HasExited) { break }
        if (Test-AdminPage) {
            Start-Process -FilePath $adminUrl
            exit
        }
        Start-Sleep -Milliseconds 500
    } while ((Get-Date) -lt $deadline)
    if (-not $sshProcess.HasExited) { Stop-Process -Id $sshProcess.Id -Force }
    $diagnostic = if (Test-Path -LiteralPath $stderrPath) { (Get-Content -LiteralPath $stderrPath -Tail 5) -join "`n" } else { '' }
    throw ("未能打开后台。请检查网络、服务器状态或 SSH 密钥。首次主机认证或加密私钥需要先使用原 SSH 命令连接。`n`n" + $diagnostic)
}
catch {
    if ($sshProcess -and -not $sshProcess.HasExited) { Stop-Process -Id $sshProcess.Id -Force -ErrorAction SilentlyContinue }
    Show-Notice $_.Exception.Message
    exit 1
}
finally {
    if ($locked -and $mutex) { $mutex.ReleaseMutex() }
    if ($mutex) { $mutex.Dispose() }
}
