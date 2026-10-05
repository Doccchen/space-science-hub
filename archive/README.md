# 历史归档

此目录保留早期选题、设计方案与前端原型，避免与当前应用混用。2026-10-05整理时只移动文件，没有删除或重新实现原型。

## 原型

| 版本 | 网页入口 | 说明 |
|---|---|---|
| 信息冲突核对 | [index.html](prototypes/information-check/index.html) | [说明](prototypes/information-check/README.md) |
| 航天适配v1 | [aerospace.html](prototypes/aerospace-v1/aerospace.html) | [说明](prototypes/aerospace-v1/README.md) |
| 简洁航天v2 | [aerospace-v2.html](prototypes/aerospace-v2/aerospace-v2.html) | [说明](prototypes/aerospace-v2/README.md) |

各原型的HTML/CSS/JavaScript/预览脚本放在同一目录，保留相对引用。直接打开HTML即可；如需启动旧预览服务，进入对应目录运行其中的.cjs脚本。若旧端口已有预览进程，需先结束该旧进程，不能同时占用同一端口。

当前正式前端代码在 [web/](../web/)，不要在历史原型中实现新功能。

## 早期方案

- [早期网站实施方案](plans/网站实施方案.md)：科研文献主题阶段的资料。
- [信息核对前端设计方案](plans/前端设计方案.md)：此前选题的界面方案。
- [建设方案v1.2审核意见](reviews/建设方案v1.2-审核意见.md)：新闻与Agent方案的早期审核。

当前项目状态与文档见 [文档索引](../docs/README.md)。本地部署压缩包放在artifacts/packages，数据库与运行证据仍在data，均不提交Git。
