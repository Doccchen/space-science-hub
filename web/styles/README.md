# 主页面样式入口

主页面只加载 `base.css` → `components.css` → `pages.css`。这三份文件由 `tools/build_styles.py` 生成，不直接手改。

| 入口 | 职责 | 按原覆盖顺序合入的源文件 |
|---|---|---|
| base.css | 全局变量、基础排版、重置与默认布局 | style.css |
| components.css | 新闻筛选与分页、资源卡片、问答组件及旧组件兼容样式 | resources.css、glass-theme.css、ai.css、frontend-refinement.css、quiet-ui.css |
| pages.css | 线上杂志外观、各页面布局、动效、共享角色与独立欢迎层 | editorial.css、ai-layout.css、site-motion.css、design-system.css、site-welcome.css |

维护时先按职责修改对应源文件，再运行 `python tools/build_styles.py`；检查使用 `python tools/build_styles.py --check`。源文件及三个生成入口应一起提交。前端发布脚本会自动重建入口。

本次收拢保持规则、媒体查询及覆盖顺序，不做未知旧规则清理，避免影响既有筛选、阅读弹窗和问答。旧 URL 继续保留给独立资源页与历史发布脚本。新闻阅读弹窗的 `news-agent.css` 仍由阅读器加载，不受三份主页面入口的职责划分影响。

生成工具将相对图片 URL 保持为原 `/assets/` 路径，防止入口进入 `styles/` 目录后图片路径改变。
