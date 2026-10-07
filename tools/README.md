# 项目工具导航

工具按用途在本目录保留，避免改变现有导入和部署路径。生成的发布文件放入 `artifacts/packages/`；运行证据、数据库和密钥不提交 Git。

| 用途 | 主要入口 | 使用说明 |
|---|---|---|
| 新闻采集与验收 | `probe_sources.py`、`probe_international.py`、`accept_news.py`、`accept_domestic.py` | 来源探测可能访问网络；固定离线测试在 `tests/` |
| 历史回填 | `backfill_domestic.sh` | 按相应来源的 `docs/backfill/` 记录操作 |
| 新闻阅读与管理 | `reading_manage.py`、`admin_user.py`、`backup_review.py`、`accept_reading.py` | 涉及运行数据，按部署文档备份及核对目标 |
| 资料准备与验收 | `prepare_resources.py`、`prepare_resource_covers.py`、`draft_resource_metadata.py`、`prepare_resource_release.py`、`accept_resources.py` | 中间产物不代替正式 `content/` 与 `web/` 资源 |
| 资料后台持久化 | `resources_manage.py` | 显式 migrate、inspect、SQLite 一致性 backup、旧版目录 export；见资料管理后台部署说明 |
| 百炼配置与探测 | `configure_ai.py`、`probe_bailian.py`、`run_bailian_probe.sh` | 密钥只在运行环境；探测真实服务会产生实际用量，不默认执行 |
| AI 设置后台 | `ai_manage.py`、`package_ai_management.py` | 主密钥生成、环境显式 init、脱敏 inspect、私有 export-env；定向发布包不含密钥/库/Compose，按独立密钥挂载说明部署 |
| 本机后台一键入口 | `open_admin.ps1` | 项目根目录快捷方式自动建立/复用 SSH 转发并打开浏览器；保留管理员密码，Close 只结束本入口自己的连接 |
| 卫星百科访问评估 | `probe_satwiki.py` | 最多两个只读 HTTP 请求，不下载词条；API 403或限流后停止，见卫星百科批量获取调研 |
| 卫星百科官方导出整理 | `inspect_satwiki_export.py` | 离线校验官方 XML，保存原文件、Wikitext 和版本来源清单；不是知识库成品转换器 |
| 卫星百科百炼文档准备 | `prepare_satwiki_bailian.py` | 首批 30 篇转 UTF-8 Markdown；依赖 `requirements-satwiki.txt`，保留公式、表格和来源，不上传云端 |
| 发布打包 | `package_*.py` | 输出发布包与清单；旧包不自动代表当前工作区 |
| 部署与回退 | `upgrade_*.sh`、`install_ai_release.py`、`deploy_accept.sh`、`final_acceptance.sh` | 优先读对应 `docs/deployment/`，不能混用不同阶段包和备份 |
| 本地预览 | `preview_*.py` | 仅本机离线演示，不作为线上真实回答或部署验收 |

完整离线测试在项目根目录运行：`python -m pytest -q`。服务器操作与 Git 提交、推送由用户执行。
