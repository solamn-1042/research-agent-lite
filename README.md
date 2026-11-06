# 资料调研 Agent · Docker 入门版（Day 2）

这是2026-10-21开始的七天项目第二课。功能思路参考 [Local Deep Researcher](https://github.com/langchain-ai/local-deep-researcher)，本版本用LangGraph的显式State和条件边组织模型决策/工具执行循环。默认只读取五个官方文档站点，代码与测试均在Docker容器内运行。

## 启动与升级

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

输入：请阅读Docker官方资料，解释Compose怎样管理多个服务，给两条带原文定位的结论。

可能结果：search_web找到来源，read_web取得正文节选，finish_report提交包含已读来源ID和原文定位的短报告。首次搜索未取得资料时，模型可改词补查，最多再查两次。范围过宽时使用ask_user澄清。

引用格式和原文定位可由代码检查；结论是否受到证据支持仍须人工验收。个人RAG、报告保存、任务恢复和MCP将在后续加入。旧课已发不表示学习者已经完成。

## 文件说明

- app.py：网页、API开关、会话历史与执行记录。
- agent.py：ResearchState、decide/act图循环、结构化报告校验。
- agent_day1.py：保留的第一天执行器，用于运行原有回归测试。
- tools.py：搜索、按来源ID读取、追问、结束报告的工具契约；前两项在此执行。
- reader.py：精确域名与IP边界、HTTPS正文节选、内容版本。
- Dockerfile / compose.yaml：容器运行与持久化卷。
- docs/DAY1.md / docs/DAY2.md：两课完整教材，按最新DAY2.md升级；其指令避免覆盖.env和学习日志。
- docs/SEVEN_DAY_PLAN.md：七天路线、功能范围与最终验收。
- docs/INTERVIEW_CHECKLIST.md：能力问题、对应日期和证据清单。
- docs/VALIDATION_DAY2.md：40项工程测试及未验证项。
- tests：不调用付费API的工程测试。

API开关、研究State和会话报告暂存在进程内，重启后会清空；命名卷已配置，Day 4才实现任务与报告持久化。当前为个人本机应用，端口仅绑定127.0.0.1。详情、业务用例和独立练习见docs/DAY2.md。
