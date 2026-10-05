# 新闻解析结构样本

2026-10-05由用户在目标服务器运行只读probe_sources.py，取得四源列表与每源三个详情。
原始文件位于本地data/server-probes/source-probes，未提交全文。manifest.json保存详情原始URL和SHA256以及列表原始SHA256。
此处裁减保留实际选择器、日期、来源、列表链接和最多160字符正文；删除图片和无关导航。
列表分页脚本保留官网原结构，不运行其中JavaScript。CAS page-1.json来自同域公开接口，裁减无关字段和正文，保留公司栏目cid=16及total。
各测试对样本进行日期、错误状态等明确变异，仅用于隔离临时数据库，不能当作线上新闻。

2026-10-05补充CAS旧模板legacy-129/54：从已审核公开接口发现详情URL后读取原始页面，来源分别为https://www.cas-space.com/article/129.html（2025/12/10）与https://www.cas-space.com/article/54.html（2022/07/27）。原响应保存在data/cas-undated；裁减保留实际“来源在前，发布时间在后”的详情元数据及最多120字符正文，用于防止日期提取依赖节点顺序。
