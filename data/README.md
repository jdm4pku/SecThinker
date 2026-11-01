# 安全代码生成数据集 Review 清单

工作区：`server3:/efs-exp/wamhyppyh/run_exp2`。先下载、保留版本和来源，再通过 Review 选择实验数据集。

| 数据集 | 子集 | 数量 | 状态 | 入口 |
| --- | --- | --- | --- | --- |
| CodeSecEval | SecEvalBase + SecEvalPlus | 115 + 140 = 255 | 已下载并静态校验；未运行测试或实验 | [中文 Review 说明](CodeSecEval/REVIEW_zh.md) |
| CodeGuard+ | 当前 base 快照 | 103（Python 71 / C 31 / C++ 1） | 已下载并静态校验；与 README 的91题口径不同 | [中文 Review 说明](CodeGuardPlus/REVIEW_zh.md) |

版本锁定见 `datasets.lock.json`。CodeSecEval 原始文件、官方数据卡和评测 notebook 位于 `CodeSecEval/`，任务目录位于 `CodeSecEval/review/task_index.csv`。

旧 H100 工件不会因为工作区切换而自动出现在此目录；当前已准备 CodeSecEval 和 CodeGuard+；尚未在 server3 准备 CWEval。
