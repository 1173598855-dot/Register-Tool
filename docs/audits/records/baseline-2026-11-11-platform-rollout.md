# 平台化改造基线快照（2026-11-11）

对应方案：`docs/audits/plans/plan-2026-11-10-platform-rollout.md` 的 **Phase 0.3**。
这份文件的用途只有一个：**让后面每一个数字都能被对比**。所以每一行都给出可复现命令，
而不是只写一个当时的值。

起点：`83b59e8`（Phase 0 之前最后一版 fork/main）。本文件落盘时：`main` 见文末。

---

## 1. 结构基线（棘轮冻结的判据）

| 指标 | 起点 | 现在 | 复现命令 |
| --- | --- | --- | --- |
| `import-layer` 模块级边 / 目录对 | 473 / 78 | **459 / 78** | `python scripts/import_layer_ratchet.py` |
| ↳ 其中 mutual / minority / delayed | 17 / 46 / 307 | 17 / 45 / 307 | 同上 |
| `delayed-import` statements / edges | 473 / 362 | 473 / 362 | `python scripts/delayed_import_ratchet.py` |
| ↳ 分类 | cycle 8 / startup 105 / provider 37 / deferred 212 | 同 | 同上 |
| `function-length` 冻结函数 | 64 | 64（0 可收紧） | `python scripts/function_length_ratchet.py` |
| `bare-print` | 478 | 478 | `python scripts/bare_print_ratchet.py` |
| `module coverage` | 336 / 336，43 组 | 336 / 336，43 组 | `python scripts/module_coverage_check.py` |
| `root-module` 包根模块 | 79 | 79（新增 10 组职责分类） | `python scripts/root_module_ratchet.py` |
| `entry-point` 声明入口 | 9 | 9 | `python scripts/entry_point_ratchet.py` |
| `provider-decoupling` 同名 def | 271（237 委派 / 0 相同 / 34 分歧） | 同 | `python scripts/provider_decoupling_ratchet.py` |
| `pack-boundary` 违规 | 0（4 条规则） | 0 | `python scripts/pack_boundary_ratchet.py` |
| `kernel-boundary` 叶子模块 | 10 | 10 | `python scripts/kernel_boundary_ratchet.py` |
| `sunk-copy` 配对 | 3 对一致 | 3 对一致 | `python scripts/sunk_copy_parity.py` |
| `payment-legacy` 冻结文件 | 22 | 22 | `python scripts/payment_legacy_manifest.py` |

`import-layer` 的两处变化都是**只减不增**，两处都来自删死导入：

1. 473 → 472：`registration/outcome.py` 里一条从未被读取的
   `from ..kernel.error_classification import classify_error`；
2. 472 → 471（minority 46 → 45）：`cli.py` 里一条从未被使用的
   `from .registration_drivers.base import driver_choices` —— 真正的消费方是
   `cli_parsers/core.py`，它自己直接导入；
3. 471 → 465 → 459：`pay_link` 五个 legacy 分片（`adapters`/`base`/`registry`，随后
   `normalize`/`persistence`）里，拆分前主模块留下的 `payment.catalog` /
   `payment.operation` / `payment.routing` 死引用被删掉 —— 十二条 legacy shell →
   `payment.*` 的边随之消失（`pairs` 与 `minority` 均不变）。

理由都写在 `tests/governance/test_import_layer_ratchet.py` 的固定数字注释里。

## 2. 技术债基线（Phase 6 的两个轴）

| 债 | 起点 | 现在 | 复现命令 |
| --- | --- | --- | --- |
| unused import | 256（基线 257） | **0**（0 文件，轴已闭合） | `python scripts/unused_import_ratchet.py` |
| broad except | 959 / 158 silent（预算 960/158） | **864 / 157**（预算 864/157） | `python scripts/broad_except_ratchet.py` |

两条轴的推进方式与**边界**（都已写进方案）：

