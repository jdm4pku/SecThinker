# CodeGuard+ 下载与 Review 说明

下载日期：2026-10-19。对应论文：Constrained Decoding for Secure Code Generation。

## 来源与版本

- 官方仓库：https://github.com/CodeGuardPlus/CodeGuardPlus
- 官方主页：https://codeguardplus.github.io/
- 固定提交：`0528ee9e527fa57b9a1c82c564beb854f1881fd5`。
- 完整保存当前提交的524个仓库文件，包括数据、功能测试、查询文件、评价代码、依赖清单及原始许可证；没有执行仓库代码或安装依赖。
- 通过本机内存转发官方 GitHub 归档到 server3；每个文件与官方 Git tree blob OID 一致，传输后 SHA-256 校验通过。数据和代码仅保存于远端目录。

## 当前下载快照的实际范围

| 项目 | 数量 |
| --- | ---: |
| 按 `data/base/**/info.json` 统计的任务 | 103 |
| Python | 71 |
| C | 31 |
| C++ | 1 |
| 任务元数据中的不同 CWE | 42 |
| 配套 `unit_test/.../functional.py` | 103 |

官方 README / 主页写的是91个提示、34类CWE；当前仓库快照实际为103个任务、42类CWE。本次完整保存当前公开快照，没有自行筛选成论文的91题。后续复现实验需明确采用哪个版本和任务集合。

当前只发布 `data/base`，README 中提到的 `data/perturbed` 仍不存在，不能当作已下载的第二子集。

## 任务结构

每个任务通常包含：

- `data/base/<cwe>/<scenario>/info.json`：语言、CWE、场景及安全查询配置。
- `file_context.py/.c/.cpp`：文件级代码上下文。
- `func_context.py/.c/.cpp`：函数级代码前缀与说明。
- `unit_test/<cwe>/<scenario>/functional.py`：功能测试，部分任务还附测试辅助文件。

官方生成脚本读取并组合文件级和函数级上下文。因此这是带代码上下文的补全基准，不能直接视为统一的纯自然语言需求集合。完整任务目录在 `review/task_index.csv`。

## 评价与下载边界

- 功能评价通过单元测试；安全评价使用 CodeQL / SonarQube 等静态分析，和 CodeSecEval 的执行式安全断言并非同一种判据。
- 85条任务的 `check_ql` 引用外部 CodeQL 路径，9条为其他或本地路径，9条为 null。完整运行仍需依据原始脚本配置工具和适用任务；本次没有把 null 自动判定为缺失安全能力。
- 文件完整性检查、任务上下文与配套功能测试路径检查均通过；这些结果不等同于测试已经跑通。
- 本次没有下载大型 CodeQL CLI、安装 SonarQube 或启动服务，也未调用模型。

原始 README、LICENSE 均保持原样。原始下载记录在 `provenance/download_manifest.json`；统计在 `provenance/validation.json`。
