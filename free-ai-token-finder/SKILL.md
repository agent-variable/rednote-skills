---
name: free-ai-token-finder
description: 用固定的官方来源目录和 Python 查询工具盘点免费 AI API、Token、周期额度、试用赠金和产品内积分。支持按站点、用途、接入方式和费用条件筛选，输出官方证据与核验状态。
---

# 免费 AI Token 查找器

**优先使用本目录的 Python 工具。** 来源和核验规则在 [data/sources.json](data/sources.json)，快照在 [data/catalog.json](data/catalog.json)，命令入口在 [scripts/catalog.py](scripts/catalog.py)。有 Python 3.10+、完整工具和终端执行能力时，从已安装的技能目录或用绝对路径运行。

- 综合盘点用 `python3 scripts/catalog.py query --format json`。快照缺失、`is_stale` 为 true，或用户明确要求实时核验时，有联网执行能力就运行 `python3 scripts/catalog.py refresh` 后再查询。刷新只读取固定官方公开网页，输出当次状态。结果为空或某家来源不可用时，保留脚本的覆盖和异常报告。
- 定向筛选加相应参数，例如 `--market cn --access api --topic text --no-upfront-payment`。`--market cn` 表示中国大陆站，`international` 表示国际服务。外部 API 用 `--access api`，应用内额度用 `--access product`，指定云平台用 `--access platform`。主题用 `text`、`code`、`image`、`video`、`audio`、`documents`、`embeddings`（向量与重排）。`--billing stops` 只查超额即停，`--billing opt-in-stop` 查可通过设置控制的权益。
- 写清额度用完后的费用边界。无预充值指已核验的开通门槛，用量是否自动停止看单独的计费字段。保留来源、原始单位、资格、核验时间和截止日期。结果为空时报告覆盖范围，不把其他市场、产品内积分或待核验条目填进结果。

本机缺少脚本、来源清单、Python 或终端执行能力时，切换到助手自带的联网搜索和网页阅读。按 [联网核验规则](references/web-fallback.md) 从厂商官方资料查，并注明本次查找方式和覆盖范围。用户自行登录、领取或创建密钥。
