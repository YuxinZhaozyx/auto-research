# auto-research

> 用于自动化科研的可移植 agent skill 集合。

> ⚠️ **开发中** —— 技能、脚本与接口可能随时变动,恕不另行通知。

[English](README.md) | **简体中文**

---

## 项目简介

`auto-research` 是一个持续扩充的**可移植 agent skill(技能)集合**,用于自动化科研中繁琐的环节——检索论文、验证其是否真实存在、提取关键观点、综合撰写文献综述。每个技能都是一个自包含的指令文件加零依赖辅助脚本,可加载到 Claude Code 或任意兼容 harness 中。

目前包含:

- **`literature-review`** —— 一条「检索 → 验证 → 分析 → 综合」流水线。从 Zotero(MCP)、本地 PDF、Semantic Scholar、网络抓取候选,对每篇执行四层反幻觉检查,并将结构化综述写入 `REVIEW.md`。

更多技能正在规划中。

## 快速开始

```bash
git clone https://github.com/YuxinZhaozyx/auto-research.git
cd auto-research
cp .env.example .env   # 随后填入变量值(见下方「环境变量」)
```

需要 Python 3.9+ 及支持技能的 harness。将技能文件夹复制到 harness 的 skills 目录即可全局可用;否则保留在项目仓库内,会被自动识别。

## 环境变量

将 `.env.example` 复制为 `.env` 并填入变量值。各变量说明:

| 变量 | 是否必需 | 说明 |
|------|----------|------|
| `SEMANTIC_SCHOLAR_API_KEY` | 推荐 | Semantic Scholar API 密钥。[在此申请](https://www.semanticscholar.org/product/api),须以 `s2k-` 开头。用于 Semantic Scholar 检索与验证。若未设置,技能将降级为使用 WebSearch 工具检索文献。 |
| `CROSSREF_VERIFY_EMAIL` | 推荐 | 你的机构邮箱,放入 CrossRef 的 `User-Agent` 中。可降低被限流的概率。未设置则回退到占位值。 |
| `PYTHONIOENCODING` | — | `.env.example` 中固定为 `utf-8`;确保非 ASCII 元数据正确处理。请勿修改。 |
| `PYTHONUTF8` | — | `.env.example` 中固定为 `1`;启用 Python 的 UTF-8 模式。请勿修改。 |

## 使用方法

### `literature-review`

围绕某个主题完成检索、验证、分析与综述。

**工作原理。** 按优先级依次检索多个数据源,随后对每篇候选论文执行反幻觉检查,在任何分析之前滤除虚构引用。对通过的论文逐篇提取其问题、方法、结果与相关性;再按主题分组,梳理共识、分歧以及你可以填补的研究空白。未配置的数据源会被静默跳过,因此始终能优雅降级。

```
/literature-review "面向图像生成的扩散模型"
```

用 `— sources:` 指令限定数据源(默认 `all`):

| 数据源 | 覆盖范围 |
|--------|----------|
| `zotero` | 经 MCP 访问你的 Zotero 文献库(集合、标签、批注、BibTeX) |
| `local` | 项目 `literature/` 文件夹中的 PDF(每篇前 3 页) |
| `semantic-scholar` | 已发表会议/期刊论文(IEEE、ACM、Springer),含引用数与 TLDR |
| `web` | 跨学术来源的广覆盖网络检索 |

```
/literature-review "主题" — sources: zotero, local
/literature-review "主题" — sources: web, semantic-scholar
```

行内指定自定义本地 PDF 路径:

```
/literature-review "主题" — paper library: ~/my_papers/
```

**Zotero(可选)。** `zotero` 数据源需要一个 Zotero MCP server。安装一个(如社区版 `zotero-mcp` 包),在 harness 的 MCP 设置中注册,指向你的文献库——可连接本地 Zotero 应用(在 *编辑 → 首选项 → 高级 → 常规* 中勾选「允许本机其他应用与 Zotero 通信」),或使用 Zotero Web API 密钥。技能会在运行时自动探测可用的 Zotero 工具;若不存在,`zotero` 将被直接跳过,由其余数据源接管。

产出写入 `literature/summary/REVIEW.md` —— 文献表格 + 叙述性综述,可选 `references.bib`。每篇论文标注验证状态(`✅ verified` / `⚠️ UNVERIFIED` / `… VERIFY_PENDING`);未验证者绝不静默丢弃,便于你自行审计检索质量。

## 致谢

本项目的部分技能是在 [ARIS(Auto-claude-code-research-in-sleep)](https://github.com/wanshuiyin/Auto-claude-code-research-in-sleep)(作者 wanshuiyin)的基础上修改而来。完整归属信息见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。

## 许可证

[MIT License](LICENSE) —— © 2026 Yuxin Zhao (YuxinZhaozyx)。
