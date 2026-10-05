# 航天新闻测试版部署

2026-10-05最终验收已完成：298条记录、容器healthy、全部回填数据重建保留及备份恢复通过，浏览器操作由用户确认正常。当前结果见[新闻扩源阶段收尾](docs/acceptance/新闻扩源阶段收尾.md)。历史覆盖限制和断点保留，不需重复部署。

国内扩源新版请使用[国内扩源迁移与部署](docs/deployment/国内扩源迁移与部署.md)中的升级流程。保持现有.env和持久卷，不重复执行首次部署；2025-10-01起历史任务单独运行。以下为原版本部署记录。

## 临时公网 IP 测试入口

用户已完成公网监听配置并确认国内网络可访问，入口为
`http://8.137.164.100:8080`。公网配置重建后容器已确认 healthy，端口为 `0.0.0.0:8080->8000/tcp`。用户反馈国外网络不可达，原因尚未定位。以下命令已由用户执行，无需重复操作。

服务器执行以下命令，仅修改当前项目 `.env` 的监听地址和端口，然后重建应用容器，沿用现有命名卷：

```bash
cd /opt/space-news
cp -p .env ".env.before-public-$(date -u +%Y%m%dT%H%M%SZ)"
python3 - <<'PY'
from pathlib import Path
p = Path('.env')
lines = [line for line in p.read_text().splitlines()
         if not line.strip().startswith(('BIND_ADDRESS=', 'WEB_PORT='))]
p.write_text('\n'.join(lines + ['BIND_ADDRESS=0.0.0.0', 'WEB_PORT=8080']) + '\n')
PY
docker compose config --quiet && docker compose up -d --no-deps app
docker compose ps
```

在阿里云控制台为该服务器添加入站 TCP 8080 规则。若实例是轻量应用服务器，使用防火墙页面；若是 ECS，使用安全组入方向规则。需要任何测试者均可访问时，来源设为 `0.0.0.0/0`。
浏览器打开上述 IP 地址，并访问 `/api/health` 核对真实服务可用。
若页面不通，先检查 `docker compose ps` 的端口绑定与 `curl http://127.0.0.1:8080/api/health`，再核对云端入站规则及服务器已有防火墙。

## 本轮部署与验收入口（2026-10-05）

更新：用户已在服务器执行脚本，2026-10-05 13:29:26（北京时间）五项服务器检查通过，实际入库 NASA 10 / ESA 9，共 19 条。证据目录 `/opt/space-news/acceptance-20261005T052833Z`。后续已确认容器 healthy，浏览器交互待确认，详见 `docs/acceptance/新闻部署验收记录.md`。以下未部署描述属于此前准备阶段记录。

本轮 Agent 在受限环境连接 SSH 返回 Permission denied，获准重试后返回
`Connection closed by 8.137.164.100 port 22`。未登录服务器，未执行部署，不能声明服务器验收通过。

部署包现包含 `tools/deploy_accept.sh` 与 `tools/accept_news.py`。
首次部署可沿用下面的上传、解压命令，再在服务器执行：

```bash
cd /opt/space-news
bash tools/deploy_accept.sh
```

脚本为缺失的 `.env` 写入 ECR 镜像与阿里云包索引配置，保留已有配置。
先校验 Compose，再为当前运行实例备份 SQLite，构建启动应用。
在 `acceptance-UTC时间/` 保存运行日志、容器 ID、卷名与 JSON 结果。
如果目录已有部署，解压覆盖前应先另行备份已有代码及配置；脚本的数据库备份不能替代代码备份。

验收检查：

- 服务器实际请求 NASA/ESA，执行两轮采集；两源均需成功并有记录。
- 再抓取真实 RSS 原始内容，把同一内容经采集函数重复处理两次；记录身份和数量不得变化，数据库不得存在重复来源/规范化 URL。
- 全部/NASA/ESA 使用 limit=2 遍历 API 游标，与数据库完整排序比较，检查无重复、无遗漏，详情与非法参数响应正确。
- 用 MockTransport 在真实采集函数内模拟连接故障，使用当前数据库检查历史仍可读、失败状态可见、最近成功时间保留；结束后恢复来源状态。此项是故障注入，不声称上游真实发生故障。
- 强制重建应用容器，核对容器 ID 变化、卷名相同、历史新闻 ID/来源/URL/首次入库时间保留，并重新检查 API。

任一断言失败会中止脚本并返回非零状态。脚本不删除数据卷。
浏览器交互需通过 SSH 转发另行验收：点击新闻栏目、NASA/ESA/全部筛选，打开详情并核对原文链接。
现有真实 feed 约 19 条，默认首批 20 条时可能没有“加载更多”；脚本以 limit=2 验证后端分页，不能因此声称已验收前端加载更多按钮。
本轮尚未在 Linux 执行部署脚本，也未完成浏览器交互验收。

