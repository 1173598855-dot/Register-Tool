# ADR-0015: Provider Pack Platform（多注册架构的独立维护单元）

- Status: Accepted
- Date: 2026-11-10
- Supersedes scope of: [ADR-0014](0014-provider-pack-foundation.md)（保留其"附加、不改行为"的原则，但没有定义生命周期、命名空间与边界执法）

## Context

ADR-0014 只订了"清单 + 懒适配器"。它回答了"怎么声明一个 provider"，没有回答
操作者真正需要的问题：

1. 一套新注册架构的代码放哪里？（包根被 `root_module_ratchet` 冻结，`packs/`
   是契约层，不该放实现）
2. 两套架构怎么互不影响？（配置键、运行目录、日志前缀）
3. 升级一套架构时，怎么只动这一套？（版本、钩子、自己的测试）
4. 怎么保证声明与代码不分家？（manifest 引用的函数被改名了，谁来报错）

## Decision

把 pack 提升为**架构的维护单元**，由四个机制支撑：

1. **manifest 版本化并带 API 门。** `provider-pack.v2` 增加 `api_version` 与
   `status`；`SUPPORTED_API_VERSIONS` 之外的清单一律拒绝加载，而不是"尽力解释"。
   v1 仍被接受并归一化，ADR-0014 写过的清单不会因为内核升级而失效。
2. **命名空间由 id 派生，不可声明。** `PackNamespaces.for_pack()` 生成
   `packs.<id>`（配置）、`packs/<id>`（存储）、`pack.<id>`（遥测）。派生消除了
   "声明写错"这一整类缺陷，也让两套架构在结构上不可能串味。
3. **实现落在 `sms_tool/platforms/<short>/`。** builtin pack 目录只允许 JSON，
   manifest 用 `module.path:attribute` 引用实现。这条同时解决了"代码去哪"与
   "声明与代码分家"两个问题：改名会让 `--pack-verify` 立刻失败。
4. **边界靠零基线棘轮执法。** `scripts/pack_boundary_ratchet.py` 检查 leaf
   契约（`packs/` 只 import stdlib）、内核不得 import builtin pack、builtin 只放
   数据、manifest 与目录一致。正确值是 0，所以不需要基线，新增违规立刻红灯。

生命周期钩子 `verify` / `doctor` / `migrate` / `upgrade` 是显式预留通道：pack
声明实现了哪些，`--pack-info` 把没实现的列成 `missing_hooks`，所以"预留"是
可读状态而不是口头承诺。

## Consequences

- 加一套架构 = 一条 `scripts/pack_new.py` + 填 `flow.py`；内核无改动。
- `--pack-list` / `--pack-info` / `--pack-verify` 成为运维入口，桌面端可经
  `--desktop-ipc` 拿同一份 JSON。
- `GPT_PACK_PATH` 提供仓库外开发/热修通道，builtin 永远先被搜索，发布构建不会
  因为操作者设了环境变量而看不到自带 pack。
- 现状不变：ChatGPT 的实现仍在 `registration/`、`accounts/`、`auth_flow/`，
  迁移按 [provider-packs.md](../current/provider-packs.md) 的 P2–P5 逐步进行，
  且 **P4（第二套架构落地）之前不搬代码**。
- `company` 级约束：`retryable` / `terminal` 只是观测词汇，处置仍归
  `registration/policy.py` 与 `failure_registry`，manifest 不承载重试策略。
