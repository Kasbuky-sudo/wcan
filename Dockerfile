# ===== 镜像源配置 =====
# 支持通过 --build-arg BASE_IMAGE=xxx 自定义基础镜像
# 默认使用 docker.m.daocloud.io（稳定），可替换为其他源：
#   docker.1ms.run / dockerpull.com / dockerhub.icu / hub.rat.dev
# 或提前拉取: docker pull python:3.11-slim && docker tag python:3.11-slim local/python:3.11-slim
ARG BASE_IMAGE=docker.m.daocloud.io/library/python:3.11-slim

# ===== Stage 1: builder（安装依赖，不进入最终镜像） =====
FROM ${BASE_IMAGE} AS builder

# APT 加速（阿里云 Debian 源，x86 + arm64 通用）
RUN sed -i 's|deb.debian.org|mirrors.aliyun.com|g' /etc/apt/sources.list.d/debian.sources 2>/dev/null || \
    sed -i 's|deb.debian.org|mirrors.aliyun.com|g' /etc/apt/sources.list

# 安装编译依赖（lxml 等可能需要 gcc）
RUN apt-get update && \
    apt-get install -y --no-install-recommends gcc g++ libxml2-dev libxslt1-dev && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /build

COPY pip.conf /etc/pip.conf
COPY requirements.txt .

# pip 安装到 /install 目录（阿里云首选，清华/华为备用）
RUN pip install --no-cache-dir --prefix=/install \
    -i https://mirrors.aliyun.com/pypi/simple/ -r requirements.txt || \
    pip install --no-cache-dir --prefix=/install \
    -i https://pypi.tuna.tsinghua.edu.cn/simple/ -r requirements.txt || \
    pip install --no-cache-dir --prefix=/install \
    -i https://mirrors.huaweicloud.com/pypi/simple/ -r requirements.txt || \
    pip install --no-cache-dir --prefix=/install -r requirements.txt

# ===== Stage 2: runtime（最终镜像，体积更小） =====
FROM ${BASE_IMAGE}

# APT 加速
RUN sed -i 's|deb.debian.org|mirrors.aliyun.com|g' /etc/apt/sources.list.d/debian.sources 2>/dev/null || \
    sed -i 's|deb.debian.org|mirrors.aliyun.com|g' /etc/apt/sources.list

# 时区配置 + 运行时依赖（libxml2/libxslt 供 lxml 使用）
ENV TZ=Asia/Shanghai
RUN apt-get update && \
    apt-get install -y --no-install-recommends tzdata libxml2 libxslt1.1 && \
    ln -sf /usr/share/zoneinfo/Asia/Shanghai /etc/localtime && \
    echo "Asia/Shanghai" > /etc/timezone && \
    rm -rf /var/lib/apt/lists/*

# 从 builder 复制已安装的 Python 依赖
COPY --from=builder /install /usr/local

WORKDIR /app

# 字体文件
COPY 仿宋_GB2312.ttf /usr/share/fonts/
COPY simhei.ttf /usr/share/fonts/

# 应用代码
COPY . .

RUN mkdir -p /app/文章 && \
    chmod 755 /app/文章 && \
    chmod +x /app/run.py && \
    chmod +x /app/entrypoint.sh && \
    chmod -R 755 /app

EXPOSE 10015

# 健康检查：每 30 秒探测 /api/health，连续 3 次失败标记为 unhealthy
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD python -c "import urllib.request,sys; r=urllib.request.urlopen('http://localhost:${PORT:-10015}/api/health', timeout=8); sys.exit(0 if r.status==200 else 1)" || exit 1

# 启动命令（bash 前缀绕开 Windows 文件无执行权限问题）
CMD ["bash", "/app/entrypoint.sh"]
