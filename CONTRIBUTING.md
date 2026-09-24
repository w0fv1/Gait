# 贡献指南

欢迎报告问题和提交改进。提交问题时请说明操作系统、Python 与 JDK 版本、所用 Norm 版本或提交、复现步骤，以及预期和实际结果。请先移除日志、命令和截图中的 API 密钥、私人仓库内容与其他敏感信息。

## 开发环境

需要 Git、Python、JDK 25 和 [Norm](https://github.com/normlanguage/Norm) 源码。把 Norm 放在本仓库同级目录，或设置 `NORM_HOME`。使用与 `dependencies.lock.json` 匹配的 Norm 源码；`python scripts/manage.py prepare` 会校验指纹。先在 Norm 工作区用 Maven wrapper 构建运行时（Windows：`.\mvnw.cmd -DskipTests package`；其他系统：`./mvnw -DskipTests package`），然后在本仓库执行：

```powershell
python scripts/manage.py prepare
python scripts/manage.py build
$env:GAIT_EXECUTABLE = (Resolve-Path .\dist\gait.exe).Path
python -m unittest discover -s tests -v
```

如需运行 Windows 控制台相关测试，安装 `pip install -r tests/requirements-windows.txt`。测试使用本地模拟接口，不需要真实 API 密钥。

## 提交改动

让每个提交聚焦一个主题，并在更改行为时更新相关测试和文档。提交前确认 `git status` 只包含预期文件，且没有配置文件、密钥、构建产物或测试临时数据。通过 GitHub Pull Request 提交，并说明改动目的及验证方式。
