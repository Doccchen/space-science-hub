# 资料下载实施准备数据

日期：2026-10-05。此目录用于人工审核，不是应用运行时公开目录。

最新产物：[28份简介与封面审核草稿](metadata-review.md)、[24张封面上传清单](cover-upload-manifest.json)。28份候选已填入草稿；三本下载为用户人工通过，其余25份按用户要求跳过网络核验。全部保持published=false。运行时content/resources.json已同步28份未公开草稿，私人预览在内存中展示草稿，不代表已发布。

- [filename-mapping.csv](filename-mapping.csv)：31份名称映射，5行逗号错位已规范化；原表未修改。
- [resources.candidates.json](resources.candidates.json)：31份候选，全部published=false。28份含候选OSS键，3份未列出对象的键为空。标题是文件名草稿，其余内容尚未核验。
- [inventory-check.json](inventory-check.json)：本地统计、修复行号、未列出文件及生成时间。size_bytes来自本地文件长度，不是远程HEAD验证。

运行时清单位于content/resources.json，当前全部未公开；不能把候选文件直接当成审核后的元数据发布。候选review字段只记录准备状态，公开API不返回该字段。

重建示例（在项目根目录执行）：

```powershell
.\.venv\Scripts\python.exe tools\prepare_resources.py --source E:/storage/oss-public --output docs/research/resources-preparation-next
```

已有输出不覆盖，人工修改后使用新目录比较。该脚本严格适用于此次检查过的无引号源表：每行最后一个逗号后的值必须精确匹配本地PDF；源格式变更时会拒绝处理。

完整审核与实施约定见[审核报告](../../reviews/OSS电子书资料下载方案-审核与实施准备.md)。准备阶段未生成封面或草拟书籍内容介绍。后续用户已确认三本完整下载、大小一致、PDF可打开且直接下载，候选review字段已记录人工验收；详见[验收记录](../../acceptance/OSS样本重新检查-20261005.md)。其余对象仍待核验，全部候选仍未公开。
