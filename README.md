# 航天新闻与科普平台

项目暂定名称：Space Science Hub。包含航天新闻、科普 Agent、资料下载三个栏目，当前优先新闻与 Agent，资料下载后置。

## 当前状态

- 已实现：NASA/ESA RSS 采集、SQLite 幂等入库、来源筛选、新闻列表与分页、来源摘要节选、新闻详情和原文链接。
- 本地验证：实际采集 19 条新闻（NASA 10、ESA 9），10 项后端测试通过。
- 科普 Agent：目前仅有明确标注的固定演示；真实生成、双版本输出和事实核验待开发。
- 资料下载：空状态，暂不开发。
- Docker：部署文件已准备，尚未完成容器构建及服务器验收。测试服务器已成功拉取 ECR Python 3.12 基础镜像。

## 技术结构

Python 3.12 / FastAPI / httpx / feedparser / SQLite，HTML、CSS、JavaScript 前端，Docker Compose 测试部署。测试版单个应用容器提供静态页面与 API；公开部署时再完善入口、HTTPS及反向代理。

```text
backend/          新闻采集、存储与 API
web/              当前网站前端
tests/            后端固定测试
Dockerfile        应用镜像
compose.yaml      测试部署，单 worker
.env.example      无密钥的配置示例
DEPLOY.md         现有部署说明
docs/             开发分工与阶段验收
```

## 本地运行

```bash
python -m venv .venv
# Linux/macOS: source .venv/bin/activate
# Windows PowerShell: .venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m backend.news
python -m uvicorn backend.app:app --host 127.0.0.1 --port 8000 --workers 1
```

访问 http://127.0.0.1:8000 。应用启动后立即进行一轮采集，之后每小时更新。首次查看可能暂时无记录。

```bash
python -m unittest discover -s tests -v
```

## 容器测试

将 `.env.example` 复制为 `.env`，按环境设置镜像来源。若 Docker Hub 不可访问，可使用已验证可拉取的 `public.ecr.aws/docker/library/python:3.12-slim`，或将其固定到已核对的 digest。镜像与包索引访问需按部署环境实测。

```bash
docker compose config --quiet
docker compose up -d --build
docker compose ps
```

默认只监听服务器本机8080，可通过SSH转发测试。数据库使用命名卷，迁移必须包含一致性备份；不要使用 `docker compose down -v` 删除持久数据。

## 管理与开发

采用 Issues 明确目标、范围与验收；实现使用短期功能分支与 Pull Request。方案制定与结果审核由规划方负责，具体编程、测试与部署由实施 Codex 完成。后续不根据旧原型或旧方案推断新增功能。

开发阶段保持私有仓库，不预先指定开源许可。第三方组件或资料的许可按实际使用核对。

## 数据与能力边界

新闻来源限定为人工批准的官方入口；来源身份不等于内容永远正确。页面展示来源摘要节选，不冒充全文。发布时间缺失时不以采集时间替代。科普示例不等于对当前新闻的真实AI分析。

不要提交私钥、API key、实际 `.env`、运行数据库、日志、部署备份与虚拟环境。
