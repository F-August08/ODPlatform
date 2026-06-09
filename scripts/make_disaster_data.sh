#!/bin/bash
# scripts/make_disaster_data.sh
# 为 D2.5 课程造灾难现场数据
set -e

echo "🎬 准备灾难现场..."

# 1. data/raw/ 假装放了珍贵的标注数据(撞墙③要保护这个)
mkdir -p data/raw/precious_dataset/images
mkdir -p data/raw/precious_dataset/labels
for i in $(seq 1 200); do
    echo "fake image $i bytes" > "data/raw/precious_dataset/images/img_${i}.jpg"
    echo "0 0.5 0.5 0.3 0.4" > "data/raw/precious_dataset/labels/img_${i}.txt"
done
echo "  ✅ data/raw/precious_dataset/ — 400 个文件(模拟珍贵标注)"

# 2. runs/ 里造一个 2GB 的稀疏文件(撞墙④:删除这个会跑文件系统)
mkdir -p runs/exp_2026_05_10
# 稀疏文件:占名义 2GB,实际磁盘占用接近 0 — 跨平台方案
dd if=/dev/zero of=runs/exp_2026_05_10/best.pt bs=1 count=0 seek=2G 2>/dev/null
echo "  ✅ runs/exp_2026_05_10/best.pt — 2 GB(稀疏文件,删除时会跑文件系统)"

# 3. runs/ 里造大量小文件(撞墙④:大量 inode 删除是真的慢)
mkdir -p runs/exp_2026_05_10/tb_logs
for i in $(seq 1 5000); do
    echo "step $i loss 0.${i}" > "runs/exp_2026_05_10/tb_logs/event.${i}"
done
echo "  ✅ runs/exp_2026_05_10/tb_logs/ — 5000 个小文件(大量 inode)"

# 4. apps/platform/logging/ 一些已存在日志(撞墙⑤的舞台)
mkdir -p apps/platform/logging/training/2026-05-10
for i in $(seq 1 50); do
    echo "training run $i log content" > "apps/platform/logging/training/2026-05-10/run-${i}.log"
done
echo "  ✅ apps/platform/logging/ — 50 份训练日志"

echo ""
echo "🎬 灾难现场准备就绪。"
echo "   总文件数:约 5650"
echo "   总名义大小:约 2 GB(磁盘实际占用 < 100 MB,得益于稀疏文件)"
du -sh data/raw runs apps/platform/logging 2>/dev/null