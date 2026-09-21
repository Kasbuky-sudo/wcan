#!/bin/bash
# © SONGJUNSONG · Jilin Business and Technology College · School of Finance and Economics
#
# 提前拉取 Python 基础镜像（多源备选，解决 429 限流问题）
# 用法: bash pull-image.sh
#
# 拉取成功后，Dockerfile 会自动使用本地缓存，不再请求远程源。

set -e

IMAGE_TAG="python:3.11-slim"

# 镜像源列表（按稳定性排序）
MIRRORS=(
    "docker.m.daocloud.io"
    "docker.1ms.run"
    "dockerpull.com"
    "dockerhub.icu"
    "hub.rat.dev"
    "docker.xuanyuan.me"
)

echo "============================================"
echo "  Python 基础镜像拉取工具"
echo "  目标: ${IMAGE_TAG}"
echo "============================================"
echo ""

# 检查本地是否已有镜像
if docker image inspect "${IMAGE_TAG}" >/dev/null 2>&1; then
    echo "[OK] 本地已存在 ${IMAGE_TAG}，无需拉取"
    exit 0
fi

# 逐个尝试镜像源
for MIRROR in "${MIRRORS[@]}"; do
    FULL_IMAGE="${MIRROR}/library/${IMAGE_TAG}"
    echo "[尝试] 从 ${MIRROR} 拉取..."
    if docker pull "${FULL_IMAGE}" 2>/dev/null; then
        echo "[成功] 从 ${MIRROR} 拉取成功"
        # 打标签为标准名称，Dockerfile 可直接用 python:3.11-slim
        docker tag "${FULL_IMAGE}" "${IMAGE_TAG}"
        echo "[完成] 已标记为 ${IMAGE_TAG}"
        echo ""
        echo "现在可以正常执行 docker-compose build"
        exit 0
    else
        echo "[失败] ${MIRROR} 不可用"
    fi
done

# 所有镜像源都失败，尝试官方源
echo ""
echo "[尝试] 从 Docker Hub 官方源拉取..."
if docker pull "${IMAGE_TAG}" 2>/dev/null; then
    echo "[成功] 从官方源拉取成功"
    exit 0
fi

echo ""
echo "[错误] 所有镜像源均不可用"
echo ""
echo "手动解决方案:"
echo "  1. 检查网络连接"
echo "  2. 手动拉取: docker pull python:3.11-slim"
echo "  3. 或使用代理: HTTPS_PROXY=http://your-proxy:port bash pull-image.sh"
echo "  4. 或在 docker-compose.yml 中修改 BASE_IMAGE 为可用源"
exit 1
