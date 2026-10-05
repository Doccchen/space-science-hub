# OSS电子书资料下载方案：审核与实施准备

日期：2026-10-05。审阅对象：[实施方案](../plans/OSS电子书资料下载实施方案.md)，并核对当前 backend、web、Docker 配置、本地文件和 OSS 对象记录。

后续实施状态：用户明确豁免其余25份逐项网络核验，该项不再作为实施或发布门槛；本地功能与封面/简介草稿已完成，见[最新实施记录](../acceptance/OSS资料下载本地实施记录-20261005.md)。以下保留审阅当时的建议和状态，不将豁免改写为检查通过。

## 结论与本次范围

**方案可作为开发基线；可以开始本地实现，尚未满足公开发布条件。** 网站提供静态目录、OSS直接提供PDF的架构符合当前FastAPI和原生JavaScript项目，不需要数据库迁移或运行时PDF处理。

本次用户要求是“审核这个实施方案并准备实施”。方案中的“当前只制定方案”是原规划阶段描述，不作为新的用户指令；其中上传、部署、用户审核等步骤也不等于本轮已授权或已执行。此次完成审阅、规范化候选数据与可复用准备脚本，未实施应用功能、上传封面、修改OSS对象/权限、部署或提交推送。

未找到适用于本项目的AGENTS.md。工作区原有README.md、docs/README.md修改，以及.gitattributes、方案和对象清单的未跟踪状态均保留。code-review技能面向提交差异，本轮没有用户指定的比较基点，未按其差异审阅流程执行。

## 需要落实的修订

| 级别 | 位置与问题 | 实施约定 |
|---|---|---|
| P1（发布前） | 方案第1、3、7节：28个对象出现在控制台不等于元数据已审核、允许公开分发、可完整下载；published只有布尔值，审核证据未落实 | 候选数据全部published=false；审核记录逐项保留内容依据、发布确认、封面页、对象检查日期和结果。通过检查的条目才进入运行时目录；3份未列出对象不生成运行时条目。 |
| P1（发布前） | 第5节：附件下载依赖OSS实际响应头，当前未核验；更新对象元数据可能覆盖其他元数据 | 先只读获取当前元数据，再准备修改差异；保留已有Content-Type、Cache-Control和自定义元数据。对三本试跑attachment和中文文件名，浏览器验证后再扩展。不要凭a.download或302声称下载成功。 |
| P2 | 第4、5节：公开域名/可选前缀与含public/的object_key并存，容易出现重复public/、越界路径或错误拼接 | 配置只存HTTPS origin（无路径、查询、片段、用户名），object_key/cover_key存原始完整键。PDF限定public/，封面限定public/covers/。验证实际主机为space-hub-pub.oss-cn-chengdu.aliyuncs.com；拒绝绝对路径、空路径段、点路径段、反斜线和控制字符；逐路径段编码一次，不用可被绝对URL覆盖的无约束urljoin。需要新增域名时修改审核后的允许列表。 |
| P2 | 第2节有格式筛选，第5节没有format参数；分类选项来源、响应结构和页码边界未定义 | 首版只有PDF，展示格式标签即可，不设置无意义格式筛选；分类选项随列表响应提供，来自全部已发布目录，不受当前分页截断。下文固定列表契约与分页行为。 |
| P2 | 第4、6节提到Dockerfile/.dockerignore，但漏了compose.yaml环境变量传递；目录加载失败处理未定义 | 同步修改.env.example与compose.yaml.environment；仅放.env不会自动进入容器。运行时目录启动读取并校验，更新后重启；缺失/损坏时资源API返回503并记录服务端错误，新闻API继续工作，不回退展示未审核候选数据。 |
| P2 | 第7节“断链或下架资料不存在无效可用按钮”，但同时禁止每次页面加载远程探测 | 这只能由发布前验收、用户报障及维护下架保证，无法保证OSS对象被独立删除后的即时识别。发现异常后将published改为false并重启，列表/详情/下载均不可达；下载302设置Cache-Control: no-store。 |
| P2 | web/index.html:13仍写“PDF可另设在线阅读入口”；现有导航由studio.js.showPage统一切换 | 实施时同步修正文案；新增resources-ui.js与页面切换事件，首次进入资料页才请求目录，重新进入保留筛选状态；不重复绑定或破坏现有导航。 |

