#!/bin/bash

echo "正在启动微信公众号文章爬取工具..."

# 检查Docker是否安装
if ! command -v docker &> /dev/null; then
    echo "错误: Docker未安装，请先安装Docker"
    exit 1
fi

# 检查Docker Compose是否安装
if ! command -v docker-compose &> /dev/null; then
    echo "错误: Docker Compose未安装，请先安装Docker Compose"
    exit 1
fi

# 创建文章目录并设置权限
mkdir -p 文章
chmod 755 文章
echo "文章目录已创建: $(pwd)/文章"

# 配置Docker使用华为镜像源
echo "配置Docker使用华为镜像源..."
sudo mkdir -p /etc/docker
sudo tee /etc/docker/daemon.json <<-'EOF'
{
  "registry-mirrors": [
    "https://mirrors.huaweicloud.com"
  ]
}
EOF
sudo systemctl daemon-reload
sudo systemctl restart docker

# 构建并启动容器
echo "正在构建Docker镜像..."
docker-compose build

echo "正在启动服务..."
docker-compose up -d

echo "服务启动完成！"
echo "请访问: http://localhost:10015"
echo ""
echo "查看日志: docker-compose logs -f"
echo "停止服务: docker-compose down"