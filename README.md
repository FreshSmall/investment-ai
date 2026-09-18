# AI投资系统
investment-ai

个人 AI 投资研究系统：数据采集 → 清洗去重 → AI 分类分级 → 深度分析 → Obsidian 知识沉淀 → Daily Review。

文档：[docs/feasibility-analysis.md](docs/feasibility-analysis.md) · [docs/architecture.md](docs/architecture.md) · [docs/implementation-plan.md](docs/implementation-plan.md)

## 快速开始

```bash
uv venv && uv pip install -e ".[dev]"
cp .env.example .env   # 填入 DB / LLM 凭证
alembic upgrade head   # 建表（库需先存在）
python main.py daily --providers mock   # mock 全链路
```
