# 航天新闻与科普平台

项目暂定名称：Space Science Hub。包含航天新闻、科普 Agent、资料下载三个栏目，当前优先新闻与 Agent，资料下载后置。

## 当前状态

2026-10-05新闻扩源与日期窗口回填阶段已收尾。服务器最终核对298条新闻：国家航天局143、中国载人航天82、中科宇航42、蓝箭12，另有NASA/ESA19条。用户确认新版分类、单来源、加载更多和详情正常；最终全部记录重建保留及独立备份恢复通过，容器healthy，小时采集已恢复。入口[测试网站](http://8.137.164.100:8080)，国内网络可访问，服务器限制国外IP访问。

历史覆盖保留两项说明：国家航天局32/301页，用户明确选择按2025-10-01起的日期窗口收尾，未全量核对；中国载人航天保留41个较早归档访问/结构异常。两家公司当前审核栏目归档已枚举，无缺口。不声称四源全部历史完整。

操作见[国内扩源迁移与部署](docs/国内扩源迁移与部署.md)，最终结果见[新闻扩源阶段收尾](docs/新闻扩源阶段收尾.md)，过程见[国内扩源实施与验收记录](docs/国内扩源实施与验收记录.md)。用户自行Git提交，Agent未提交或推送。

- 已实现：NASA/ESA RSS、四家国内官方来源适配器、幂等入库、类别与来源筛选、稳定游标分页、有限摘要/正文节选、内容来源与日期精度、详情与原文链接、断点回填及兼容迁移。
- 新版本地与服务器29项固定测试通过；真实采集、重复内容、筛选分页、故障历史保留、备份恢复和全部回填记录容器重建检查通过。
- 科普 Agent：目前仅有明确标注的固定演示；真实生成、双版本输出和事实核验待开发。
- 资料下载：空状态，暂不开发。
- Docker：测试服务器现有命名卷持久化，最终容器重建后298条记录身份保留，独立备份恢复通过，容器healthy。

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