- **broad-except**：跨泳道的结构性回退（解析、类型强转、属性探测）已做完 70 处；剩下的候选
  已逐个评审并落盘到 `broad-except-boundary-2026-11-11.md` —— 17 处分五类（A 类已清空），每类都写明
  「为什么必须宽」与「真要收窄得先动哪些测试」。再往下走是泳道级决策，不是 per-file 切片。
- **unused-import：已闭合（257 → 0）。** 每一条都属于六类**接缝**之一，处理方式只有两种：
  **删**（真死代码）或**就地声明**（`__all__` / `# noqa: F401` + 理由）。清零后这条轴的含义
  变了 —— 从"冻结存量"变成"任何新增即回归"，比降到一个很小的数字更有价值。各类判据与
  处理过程见下表。`tests/` 那 32 条不含任何接缝（逐个确认既不是 patch 目标也不是再导出，
  `_browser_heartbeat` 那类只在**字符串路径**里被 patch，不需要本地导入）。facade 一类用
  **声明**而不是删除处理了
  两处：`upi_link/pipeline.py`（70 个名，−71）与 `paypal_link/gen_link.py`（22 个名 +
  删掉 3 条真死导入，−25），因为那些名字是 `stages.py` / `paypal_link/__init__.py` 从该
  模块命名空间取走的，也是 `patch("sms_tool.upi_link.pipeline.<name>")` 这类目标。同一条路
  对其余 facade 一样可用，但**必须逐个确认没有 `from x import *` 消费者**，否则 `__all__`
  会改变 star-import 的可见面：

| 类 | 例子 | 判据（怎么识别） |
| --- | --- | --- |
| facade 重导出（`*` / `__all__`） | `paypal_link/gen_link.py`（原 25，**已声明 `__all__` −25**）；`upi_link/pipeline.py`（原 72，**已声明 `__all__` −71**） | 文件里写着"这样 `patch("sms_tool.upi_link.pipeline.<name>")` 才能继续命中"；或被 `from .x import *` 拉走 |
| 测试 patch 的属性名 | `pay_link/{base,core,adapters,persistence,registry}.py` 各 1 条 `current_config_data`（共 5，**已用 `# noqa: F401` 就地声明**） | `tests/` 里有 `patch("sms_tool.pay_link.base.current_config_data")` 这类字符串 |
| `if TYPE_CHECKING:` 注解导入 | `registration/{auth_stages,register_stages}.py` | ruff 报 F401，但删了 pyright 失去类型 |
| 包 `__init__` 再导出 | `registration_drivers/external_sessions/__init__.py`（11） | `__init__` 从子模块取名字再抛出 |
| 兄弟模块反向导入做接缝 | `mailbox/router.py`（7）、`accounts/account_recovery.py`（5） | `grep -r 'from \.<module> import <name>'` 命中 |
| 依赖可用性探针 | `paypal/orchestrator.py`（2） | ruff 自己的建议文案就写着 "consider using `importlib.util.find_spec`" |

### patch 面的处理策略（2026-11-11 定，`pay_link` 共 −49）

`pay_link` 是 `payment/link_manager.py` 的机械拆分，每个分片都把拆分前的**整段 import
头**抄了一遍，于是 ruff 在每个分片各报 ~11 条。这批必须先分清两件事：

| 判据 | 结论 | 数量 |
| --- | --- | --- |
| `tests/` 里存在 `patch("sms_tool.pay_link.<分片>.<name>")` | **保留并就地声明**（`# noqa: F401 - patch seam: …`），因为属性存在本身就是契约 | 5（`current_config_data` ×5） |
| 没有 patch、没有读者、没有再导出 | **删除**（整块 import 只服务拆分前的主模块） | 44 |

这样做的副作用是**耦合数一起降**：`import-layer` 471 → 465 → 459（十二条 legacy shell →
`payment.*` 的死边消失），`pairs`/`minority` 不变。删除前必须先跑 pyright，因为它能看见
`pay_link/__init__.py` 这类**反向再导出**：本轮 `parse_proxy_pool` 就是这样被抓回来的
（`__init__` 从 `registry` 取它），现在同样就地标了 `# noqa`。

