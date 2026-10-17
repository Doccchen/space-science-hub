# Windows PowerShell 5.1: local OCR of already-rendered opening pages only.
$ErrorActionPreference='Stop'
Add-Type -AssemblyName System.Runtime.WindowsRuntime
[Windows.Media.Ocr.OcrEngine,Windows.Foundation,ContentType=WindowsRuntime] | Out-Null
[Windows.Storage.StorageFile,Windows.Storage,ContentType=WindowsRuntime] | Out-Null
[Windows.Graphics.Imaging.BitmapDecoder,Windows.Foundation,ContentType=WindowsRuntime] | Out-Null
$taskMethod=([System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {
 $_.Name -eq 'AsTask' -and $_.IsGenericMethodDefinition -and $_.GetParameters().Count -eq 1 -and $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1'
})[0]
function Await-Operation($Operation,[Type]$ResultType){
 $operationTask=$taskMethod.MakeGenericMethod($ResultType).Invoke($null,@($Operation))
 $operationTask.Wait()
 $operationTask.Result
}
$engine=[Windows.Media.Ocr.OcrEngine]::TryCreateFromUserProfileLanguages()
$base=Join-Path (Split-Path $PSScriptRoot -Parent) 'artifacts/home-books-20261017'
foreach($folder in Get-ChildItem -LiteralPath $base -Directory -Filter 'book-*'){
 $records=@()
 foreach($page in 2..4){
  $path=Join-Path $folder.FullName "page-$page.jpg"
  $file=Await-Operation ([Windows.Storage.StorageFile]::GetFileFromPathAsync($path)) ([Windows.Storage.StorageFile])
  $stream=Await-Operation ($file.OpenReadAsync()) ([Windows.Storage.Streams.IRandomAccessStreamWithContentType])
  $decoder=Await-Operation ([Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($stream)) ([Windows.Graphics.Imaging.BitmapDecoder])
  $bitmap=Await-Operation ($decoder.GetSoftwareBitmapAsync()) ([Windows.Graphics.Imaging.SoftwareBitmap])
  $result=Await-Operation ($engine.RecognizeAsync($bitmap)) ([Windows.Media.Ocr.OcrResult])
  $records+=@{page=$page;text=$result.Text}
  $bitmap.Dispose();$stream.Dispose()
 }
 $json=ConvertTo-Json -InputObject $records -Depth 3
 [IO.File]::WriteAllText((Join-Path $folder.FullName 'ocr.json'),$json,[Text.UTF8Encoding]::new($false))
 Write-Output $folder.Name
}
