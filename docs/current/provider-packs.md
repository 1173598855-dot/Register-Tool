# Provider Packs: 多注册架构的平台契约

一个 **pack** 就是一套注册架构（平台）的完整可维护单元：端点、入口、能力、
失败词汇、生命周期钩子、以及从 id 派生的三个独立命名空间。加一套新架构 =
新增一个 `sms_tool/platforms/<short>/` 子包 + 一个 manifest，**不改内核、不碰
另一套架构**。

本文是平台契约与运维面。ChatGPT 是第一个 pack；它目前仍由既有模块实现，
manifest 通过 `module.path:attribute` 引用它们（见 [迁移路线](#迁移路线)）。

## 为什么要有这一层

在 pack 之前，每加一套注册架构都只有两种落点，两种都有代价：

- 往 `sms_tool/` 包根加模块 —— `scripts/root_module_ratchet.py` 直接拒绝，
  因为包根已经是"新模块的默认垃圾桶"；
- 往 `registration/` 里加分支 —— 阶段顺序、失败策略、代理泳道全部混在一起，
  `import_layer_ratchet` 的层方向也随之失效。

pack 层把"架构"变成**数据 + 一组被字符串引用的入口**：内核只认识 manifest，
不认识具体实现，因此两套架构在结构上不可能互相 import。

## 目录与预留通道

```text
sms_tool/packs/                     契约层（模块级只允许 stdlib）
  contracts.py                      PackManifest / RiskSignal / PackNamespaces / 能力词汇
  registry.py                       注册表 + LegacyProviderPack 懒解析
  loader.py                         发现：builtin + GPT_PACK_PATH 外部根
  admin.py                          只读运维面（list / info / verify）
  dispatch.py                       能力分派：能力名 → 可调用对象（无静默回退）
  builtin/<dir>/manifest.json       随仓库发布的 pack（**只放 JSON**）

sms_tool/platforms/<short>/         实现层（一套架构一个子包）
  flow.py                           被 manifest 引用的入口函数

tests/packs/                        平台契约测试 + 每个 pack 一个契约测试
docs/packs/<pack_id>.md             每个 pack 自己的运维/升级说明
```

| 通道 | 机制 | 状态 |
| --- | --- | --- |
| 外部 pack 根 | 环境变量 `GPT_PACK_PATH`（`os.pathsep` 分隔，builtin 永远先搜） | 已接通 |
| 能力命名空间 | `CAPABILITY_VOCABULARY` 闭集；`x-` 前缀留给厂商自研能力 | 已接通 |
| 配置命名空间 | `packs.<pack_id>` | 已派生，尚无 pack 使用 |
| 存储命名空间 | `runtime/packs/<pack_id>/` | 已派生，尚无 pack 使用 |
| 遥测命名空间 | `pack.<pack_id>` | 已派生，尚无 pack 使用 |
| 生命周期钩子 | `verify` / `doctor` / `migrate` / `upgrade` | `verify` 已实现；其余三个是显式空位 |
| 风险词汇 | `risk_signals`，与重试策略解耦 | 已接通 |

三个命名空间**由 id 派生而不是声明**：`PackNamespaces.for_pack()` 是唯一来源，
所以两套架构的配置键、目录、日志前缀不可能相撞，也没有可写错的字段。

## Manifest（`provider-pack.v2`）

| 字段 | 必填 | 说明 |
| --- | --- | --- |
| `schema` | 是 | `provider-pack.v2`；`provider-pack.v1`（ADR-0014）仍被接受并归一化 |
| `id` | 是 | 小写点分标识，如 `openai.chatgpt`；目录名必须是 id 或其最后一段 |
| `display_name` | 是 | `--pack-list` 展示名 |
| `version` | 是 | 语义化版本，架构自己的升级节奏 |
| `api_version` | v2 必填 | 写 manifest 时面向的平台 API；不在 `SUPPORTED_API_VERSIONS` 内直接拒绝 |
| `status` | v2 必填 | `active` / `experimental` / `deprecated` / `disabled`；`disabled` 不可被工作流解析 |
| `capabilities` | 是 | 必须是能力词汇表成员，或 `x-` 前缀扩展 |
| `endpoints` | 是 | HTTPS URL，禁止内嵌凭据（`user:pass@` 直接报错） |
| `entrypoints` | 是 | `module.path:attribute`，非空 |
| `hooks` | 否 | 仅允许 `LIFECYCLE_HOOKS` 中的键 |
| `risk_signals` | 否 | `code`/`category`/`retryable`/`terminal`；不得自相矛盾或重复 |

校验发生在**加载时**：一个能力名写错、一个端点带明文口令，都会在
`--pack-list` 时失败，而不是在注册到一半时失败。

## 运维面（独立入口）

```powershell
python -m sms_tool --pack-list                    # 所有 pack + 能力矩阵
python -m sms_tool --pack-info openai.chatgpt     # 单个 pack 的 manifest/命名空间/钩子
python -m sms_tool --pack-verify openai.chatgpt   # 解析每个入口与钩子
python -m sms_tool --pack-verify                  # 全部 pack
python -m sms_tool --pack-list --json             # 机器可读（也可 --desktop-ipc）
python -m sms_tool --pack acme.portal --quota-usage   # 指定由哪套架构跑这个能力
```

`--pack-verify` 是唯一会真正 import 的操作，因为"这个入口到底存不存在"无法从
manifest 读出。它**逐条报告**而不是抛异常：半坏的 pack 正是运维要发现的状态。
`--pack-info` 会列出 `missing_hooks`，即平台预留但该 pack 尚未实现的通道。

退出码沿用仓库约定：`0` 正常，`2` 前置/校验失败。

## 新增一套注册架构

```powershell
python scripts/pack_new.py --id acme.portal --display-name "Acme Portal"
python -m sms_tool --pack-verify acme.portal
python -m pytest -q tests/packs
```

生成器一次性写出五样东西，这就是那套架构的独立维护面：

| 产物 | 作用 |
| --- | --- |
| `sms_tool/platforms/acme_portal/flow.py` | 实现入口（`verify` 钩子 + `register_email`），初始 `NotImplementedError` |
| `sms_tool/packs/builtin/acme_portal/manifest.json` | `status: experimental`，端点占位使用 `.invalid` TLD |
| `tests/packs/test_acme_portal_pack.py` | 该架构自己的契约测试：入口是否还解析得到 |
| `docs/packs/acme.portal.md` | 端点/能力/命名空间/升级清单 |
| 文档索引行 | `docs/packs/README.md` 的表格 |

之后只改 `flow.py`；`--pack-verify` 是升级前后的固定检查点。`experimental` →
`active` 是一次显式编辑，不是默认值。

## 边界规则（可执行）

| 规则 | 执行者 |
| --- | --- |
| `sms_tool/packs/*.py` 模块级只 import stdlib 或包内相对 import | `scripts/pack_boundary_ratchet.py`（leaf contract） |
| 内核任何模块都不得 import `sms_tool.packs.builtin.*` | 同上 |
| `builtin/<dir>/` 只允许 `.json`；manifest 不得指向 builtin | 同上（layout + manifest contract） |
| 每个 builtin pack 一个合法 manifest，id 与目录一致且全局唯一 | 同上 |
| 一套架构的实现不得 import 另一套 | [目录职责](../directory-map.md) 边界说明 + 评审 |

这个棘轮**没有基线**：每条规则的正确值都是 0，所以新增违规立刻失败，清理
也不许改基线。它同时受 `tests/governance/test_pack_boundary_ratchet.py` 约束，
每条规则都用一棵一次性目录树的变异证明它真的会失败。

## 迁移路线

| 阶段 | 动作 | 行为变更 |
| --- | --- | --- |
| P0（已完成） | 冻基线：全量 pytest / dotnet / 结构闸绿 | 无 |
| P1（已完成） | manifest 契约 + 注册表 + 发现 + 运维面 + 脚手架 + 边界棘轮 | 无（ChatGPT 仍走原调用链） |
| P2（已接通 3 个消费点 + 选择器） | `account.health` 经 `dispatch` 注入到 `--quota-usage` / `--refresh-local-quota` / `--one-click-scan`；`--pack` + `GPT_PACK_ID` 解决多架构歧义 | 单能力，等价性有测试 |
| P3 | 把 `registration/` 的阶段体迁入 `platforms/chatgpt/`，manifest 改指向新位置 | 结构，行为不变 |
| P4 | 第二套架构落地，验证抽象（第一个 pack 不能证明通用性） | 新增架构 |
| P5 | 桌面端按 `capabilities` 渲染页面；CLI 加 `--provider <pack_id>` | UI/入口 |

**P4 之前不迁 ChatGPT 的代码。** 只有一个 pack 时，任何"通用工作流图"都是
按一个样本猜的抽象；`registration/policy.py`、`checkout_contract`、邮箱 OTP
契约目前都只有单个实现，尚未被证明平台无关。

## 能力分派（P2 的实际形状）

`dispatch.resolve_capability_entrypoint(capability, entrypoint)` 是"哪个 pack 拥有
这个能力、它的入口解析成什么"的唯一回答者。三条失败规则，全部**显式**：

| 情况 | 结果 |
| --- | --- |
| 没有启用的 pack 声明该能力 | `CapabilityDispatchError`，并提示跑 `--pack-list` |
| 多个 pack 声明且未指定 `pack_id` | 报错——按 id 顺序挑第一个是没人做过的路由决策 |
| 指定的 `pack_id` 并未声明该能力 | 报错，并列出实际声明者 |
| 能力名不在词汇表且不以 `x-` 开头 | 报错，并打印词汇表 |

**没有"找不到就回退到老函数"这条路径。** 静默回退会让坏 pack 与好 pack 无法区分，
这正是注册泳道在宽泛 `except` 上付过的代价。

### 多套架构声明同一能力时怎么选

选择顺序是固定的，且**只有一种明确来源**才会生效：

| 优先级 | 来源 | 说明 |
| --- | --- | --- |
| 1 | `--pack <PACK_ID>` | 命令行显式指定 |
| 2 | 环境变量 `GPT_PACK_ID` | 进程级默认；桌面宿主可像 `GPT_REGISTER_CONFIG_DIR` 一样下发给后端 |
| 3 | 唯一声明者 | 只有一套架构声明该能力时不需选择器 |
| 4 | 报错 | 多套声明且前两级都没给 ⇒ 报错并列出声明者 |

**永远不按 id 顺序取第一个**——那是没人做过的路由决策。默认值放在环境变量而不是
配置分片，是因为它选的是"这个进程跑哪套实现"，与 `GPT_REGISTER_CONFIG_DIR` /
`GPT_PACK_PATH` 同类；放进配置分片会连带牵动分片归属清单、C# `ConfigStore` 对等
检查和 config-key 棘轮。

### 已接通的能力

| 能力 | 入口 | 消费点 | 保证 |
| --- | --- | --- | --- |
| `account.health` | `account_liveness` | `--quota-usage`（单账号） | `tests/packs/test_capability_dispatch.py`：解析出的对象**就是**工作流原本直接 import 的那个函数（对象同一性） |
| `account.health` | `account_liveness` | `--refresh-local-quota` / `--quota-mode local`（批量，经 `_probe_liveness_with_retries`） | 注入测试：`probe_fn` 真的到达重试助手 |
| `account.health` | `account_liveness` | `--one-click-scan`（批量扫描） | 注入测试：每个账号的 `_scan_one` 都拿到注入的 callable |

三个消费点的 `probe_fn` 默认仍是直接 import，所以既有调用方与既有测试一个都不变。
注入走显式关键字：**没有新增任何跨目录 import 边**（`import-layer` 仍是 473 边 /
78 对，`delayed` 仍是 473/362），这是刻意的——批处理所在的
`sms_tool/accounts -> sms_tool` 预算已顶死 36 条，用 `importlib` 绕静态图属于骗门禁。

### 这条路上的一处结构约束（需要决策）

`scripts/import_layer_ratchet.py` 按 `(源目录, 目标目录)` 冻结 import 语句**条数**，
只许降不许升。`sms_tool/accounts -> sms_tool` 已是 36 条，因此
**无法**在 `accounts/` 里新增一条 `from ..packs import …`。所以 P2 的分派点在
`cli.py`（包根，与 `packs` 同目录，不计边），再由既有注入缝把 callable 递进去。

要把 `account_scan` / `recovery_batch` 这些批处理消费点也接上，需要先做一个决策：
要么把 `packs` 提升为独立目录节点并接受新的一对边（`ordered_pairs` 78 → 79），
要么继续走"命令层解析 + 注入"。两者都不是零成本，所以留给显式评审，而不是
偷偷用 `importlib` 绕开静态图。

## 每套架构的 A/B 开关往哪记

`scripts/experiment_ledger.json` 的扁平 `toggles` 是注册泳道的 `registration.*` 开关，
第二套架构的开关不是 `registration.*` 键，塞进同一张表就等于假装一个平台的实验是另一
个平台的。所以台账有第二个区：

```text
packs.<pack_id>.toggles.<key> = {kind, default, status, doc, [id], [verdict], [expires]}
```

`scripts/experiment_ratchet.py` 对这一段能证明两件事，并明确声明它**证明不了**第三件：

| 检查 | 结果 |
| --- | --- |
| pack id 必须是随仓库发布的 pack | 已退役架构的条目会失败，而不是留着没人管 |
| 决策必须完整（kind/status/default、ab 的 hypothesis id、concluded 的 verdict、open 的到期日、`doc` 必须存在） | 失败即红 |
| 同一个 hypothesis id 不得被两套架构共用 | 失败即红（与注册泳道共享同一张 id 表） |
| **代码确实读了这个开关** | **证明不了**：目前没有 pack 作用域的 flag reader。因此 `retired` 在这里被直接拒绝——没人读的键没有什么可"退役"的，记一个不可验证的状态比不记更糟 |

### pack 作用域的配置读取（2026-11-11 落地）

读者**不在** `sms_tool/kernel/flags.py`，也不在命令层自己算——它放在 `packs/admin.py`，
理由有两条，都是被仓库自己的规则逼出来的：

| 约束 | 结论 |
| --- | --- |
| `pack_boundary_ratchet` 规则 1：该包只许导入标准库 | reader 必须只用 stdlib 实现；`from ..kernel.flags import ...` 会逃出包边界（零基线，不改） |
| `import_layer_ratchet`：`sms_tool -> sms_tool/kernel` 已顶死 35 条 | 从命令层导 kernel 要 +1 条边 → 直接红。实测过，见下 |

| 层 | 谁做什么 |
| --- | --- |
| `packs/admin.py::pack_configured_toggles(config, pack_id)` | 唯一的 reader：逐层 `Mapping` 守卫（生产配置把每个 section 冻成 `mappingproxy`，`dict` 判断在真实运行里会静默读默认值）。**pack id 当一个键用，不按点号拆**——id 自己带点（`openai.chatgpt`），split 回来分不清 section 和 key |
| `packs/admin.py::pack_detail(..., config=)` | 命名空间本来就由这个函数报告（`namespaces.config == "packs.<id>"`），所以"这套架构现在配了什么"归它答。`config=None`（没查）与 `{}`（查了、什么都没配）是两种不同事实，所以 `None` 时不出现该键 |
| `cli.py` | `--pack-info` 把 `CFG` 传进去。**一行，零新增 import 边** |

所以 `--pack-info <id> --json` 现在多一个 `configured_toggles` 字段。

**过程中的两次修正（都留在这里，省下后来人重走）**：

1. 先写成 `kernel/flags.py::dotted_value("packs.openai.chatgpt.x")` —— **点号路径表达不了 pack id**，
   已有的 10 例测试当场红，改成按 segment 传参；
2. 改成 kernel reader + 命令层函数内导入后，`delayed_import_ratchet` 报 `statement count 474 > 473`。
   于是整段回退，reader 落到 `packs/admin.py`（纯 stdlib）——**两条棘轮基线一分未动**。

读者有了、也有生产调用方，但**台账那条"代码确实读了"仍然没有闭环**：要证明它，需要一个
**台账里声明的** pack 开关被代码按名字读（`retired` 才算可证）。现在台账 `packs` 段是空的，
那一步等 P3 第二套架构带来第一个真实开关。这条状态差异写在方案 Phase 2.6 里。

等某套架构真的落地一个 reader，这条检查就补上注册泳道已有的 code↔ledger 双向校验。

## 刻意不做的事

- **不引入插件热重载。** 发现发生在进程启动，manifest 变化=重启后端；热重载
  会把"配置/代码版本错配"变成运行期随机故障。
- **不引入 manifest 签名。** 外部 pack 根是可执行代码的可信边界（
  `GPT_PACK_PATH` 由操作者设置），签名在没有分发渠道前是装饰。
- **不把 `packs/` 做成可写目录。** builtin 只放数据；实现一律在 `platforms/`，
  否则"这个 pack 到底是声明还是代码"每次都要重新回答。
- **不让 manifest 承载重试策略。** `retryable`/`terminal` 是观测分类，处置仍在
  `registration/policy.py` 与 `failure_registry`；否则每个 pack 会长出一套
  自己的重试语义。
