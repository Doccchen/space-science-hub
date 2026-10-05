# 国际商业新闻固定样本

2026-10-05由用户在目标服务器执行probe_international.py，采集Arianespace与ispace当前列表及各3个详情。原响应位于data/international-server/international-probes，未提交全文。
样本保留实际新闻卡片、文章标题/分类、发布时间元数据、canonical地址、语言声明、匹配当前文章的JSON-LD及最多180字符正文，去掉图片、无关导航和相关文章。
manifest.json记录请求URL、重定向后URL及原响应SHA256。解析器选择器仅来自这些真实结构。
SpaceX为Cloudflare1009/CN拒绝访问，Blue Origin为Vercel安全检查/HTTP429，没有伪造其新闻样本；阻塞来源只测试禁用、请求失败与历史保留行为。
