# Code-Asterism

> 通过 AST 解析和 PageRank 排序，为 AI 编程工具生成精简的代码库地图

## 致谢

Code-Asterism 基于 [Aider](https://github.com/Aider-AI/aider) 的 RepoMap 核心能力改造而来。Aider 是一款优秀的 AI 结对编程工具，本项目的 AST 解析、PageRank 排序等核心算法均源自 Aider。

## 为什么需要 Code-Asterism

国内企业在私有化部署场景上有着独特的困境：需要自购 GPU 集群并自行运维，在满足高并发的条件下还要兼顾长上下文，资源极为紧张，实际可用的上下文窗口往往只有 32K~64K。

更关键的是，企业内部的主要场景不是从零构建新项目，而是维护大量**存量工程**——这些仓库往往文档缺失、维护不足，AI 工具需要在陌生代码库上快速理解业务逻辑，才能完成新功能开发和 Bug 修复。

然而，目前主流的 AI 编程工具（Claude Code、Cline 等）默认采用 Grep 方案获取代码上下文。在没有全局视野的情况下，面对语义化的开发任务，很容易陷入**重复搜索、定位失败、再搜索**的试错循环——不仅浪费开发人员时间，还持续消耗宝贵的上下文和 token。

这些企业正处于**弱模型、强工具**的阶段——开源工具可以轻松 fork 部署，但模型能力需要重资产投入。因此，通过工具层面的优化来弥补模型能力的不足，是最务实的路径。

Code-Asterism 正是为此而生：通过 AST 解析提取代码结构，再经 PageRank 排序识别最重要的符号和依赖关系，用几千 token 就能为 AI 提供整个代码库的全局视野。Code-Asterism 将 Aider 的 RepoMap 能力独立抽离，可生成地图文件供任何 AI 编程工具使用，让存量工程的维护不再"两眼一抹黑"。

## 安装

```bash
pip install code-asterism
```

## 使用

```bash
# 在代码库目录下运行，默认输出到 code-asterism.md
asterism

# 指定输出文件
asterism my-repo-map.md

# 控制 token 预算（适配不同上下文窗口）
asterism --map-tokens 2048

# 仅分析当前子目录
asterism --subtree-only

# 查看完整帮助
asterism --help
```

## 功能特性

- **AST 解析** — 基于 tree-sitter 精确分析语法结构，支持 30+ 种编程语言
- **PageRank 排序** — 通过图排序算法识别代码库中最重要的符号和依赖关系
- **Token 预算控制** — 可精确控制输出大小，适配不同上下文窗口
- **Git 集成** — 自动识别 Git 仓库，分析 tracked 文件
- **灵活过滤** — 支持 `.asterismignore` 文件和 `--subtree-only` 控制分析范围

## 命令行参数

```
asterism [REPO_MAP_FILE] [OPTIONS]

RepoMap 输出设置:
  REPO_MAP_FILE              生成的 RepoMap 文件路径（默认：code-asterism.md）
  --verbose                  启用详细输出
  --model MODEL              指定模型以匹配 tokenizer（默认 gpt-4o 的 o200k_base）
  --map-tokens MAP_TOKENS    token 数量上限（默认 4096）

RepoMap 分析范围:
  --subtree-only             仅分析当前子目录
  --add-gitignore-files      将 .gitignore 中的文件纳入分析范围
  --asterismignore FILE      忽略规则文件（默认 .asterismignore）
```

## 许可证

[Apache License 2.0](LICENSE.txt) — 本项目基于 Aider 改造，遵循原作者许可协议。
