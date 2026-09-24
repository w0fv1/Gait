# Gait

使用 Norm 实现的通用 Agent，模型直接回答，并按需调用 Git 工具。

## 获取与构建

Gait 的编译命令是 `norm build gait`，在仓库根目录运行；首次本机编译时 Norm 会准备自己的 Native Image 工具链。需要**兼容本仓库所用接口**的 [Norm](https://github.com/normlanguage/Norm) CLI。当前公开的 Norm `v0.24.0` 尚不兼容；本仓库已用 Norm 源码提交 `6c3e1c5` 构建的 CLI 验证。在兼容的 Norm 安装版发布前，需要先从该源码构建 Norm CLI（Norm 自身使用 Maven），再用它执行以下命令。当前尚未发布 Gait 预编译版本。

```powershell
norm build gait
```

产物位于 `gait/build/gait.exe`（Windows）；其他系统为 `gait/build/gait`。本仓库已包含所需的 OpenAI Norm 模块源码，不再需要额外复制这个依赖。Norm 发布兼容安装版后，Gait 的构建将只需安装该 CLI 并运行上面的 `norm build`。

```powershell
.\gait\build\gait.exe 回复ok
.\gait\build\gait.exe show the current repository status
```

每次调用接收一个请求，输出一次最终回答后立即退出。下次调用不记忆前文，不读取或保存会话。中英文可以直接输入，PowerShell 特殊字符需要引号或转义。

文本回答使用 API 的 `stream: true`，收到文本增量就立即显示，没有人工延时。JSON 模式也通过流式接口接收，但在完成后一次输出完整 JSON。

“提交代码”会检查改动并按主题分批提交，每批自动生成提交信息。可以直接限定范围，例如“只提交暂存区”或“提交 docs 下的改动”。完整行为指令见 [instructions.norm](gait/instructions.norm)。

了解文件时优先使用 `git_summarize_file` 子工具，每次一个 `path`，可用 `focus` 指定总结倾向，例如“关注接口和依赖”或“判断提交主题及相关测试”。需要源码细节时才分页读取。本次任务上下文过长时会自动整理后继续，不保存到下一次调用。

一个请求内可以完成多步工具操作，例如“看看改了什么并总结”。普通问答不要求 Git 仓库；只有使用 Git 工具时才检查仓库。可用工具及参数以 [tools.norm](gait/tools.norm) 为准。

## 模型配置

```powershell
.\gait\build\gait.exe --init
```

依次填写密钥、模型和接口地址；方括号显示当前值，密钥显示为 `******`，回车保留。支持完整的 `/responses` 和 `/chat/completions` 地址，按地址选择协议。以 `/v1` 或 `/v1/` 结尾的 Base URL 自动补成 `/v1/responses`。MiMo Token Plan 使用 `https://token-plan-cn.xiaomimimo.com/v1/chat/completions`。

小米 Token Plan 可填写模型 `mimo-v2.5-pro` 和地址 `https://token-plan-cn.xiaomimimo.com/v1`。初始化测试连接成功后才保存。

Windows 配置位于 `%APPDATA%\gait\config.json`，缺少 APPDATA 时使用 `%USERPROFILE%\AppData\Roaming\gait\config.json`。其他系统使用 `$XDG_CONFIG_HOME/gait/config.json` 或 `~/.config/gait/config.json`。

```json
{
  "apiKey": "你的完整密钥",
  "model": "mimo-v2.5-pro",
  "endpoint": "https://token-plan-cn.xiaomimimo.com/v1/responses"
}
```

环境变量 `GAIT_AI_API_KEY`、`GAIT_AI_MODEL`、`GAIT_AI_ENDPOINT` 优先于文件；已有连接时可直接说“帮我配置”或要求修改并测试配置。连接须支持所选协议的文本和函数调用；初始化使用 JSON 对象探针。请求配置修改时，新凭据必须来自用户消息。

## 输入与工具

Git 工具通过参数数组执行，保留路径、冲突与写后验证。模型可以在本次请求内多步调用工具，工具中间结果只用于本次推理，工具参数在完整响应结束并校验后才执行。不提供任意 Shell 执行能力。

```powershell
.\gait\build\gait.exe --repo C:\path\to\repo 查看状态
.\gait\build\gait.exe --format json 查看状态
.\gait\build\gait.exe --stdin
```

`--repo` 选择 Git 工具目录，默认当前目录。`--format json` 输出一个 JSON 结果，包含最终 `text` 和 `tools` 记录。`--stdin` 读取到 EOF，将多行内容作为一个完整请求，与命令行请求互斥。工具名称输出到 stderr。未提供请求时提示用法并退出；`--init` 仍提供逐项配置。

临时上下文及工具调用预算见 [agent.norm](gait/agent.norm)。模型配置文件继续保留；用户请求和回复不落盘，也不使用服务端历史 ID。

## 开发

运行产物为 `gait/build/gait.exe`，需要 PATH 中的 Git 来执行 Git 工具。应用不依赖 Python 或 Java。

直接修改源码后运行 `norm build gait` 即可重新编译。开发脚本需要 Python 和兼容的 Norm CLI（通过 PATH 或 `NORM_CLI` 指定），可用于运行源码、校验依赖指纹并把构建产物复制到 `dist/`：

```text
python scripts/manage.py prepare
python scripts/manage.py run -- 回复ok
python scripts/manage.py build
```

所附 OpenAI 模块的依赖指纹见 [dependencies.lock.json](dependencies.lock.json)。请求、工具和初始化验收见 [tests](tests)，结构见 [docs/architecture.md](docs/architecture.md)。

构建后可运行测试：

```powershell
$env:GAIT_EXECUTABLE = (Resolve-Path .\gait\build\gait.exe).Path
python -m pip install -r tests/requirements-windows.txt
python -m unittest discover -s tests -v
```

## 许可证与贡献

Gait 源码以 [MPL-2.0](LICENSE) 发布。`dependencies/openai/` 包含来自 [Norm](https://github.com/normlanguage/Norm/tree/main/norm/libraries/openai) 的 OpenAI 模块源码，其来源和许可证见 [SOURCE.md](dependencies/openai/SOURCE.md)。构建时使用的 Norm 工具链仍受 [Norm 的许可证与第三方声明](https://github.com/normlanguage/Norm/blob/main/LICENSING.md) 约束。贡献流程见 [CONTRIBUTING.md](CONTRIBUTING.md)。