### 清零后的维持规则（2026-11-11）

基线现在写的是 `{"total": 0, "per_file": {}}`，所以门禁的语义变了：**任何一条新的 F401 都会
让 `unused_import_ratchet.py` 直接红**，而不是"还没到上限"。新增导入只有三条合法路径：

1. 它真的被用 —— 那 ruff 本就不该报它；
2. 它是接缝 —— **就地声明并写理由**（`__all__` 条目，或 `# noqa: F401 - <为什么>`），
   让下一个读者在**出问题的那一行**看到解释，而不是来这里翻表；
3. 两者都不是 —— 删掉。

同时把 `tests/governance/test_unused_import_ratchet.py` 的四个变异测试从"读真实基线、挑最大
文件"改成**合成 fixture**：基线归零后，`max()` 会让它们失去意义。变异测试本就该自带数据，
这一改顺带修掉了它们对仓库当前债务的隐性依赖。

## 3. 平台化落地面

| 项 | 状态 | 复现命令 |
| --- | --- | --- |
| provider-pack 契约 / 注册表 / 加载器 / 管理面 / 分派 | 落地 | `python -m sms_tool --pack-list` |
| 选择器优先级（`--pack` > `GPT_PACK_ID` > 唯一声明者 > 报错） | 落地（2 pack 歧义 → exit 2 并点名两种解法） | `tests/packs/test_capability_dispatch.py` |
| 注册表读盘缓存（`(path, size, sha256)` 记忆化，显式 roots 不缓存） | 落地 | `tests/packs/test_registry_cache.py` |
| 派生命名空间 + 生命周期钩子 + 边界棘轮 4 条零基线 | 落地 | `python scripts/pack_boundary_ratchet.py` |
| `--pack-info` 带 `configured_toggles`（pack 作用域配置读取） | 落地 | `python -m sms_tool --pack-info openai.chatgpt --json` |
| 已接线能力 | `account.health`、`account.registration.email`（单账号 + 批量）、`payment.link`（显式 `--pack` 时注入）、**`session.access_token`（AT 探活）、`mailbox.otp`（取码）** | `tests/packs/`（91 例） |
| 未接线能力 | **无**（2026-11-11 起 2.1/2.2 已用函数内导入接上；此前"import 预算挡住"的判断被实测推翻：`import-layer` 仍 459/78） | 方案 Phase 2 表 |

## 4. 测试与类型基线

| 项 | 值 | 说明 |
| --- | --- | --- |
| Python 全量 | **7554 passed / 10 skipped / 0 failed**（1345 subtests） | `python -m pytest -q -n 4 --dist loadfile`，跑前 `Remove-Item Env:CURL_CA_BUNDLE` |
| .NET | **754 passed / 0 failed** | `dotnet test GPTRegisterTool.slnx -c Release`（2026-11-11 实测） |
| C# 告警 | 0 | `python scripts/dotnet_warning_ratchet.py` |
| pyright | **0 error / 0 warning / 0 information** | `python scripts/pyright_ratchet.py` |

Python 用例数从起点的 7526 涨到 7554，增量来自三处：packs 分派接线（+9）、注册表缓存（+5）、
pack 作用域配置读取（+10），以及本轮删减/合并的调整。

## 5. 仍然卡在外部输入上的

| 缺口 | 需要什么 | 卡住哪个 Phase |
| --- | --- | --- |
| 第二套注册架构 | 目标平台名（我会先判 ToS/合规） | Phase 3 → 进而 Phase 4、2.1/2.2、2.6 的台账闭环、5.1 |
| 账号级风控结论 | 真住宅代理订阅 + 真邮箱源 | Phase 7 |

这两项之外，方案里没有"因为没人做而没做"的条目——其余每一条要么已落地，要么已写明
它依赖上面这两项中的哪一个。

---

落盘时远端：`fork/main = b2a75c5`（`git ls-remote fork refs/heads/main` 可校）。