2026-10-05。目标服务器：Ubuntu 24.04.2 / root@8.137.164.100。Docker和Compose已安装；NASA与ESA出网HTTP200。Docker Hub拉取hello-world超时。当前应用已在本机验证，服务器尚未部署。

## 已完成

真实RSS采集、SQLite幂等入库、来源与发布时间、文本摘要、列表/来源筛选/游标分页、详情及原文链接、状态展示、小时更新。英文内容保留原文。来源失败保留历史数据；缺少发布日期明确展示。

科普Agent仍是固定示例，未接入新闻或模型；资料下载未实现。页面不能把示例视为当前新闻的解读结果。

本地真实数据19条（NASA10、ESA9），10项后端测试通过，页面及API HTTP检查通过。未执行浏览器交互验收、容器镜像构建和服务器实测。

## 1. 先解决基础镜像访问

Docker 官方在 ECR Public 提供官方镜像分发入口，参考：https://www.docker.com/blog/news-from-aws-reinvent-docker-official-images-on-amazon-ecr-public/ 。这是替代仓库，不代表该服务器一定可访问。

服务器只需先尝试：

```bash
timeout 90s docker pull public.ecr.aws/docker/library/python:3.12-slim
```

成功后在.env中设置PYTHON_IMAGE为上述地址；可将返回的RepoDigest用于固定镜像版本。失败请保留具体错误，不配置未经核对的公共加速站，也不持续重复同一请求。可随后使用用户阿里云账号的ACR镜像仓库或在可联网机器构建后通过docker save/load传递镜像；选择方式后再补命令。

## 2. 上传部署包

在本机PowerShell运行：

```powershell
scp -i "D:\Documents\竞赛\AI+信息素养\GPT.pem" "D:\Documents\竞赛\AI+信息素养\GPT-WebSite\artifacts\packages\space-news-release.tar.gz" root@8.137.164.100:/root/
```

部署包仅包含backend、web、测试、Dockerfile、Compose、依赖和说明，不包含私钥、本机数据库、.env或虚拟环境。

## 3. 在服务器构建和启动

先确认/opt/space-news是本项目的测试目录；首次部署创建目录。已有部署时先备份，不用此流程直接覆盖。

```bash
mkdir -p /opt/space-news
tar -xzf /root/space-news-release.tar.gz -C /opt/space-news
cd /opt/space-news
cp -n .env.example .env
```

编辑.env：若ECR镜像拉取成功，设置：

```dotenv
BIND_ADDRESS=127.0.0.1
WEB_PORT=8080
COLLECT_INTERVAL_SECONDS=3600
PYTHON_IMAGE=public.ecr.aws/docker/library/python:3.12-slim
PIP_INDEX_URL=https://mirrors.aliyun.com/pypi/simple/
```

应用运行依赖已固定。阿里云PyPI镜像在本机依赖安装验证中可用，服务器构建仍需实测。没有使用Snap Docker或修改Docker全局镜像加速配置。

```bash
docker compose config --quiet
docker compose up -d --build
docker compose ps
docker compose logs --tail=80 app
curl -fsS http://127.0.0.1:8080/api/health
curl -fsS 'http://127.0.0.1:8080/api/news?limit=2'
```

首次启动立即采集，之后每小时一轮。刚启动时health里的articles可能为0，等待首轮日志后再看列表。没有公开手动采集接口。

测试版先由一个非root应用容器同时提供静态前端与API，减少基础镜像依赖；内存上限640MB、CPU上限1核。下一阶段公开部署再增加Nginx与HTTPS，后端和前端无需重写。SQLite保存在Docker命名卷。此容器只能单worker/单实例调度，不能直接扩容多个worker。

## 4. 从本机访问服务器测试页

默认8080只监听服务器本机，不需要改云防火墙。在本机PowerShell新开终端并保持连接：

```powershell
ssh -i "D:\Documents\竞赛\AI+信息素养\GPT.pem" -L 8080:127.0.0.1:8080 root@8.137.164.100
```

浏览器访问 http://127.0.0.1:8080 。如果本机8080已占用，用-L 18080:127.0.0.1:8080并访问18080。

后续需要公开访问再确定域名、HTTPS、入口和允许的云端口；当前没有公开暴露数据库或Docker管理接口。

## 5. 数据保留与迁移

docker compose down不会删除命名卷；不要使用down -v。迁移时用SQLite backup创建一致性副本，不直接复制正在写入的WAL数据库主文件。API与数据库路径未写死公网IP。配置文件、Compose及命名卷数据需一并迁移。

数据备份命令（在项目目录执行）：

```bash
docker compose exec -T app python -c "import sqlite3; a=sqlite3.connect('/data/news.sqlite3'); b=sqlite3.connect('/data/backup.sqlite3'); a.backup(b); b.close(); a.close()"
```

再将/data/backup.sqlite3从容器复制到独立备份位置，需保存到服务器以外才构成异地备份。为防止覆盖，真正运维时采用带日期的备份命名。
