# SecThinker：INDICT / AutoSafeCoder 实验交接

本仓库是复现实验交接快照，包含代码、固定数据、依赖清单和配置；不包含模型权重、虚拟环境、服务器凭据和历史实验输出。生成模型为 Qwen3.8-27B，合作者自行准备模型服务。这里的模型名是现有服务标识，复现实验时还需记录实际权重来源、revision 和推理后端版本。

## 任务与交付

1. 接通 INDICT，在 CodeSecEval 和 CodeGuard+ 上运行并评测。
2. 接通 AutoSafeCoder，在 CodeSecEval 和 CodeGuard+ 受支持的 Python 子集上运行并评测。
3. 提交完整配置、运行命令、逐题代码与调用记录、逐题 F/S/Joint、汇总结果、失败原因和方法改动说明。

这是从实验服务器提取并调整路径的研究代码，**不是已经在全新机器验证过的一键安装包**。本次验证了语法、任务加载、配置读取和覆盖范围，没有运行新的模型实验或完整评测。运行前先完成下述评测基础设施准备。

## 固定数据与指标

| 数据 | 样本数 | AutoSafeCoder 覆盖 |
|---|---:|---:|
| CodeSecEval | 255（Base 115 + Plus 140） | 255 Python |
| CodeGuard+ | 103（Python 71 / C 31 / C++ 1） | 71 Python，32 不支持 |

数据位于 `data/`，来源和版本见 `data/datasets.lock.json`、各数据集的 `provenance/` 和 README。由于上游公开样本含疑似 API key，交接版将该字符串改为 `REDACTED_PUBLIC_DATASET_API_KEY`；原始来源清单不代表脱敏后的哈希，改动记录见 `docs/packaging-changes.json`。CodeGuard+ 中生成测试密钥的测试代码保留原样。

F 为功能通过，S 为安全通过，Joint 为同一道题同时满足 F 与 S，不能用两个比率相乘。CodeSecEval 使用 Test-FP / Test-SP；CodeGuard+ 使用功能测试和现有 CodeQL / Sonar 检查。统一入口为 `src/table2_baselines/evaluate.py`。工具错误/超时不得当成安全通过；保留未知状态及失败原因。报告指标分母、eligible/unsupported 和评测完成数。AutoSafeCoder 的 Python 子集结果不能直接称作 CodeGuard+ 全量成绩；跨方法比较时另报共同 Python 子集。

## 安装与检查

推荐 Linux x86_64、Python 3.10。依赖清单足以重建 Python 环境，无需传输已安装环境。

```bash
bash bin/setup_indict.sh
bash bin/setup_autosafecoder.sh
export PYTHONPATH="$PWD/src"
python3.10 -m table2_baselines.cli inspect
python3.10 -m table2_baselines.cli prepare
```

`prepare` 只生成任务计划，不调用模型。官方源代码在 `baseline/`，兼容代码在 `src/autosafecoder_prepared/`，统一适配器在 `src/table2_baselines/`。不要直接运行上游 main 脚本绕过项目隔离执行器。历史 `services/*/validate.py` 有服务器快照校验要求；打包后的路径/脱敏变化可能使旧哈希校验失败，不能据此声称新机器已验证通过。

## 必须在新机器准备的运行组件

- OpenAI-compatible 模型服务；按实际部署填写 model、base_url、api_key_env。密钥只通过环境变量提供。
- `envs/benchmark-rootfs`：Linux 隔离执行根目录、Python 测试依赖、C/C++ 编译工具；`runs/_setup/prompt_baselines/rootfs_static_manifest.json`：对应文件 SHA256 清单。
- `src/table2_baselines/jail.py` 使用 chroot、降权、seccomp 和资源限制；需要匹配的 Linux 权限配置。不要改成在宿主机直接 exec 生成代码。
- rootfs 和清单准备后运行 `python3.10 services/table2/prepare_runtime.py` 创建私有执行镜像。
- CodeGuard+ 安全评测需要 CodeQL、对应查询包、SonarQube、Sonar scanner 和 JDK。现有路径位于 `tools/prompt_eval/`；自定义查询已提供，二进制自行安装。查看 `src/prompt_baselines/codeguard.py` 和 `start_sonar.py` 的路径/服务配置。`libefs_lock_compat.so` 的源码在 `src/prompt_baselines/efs_blocking_lock_compat.c`，如不使用 EFS 需明确记录兼容配置调整。

本仓库不附带上述 rootfs 和大型工具，也不含完整的自动重建脚本；合作者需要完成这些接入后才可生成正式指标。先通过合成正反例和少量样本验证，再运行全量。

## 模型配置与运行

`config/table2/runtime.json` 默认关闭正式运行。AutoSafeCoder 示例为 `config/table2/autosafecoder_prefix_v2_gpu03_20261101.json`，文件名沿用历史实验命名，端口只是示例，需改为自己的服务。该配置全部模型角色使用 Qwen3.8-27B，n=1、temperature=0、top_p=1、seed=42、max_tokens=8192、关闭原生 thinking；120 次变异，静态/动态阶段各最多 4 次修复。

完成基础设施预检后：

```bash
bash bin/table2.sh generate --method autosafecoder --dataset codesec_eval \
  --config config/table2/autosafecoder_prefix_v2_gpu03_20261101.json --auto-evaluate
bash bin/table2.sh generate --method autosafecoder --dataset codeguard_plus \
  --config config/table2/autosafecoder_prefix_v2_gpu03_20261101.json --auto-evaluate
# 续跑必须指定原输出目录，避免另建批次；配置也必须保持一致。
bash bin/table2.sh generate --method autosafecoder --dataset codesec_eval \
  --config config/table2/autosafecoder_prefix_v2_gpu03_20261101.json --output output/原目录 --auto-evaluate
bash bin/table2.sh summarize --output output/原目录
```

INDICT 在 runtime.json 填写 generation / critic / search 三个角色、搜索服务和预算，通过真实搜索探测后才启用 live_search_enabled 与 formal_experiments_enabled。generation 使用 Qwen3.8-27B；critic 和 search 的选择需明确记录，不要默认认为所有角色已经确定。命令格式同上，将 method 改为 indict，并选择对应配置。

## 方法差异与未完成项

- INDICT 固定官方提交 `83655faaa833c77ceb19644415f6a57e4e735a71`。此前 Yahoo/Wikipedia 与搜索辅助模型可用性存在障碍，尚不能称为已完成复现。当前配置最多 3 轮，已有记录注明论文最多 5 轮，需统一协议。Python 有执行后反馈，C/C++ 只有 preemptive 反馈。禁止用空检索冒充完整方法。
- AutoSafeCoder 固定提交 `62895d8325cffd73040fa5ced8594cb00f75d063`。使用作者 LLM 静态审查路径，非静默替换成 Bandit；代码 120 次 fuzz 与论文记录的 150 次有差异。兼容副本修正了 main 未触发造成假通过、异常传播、变异参数和失败样本重测等问题，详见 `downloads/AutoSafeCoder/compatibility-changes.json`。运行时进一步由适配器接入隔离执行。该结果应标记为 Qwen 适配实现。
- 不向生成或修复流程提供 benchmark 测试答案。方法自己的 fuzz 通过不等于 benchmark 功能通过。

上游代码和数据保留各自版权、许可证及来源说明；本交接仓库不重新许可第三方内容。
