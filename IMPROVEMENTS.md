# 编舟文心 v4.1.7 改进清单

> 基于全量代码审阅（app.py / crawler.py / ai_agent.py / mcp_server.py / knowledge_base.py / feishu_bot.py / jobs/mps.py / werss/* / templates/* 等 40+ 文件）整理。
> 按 **优先级 P0（严重）→ P1（重要）→ P2（建议）** 分级，每项标注所在文件与行号。

---

## 一、安全性问题（P0 优先处理）

### 1.1 硬编码密码 🔴
- **位置**：[app.py:1405](file:///c:/Users/User/Desktop/WeChat-Article/app.py#L1405)、[app.py:1474](file:///c:/Users/User/Desktop/WeChat-Article/app.py#L1474)
- **问题**：清空历史 / 清空知识库的密码 `<已移除的旧口令>` 直接硬编码在源码中，任何能读到代码的人都能绕过
- **建议**：迁移到 `config.yaml` 的 `admin_password` 字段（bcrypt 哈希存储），或使用环境变量 `WCAN_ADMIN_PWD`

### 1.2 敏感信息明文存储 🔴
- **位置**：[config.yaml:65](file:///c:/Users/User/Desktop/WeChat-Article/config.yaml#L65)
- **问题**：飞书 `app_secret: "<已移除的飞书密钥>"` 明文写入配置文件，若 config.yaml 进入版本控制则泄露
- **建议**：所有 secret 类字段改用环境变量引用 `${FEISHU_APP_SECRET}`，Config 类已支持该语法

### 1.3 WebDAV / 邮箱密码明文落盘 🔴
- **位置**：[app.py:718](file:///c:/Users/User/Desktop/WeChat-Article/app.py#L718) save_webdav_config、[app.py:204](file:///c:/Users/User/Desktop/WeChat-Article/app.py#L204) save_notify_config
- **问题**：`webdav_config.json` 和 `notify_config.json` 中 password / smtp_password 字段明文 JSON
- **建议**：复用 `werss/file.py` 的 `FileCrypto`（HMAC-SHA256）加密敏感字段，读取时解密

### 1.4 所有 API 无鉴权 🔴
- **位置**：app.py 全部 `@app.route`
- **问题**：`/api/restart`、`/api/update/do`、`/api/kb/clear`、`/api/history/clear`、`/api/mps/<id>/fetch` 等敏感接口任何人访问 10015 端口即可调用
- **建议**：引入 Flask 装饰器 `@require_auth`，基于 `werss/models/user.py` 的 User 表 + session token；或至少加 IP 白名单中间件

### 1.5 路径遍历风险 🟠
- **位置**：[app.py:1009](file:///c:/Users/User/Desktop/WeChat-Article/app.py#L1009) `static_files` 路由
- **问题**：`send_from_directory(os.path.dirname(...), filename)` 未限制 filename 范围，可能通过 `../` 读取上级文件
- **建议**：使用 `safe_join` 或限制白名单后缀

### 1.6 Flask secret 默认值 🟠
- **位置**：[config.yaml:12](file:///c:/Users/User/Desktop/WeChat-Article/config.yaml#L12) `secret: "change-me-to-a-random-string"`
- **问题**：虽然当前未使用 session，但若后续启用则默认值会被用于签名，存在伪造风险
- **建议**：启动时校验 secret 是否为默认值，是则拒绝启动或自动生成随机值

### 1.7 SQL LIKE 拼接 🟡
- **位置**：[mcp_server.py](file:///c:/Users/User/Desktop/WeChat-Article/mcp_server.py) search_articles
- **问题**：title + description LIKE 拼接虽用参数化，但需确认 `%` 通配符未转义，可能引发 ReDoS
- **建议**：对用户输入的 `%`、`_` 进行转义

---

## 二、代码质量问题（P1）

### 2.1 app.py 单文件过于庞大 🔴
- **位置**：[app.py](file:///c:/Users/User/Desktop/WeChat-Article/app.py) 2753 行
- **问题**：路由 + 通知 + WebDAV + 邮件 + 历史 + 版本 + 更新 + 一言全部堆在一个文件，难以维护
- **建议**：拆分为 `app/routes/`（按业务域分文件）、`app/services/notify.py`、`app/services/webdav.py`、`app/services/history.py` 等

### 2.2 全局可变状态线程不安全 🟠
- **位置**：[app.py:124](file:///c:/Users/User/Desktop/WeChat-Article/app.py#L124) crawl_status、[app.py:133](file:///c:/Users/User/Desktop/WeChat-Article/app.py#L133) sync_status、replace_status、webdav_upload_status、update_progress、`_yiyan_state`
- **问题**：多线程读写全局字典无锁，并发请求时数据竞争（如同时爬取 + 轮询状态）
- **建议**：引入 `threading.Lock` 或改用 `queue.Queue` + 单线程消费

### 2.3 __version__ 定义位置错误 🟠
- **位置**：[app.py:2337](file:///c:/Users/User/Desktop/WeChat-Article/app.py#L2337)
- **问题**：`__version__ = "4.1.7"` 在文件末尾才定义，但第 340、1851、2121、2373 行等多处提前引用，依赖 Python 模块加载机制才能工作，可读性差
- **建议**：移到文件开头或单独 `version.py`

### 2.4 重复代码 🔴
- **位置**：[app.py:304](file:///c:/Users/User/Desktop/WeChat-Article/app.py#L304) send_email_notification 与 [app.py:1826](file:///c:/Users/User/Desktop/WeChat-Article/app.py#L1826) _send_single_email
- **问题**：两个函数 90% 逻辑重复（MIME 构建、emoji 转义、HTML 模板）
- **建议**：抽取 `_build_email_msg(message, ec) -> MIMEMultipart` 公共函数

### 2.5 异常捕获过于宽泛 🟠
- **位置**：全项目大量 `except Exception:` 和 `except:`
- **示例**：[app.py:194](file:///c:/Users/User/Desktop/WeChat-Article/app.py#L194)、[app.py:869](file:///c:/Users/User/Desktop/WeChat-Article/app.py#L869)、[app.py:1374](file:///c:/Users/User/Desktop/WeChat-Article/app.py#L1374)
- **问题**：掩盖具体错误，调试困难；`except:` 连 KeyboardInterrupt 都吞掉
- **建议**：捕获具体异常类型，至少记录 traceback

### 2.6 使用 print 而非 logging 🟠
- **位置**：全项目
- **问题**：无日志级别、无文件输出、无轮转，Docker 重启后日志丢失
- **建议**：引入 `logging` 模块，配置 RotatingFileHandler + 控制台输出，按模块分 logger

### 2.7 未使用的变量和导入 🟡
- **位置**：
  - [app.py:2126](file:///c:/Users/User/Desktop/WeChat-Article/app.py#L2126) `syncing = False`、`sync_interval_minutes = 60` 从未使用
  - [app.py:2128](file:///c:/Users/User/Desktop/WeChat-Article/app.py#L2128) 注释 `# ==================== 通用配置(定时) ====================` 下无内容
- **建议**：清理死代码

### 2.8 魔法数字散落 🟡
- **示例**：
  - 历史记录上限 2000（app.py:647, 503）
  - 日志上限 500/100/50（app.py:153, 802, 900）
  - 重试间隔 3s（app.py:385）
  - AI Agent max_rounds=5（ai_agent.py）
- **建议**：抽取到 `constants.py` 或 config.yaml

### 2.9 缺少类型注解和 docstring 🟡
- **位置**：全项目大部分函数
- **建议**：关键公共函数添加 type hints 和 docstring，便于 IDE 提示和后续维护

---

## 三、架构问题（P1）

### 3.1 数据库 session 泄漏风险 🔴
- **位置**：[app.py:1159](file:///c:/Users/User/Desktop/WeChat-Article/app.py#L1159) 等多处
- **问题**：`session = DB.get_session()` 后异常未 close，连接池耗尽
- **示例**：
  ```python
  session = DB.get_session()
  mps = session.query(Feed)...all()
  session.close()  # 若 query 抛异常则不会执行
  ```
- **建议**：统一使用 `with DB.get_session() as session:` 上下文管理器

### 3.2 无数据库迁移机制 🟠
- **问题**：表结构变更靠 `Base.metadata.create_all()`，已有表新增字段不会自动添加
- **建议**：引入 Alembic 做版本化迁移

### 3.3 定时任务与 Web 服务同进程 🟠
- **位置**：[app.py:2722](file:///c:/Users/User/Desktop/WeChat-Article/app.py#L2722) start_scheduler
- **问题**：批量爬取任务异常可能拖垮 Web 服务；反之亦然
- **建议**：拆分为独立 worker 进程，通过队列（Celery / RQ）通信

### 3.4 缺少 API 限流 🟠
- **问题**：所有接口无限流，外部可轻易 DDoS
- **建议**：引入 `flask-limiter`，对 `/api/ai/chat`、`/crawl` 等重接口限流

### 3.5 缺少 /health 健康检查端点 🟡
- **问题**：Dockerfile 无 HEALTHCHECK，K8s 等编排工具无法探活
- **建议**：新增 `/api/health` 返回 `{status, version, db, scheduler, feishu}`

### 3.6 缺少 API 版本化 🟡
- **问题**：所有 API 路径为 `/api/xxx`，未来不兼容升级困难
- **建议**：改为 `/api/v1/xxx`

---

## 四、性能问题（P1）

### 4.1 历史记录全量加载 🔴
- **位置**：[app.py:487](file:///c:/Users/User/Desktop/WeChat-Article/app.py#L487) `_load_crawl_history`
- **问题**：一次性 json.load 全部 2000 条记录到内存，每次写入都重新 dump 全量
- **建议**：改用 SQLite Article 表为主，crawl_history.json 仅作缓存；或分页加载

### 4.2 历史记录 HTML 每次全量重生成 🟠
- **位置**：[app.py:524](file:///c:/Users/User/Desktop/WeChat-Article/app.py#L524) `_save_history_html`
- **问题**：2000 条记录每次都重新拼接 HTML 字符串并写文件
- **建议**：增量更新，或改为前端渲染（后端只返回 JSON）

### 4.3 Knowledge Base 搜索线性扫描 🟠
- **位置**：[app.py:2253](file:///c:/Users/User/Desktop/WeChat-Article/app.py#L2253) search_kb
- **问题**：`os.walk` 遍历所有 .txt 文件，文件名匹配用 `keyword.lower() in f.lower()`
- **建议**：复用 `knowledge_base.py` 的 `.kb_index.json` 索引，或用 Whoosh 全文检索

### 4.4 前端轮询过于频繁 🟠
- **位置**：[index.html:3715](file:///c:/Users/User/Desktop/WeChat-Article/templates/index.html#L3715)
- **问题**：
  - 每 30 秒：loadDailyStats + loadHistory + updateWebdavStatus + updateReplaceStatus + updateAuthStatusAll + loadYiyan + loadMps×2（共 8 个请求）
  - 每 3 秒：/api/task-status
- **建议**：合并为单个 `/api/poll` 端点返回聚合数据；或用 WebSocket 推送

### 4.5 图片下载无并发 🟡
- **位置**：crawler.py create_word_document
- **问题**：文章图片串行下载，10 张图可能耗时 10 秒
- **建议**：用 `concurrent.futures.ThreadPoolExecutor` 并发下载

### 4.6 数据库索引缺失 🟡
- **位置**：[werss/models/article.py](file:///c:/Users/User/Desktop/WeChat-Article/werss/models/article.py)
- **问题**：Article 表的 `publish_time`、`mp_id`、`status` 高频查询字段无显式 `index=True`
- **建议**：添加 `index=True` 或在 `__table_args__` 中定义复合索引

### 4.7 AI Agent 串行 tool-calling 🟡
- **位置**：ai_agent.py run_agent
- **问题**：5 轮 tool-calling 每轮都调用 LLM，单次对话可能 30 秒+
- **建议**：工具调用结果缓存；或支持并行工具调用（OpenAI 已支持 parallel_tool_calls）

---

## 五、用户体验问题（P1）

### 5.1 viewport 禁用缩放（无障碍问题）🔴
- **位置**：[index.html:5](file:///c:/Users/User/Desktop/WeChat-Article/templates/index.html#L5) `maximum-scale=1.0, user-scalable=no`
- **问题**：违反 WCAG 1.4.4，视障用户无法放大页面
- **建议**：移除 `maximum-scale=1.0, user-scalable=no`

### 5.2 复制 / 右键被全局禁用 🔴
- **位置**：[index.html:2059-2061](file:///c:/Users/User/Desktop/WeChat-Article/templates/index.html#L2059)
  ```js
  document.addEventListener('copy', function(e) { e.preventDefault(); });
  document.addEventListener('cut', function(e) { e.preventDefault(); });
  document.addEventListener('contextmenu', function(e) { e.preventDefault(); });
  ```
- **问题**：用户无法复制 AI 回复、错误信息、历史标题；开发者无法右键检查元素
- **建议**：移除这三行；如需保护内容，仅对特定元素禁用

### 5.3 历史记录无搜索 / 筛选 / 分页 🟠
- **位置**：[index.html:2065](file:///c:/Users/User/Desktop/WeChat-Article/templates/index.html#L2065) loadHistory
- **问题**：2000 条记录一次渲染，无法按公众号、日期、状态筛选
- **建议**：增加搜索框 + 日期选择器 + 分页（每页 50 条）

### 5.4 AI 对话无停止按钮 🟠
- **位置**：[index.html:2984](file:///c:/Users/User/Desktop/WeChat-Article/templates/index.html#L2984) sendAiChat
- **问题**：发送后无法中断，5 轮 tool-calling 可能等 30 秒
- **建议**：使用 AbortController，发送按钮发送中变为"停止"

### 5.5 错误提示不友好 🟡
- **示例**：多处 `showToast('失败')`、`showToast('保存失败')` 无具体原因
- **建议**：错误信息包含原因 + 建议操作

### 5.6 移动端 TabBar 6 项拥挤 🟡
- **位置**：[index.html:1321](file:///c:/Users/User/Desktop/WeChat-Article/templates/index.html#L1321)
- **问题**：AI / 提取 / 替换 / 历史 / RSS / 设置 共 6 项，小屏设备图标文字拥挤
- **建议**：合并"替换"到"提取"二级页；或将"设置"放入侧滑菜单

### 5.7 无加载骨架屏 🟡
- **问题**：列表加载时仅显示"加载中..."文字，无骨架屏占位
- **建议**：增加 skeleton loader

### 5.8 无网络断开提示 🟡
- **问题**：fetch 失败仅 catch 静默处理，用户无感知
- **建议**：监听 `online` / `offline` 事件，顶部显示离线横幅

### 5.9 二维码过期不自动刷新 🟡
- **位置**：[index.html:1806](file:///c:/Users/User/Desktop/WeChat-Article/templates/index.html#L1806) startAuthPolling
- **问题**：授权过期后需用户手动点击"获取登录二维码"
- **建议**：检测到 expired 状态自动调用 getQrCodeBtn

### 5.10 表单无前端校验 🟡
- **示例**：WebDAV host、邮箱地址、URL 字段仅判断非空
- **建议**：增加格式校验（regex）

---

## 六、错误处理与健壮性（P1）

### 6.1 文件写入无原子性 🔴
- **位置**：[app.py:205](file:///c:/Users/User/Desktop/WeChat-Article/app.py#L205) save_notify_config、save_webdav_config 等
- **问题**：`json.dump` 直接写入目标文件，写入中途异常会导致文件损坏（如断电）
- **建议**：写入临时文件 `xxx.tmp` 后 `os.rename` 原子替换

### 6.2 网络请求超时不统一 🟠
- **位置**：部分 requests 调用未设 timeout
- **示例**：[app.py:213](file:///c:/Users/User/Desktop/WeChat-Article/app.py#L213) send_webhook_notification 设了 10s，但部分内部调用未设
- **建议**：全局封装 `requests.request` 强制 timeout

### 6.3 线程异常静默失败 🟠
- **位置**：[app.py:1054](file:///c:/Users/User/Desktop/WeChat-Article/app.py#L1054) 等多处 `threading.Thread(target=...).start()`
- **问题**：daemon 线程内异常不会传播到主线程，仅打印到 stdout
- **建议**：封装线程包装器，捕获异常后记录日志 + 通知

### 6.4 JSON 解析未捕获异常 🟡
- **位置**：[app.py:175](file:///c:/Users/User/Desktop/WeChat-Article/app.py#L175) 等多处 `json.load(f)`
- **问题**：配置文件损坏时 JSONDecodeError 未捕获
- **建议**：try/except JSONDecodeError，返回默认配置并告警

---

## 七、配置与部署问题（P2）

### 7.1 Docker 镜像未优化 🟠
- **位置**：[Dockerfile](file:///c:/Users/User/Desktop/WeChat-Article/Dockerfile)
- **问题**：单阶段构建，最终镜像包含构建工具等冗余文件
- **建议**：多阶段构建，runtime 阶段仅复制 site-packages 和代码

### 7.2 Dockerfile 无 HEALTHCHECK 🟡
- **建议**：`HEALTHCHECK --interval=30s CMD curl -f http://localhost:10015/api/health || exit 1`

### 7.3 端口硬编码 🟡
- **位置**：[app.py:2752](file:///c:/Users/User/Desktop/WeChat-Article/app.py#L2752) `port=10015`
- **建议**：改为 `int(os.environ.get('PORT', 10015))`

### 7.4 数据目录硬编码 🟡
- **位置**：`/app/文章`、`/app/Knowledge base`、`/app/报错文档` 散落各处
- **问题**：非 Docker 部署时路径不存在；Windows 开发时路径不兼容
- **建议**：统一到 config.yaml 的 `paths` 节，支持相对路径

### 7.5 无数据备份机制 🟡
- **问题**：SQLite 单文件，无定时备份
- **建议**：APScheduler 增加每日备份任务，保留最近 7 份

### 7.6 依赖版本范围过宽 🟡
- **位置**：[requirements.txt](file:///c:/Users/User/Desktop/WeChat-Article/requirements.txt)
- **问题**：全部用 `>=`，可能引入不兼容更新
- **建议**：锁定具体版本或使用 `~=` 兼容更新，配合 `pip-compile` 生成 lock 文件

---

## 八、可维护性问题（P2）

### 8.1 缺少单元测试 🔴
- **问题**：整个项目无 `tests/` 目录，无 pytest 配置
- **建议**：为核心模块（crawler、knowledge_base、ai_agent、jobs/mps）添加单元测试，覆盖率目标 60%+

### 8.2 缺少 Lint 配置 🟡
- **问题**：无 `.pylintrc`、`.flake8`、`pyproject.toml`
- **建议**：引入 ruff（速度快），配置在 CI 中强制检查

### 8.3 缺少 API 文档 🟡
- **问题**：30+ API 接口无文档
- **建议**：引入 OpenAPI/Swagger 自动生成

### 8.4 代码风格不统一 🟡
- **问题**：单引号 / 双引号混用，缩进有时 4 空格有时 2 空格
- **建议**：引入 `black` + `isort` 自动格式化

### 8.5 注释不足 🟡
- **问题**：部分复杂逻辑无注释，如 [app.py:524](file:///c:/Users/User/Desktop/WeChat-Article/app.py#L524) `_save_history_html` 中对 is_dup、is_modified、is_repost 的判断逻辑
- **建议**：复杂业务逻辑添加注释说明

---

## 九、功能扩展建议（P2）

### 9.1 MCP 工具数量过多
- **问题**：22 个工具，LLM 选择困难，token 消耗大
- **建议**：按场景分组（文章 / 知识库 / 系统 / 通知），动态加载相关工具集

### 9.2 AI 提示词硬编码
- **位置**：ai_agent.py system_prompt
- **建议**：抽取到 `prompts/system.txt`，支持热加载

### 9.3 KB 关键词类别固定
- **问题**：6 类（人名/地名/活动/主题/获奖/关键词）不可配置
- **建议**：config.yaml 增加 `kb.keyword_categories` 列表

### 9.4 通知类型固定
- **问题**：3 种（rss_expiry / task_reminder / error_reminder）不可扩展
- **建议**：改为插件式注册

### 9.5 无多用户支持
- **问题**：单用户系统，User 表存在但未用于登录
- **建议**：启用 Flask-Login，支持多用户 + 权限隔离

### 9.6 无国际化
- **问题**：全中文硬编码
- **建议**：引入 Flask-Babel，至少支持中英文

### 9.7 飞书 Bot 无群聊支持
- **位置**：feishu_bot.py
- **建议**：支持群聊 @机器人触发

### 9.8 无暗色模式
- **问题**：只有绿 / 红 / 黑白三套主题
- **建议**：增加 `theme-dark`，跟随系统 `prefers-color-scheme`

---

## 十、改进优先级路线图

### 第一阶段（P0，立即处理）
1. 移除硬编码密码，迁移到 config + bcrypt
2. 飞书 app_secret 等敏感信息改用环境变量
3. WebDAV / 邮箱密码加密存储
4. 为敏感 API 增加鉴权
5. 修复路径遍历风险
6. 移除 viewport 缩放禁用
7. 移除全局 copy/cut/contextmenu 禁用

### 第二阶段（P1，近期处理）
1. app.py 拆分模块化
2. 全局状态加锁或改队列
3. 数据库 session 改上下文管理器
4. 引入 logging 替换 print
5. 历史记录改 SQLite 为主 + 分页
6. 前端轮询合并为聚合端点
7. 文件写入原子化
8. 增加单元测试框架
9. AI 对话增加停止按钮
10. 历史记录增加搜索筛选

### 第三阶段（P2，中期优化）
1. 引入 Alembic 数据库迁移
2. 定时任务拆分独立进程
3. 引入 API 限流
4. Docker 多阶段构建
5. 引入 ruff + black 统一代码风格
6. 路径配置化
7. 增加暗色模式
8. 增加健康检查端点
9. 数据库索引优化
10. 图片并发下载

---

## 统计

| 类别 | P0 | P1 | P2 | 合计 |
|------|----|----|----|------|
| 安全性 | 6 | 1 | 0 | 7 |
| 代码质量 | 0 | 5 | 4 | 9 |
| 架构 | 0 | 4 | 2 | 6 |
| 性能 | 0 | 4 | 3 | 7 |
| 用户体验 | 2 | 3 | 5 | 10 |
| 错误处理 | 0 | 3 | 1 | 4 |
| 配置部署 | 0 | 1 | 5 | 6 |
| 可维护性 | 0 | 0 | 5 | 5 |
| 功能扩展 | 0 | 0 | 8 | 8 |
| **合计** | **8** | **21** | **33** | **62** |

共识别 **62 项** 改进点，建议按路线图分三阶段推进。
