# scripts/make_disaster_data.ps1
# 为 D2.5 课程造灾难现场数据

Write-Host "🎬 准备灾难现场..."

# 1. data/raw/
New-Item -ItemType Directory -Force -Path "data/raw/precious_dataset/images" | Out-Null
New-Item -ItemType Directory -Force -Path "data/raw/precious_dataset/labels" | Out-Null
1..200 | ForEach-Object {
    "fake image $_" | Set-Content "data/raw/precious_dataset/images/img_$_.jpg"
    "0 0.5 0.5 0.3 0.4" | Set-Content "data/raw/precious_dataset/labels/img_$_.txt"
}
Write-Host "  ✅ data/raw/precious_dataset/ — 400 个文件"

# 2. 2GB 稀疏文件
New-Item -ItemType Directory -Force -Path "runs/exp_2026_05_10" | Out-Null
fsutil file createnew "runs/exp_2026_05_10/best.pt" 2147483648 | Out-Null
fsutil sparse setflag "runs/exp_2026_05_10/best.pt" | Out-Null
Write-Host "  ✅ runs/exp_2026_05_10/best.pt — 2 GB"

# 3. 5000 小文件
New-Item -ItemType Directory -Force -Path "runs/exp_2026_05_10/tb_logs" | Out-Null
1..5000 | ForEach-Object {
    "step $_ loss" | Set-Content "runs/exp_2026_05_10/tb_logs/event.$_"
}
Write-Host "  ✅ runs/exp_2026_05_10/tb_logs/ — 5000 个文件"

# 4. logging
New-Item -ItemType Directory -Force -Path "apps/platform/logging/training/2026-05-10" | Out-Null
1..50 | ForEach-Object {
    "training run $_" | Set-Content "apps/platform/logging/training/2026-05-10/run-$_.log"
}
Write-Host "  ✅ apps/platform/logging/ — 50 份日志"

Write-Host ""
Write-Host "🎬 灾难现场准备就绪。"