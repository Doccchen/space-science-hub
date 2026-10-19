param([int]$Port = 8878,[string]$ReaderPython = '')
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$readerArgs=@('-m','tools.run_integrated_site','--port',"$Port")
if($ReaderPython){$readerArgs+=@('--reader-python',$ReaderPython)}
& (Join-Path $PSScriptRoot '.venv\Scripts\python.exe') @readerArgs
