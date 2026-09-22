# 部署与运行

> **当前状态（2026-09）**：本项目只以 **Windows 单机程序**分发（单文件 exe，双击即用，无需 Python 环境）。下面关于 Docker / 服务器部署的章节仅作备查，已不再维护，后续跨平台计划以实际需要为准。

按使用场景从简到繁排列，**单机 Windows 直接看第一节**。

---

# 一、Windows 单机运行（推荐）

不需要 Docker、不需要服务器，装好 Python 双击即可。适合放在一台 Windows 机器上自己用，或者放在社团的电脑上让部员通过局域网访问。

## 1. 前提

安装 **Python 3.9 或更高版本**：<https://www.python.org/downloads/windows/>

安装时**务必勾选 `Add Python to PATH`**，否则启动器找不到它。

## 2. 启动

双击项目根目录下的 **`start.bat`**。

首次运行会自动完成这些事（约 1–3 分钟，取决于网速）：

1. 检查 Python
2. 在项目下创建虚拟环境 `.venv`
3. 用清华镜像安装依赖到虚拟环境（不污染系统 Python）
4. 补齐 `notify_config.json`、`webdav_config.json`、`data/`
5. 启动服务并打开访问地址

看到这样的输出就成功了：

```
[4/4] 启动服务...

   本机访问   : http://127.0.0.1:10015
   局域网访问 : http://192.168.x.x:10015
```

用浏览器打开 `http://127.0.0.1:10015`，然后去「公众号同步」页扫码登录微信。

## 3. 停止与重启

- **停止**：直接关掉那个黑色命令行窗口。
- **重启**：关掉窗口再双击一次 `start.bat`。
- 在网页「关于」页点「重启应用」时，进程会退出，**`start.bat` 的窗口会自动把它重新拉起来**，等 5 秒即可。

## 4. 让部员通过局域网访问

`start.bat` 已经把地址打印出来了（形如 `http://192.168.1.23:10015`），把这个地址发给部员即可。

需要注意两点：

1. **首次启动时 Windows 会弹出防火墙提示，要选「允许访问」**，否则其他机器连不上。如果当时点了取消，去
   `控制面板 → Windows Defender 防火墙 → 允许应用通过防火墙` 里把 Python 勾上。
2. 部员必须和这台机器在**同一个局域网**内（同一个路由器 / 同一个校园网段）。

⚠️ 这种方式**没有登录保护**，局域网里任何人拿到地址都能使用全部功能。仅在可信网络（社团活动室、家庭网）里这样用。要放到公网请走第三节。

## 5. 应用自身的登录与权限说明

`config.yaml` 里的 `server.auth_web` **不是**网页登录开关——它用来切换微信驱动的实现（见 `werss/driver/base.py`）。

全项目只有 `/api/update/do` 和 `/api/restart` 两个接口校验管理员密码，其余接口都不需要登录。管理员密码通过环境变量 `WCAN_ADMIN_PWD` 设置（见 `.env.example`），不设置时这些敏感操作会直接被拒绝（安全默认值）。

## 6. 数据都在哪

| 路径 | 内容 |
| --- | --- |
| `文章/` | 抓取生成的 Word 文档，按日期分目录 |
| `data/` | SQLite 数据库 `articles.db`、微信授权 `wx.lic`、日志 |
| `config.yaml` | 应用配置（版本号由启动流程自动同步） |
| `notify_config.json` | 通知渠道配置 |
| `webdav_config.json` | WebDAV 备份配置 |
| `.venv/` | 虚拟环境，删掉后下次启动会重建 |

**备份只需要拷 `文章/`、`data/`、`config.yaml` 和两个 json 文件。**

## 7. 常见问题

**提示没有检测到 Python**
没装，或者装的时候没勾 `Add Python to PATH`。重装一遍并勾上，或手动把 Python 目录加进 PATH。

**依赖安装失败**
多数是网络问题。启动器已经优先用清华镜像，失败后会自动回退官方源。仍然失败的话，挂个代理再试：

```bat
set HTTP_PROXY=http://127.0.0.1:7890
set HTTPS_PROXY=http://127.0.0.1:7890
start.bat
```

