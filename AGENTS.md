# 仓库维护与发布

## 提交范围

- `main` 维护 `README.md`、`AGENTS.md` 和 `free-ai-token-finder/`。保留完整 Skill、Python 查询工具、官方来源清单、快照和联网兜底说明。
- 小红书单文件版由 Python 工具导出，以 `SKILL.md` 附在 GitHub Release。静态目录和其他导出文件留在输出目录。
- 提交前检查 `git status --short` 和 `git diff --cached`。公开文件、提交信息和 Release 说明只使用项目公开信息。凭据和本机路径留在仓库之外。

## 验证与提交

从仓库根目录执行查询。发版时从同一份已核验的快照生成附件。

```bash
python3 free-ai-token-finder/scripts/catalog.py query --market cn --access api --topic text --no-upfront-payment
python3 free-ai-token-finder/scripts/catalog.py export --output /path/to/output
git add -- README.md AGENTS.md free-ai-token-finder/
git diff --cached --check
git -c 'user.name=agent-variable-publisher[bot]' \
    -c 'user.email=359375883+agent-variable-publisher[bot]@users.noreply.github.com' \
    commit -m "Describe the change"
git show -s --format=fuller HEAD
```

公开提交的作者和提交者均使用 `agent-variable-publisher[bot]`。日常变更创建新提交。只有明确要求改写已发布历史时才使用 `git commit --amend`，并确认改写前后作者和提交者都是该机器人。

## GitHub App 推送

使用组织的 `Agent Variable Publisher` GitHub App。用 App 的签名凭据申请短期安装令牌，令牌限定为 `agent-variable/rednote-skills` 和 `Contents: write`。从受保护的凭据来源将它放入当前进程的 `REDNOTE_APP_INSTALLATION_TOKEN`，避免写入远端地址、Git 配置或日志。签名私钥保存在仓库之外。 [GitHub App 安装认证](https://docs.github.com/en/apps/creating-github-apps/authenticating-with-a-github-app/authenticating-as-a-github-app-installation)

确认 `origin` 是 `https://github.com/agent-variable/rednote-skills.git` 后，通过 App 的安装令牌推送。

```bash
rednote_auth_header=$(
  python3 - <<'PY'
import base64
import os

token = os.environ["REDNOTE_APP_INSTALLATION_TOKEN"]
value = base64.b64encode(f"x-access-token:{token}".encode()).decode()
print(f"Authorization: Basic {value}")
PY
)
REDNOTE_GIT_AUTH_HEADER="$rednote_auth_header" GIT_TERMINAL_PROMPT=0 \
  git -c credential.helper= -c http.followRedirects=false \
  --config-env=http.https://github.com/.extraheader=REDNOTE_GIT_AUTH_HEADER \
  push origin HEAD:refs/heads/main
unset rednote_auth_header
```

明确授权改写已发布的 `main` 时，先读取远端旧的完整提交 SHA，将推送命令改为 `push --force-with-lease=refs/heads/main:<旧提交SHA> origin HEAD:refs/heads/main`。遇到远端有新提交时，先核对变更。

## Tag、Release 与公开校验

- 用同一个 App 令牌推送指向已验证提交的 `vMAJOR.MINOR.PATCH` tag，并通过 GitHub Release API 创建或更新 Release。把 `redskill-upload/SKILL.md` 作为附件上传，附件名保持 `SKILL.md`。 [GitHub Release API](https://docs.github.com/en/rest/releases/releases) · [附件 API](https://docs.github.com/en/rest/releases/assets)
- 修改已有版本的 tag 时，先发布新 tag，更新现有 Release 并核对附件，再清理明确授权移除的旧 tag。
- 匿名检查公开提交的 author、committer 以及仓库活动中的推送 actor，三处都应显示该机器人。发版后核对 Release 和 tag 指向同一提交，并匿名下载附件，比对 SHA-256。 [公开提交](https://github.com/agent-variable/rednote-skills/commits/main/) · [仓库活动](https://github.com/agent-variable/rednote-skills/activity)
- 完成发布后，撤销用完的安装令牌，清除进程变量中的令牌，并清理本次操作下载的临时签名文件。
