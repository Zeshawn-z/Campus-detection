$ErrorActionPreference = "Stop"

# 配置
$LocalDistPath = ".\front_end\dist"
$RemoteHost = "ali" # SSH 别名或 user@ip
$RemoteTargetDir = "/var/www/Campus-detection/front_end/"

# 检查本地构建目录是否存在
if (-not (Test-Path $LocalDistPath)) {
    Write-Error "错误: 找不到构建目录 $LocalDistPath`n请先在 front_end 目录下运行 'npm run build'"
    exit 1
}

Write-Host "0. 清理远程服务器上的 dist 目录..." -ForegroundColor Cyan
try {
    # 删除远程的 dist 目录，scp 会重新创建它
    $RemoteDistDir = "${RemoteTargetDir}dist"
    ssh $RemoteHost "rm -rf $RemoteDistDir"
}
catch {
    Write-Warning "清理命令执行出错 (如果目录不存在可忽略): $_"
}

Write-Host "1. 开始上传 dist 目录到服务器 $RemoteHost..." -ForegroundColor Cyan

# 使用 scp 递归上传
# 注意：这将把本地的 dist 文件夹完整复制到远程目录及下，形成 /var/www/Campus-detection/front_end/dist
try {
    scp -r $LocalDistPath "${RemoteHost}:${RemoteTargetDir}"
}
catch {
    Write-Error "上传失败: $_"
    exit 1
}

if ($LASTEXITCODE -ne 0) {
    Write-Error "SCP 上传命令执行失败"
    exit 1
}

Write-Host "2. 正在重载 Nginx..." -ForegroundColor Cyan

# 远程执行 nginx 重载命令
# 尝试使用 systemctl reload nginx，如果需要 sudo 权限且配置了免密 sudo，这会工作
# 如果是 root 用户登录，直接执行即可
try {
    ssh $RemoteHost "nginx -s reload"
}
catch {
    Write-Error "Nginx 重载失败: $_"
    exit 1
}

if ($LASTEXITCODE -ne 0) {
    Write-Warning "nginx -s reload 执行可能遇到问题，尝试使用 systemctl..."
    ssh $RemoteHost "sudo systemctl reload nginx"
}

Write-Host "部署完成" -ForegroundColor Green