**提示虚拟环境不可用，正在重建**
正常现象。虚拟环境里存的是绝对路径，项目被移动或复制到别的目录后就会失效，启动器会自动重建。

**端口 10015 被占用**
改 `config.yaml` 不方便（端口走环境变量），在启动器里临时指定即可：把 `start.bat` 里最后那句 `"%VPY%" run.py` 改成 `set PORT=10016` + `"%VPY%" run.py`，或者先关掉占用端口的程序。

**微信授权会过期**
需要在网页上重新扫码。建议至少配一个通知渠道（Webhook / ServerChan / 邮件），否则过期后定时同步会静默停摆。

**页面显示异常 / 样式错乱**
浏览器缓存。按 `Ctrl+F5` 强制刷新（静态资源带版本号，正常不会出现）。

---

# 二、Docker 运行（NAS / Linux）

项目仍保留完整的 Docker 支持，适合部署在 NAS（如飞牛 fnOS）或 Linux 机器上。

```bash
# 首次
cp .env.example .env          # 填写 WCAN_SECRET 与 WCAN_ADMIN_PWD
cp notify_config.example.json notify_config.json
cp webdav_config.example.json webdav_config.json
docker compose up -d --build

# 查看日志 / 停止
docker compose logs -f
docker compose down
```

要点：

- 代码是 **bind mount** 进容器的（`./app`、`./werss`、`./jobs`、`./templates`、`./static`、`./run.py` 等），改代码只需替换文件 + `docker compose restart`，不必重建镜像；只有 `requirements.txt` 变化时才需要 `--build`。
- `docker-compose.yml` 里端口默认绑定 `127.0.0.1:10015`。**在 NAS/本机上想从局域网直接访问，把它换成注释里的 `"10015:10015"`。**
- `notify_config.json` 和 `webdav_config.json` **必须先真实存在**，否则 Docker 会把它们创建成同名目录，导致保存配置失败。
- `cap_add: SYS_TIME` 只在容器启动时校准时钟。若 `docker compose up` 因此报错，删掉那两行。
- `entrypoint.sh` 每次启动都会 pip 装一遍依赖，所以首次启动会慢一两分钟，属正常；它同时会自动执行数据库迁移。

---

# 三、公网云服务器部署（可选）

把应用放到公网服务器上，让部员随时随地访问。**这一节的前提是你已经接受下面三条风险控制。**

## 上公网前必须做的三件事

1. **加登录保护。** 应用自身没有登录鉴权（见第一节第 5 点），必须在反向代理层加 HTTP Basic Auth。
2. **设置密钥。** 在 `.env` 里设置 `WCAN_SECRET` 和 `WCAN_ADMIN_PWD`。其中 `WCAN_SECRET` 用来派生 WebDAV/邮箱密码的加密密钥，**设定后不要再改**，否则已保存的密码解不开。
3. **传递真实客户端 IP。** 应用按客户端 IP 封锁 10 个国家/地区，读取 `CF-Connecting-IP` / `X-Real-IP` / `X-Forwarded-For`。反向代理不传这些头的话，拿到的是代理内网地址，**封锁会静默失效**。

## 步骤

```bash
git clone https://github.com/<账号>/<仓库名>.git /opt/wcan
cd /opt/wcan
cp .env.example .env && vi .env      # 填 WCAN_SECRET（openssl rand -hex 32）与 WCAN_ADMIN_PWD
cp notify_config.example.json notify_config.json
cp webdav_config.example.json webdav_config.json
chmod 600 .env
docker compose up -d --build
```

反向代理用仓库里的 `deploy/nginx.conf`（同时含 Caddy 版本）：

```bash
sudo apt install nginx apache2-utils
sudo cp deploy/nginx.conf /etc/nginx/conf.d/wcan.conf
sudo htpasswd -c /etc/nginx/.htpasswd wcan      # 共享账号，部员共用
sudo vi /etc/nginx/conf.d/wcan.conf              # 改 server_name 为你的域名
sudo nginx -t && sudo systemctl reload nginx
sudo apt install certbot python3-certbot-nginx
sudo certbot --nginx -d wcan.你的域名
```

