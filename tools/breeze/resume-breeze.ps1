$cmd = "F:\program_all\dsh\dafeiyu\breeze-tts\start-breeze.cmd"
if ((Test-NetConnection 127.0.0.1 -Port 8137 -WarningAction SilentlyContinue).TcpTestSucceeded) {
  Write-Host "Breeze 已经在跑，不用再开。"
  exit 0
}
Start-Process -FilePath $cmd -WindowStyle Minimized
for ($i = 0; $i -lt 45; $i++) {
  Start-Sleep -Seconds 2
  if ((Test-NetConnection 127.0.0.1 -Port 8137 -WarningAction SilentlyContinue).TcpTestSucceeded) {
    Write-Host "Breeze 已恢复，语音可以用了。"
    exit 0
  }
}
Write-Host "Breeze 60 秒没起来：双击桌面的「启动Breeze语音」看看那个黑窗口报什么。"