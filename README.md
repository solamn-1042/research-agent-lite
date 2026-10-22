# 资料调研 Agent · Docker 入门版

这是2026-10-21开始的七天项目基线。功能思路参考 [Local Deep Researcher](https://github.com/langchain-ai/local-deep-researcher)，按自己的代码逐步学习模型调用、搜索、原文证据、RAG、状态、MCP与评测。

## 第一天启动

本机准备Docker Desktop并使用Linux容器；不需要在宿主机安装Python、Conda或依赖库。将本目录放在D:\Study\CodeSoft\MyProject\research-agent-lite，用PowerShell进入本目录。

```powershell
docker version
docker compose version
```

首次将.env.example复制为.env，用编辑器填写自己的DeepSeek密钥。模型默认deepseek-flash，可按自己账号实际可用模型调整。密钥按.env注入容器，不打包到镜像。

```powershell
if (!(Test-Path .env)) { Copy-Item .env.example .env }
notepad .env
docker compose config --quiet
docker compose up --build -d
docker compose ps
```

打开 http://127.0.0.1:8501 ，勾选左侧API开关后输入研究问题。请求会调用DeepSeek并产生Token费用；公开搜索不需要额外API密钥，但可受到网络或限流影响。

```powershell
docker compose exec researcher python -m unittest discover -s tests -v
docker compose logs --tail=50 researcher
```

所有Python命令都在容器内执行。依赖更改后重新执行docker compose up --build -d；只改Python代码后可执行docker compose restart researcher并刷新网页。停止使用docker compose down；该命令保留命名卷。不要在常规操作中加入-v，后续课程的数据将存放于research_data卷。

## 业务用法

输入：帮我找3份MCP工具调用的官方入门资料，优先modelcontextprotocol.io。

可能结果：出现工具实际搜索到的标题、链接和来源ID，标注“仅搜索摘要，待阅读全文核实”；找到不足3条时如实显示实际数量。

第一天只定位待阅读来源。完整报告、笔记知识库、任务恢复和MCP将在同一项目逐日加入。

## 文件说明

- app.py：网页、API开关、会话历史与执行记录。
- agent.py：有调用/时间预算的工具循环。
- tools.py：搜索Schema、参数校验、公开来源整理。
- Dockerfile / compose.yaml：容器运行与持久化卷。
- docs/DAY1.md：第一天完整教材、命令解释、业务输入输出与面试训练。
- docs/SEVEN_DAY_PLAN.md：七天路线、功能范围与最终验收。
- docs/INTERVIEW_CHECKLIST.md：能力问题、对应日期和证据清单。
- docs/VALIDATION.md：教材已验证和待验证的实际边界。
- tests：不调用付费API的工程测试。

API开关和页面会话历史暂存在进程内，重启后会清空；命名卷已配置，Day 4才实现任务与报告持久化。当前为个人本机应用，端口仅绑定127.0.0.1。