配置里四处不能删：`auth_basic`（登录保护）、`X-Real-IP` 与 `X-Forwarded-For`（真实 IP）、`client_max_body_size 100m`（上传 Word 替换）、`proxy_read_timeout 600s`（批量同步是长任务）。

防火墙/安全组只放行 22 / 80 / 443，**不要放行 10015**。

## 更新

```bash
cd /opt/wcan && bash update.sh
```

`update.sh` 会校验工作区、只做快进合并、补齐缺失配置文件、按需重建镜像并重启。

自动更新可以配 systemd timer：

```bash
sudo tee /etc/systemd/system/wcan-update.service >/dev/null <<'EOF'
[Unit]
Description=编舟文心 自动更新
After=docker.service network-online.target

[Service]
Type=oneshot
WorkingDirectory=/opt/wcan
ExecStart=/bin/bash /opt/wcan/update.sh
EOF

sudo tee /etc/systemd/system/wcan-update.timer >/dev/null <<'EOF'
[Unit]
Description=定时检查编舟文心更新

[Timer]
OnBootSec=5min
OnUnitActiveSec=10min
Persistent=true

[Install]
WantedBy=timers.target
EOF

sudo systemctl daemon-reload && sudo systemctl enable --now wcan-update.timer
```

> 没做「网页上一键从 GitHub 更新」是刻意的：那等于在公网开一个"拉取远程代码并执行"的入口。放在服务器上跑 git pull 同样是自动的，但不对外暴露任何执行能力。

### 服务器在国内连不上 GitHub

大陆服务器拉 GitHub 经常超时，三种办法：

```bash
# 1. 走代理
git config --global http.proxy http://127.0.0.1:7890

# 2. SSH 走 443 端口（很多云主机只封了 22）
cat >> ~/.ssh/config <<'EOF'
Host github.com
  HostName ssh.github.com
  Port 443
  User git
EOF

# 3. 双远程 + Gitee 镜像（最稳）
git remote set-url --add --push origin git@github.com:<账号>/<仓库>.git
git remote set-url --add --push origin git@gitee.com:<账号>/<仓库>.git
```

## 选服务器

先决定备案：大陆机器绑域名必须 ICP 备案（个人可办，约 1–3 周）；香港/海外免备案。

| | 大陆节点 | 香港 / 海外 |
| --- | --- | --- |
| 绑域名 | 需 ICP 备案 | 免备案 |
| 部员访问 | 最快 | 30–80ms，够用 |
| 微信扫码登录 | 友好 | 有风控风险 |

- **首选**：腾讯云 / 阿里云轻量应用服务器 2核2G 国内节点（学生认证后有学生机，新用户首年常有优惠）。
- **不想备案**：腾讯云 / 阿里云轻量香港节点。
- **学生可白嫖**：GitHub Student Developer Pack 里有 DigitalOcean $200 额度；Oracle Cloud Always Free 给 ARM 4核24G 但注册常被拒。
- **不建议**：RackNerd / CloudCone 那种 $10–25/年的小机，线路不稳。

配置别低于 2核2G——首次装依赖加全量抓取会比较吃力。注意新用户优惠基本只限首年，续费会涨。

## GitHub 仓库注意事项

- `.gitignore` 已排除 `.env`、`notify_config.json`、`webdav_config.json`、`data/`、`文章/`、`update/`、`.venv/`、日志与缓存。
- `config.yaml` 要提交（本身不含密钥，密码走 `.env`）。
- `simhei.ttf` / `仿宋_GB2312.ttf` **不入库**：商业字体版权，仓库转公开时已移除，`.gitignore` 也已排除。生成 Word 时程序只把字体名写进文档、不读取字体文件，所以仓库和 exe 都不需要它们；文档最终长什么样，取决于打开文档那台机器装了什么字体。Dockerfile 的字体 `COPY` 与 docker-compose 的字体挂载都已注释，确实需要容器内有中文字体时再自行放开。
- 提交前 `git status --short` 自查一遍，确认没有把 `.env` 和两个 json 配置文件带上去。
