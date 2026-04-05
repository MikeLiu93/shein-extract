<#
.SYNOPSIS
    创建 Windows 计划任务：每天 21:00 自动运行 Shein 爬虫。
    支持从睡眠中唤醒电脑。

.DESCRIPTION
    任务名称: SheinListing-AutoPipeline
    触发时间: 每天 21:00
    功能:     唤醒电脑 → 运行 run_scheduled.cmd → 扫描新订单 → 爬取数据

.NOTES
    以管理员身份运行: 右键 → "以管理员身份运行 PowerShell" → 执行本脚本
    或在 PowerShell 中: powershell -ExecutionPolicy Bypass -File setup_schedule.ps1
#>

$TaskName    = "SheinListing-AutoPipeline"
$Description = "每天21:00自动扫描希音订单并爬取数据（支持从睡眠唤醒）"
$ScriptPath  = "C:\Users\ak\Desktop\Claude\shein extract\run_scheduled.cmd"
$WorkDir     = "C:\Users\ak\Desktop\Claude\shein extract"

# 删除旧任务（如果存在）
$existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($existing) {
    Write-Host "删除旧任务: $TaskName" -ForegroundColor Yellow
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
}

# 触发器：每天 21:00
$trigger = New-ScheduledTaskTrigger -Daily -At "21:00"

# 操作：运行 run_scheduled.cmd
$action = New-ScheduledTaskAction `
    -Execute "cmd.exe" `
    -Argument "/c `"$ScriptPath`"" `
    -WorkingDirectory $WorkDir

# 设置
$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -WakeToRun `
    -StartWhenAvailable `
    -ExecutionTimeLimit (New-TimeSpan -Hours 2) `
    -RestartCount 1 `
    -RestartInterval (New-TimeSpan -Minutes 5)

# 以当前用户身份运行（无需密码，锁屏可执行）
$principal = New-ScheduledTaskPrincipal `
    -UserId $env:USERNAME `
    -LogonType S4U `
    -RunLevel Highest

# 注册任务
Register-ScheduledTask `
    -TaskName $TaskName `
    -Description $Description `
    -Trigger $trigger `
    -Action $action `
    -Settings $settings `
    -Principal $principal

Write-Host ""
Write-Host "计划任务已创建成功！" -ForegroundColor Green
Write-Host "  任务名: $TaskName" -ForegroundColor Cyan
Write-Host "  时间:   每天 21:00" -ForegroundColor Cyan
Write-Host "  唤醒:   是（从睡眠中唤醒电脑）" -ForegroundColor Cyan
Write-Host "  脚本:   $ScriptPath" -ForegroundColor Cyan
Write-Host ""
Write-Host "可在 Task Scheduler (taskschd.msc) 中查看和修改。" -ForegroundColor Gray
