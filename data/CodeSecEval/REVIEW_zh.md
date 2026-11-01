# CodeSecEval 下载与 Review 说明

下载日期：2026-10-19。论文：Toward Secure Code Generation: Bridging Correctness and Security via Task-Adaptive Vulnerability Modeling and Execution-Based Benchmarking。SecAwareCoder 是论文的方法名称，CodeSecEval 是对应基准名称。

## 官方来源与版本

- 数据：https://huggingface.co/datasets/JasonWang1/CodeSecEval
- 作者仓库：https://github.com/CY-SCUT-MS/CodeSecEval
- 固定 revision：`c3ffce09269f2d7b092888efe05d070b6fcb97f5`。
- 官方文件按原目录和原字节保存；根目录 `README.md` 为官方原件。`provenance/`、`review/` 和本说明为本项目补充。
- server3 直连 Hugging Face 网络不可达，本次通过本机内存转发官方 HTTPS 文件后写入服务器；未在本机保存数据集副本。每个文件已核对官方 Git blob OID、传输前后 SHA-256 和大小。

## 两个子集

| 子集 | 任务数 | 来源与输入特点 | 原始文件 |
| --- | --- | --- | --- |
| SecEvalBase | 115 | 从 SecurityEval 扩展，补充安全参考实现和可执行测试；含代码骨架与注释形式的需求 | `data/SecEvalBase/test.jsonl` |
| SecEvalPlus | 140 | 新增任务，侧重高影响 CWE，主要为自然语言需求 | `data/SecEvalPlus/test.jsonl` |
| 合计 | 255 | Python 任务；官方 CodeSecEval 配置加载这两个文件的合集 | 不另造重复合集 |

两者是来源不同的子集，不是 train/test 划分；官方均使用 `test` split。

## 每题字段

| 字段 | 含义 |
| --- | --- |
| ID | 任务标识，通常含 CWE 编号 |
| Problem | 原始需求或代码形式的提示 |
| Insecure Code | 不安全实现，可用于修复任务 |
| Secure Code | 安全参考实现 |
| Test | 官方完整可执行测试 |
| Test-FP | 辅助功能测试 |
| Test-SP | 辅助安全测试 |
| Entry_Point | 目标函数入口名 |

## 本次校验与后续 Review

- 两个 JSONL 可解析，条数为 115 和 140；255 个 ID 全局唯一，8 个字段均为非空字符串。
- 官方说明称覆盖 77 类 CWE。按当前 ID 中 CWE 数字去掉前导零统计，Base 为66类、Plus 为17类、合并为73类（提取每个 ID 中的全部 CWE 标签）；这是两种统计口径的差异记录，尚未解释其成因。
- 本次仅下载和静态检查，没有执行数据集代码、参考实现、测试或模型实验，不将字段齐全视为测试正确性证据。
- Review 时分别看需求清晰度、上下文是否足够、合法功能边界、参考实现与测试一致性，以及 Test-FP / Test-SP 是否适合分项评价。
- 原始 ID 及部分 Problem 路径可能含 CWE 标签。正式模型输入协议仍待确定；参考代码和测试属于评价工件，不能因准备数据而默认输入模型。
- 当前官方数据卡的许可证状态为 under review；作者 GitHub 仓库许可证不自动等同于数据集许可证。
- 旧 H100 已有部分样例的人工分析记录；本次重新下载不意味着这些样例是未接触过的测试题。

完整任务目录：`review/task_index.csv`，包含子集、ID、从 ID 提取的 CWE、函数入口和原始 Problem。原始代码和测试仍在 JSONL 中。

## 离线读取

无须安装 datasets 库，Python 标准库即可读取：

```python
import json
from pathlib import Path
root = Path('/efs-exp/wamhyppyh/run_exp2/data/CodeSecEval')
base = [json.loads(s) for s in (root / 'data/SecEvalBase/test.jsonl').read_text().splitlines() if s.strip()]
plus = [json.loads(s) for s in (root / 'data/SecEvalPlus/test.jsonl').read_text().splitlines() if s.strip()]
print(len(base), len(plus))  # 115 140
print(plus[0]['Problem'])
```

重复静态校验：

```sh
python3 /efs-exp/wamhyppyh/run_exp2/data/CodeSecEval/provenance/validate.py
```

可执行测试的原始 notebook 位于 `notebooks/Compute_SecureCode_Pass_Rates_CodeSecEval.ipynb`；本次只保存，未运行。

## 全量中文需求阅读页

`review/CodeSecEval_255条需求_中文审阅.html` 覆盖全部255条 Problem，提供中文需求、原始英文、原始示例、子集筛选和个人审阅备注。译文不增加安全要求。

结构化译文：`review/requirements_zh.jsonl`；翻译与页面校验：`review/translation_audit.json`；重建脚本：`../../src/review/build_codesec_requirements_reader.py`（从本数据集目录出发）。

统计更正：此前71类的计算仅取了每个 ID 的首个 CWE；部分 ID 含多个 CWE，提取全部标签并归一化后为73类。官方77类的口径差异仍保留待查。
