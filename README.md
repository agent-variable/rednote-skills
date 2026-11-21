# 免费 AI Token 查找器

这里提供「免费 AI Token 查找器」的完整 Skill。安装时使用 `free-ai-token-finder/` 目录。固定来源、核验规则和筛选都由同一份 Python 工具执行。所有查找请求访问厂商公开网页。工具使用 Python 3.10+ 标准库。

| 文件 | 用途 |
| --- | --- |
| free-ai-token-finder/data/sources.json | 固定的官方页面 URL、资格、主题、地区站点和核验规则 |
| free-ai-token-finder/scripts/catalog.py | 读取公开页面、核验、归类、筛选并导出 |
| free-ai-token-finder/data/catalog.json | 最近一次真实核验结果，含来源状态和 UTC 时间戳 |
| free-ai-token-finder/references/web-fallback.md | 脚本或 Python 不可用时的模型联网核验规则 |

## 本机运行

进入 `free-ai-token-finder` 目录后运行。

    python3 scripts/catalog.py sources
    python3 scripts/catalog.py refresh
    python3 scripts/catalog.py query --market cn --access api --topic text --no-upfront-payment
    python3 scripts/catalog.py query --format json

sources 输出固定清单。refresh 把此次核验写到 data/catalog.json，并报告缺失、规则待复核和已截止的条目。query 只筛选快照。想临时重新检索又保留磁盘快照时，query 可加 --live。核验时间相差 24 小时以上的快照会提示按历史资料查看。无预充值与超额即停是不同字段。

## 小红书单文件版

从 [最新 Release 附件](https://github.com/agent-variable/rednote-skills/releases/latest/download/SKILL.md) 下载 `SKILL.md`，用于上传小红书 RED Skill。完整目录可用时，助手优先调用 Python 工具。缺少目录中的脚本、清单或 Python 执行能力时，助手用自带的联网搜索核验厂商官方资料。

维护者可在 `free-ai-token-finder/` 中先运行 `refresh`，再导出单文件版和静态目录。

    python3 scripts/catalog.py export --output /path/to/output

上传用文件是输出目录里的 `redskill-upload/SKILL.md`。如已有公开 HTTPS 托管地址，可将输出的 `web/` 文件部署到该地址，并在导出时添加 `--public-base-url` 参数。

## 维护来源

每条产品权益写明官方页面和证据条件。明确可定位的额度数字由规则提取。页面不可用、证据文字变化、同一字段出现冲突或活动已到期时，记录原因，待核验条目不会进入当前匹配结果。新增厂商或产品时，在 sources.json 登记官方页面、权益和核验规则，再跑一次 refresh 检查覆盖。

发布者用同一份快照生成分发文件，读者用相同条件筛时会基于同一批记录。目录覆盖由清单决定，发现其他厂商后需维护清单。