阿里云官方文档确认：固定下载文件名可通过对象Content-Disposition元数据设置，更新时须保留其他元数据。参见[自定义OSS文件下载时的文件名](https://help.aliyun.com/zh/oss/set-the-file-name-for-downloading-an-oss-file)。跨域链接不能仅依赖download属性，参见[MDN a元素](https://developer.mozilla.org/en-US/docs/Web/HTML/Reference/Elements/a)。本轮查阅了这两项技术依据，但没有取得实际对象响应头。

## 已完成的准备

- 源目录E:/storage/oss-public只读核对：31份PDF，实际合计2,665,985,688字节，约2542.5MiB；每个上传文件名唯一，并与本地文件一一对应。
- 控制台记录中的28份对象均匹配本地文件；3d-imaging-reconstruction.pdf、analog-electronics-6th-edition.pdf、automatic-control-principles.pdf仍为未列出状态。
- 确认标准CSV解析错位5行，源行号3、21、24、25、27；按最后一个逗号分割后，以真实文件名严格验证，另存规范CSV。原CSV和PDF没有修改。
- 生成31份候选记录，稳定id采用上传文件名去掉扩展名；精确大小来自本地stat。标题只是去掉.pdf的原始名称，作者、版本、语言、分类、介绍、封面均待审核，不将文件名推断当成已验证事实。
- 候选published均为false；28份记录存候选public/对象键，3份未列出记录object_key=null。该候选文件不是运行时content/resources.json。
- 当前项目Python为3.12.14，有httpx，未安装fitz/PyMuPDF、pypdf和Pillow。封面处理尚未试跑；实施时使用独立离线处理环境，不把PDF依赖加入运行时requirements.txt。

准备产物位于[resources-preparation目录](../research/resources-preparation/README.md)：规范CSV、候选JSON、校验摘要。[准备脚本](../../tools/prepare_resources.py)只依赖标准库，遇到漏配、重复、源格式变化或未知对象会停止；已有输出拒绝覆盖，以免冲掉人工审核结果。

### 三本网络检查结果

后续重测：用户将OSS从私有调整为公共读后，首本样本HTTPS HEAD在沙箱外仍发生TLS握手失败，未取得HTTP响应；进一步直连TLS 1.2测试未获批准。随后用户确认三本均能直接下载、大小与本地一致、PDF可打开，三本人工下载验收通过，响应头原值仍未独立核验。详见[2026-10-05重新检查记录](../acceptance/OSS样本重新检查-20261005.md)。下表保留首次自动检查结果。

| 试跑候选 | 本地字节数 | 本轮只读HEAD |
|---|---:|---|
| numerical-analysis-2nd-edition.pdf | 9,472,498 | 沙箱内DNS失败；沙箱外TLS连接失败 |
| guidance-systems-lecture-notes.pdf | 281,843,279 | 同上 |
| cpp-programming.pdf | 195,150,026 | 同上 |

未取得HTTP状态、Content-Length、Content-Type或Content-Disposition；没有完整下载、封面生成或远程上传。传输失败不证明对象失效。选择这三份覆盖较小文件、大文件和多作者文件名，属于试跑建议，不代表最终发布选择。

## 固定首版接口与实现位置

运行时content/resources.json采用JSON数组，只放纳入运行时目录的资料，不携带候选review字段。未审核记录可以不进入该文件；允许published=false记录用于暂时下架。公开API使用显式字段白名单，不直接返回原始文件名、内部对象键、审核记录或本地路径。

### 接口契约

- GET /api/resources：q默认空，最多120字符；category最多80字符；page>=1；1<=page_size<=48，默认12。非法参数返回422。q对标题、authors和tags执行Unicode规范化、casefold后的子串匹配；不解析PDF。
- 排序按(display_order, id)。切换搜索/分类回第1页。页码超过末页返回空items，保留total/pages；总数0时pages=0。
- 响应形态：`{items: [...], total, page, page_size, pages, categories: [...]}`。categories是全部公开目录中去重的实际分类；缺失分类不制造占位类别。空目录返回200及空数组。
- items公开字段：id、title、authors、edition、language、category、tags、format、size_bytes、description_short、cover_url、download_url。download_url为本站`/api/resources/{id}/download`；cover_url经同一受控URL构造器生成，允许null。
- GET /api/resources/{id}：仅公开条目，额外返回description、source_note；未知和未公开id均404，不泄露审核状态。
- GET /api/resources/{id}/download：显式302，附Cache-Control: no-store；未知/未公开id为404，配置或目录不可用为503。不接受客户端url/key/bucket，不发远程请求，不读取PDF。
- 所有元数据按普通文本渲染，使用textContent；不把文件名或介绍拼入innerHTML。封面加载失败退回带标题的“暂无封面”。详情使用dialog，支持Esc、关闭按钮、焦点恢复；资料加载失败显示重试。

### 文件级任务

| 文件 | 改动 |
|---|---|
| backend/resources.py（新增） | 目录校验、公开投影、查询分页、受控OSS URL构造；不调用news数据库 |
| backend/app.py | 注册资源路由；沿用静态资源挂载和新闻生命周期，不引入第二个采集任务 |
| content/resources.json（新增） | 经审核的运行时清单；本地功能开发可用空数组，接口测试用临时目录 |
| web/resources-ui.js（新增） | 搜索防抖、分类、分页、详情、旧请求取消/结果序号保护；点击下载使用普通a链接 |
| web/index.html、web/style.css、web/studio.js | 替换资料空状态、加载新脚本和页面切换事件，局部样式与关于页文案 |
| Dockerfile、.dockerignore | COPY content；只放行运行时JSON，不把离线预览图、候选清单和PDF打入镜像 |
| .env.example、compose.yaml | 声明并传入RESOURCE_OSS_ORIGIN与RESOURCES_PATH；路径默认/app/content/resources.json，origin为上述明确允许的HTTPS主机 |
| tests/test_resources.py（新增） | 临时JSON测试查询、分页、公开过滤、404/422/503、URL编码/拒绝越界及302；断言下载不触发远程网络或PDF读取 |
| tools/accept_resources.py（实施时新增） | 离线目录校验与可显式启用的远程HEAD检查，按实际结果留证；完整下载不以HEAD结果代替 |
| 部署/验收文档 | 单独资源升级流程及浏览器验收记录，不复用会探测、启用新闻来源的upgrade_international.sh |

环境配置建议：RESOURCE_OSS_ORIGIN=https://space-hub-pub.oss-cn-chengdu.aliyuncs.com；RESOURCES_PATH=/app/content/resources.json（容器）。本地目录默认根据项目ROOT定位，不能将容器绝对路径作为本地启动默认值。

## 实施顺序与检查门槛

1. 本地功能可以先行：完成目录校验、三条API、页面交互及Docker配置。使用测试数据或空公开目录验证功能；不要把候选28份自动设为published=true。
2. 三本离线试跑：仅读第一页；记录页是否为真实封面、能确认的标题与出版信息。必要时少量读取目录/前言；生成缩略图和介绍草稿，注明依据页。第一页不合格的条目保持占位，等待指定封面页。
3. 元数据和发布清单审核后，将通过项转入运行时清单；在可连通环境核对HEAD字节大小及响应头，准备封面上传清单和对象元数据差异。封面上传与对象元数据修改执行前需有相应授权。
4. 本地回归：`python -m unittest discover -s tests -v`，沿用项目unittest；新闻用临时数据库、禁用采集，不触碰实际data目录。浏览器验收搜索、分页、长标题、缺图/错误状态、键盘详情及手机视图。
5. 容器检查：确认镜像内content可读、环境配置生效、资源API可用；首屏网络无PDF正文。运行容器使用COLLECT_ENABLED=0做隔离验证。
6. 服务器发布前记录旧镜像、环境、数据库备份、新闻身份与历史队列基线；保持原news-data卷，升级后比较基线，保留回退镜像。资源升级不执行新闻来源启用、回填或采集探测。
7. 浏览器完成三本完整下载并核对文件字节长度、PDF能打开，其他公开对象逐一核对存在与大小；记录封面可读及attachment行为。自动检查和人工检查分别留证，通过后再记录“已验收”。提交和push仍由用户执行。

开发估计1—2个工作日只适用于应用代码与基础验证；31份内容审核、封面页异常、网络访问和用户验收的等待时间单独计算。

## 本轮验证

准备脚本实际成功执行，输出31/28/3的对应关系、5行修复与0份公开资料。规范CSV写出后使用标准csv.reader回读验证；生成物还需人工内容审核。应用代码未改变，因此本轮不将既有新闻测试结果冒充资源功能测试。后续实施仍需完成上述接口、浏览器、容器与真实下载验收。
