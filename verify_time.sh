#!/bin/bash
# === 容器启动时区验证脚本 ===
# 检测系统时间与标准北京时间的偏差，偏差 > 5分钟则强制同步

set -e

echo "============================================="
echo "  容器时区验证 — $(date '+%Y-%m-%d %H:%M:%S')"
echo "============================================="

# 1. 检查时区配置
CURRENT_TZ=$(cat /etc/timezone 2>/dev/null || echo "unknown")
LOCALTIME_LINK=$(readlink -f /etc/localtime 2>/dev/null || echo "unknown")

echo "[时区] 当前配置: $CURRENT_TZ"
echo "[时区] /etc/localtime -> $LOCALTIME_LINK"

if [ "$CURRENT_TZ" != "Asia/Shanghai" ]; then
    echo "[错误] 时区未设置为 Asia/Shanghai，当前: $CURRENT_TZ"
    echo "[修复] 正在强制设置为 Asia/Shanghai..."
    echo "Asia/Shanghai" > /etc/timezone
    ln -sf /usr/share/zoneinfo/Asia/Shanghai /etc/localtime
    echo "[修复] 时区已重置"
fi

# 2. 检查时间偏差
echo ""
echo "[NTP] 正在检查时间偏差..."

# 获取系统当前 unix 时间
SYS_TIME=$(date +%s)

# 通过 HTTP 获取标准北京时间 (使用淘宝/腾讯API)
NET_TIME=$(curl -s --connect-timeout 5 "http://api.m.taobao.com/rest/api3.do?api=mtop.common.getTimestamp" 2>/dev/null | python3 -c "import sys,json; d=json.load(sys.stdin); print(int(d['data']['t'])/1000)" 2>/dev/null || echo "0")
if [ "$NET_TIME" = "0" ]; then
    NET_TIME=$(curl -s --connect-timeout 5 "https://api.qq.com/time" 2>/dev/null | python3 -c "import sys,json; d=json.load(sys.stdin); print(int(d.get('t',0)))" 2>/dev/null || echo "0")
fi
if [ "$NET_TIME" = "0" ]; then
    # 兜底: 用 HTTP Date 头
    NET_TIME=$(curl -sI --connect-timeout 5 "http://www.baidu.com" 2>/dev/null | grep -i "^Date:" | python3 -c "import sys,time; from email.utils import parsedate_to_datetime; line=sys.stdin.read().strip(); d=parsedate_to_datetime(line[6:]); print(int(d.timestamp()))" 2>/dev/null || echo "0")
fi

if [ "$NET_TIME" = "0" ] || [ -z "$NET_TIME" ]; then
    echo "[警告] 无法获取网络标准时间，跳过时间偏差检查"
else
    DIFF=$(python3 -c "print(abs($SYS_TIME - $NET_TIME))")
    DIFF_INT=$(python3 -c "print(int(abs($SYS_TIME - $NET_TIME)))")
    echo "[NTP] 系统时间: $(date -d @$SYS_TIME '+%Y-%m-%d %H:%M:%S' 2>/dev/null || date -r $SYS_TIME '+%Y-%m-%d %H:%M:%S')"
    echo "[NTP] 标准时间: $(date -d @$NET_TIME '+%Y-%m-%d %H:%M:%S' 2>/dev/null || date -r $NET_TIME '+%Y-%m-%d %H:%M:%S')"
    echo "[NTP] 偏差: ${DIFF} 秒"

    if [ "$DIFF_INT" -gt 300 ]; then
        echo "[警告] 时间偏差超过 5 分钟 (${DIFF_INT}秒)，触发强制同步！"
        chronyd -q 'server cn.pool.ntp.org iburst' 2>/dev/null || \
        ntpd -q -g -p cn.pool.ntp.org 2>/dev/null || \
        echo "[错误] NTP 强制同步失败，请检查网络连接"
    else
        echo "[通过] 时间偏差在允许范围内"
    fi
fi

echo ""
echo "============================================="
echo "  时区验证完成 — 启动应用"
echo "============================================="
