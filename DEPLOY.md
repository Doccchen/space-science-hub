# 航天新闻测试版部署

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
scp -i "D:\Documents\竞赛\AI+信息素养\GPT.pem" "D:\Documents\竞赛\AI+信息素养\GPT-WebSite\space-news-release.tar.gz" root@8.137.164.100:/root/
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
