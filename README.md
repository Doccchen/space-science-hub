# 知航 · 航天新闻与知识库问答平台

让知识易懂，让依据可见。

> 当前状态（2026-10-07）：新闻、百炼知识库问答、资料下载已上线；用户已确认资料管理正常，并提供 AI 后台两容器 healthy、配置 applied 的输出。此前简洁前端 UI 已由用户确认部署；用户随后确认采用「航天科技杂志 + 沉浸新闻首屏」，新前端已在本地完成并生成升级包，尚未部署服务器。AI 回答仅统一主题配色，内容逻辑不变。本说明区分用户反馈与 Agent 本地验证，不代表新的远程独立验收。

[功能概览](#功能概览) · [架构与依赖](#架构与依赖) · [快速部署](#docker-快速部署) · [配置说明](#配置说明) · [本地开发](#本地开发) · [服务器迁移](#备份与服务器迁移) · [详细文档](#详细文档)

## 功能概览

| 模块     | 功能                                                                                       |
| -------- | ------------------------------------------------------------------------------------------ |
| 航天新闻 | 采集已批准的官方来源；按类别、地区、来源筛选；分页浏览；展示来源与发布时间                 |
| 新闻阅读 | 按来源策略提供政府新闻全文弹窗或原文链接；支持受控新闻图片展示                             |
| AI 问答  | 调用百炼知识库服务；支持独立提问、有限追问、新对话、本次检索资料展示与额度限制             |
| 资料下载 | 搜索、分类、分页和静态封面；PDF 由 OSS 直接下载，当前目录有 28 份资料                      |
| 私有管理 | 独立资料管理与 AI 设置；支持修订恢复、加密 Key、配置应用及受限测试；新闻审核管理入口已退役 |

AI 问答基于独立知识库，不自动携带新闻内容。“本次检索资料”展示实际返回的资料信息，不表示回答的每一句都已经核实。资料页不提供在线 PDF 预览。

新闻范围排除 NASA APOD（Astronomy Picture of the Day）类条目：新条目不入库，旧条目不公开展示但保留历史记录。普通 NASA 新闻继续采集。[排除策略与部署](docs/deployment/APOD排除部署-20261007.md)，本轮代码修改尚待服务器升级。

NASA/ESA 新闻支持独立署名的可选缩略图，图片缺失时仍为纯文字；ESA 全文展示策略不变。自动采集开关默认关闭，未知权利或第三方图片不自动展示。[图片部署与登记](docs/deployment/NASA与ESA新闻配图部署-20261007.md)，尚待服务器升级及真实采集验证。

## 架构与依赖

```text
浏览器
  │ 同域页面与 /api 请求
  ▼
FastAPI 应用容器（单 worker）
  ├─ web/：静态页面、样式与交互
  ├─ 新闻 API、定时采集、全文处理
  ├─ 资料目录 API ─────► OSS（浏览器直接下载 PDF）
  ├─ AI API ─────────► 百炼（已发布服务及关联知识库）
  └─ /data 持久卷
       ├─ news.sqlite3：新闻、阅读、管理等数据
       ├─ ai.sqlite3：AI 会话、请求状态与用量（启用 AI 后）
       ├─ site-management.sqlite3：资料、历史修订、加密 AI 配置和审计
       └─ news-images/：新闻图片

可选私有管理容器 ─────► 同一 /data 持久卷
应用/管理容器 ────────► 独立主密钥文件（只读挂载、单独备份）
```

前后端代码分目录维护，通过 API 交互；部署时共用一个应用容器和域名，无需独立前端构建。SQLite 使用 Python 标准库，无需单独安装数据库服务器。定时采集在应用进程内运行，当前必须使用单 worker、单应用实例。

### 软件依赖

| 用途           | 依赖                                                               |
| -------------- | ------------------------------------------------------------------ |
| 容器部署       | Docker Engine、Docker Compose v2；宿主机无需安装 Python 或 Node.js |
| 本地运行       | Python 3.12、pip、虚拟环境                                         |
| 后端服务       | FastAPI、Uvicorn、Pydantic                                         |
| 新闻采集与解析 | httpx、feedparser、Beautiful Soup                                  |
| 图片处理       | Pillow                                                             |
| 后台密钥加密   | cryptography / Fernet；主密钥不进入数据卷或 Git                    |
| 前端运行       | 支持现代 JavaScript 的浏览器；无需 npm 构建                        |
| 开发检查       | Python unittest；前端状态回归测试另需 Node.js                      |

完整运行依赖及固定版本见 [requirements.txt](requirements.txt)。Docker 构建会自动安装它们；测试工具不属于生产运行依赖。

### 外部服务

- **新闻来源**：服务器需要能够访问配置的官方新闻站点；个别来源可能受地域、网络或上游访问策略限制。
- **百炼知识库**：启用 AI 需要有权限的 API Key、业务空间 ID、已发布的知识问答服务 ID及其关联知识库。当前适配器连接北京业务空间接口；切换区域需要核对并调整实现，不能只替换 ID。
- **OSS 资料存储**：当前资料目录指向阿里云 OSS。复用原存储需要下载对象可访问；使用自己的 Bucket 时，需同步 PDF、调整目录中的对象信息，并配置存储来源。

新闻浏览和资料模块不要求启用 AI。百炼调用与 OSS 服务的费用由对应云账户承担；网站请求额度不是云账单的金额硬上限。

## Docker 快速部署

以下服务器命令使用 **Linux Bash**，在包含 `compose.yaml` 的项目根目录执行。已有部署请先阅读[更新与日常维护](#更新与日常维护)，不要覆盖已有 `.env`。

### 1. 准备服务器与源码

安装 Docker Engine 和 Compose v2，确认可用：

```bash
docker --version
docker compose version
```

将当前项目完整源码上传或检出到服务器，例如 `/opt/space-news`。首次部署不需要上传本地 `.venv`、`data` 或历史发布包。迁移已有网站时，数据单独按迁移章节恢复。

现有 Compose 将应用限制为 1 CPU、640 MB 内存；管理服务另有资源限制。这是容器上限，不是整机容量保证，宿主机还需要为系统、构建和磁盘增长预留空间。

### 2. 创建配置

```bash
cd /opt/space-news
cp .env.example .env
chmod 600 .env
```

仅在 `.env` 不存在时执行复制。编辑 `.env`，默认适合服务器本机测试：

```dotenv
BIND_ADDRESS=127.0.0.1
WEB_PORT=8080
AI_ENABLED=0
```

首次可保持 AI 关闭，先确认新闻和资料页面可用。要开放公网访问，将 `BIND_ADDRESS` 改为 `0.0.0.0`，并开放服务器防火墙和云安全组的对应 TCP 端口。

### 3. 生成独立主密钥、构建并启动

当前 Compose 包含只读主密钥挂载；首次安装必须先生成文件。已有部署不要重新生成密钥，直接使用原文件；恢复加密配置时必须同时恢复原管理库与主密钥。

```bash
docker compose config --quiet
docker compose build app
install -d -m 700 -o 10001 -g 10001 secrets
docker run --rm --user 10001:10001 --mount type=bind,src="$PWD/secrets",dst=/secrets \
  space-news-app python tools/ai_manage.py generate-key --output /secrets/site-management.key
docker compose up -d --no-build app
docker compose ps
curl -fsS http://127.0.0.1:8080/api/health
```

生成工具拒绝覆盖已有文件，不输出密钥。主密钥放在宿主机 `secrets/site-management.key`，供 app/admin 只读挂载；另在私有位置单独备份。它与百炼 API Key 是不同的密钥。

使用默认端口时，服务器本机入口为 `http://127.0.0.1:8080`。健康接口返回 `status: ok` 和新闻数量；首次启动立即采集，之后默认每小时更新，初始数量可能为 0。健康检查通过只说明应用健康接口可用，不代表百炼、OSS 或所有新闻源已验证。

默认仅监听本机，可在自己的电脑建立 SSH 转发后访问（替换尖括号中的值）：

```bash
ssh -L 18080:127.0.0.1:8080 <用户名>@<服务器地址>
```

保持 SSH 连接，浏览器打开 `http://127.0.0.1:18080`。公开部署时访问 `http://<服务器地址>:8080`；正式使用域名时，在应用前配置反向代理与 HTTPS。当前 Compose 没有自动配置域名或证书。

如果基础镜像或包索引无法访问，按服务器实际网络调整 `PYTHON_IMAGE` 和 `PIP_INDEX_URL`。已有部署曾使用 `public.ecr.aws/docker/library/python:3.12-slim` 及阿里云 PyPI 镜像；它们在新服务器上的可达性仍需实测。

### 4. 启用知识库问答（可选）

在服务器私有 `.env` 中设置：

```dotenv
AI_ENABLED=1
DASHSCOPE_API_KEY=<有权限的 API Key>
BAILIAN_WORKSPACE_ID=<北京业务空间 ID>
BAILIAN_AGENT_ID=<已发布的知识问答服务 ID>
```

不要直接复制示例中的业务 ID用于自己的云账户。密钥只保存在服务器，不放入前端代码或 Git。也可使用现有交互配置工具，通过隐藏输入写入 Key：

```bash
python3 tools/configure_ai.py
```

该工具需要宿主机 Python 3，固定修改 `/opt/space-news/.env`；其他部署目录请手动编辑自己的 `.env`。运行前核对工具的默认空间及服务配置。修改后更新应用容器配置：

```bash
docker compose up -d --no-build --no-deps app
curl -fsS http://127.0.0.1:8080/api/ai/status
```

尚未初始化后台时按环境启用；初始化后台后，配置和明确停用均优先于环境，后续设置通过后台的草稿/应用流程调整。首次显式采纳环境运行 `docker compose exec app python tools/ai_manage.py init`。详见 [AI 设置后台部署](docs/deployment/AI设置后台部署-20261006.md)。

状态检查不发送模型问题；实际网页提问会调用百炼。使用 HTTPS 后设置 `AI_COOKIE_SECURE=1`，再更新应用容器。

## 配置说明

完整示例见 [.env.example](.env.example)，容器实际接收的变量见 [compose.yaml](compose.yaml)。

| 变量                                        | 默认值                             | 说明                                         |
| ------------------------------------------- | ---------------------------------- | -------------------------------------------- |
| `BIND_ADDRESS`                              | `127.0.0.1`                        | 宿主机监听地址；公网直连时设为 `0.0.0.0`     |
| `WEB_PORT`                                  | `8080`                             | 宿主机网站端口                               |
| `PYTHON_IMAGE`                              | `python:3.12-slim`                 | 构建基础镜像                                 |
| `PIP_INDEX_URL`                             | `https://pypi.org/simple`          | 构建时依赖下载源                             |
| `COLLECT_ENABLED`                           | `1`                                | 是否启用定时采集；`0` 用于关闭采集的离线运行 |
| `COLLECT_INTERVAL_SECONDS`                  | `3600`                             | 采集间隔秒数；代码将最小间隔限制为 300 秒    |
| `GOVERNMENT_FULLTEXT_AUTO`                  | `1`                                | 政府来源自动全文处理                         |
| `RESOURCE_OSS_ORIGIN`                       | 现有 OSS 地址                      | 资料下载存储来源；对象清单仍需匹配           |
| `RESOURCES_PATH`                            | `/app/content/resources.json`      | 首次迁移源目录；启用管理库后由数据库提供资料 |
| `MANAGEMENT_DB_PATH`                        | `/data/site-management.sqlite3`    | app/admin 共用的管理库                       |
| `AI_MASTER_KEY_FILE`                        | `/run/secrets/site-management.key` | 独立解密主密钥，只读挂载，不能提交 Git       |
| `AI_ENABLED`                                | `0`                                | 是否启用知识库问答                           |
| `DASHSCOPE_API_KEY`                         | 空                                 | 百炼密钥，仅服务器使用                       |
| `BAILIAN_WORKSPACE_ID` / `BAILIAN_AGENT_ID` | 现有服务示例值                     | 业务空间与已发布服务标识                     |
| `AI_CONFIG_VERSION`                         | `1`                                | AI 服务配置版本标识                          |
| `AI_COOKIE_SECURE`                          | `0`                                | HTTPS 部署时设为 `1`                         |
| `AI_TIMEOUT_SECONDS`                        | `60`                               | 上游回答超时秒数                             |
| `AI_CONCURRENCY`                            | `2`                                | AI 并发限制；代码最大允许 4                  |
| `AI_VISITOR_DAILY_LIMIT`                    | `20`                               | 单访客每日问答次数                           |
| `AI_IP_DAILY_LIMIT`                         | `30`                               | 单连接 IP 每日问答次数                       |
| `AI_SITE_DAILY_LIMIT`                       | `100`                              | 全站每日问答次数                             |
| `AI_DAILY_TOKEN_LIMIT`                      | `200000`                           | 网站每日 token 控制阈值                      |
| `AI_TOKEN_RESERVATION`                      | `20000`                            | 每次调用前预留的 token 额度                  |
| `ADMIN_ORIGIN`                              | `http://127.0.0.1:18080`           | 私有管理页面预期访问来源                     |

Compose 固定将新闻库和 AI 库放在 `/data/news.sqlite3`、`/data/ai.sqlite3`，并挂载 `news-data` 命名卷。`.env` 由 Compose 读取并替换配置；本地直接运行 Python 时不会自动加载 `.env`。

反向代理部署需要明确可信代理和访客 IP 传递方式。当前 AI 限额使用应用看到的连接 IP；代理配置不当可能让多个用户共享同一 IP 额度，不应直接信任任意客户端代理头。

## 本地开发

在项目根目录创建 Python 3.12 虚拟环境。

**Windows PowerShell：**

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m uvicorn backend.app:app --host 127.0.0.1 --port 8000 --workers 1
```

**Linux / macOS：**

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m uvicorn backend.app:app --host 127.0.0.1 --port 8000 --workers 1
```

访问 `http://127.0.0.1:8000`。默认新闻库为 `data/news.sqlite3`，AI 默认关闭；采集随应用启动，无需额外运行采集命令。本地使用代码默认的资料目录路径，不要将容器示例中的 `/app/...` 路径直接导入本地环境。

需要环境变量时，在当前终端设置，例如关闭联网采集：

```powershell
# Windows PowerShell
$env:COLLECT_ENABLED = "0"
```

```bash
# Linux / macOS
export COLLECT_ENABLED=0
```

### 测试

```bash
python -m unittest discover -s tests -v
node tests/test_news_state.cjs
```

第一项运行后端固定测试，第二项运行前端新闻状态回归检查；Node.js 仅为第二项所需。固定测试使用离线数据或模拟上游，不代替真实新闻采集、PDF 下载和付费问答验收。最近记录的完整离线 pytest 结果为 109 项通过，详情见验收文档；如选择 pytest，需另行安装该开发工具。

## 更新与日常维护

更新前备份当前源码、`.env` 和持久数据，确认要发布的版本。已有运行容器可能经过前端热更新，磁盘源码未必与其完全一致；这种情况需同时保留运行容器中的 `/app/web`，避免重建时回退页面。

更新完整源码后：

```bash
docker compose config --quiet
docker compose up -d --build app
docker compose ps
docker compose logs --tail=80 app
```

保持原 Compose 项目名和数据卷，重建应用不会删除已有卷。改变项目目录名或 `-p` 项目名可能创建新的空卷，表现为新闻或会话数据“消失”；先检查实际挂载，再判断数据是否丢失。

`docker compose stop app` 可停止应用；`docker compose down` 保留命名卷。**不要使用 `docker compose down -v`，它会删除持久卷。**

### 可选私有管理服务

`admin` 使用 `review` profile，仅绑定服务器本机 8090，与 app 共用 `space-news-app` 镜像和 `/data` 卷。profile 名保留兼容，当前后台只提供资料管理与 AI 设置，不挂载新闻审核接口或启动审核线程。

```bash
docker compose --profile review up -d --no-build admin
docker compose --profile review exec admin python -m tools.admin_user
```

管理员工具通过隐藏输入设置密码；已有账号不要重复运行，重设会撤销旧会话。首次显式初始化资料和 AI 后台：

```bash
docker compose exec app python tools/resources_manage.py migrate --source /app/content/resources.json
docker compose exec app python tools/ai_manage.py init
```

迁移/初始化不会覆盖已有管理修改。SSH 转发与 ADMIN_ORIGIN 保持一致：

```bash
ssh -L 18080:127.0.0.1:8090 <用户名>@<服务器地址>
```

浏览器打开 `http://127.0.0.1:18080`。Windows 本机也可使用 [一键后台入口](docs/deployment/后台一键入口-20261006.md)。详细操作见 [资料管理部署](docs/deployment/资料管理后台部署-20261006.md)和 [AI 设置后台部署](docs/deployment/AI设置后台部署-20261006.md)。

## 备份与服务器迁移

迁移需要 **程序、私有配置、持久数据** 三部分。Docker 镜像包含应用及静态资源，不包含 `.env`、数据卷、OSS PDF 或百炼知识库。

| 内容             | 迁移方式                                                                           |
| ---------------- | ---------------------------------------------------------------------------------- |
| 源码与部署配置   | 上传当前完整版本，在新服务器构建                                                   |
| `.env`           | 通过私有通道传输，保持权限 600，按新入口调整配置                                   |
| `/data` 持久卷   | 停止所有写入后完整备份和恢复，包含新闻、AI、管理三个 SQLite 库、启用标记及新闻图片 |
| 独立主密钥       | 单独通过私有通道备份/恢复，容器只读挂载；不能重新生成代替原密钥                    |
| OSS PDF          | 继续使用原 Bucket 时无需搬动；更换时同步对象并更新资料目录                         |
| 百炼服务与知识库 | 继续使用原服务时无需搬动；更换账户时重新发布服务并更新标识与密钥                   |
| 域名与证书       | 在新服务器重新配置代理、证书、DNS 和防火墙                                         |

### 停机备份与恢复示例

以下为 **Linux Bash 的新服务器迁移模板**，采用短暂停机备份整个数据卷。执行前确认没有独立采集、回填或管理写入进程；每一步成功后再继续。此模板未在本轮实际跨服务器执行。

**旧服务器：** 在原项目目录执行，保持原 Compose 项目名。

```bash
umask 077
mkdir -p migration-backup
docker compose --profile review stop app admin
docker compose run --rm --no-deps -T --user 0 --entrypoint tar app \
  -C /data -czf - . > migration-backup/data.tar.gz
tar -tzf migration-backup/data.tar.gz
cp -p .env migration-backup/server.env
sha256sum migration-backup/data.tar.gz > migration-backup/data.tar.gz.sha256
```

确认备份成功并将备份、校验文件、私有配置和当前完整源码传到新服务器。迁移期间保持旧服务停止，避免切换后遗漏新增数据。若取消迁移，可启动原 app，并按原状态恢复可选 admin。

**新服务器：** 进入上传的项目目录，将私有配置恢复为 `.env`。按新服务器修改监听地址、端口和 HTTPS 设置，但暂不启动应用。将单独保存的原主密钥恢复到 `secrets/site-management.key`，目录 0700、文件 0600，所有者为容器可读的 10001:10001；不得重新生成替代。

```bash
cp migration-backup/server.env .env
chmod 600 .env
sha256sum -c migration-backup/data.tar.gz.sha256
docker compose config --quiet
docker compose build app
```

校验文件中的路径相对于项目根目录。下一步检查目标卷为空；检查失败时停止，不要覆盖现有服务的数据。

```bash
docker compose run --rm --no-deps -T --user 0 --entrypoint python app \
  -c "from pathlib import Path; import sys; sys.exit('Target /data is not empty; stop restore') if any(Path('/data').iterdir()) else None"
```

仅在检查成功后恢复：

```bash
docker compose run --rm --no-deps -T --user 0 --entrypoint tar app \
  -C /data -xzf - < migration-backup/data.tar.gz
docker compose up -d --no-build app
docker compose ps
curl -fsS http://127.0.0.1:8080/api/health
curl -fsS http://127.0.0.1:8080/api/ai/status
```

整卷备份保留源文件所有权；当前镜像应用用户为 UID/GID `10001:10001`。调整过运行用户的部署需要另行核对恢复后的权限。示例健康检查使用默认 8080 端口。

最后核对新闻数量、历史条目和图片、资料下载、AI 启用状态；需要实际问答验证时由运营者确认收费调用。确认新服务正常后再切换流量。原服务器与备份保留到迁移验收完成，管理容器按需单独启用。

在线备份不能只复制正在写入的 SQLite 主文件，WAL 数据可能尚未合并。已有 `tools/backup_review.py` 提供新闻库及其引用图片的校验备份，但不包含 AI 库，不能单独当作完整网站迁移备份。备份中的会话与私有配置应保存到受限位置，并另留一份服务器外副本。

## 常见问题

| 现象                  | 检查方向                                                             |
| --------------------- | -------------------------------------------------------------------- |
| 网站无法从外部打开    | 默认仅绑定 `127.0.0.1`；检查监听地址、端口、SSH 转发、防火墙和安全组 |
| 首次新闻数量为 0      | 等待首轮采集，查看 app 日志及来源网络；上游失败不等于数据库损坏      |
| AI 页面显示未开放     | 已初始化后台时检查已应用配置；未初始化时检查环境 AI_ENABLED               |
| AI 提示服务配置不可用 | Key 权限、北京业务空间 ID、已发布服务 ID和关联知识库是否匹配         |
| PDF 下载失败          | OSS 对象是否存在、可访问，资料目录与存储来源是否一致                 |
| 重建后出现空数据库    | Compose 项目名、实际挂载卷是否改变；不要先删除旧卷                   |
| 镜像构建失败          | 基础镜像及 Python 包索引可达性，固定依赖能否安装                     |
| 管理服务找不到镜像    | 是否构建了 Compose 引用的 `space-news-app` 镜像                      |

## 项目目录

```text
backend/          API、新闻采集、阅读、管理、百炼适配与数据存储
web/              当前网站前端、品牌资源与资料封面
admin_web/        私有管理前端
content/          资料目录与阅读配置
tests/            后端固定测试与前端状态回归检查
tools/            发布、升级、备份、采集验证与预览工具
docs/             方案、部署、验收、设计与研究文档
archive/          已停止使用的早期方案与原型
artifacts/        本地发布包、预览与准备产物，仅目录说明纳入 Git
data/             本地数据库与运行数据，不纳入 Git
Dockerfile        Python 应用镜像定义
compose.yaml      应用与可选管理服务、命名卷、健康检查
.env.example      无密钥配置示例
requirements.txt  固定版本的运行依赖
```

网页入口为 `web/index.html`，应用入口为 `backend/app.py`。

## 详细文档

- [文档总览](docs/README.md)与[工具导航](tools/README.md)
- [项目整理与上线状态记录](docs/acceptance/项目整理与上线状态记录-20261006.md)
- [知航前端品牌、筛选与阅读优化记录](docs/acceptance/知航前端品牌筛选与阅读优化记录-20261006.md)
- [知航前端升级部署](docs/deployment/知航前端品牌筛选与阅读优化部署.md)
- [百炼知识库正式接入部署](docs/deployment/百炼知识库网页正式接入部署.md)
- [资料管理后台部署](docs/deployment/资料管理后台部署-20261006.md)
- [AI 设置后台部署](docs/deployment/AI设置后台部署-20261006.md)
- [简洁前端 UI 实施记录](docs/acceptance/简洁前端UI实施记录-20261007.md)与[部署](docs/deployment/简洁前端UI部署-20261007.md)
- [杂志前端实施记录](docs/acceptance/杂志前端实施记录-20261007.md)与[部署](docs/deployment/杂志前端部署-20261007.md)：当前最新本地设计，正式网页已修改，待服务器更新。
- [资料下载验收记录](docs/acceptance/资料下载部署验收记录-20261005.md)
- [国际商业扩源验收与未解决清单](docs/acceptance/国际商业扩源验收与未解决清单.md)
- [国内扩源阶段收尾](docs/acceptance/新闻扩源阶段收尾.md)
- [历史测试部署记录](DEPLOY.md)

阶段文档保留当时的状态与命令，较早的“待实现”“待验收”不代表当前状态。首次部署以本 README 为入口；已有服务器执行差量升级时，使用对应版本的部署文档，不要混用历史发布包。

## 内容、协作与许可

新闻入口限定为人工批准的官方来源。NASA、国家航天局和中国载人航天按现行策略提供自动政府全文；ESA及企业来源公开标题、元数据和原文链接，不公开摘要、正文或配图。来源身份与自动展示策略不等于事实已核实或转载许可已取得；保留真实版权状态，不伪造授权。部分来源存在地域访问阻塞、归档异常及历史覆盖限制，详见验收记录。

开发使用 Issues 明确目标、范围与验收，通过短期分支和 Pull Request 协作。提交前运行对应检查；不要提交密钥、私钥、实际 `.env`、运行数据库、会话数据、日志、部署备份与虚拟环境。

项目目前保持私有开发，尚未指定开源许可证。引用开源项目的文档组织方式不改变本项目许可；第三方组件与资料分别遵循各自许可和授权条件。

### README 结构参考

- [Full Stack FastAPI Template](https://github.com/fastapi/full-stack-fastapi-template)：技术栈、功能概览与开发、部署文档入口的组织方式。
- [Immich](https://github.com/immich-app/immich)：自托管项目的功能表、安装与文档导航、备份提示的组织方式。
- [Docker Compose 官方文档](https://docs.docker.com/reference/cli/docker/compose/run/)及[环境变量说明](https://docs.docker.com/compose/how-tos/environment-variables/envvars/)：容器命令和配置行为的核对依据。

本说明根据当前项目代码编写，未照搬参考项目的技术栈、部署配置或许可证。

品牌更新（2026-10-07）：公共前端名称已改为「轨道志 / ORBIT JOURNAL」，标志和浏览器图标统一为深蓝轨道与橙色标记点；本地实现完成，服务器未更新。[品牌设计](docs/design/轨道志品牌设计-20261007.md)。

品牌最终调整（2026-10-07）：用户选择名称「知航 / ZHIHANG」，保留新轨道图标，左上角使用宋体艺术刊头。公共前端与升级包已同步更新，服务器尚未部署。
