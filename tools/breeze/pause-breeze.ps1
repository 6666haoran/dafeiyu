$exe = "F:\program_all\dsh\dafeiyu\breeze-tts\bin\breeze-tts-2-v0.1.7-windows-x64-vulkan\breeze-server.exe"
$procs = @(Get-Process breeze-server -ErrorAction SilentlyContinue | Where-Object { $_.Path -eq $exe })
if (-not $procs.Count) { Write-Host "Breeze 已经在停着，不用再关。"; exit 0 }
$procs | Stop-Process -Force
Start-Sleep -Seconds 1
Write-Host "Breeze 已暂停，显存释放了。看完图双击「看完图-恢复Breeze」。"