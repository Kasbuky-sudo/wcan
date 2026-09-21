#!/bin/bash
# © SONGJUNSONG · Jilin Business and Technology College · School of Finance and Economics
#
# 从 GitHub 拉取最新代码并重启服务（云服务器部署用）
#
# 用法:
#   bash update.sh              # 拉取当前分支最新代码并重启
#   bash update.sh main         # 指定分支
#
# 建议配合定时任务做自动更新，见 DEPLOY.md「自动更新」一节。

set -euo pipefail
cd "$(dirname "$(readlink -f "$0")")"

BRANCH="${1:-main}"

# ---- 兼容 docker compose v2 插件与旧版 docker-compose ----
if docker compose version >/dev/null 2>&1; then
    DC="docker compose"
elif command -v docker-compose >/dev/null 2>&1; then
    DC="docker-compose"
else
    echo "错误: 未找到 docker compose 或 docker-compose" >&2
    exit 1
fi

echo "============================================"
echo "  编舟文心 更新程序"
echo "  分支: ${BRANCH}"
echo "============================================"

if [ ! -d .git ]; then
    echo "错误: 当前目录不是 git 仓库。首次部署请先用 git clone 拉取代码。" >&2
    echo "      见 DEPLOY.md「首次部署」。" >&2
    exit 1
fi

echo ""
echo "[1/5] 检查工作区是否干净..."
if ! git diff --quiet || ! git diff --cached --quiet; then
    echo "  工作区有未提交的改动，已中止，以免覆盖你的修改：" >&2
    git status --short >&2
    echo "" >&2
    echo "  这些文件通常是运行时生成的，可以忽略掉再更新：" >&2
    echo "    git checkout -- <文件>" >&2
    exit 1
fi
echo "  OK"

echo ""
echo "[2/5] 拉取 GitHub 最新代码..."
git fetch --prune origin
LOCAL_SHA=$(git rev-parse HEAD)
REMOTE_SHA=$(git rev-parse "origin/${BRANCH}")
if [ "$LOCAL_SHA" = "$REMOTE_SHA" ]; then
    echo "  已是最新版本（$(git rev-parse --short HEAD)），无需更新。"
    echo ""
    echo "  如仍想重启服务: ${DC} restart"
    exit 0
fi
echo "  $(git rev-parse --short HEAD) -> $(git rev-parse --short "origin/${BRANCH}")"

# 依赖是否变化，决定要不要重建镜像
OLD_REQ=$(git rev-parse "HEAD:requirements.txt" 2>/dev/null || echo none)
NEW_REQ=$(git rev-parse "origin/${BRANCH}:requirements.txt" 2>/dev/null || echo none)

# 只允许快进合并，避免在服务器上产生合并冲突
git merge --ff-only "origin/${BRANCH}"

echo ""
echo "[3/5] 补齐运行所需文件..."
[ -f .env ] || { cp .env.example .env; echo "  已生成 .env（内容为空，请填写 WCAN_SECRET 与 WCAN_ADMIN_PWD 后重新执行本脚本）"; echo "  生成密钥: openssl rand -hex 32"; exit 0; }
[ -f notify_config.json ] || { cp notify_config.example.json notify_config.json; echo "  已补齐 notify_config.json"; }
[ -f webdav_config.json ] || { cp webdav_config.example.json webdav_config.json; echo "  已补齐 webdav_config.json"; }
[ -f config.yaml ]       || { echo "  错误: config.yaml 缺失" >&2; exit 1; }
mkdir -p 文章 data
echo "  OK"

echo ""
echo "[4/5] 应用新版本..."
if [ "$OLD_REQ" != "$NEW_REQ" ]; then
    echo "  requirements.txt 有变化，重建镜像（较慢）..."
    ${DC} up -d --build
else
    echo "  依赖未变化，直接重启容器（代码是挂载进容器的，无需重建）..."
    ${DC} up -d
fi

echo ""
echo "[5/5] 当前状态"
${DC} ps
echo ""
echo "更新完成。查看日志: ${DC} logs -f --tail=100"
echo "数据库迁移会在容器启动时由 entrypoint.sh 自动执行。"
