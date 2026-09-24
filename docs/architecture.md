# 实现边界

| 组件 | 单一实现入口 |
| --- | --- |
| CLI 与初始化输入 | [application.norm](../gait/application.norm)、[console.norm](../gait/console.norm) |
| 模型与工具循环 | [agent.norm](../gait/agent.norm) |
| Agent 行为指令 | [instructions.norm](../gait/instructions.norm) |
| 本次调用的上下文压缩 | [context.norm](../gait/context.norm) |
| 文件快照与分页读取 | [files.norm](../gait/files.norm) |
| 单文件定向总结子工具 | [summarize.norm](../gait/summarize.norm) |
| 工具注册与严格参数解码 | [tools.norm](../gait/tools.norm) |
| Git 调用及状态观察 | [git.norm](../gait/git.norm) |
| Git 前置检查和写后验证 | [executor.norm](../gait/executor.norm) |
| 工具结果 | [result.norm](../gait/result.norm) |
| 用户配置 | [config.norm](../gait/config.norm)、[configure.norm](../gait/configure.norm)、[initialize.norm](../gait/initialize.norm) |
| 构建依赖 | [module.norm](../gait/module.norm) |

协议适配与 SSE 解码统一在 [OpenAI 模块](https://github.com/normlanguage/openai)，支持 Responses 与 Chat Completions。Agent 使用统一的 Response 和 FunctionCall；Chat 的消息、工具增量和 reasoning_content 由客户端转换。这些上下文只存在于本次调用内，不落盘，不使用服务端历史 ID。工具只从正式协议字段取得，串行执行。

协议依据：[Responses function calling](https://developers.openai.com/api/docs/guides/function-calling)、[MiMo Chat Completions](https://mimo.mi.com/docs/en-US/api/chat/openai-api)。

产品契约见 [contract.md](contract.md)，使用入口见 [README](../README.md)。
