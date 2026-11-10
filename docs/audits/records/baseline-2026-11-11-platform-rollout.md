# 平台化改造基线快照（2026-11-11）

对应方案：`docs/audits/plans/plan-2026-11-10-platform-rollout.md` 的 **Phase 0.3**。
这份文件的用途只有一个：**让后面每一个数字都能被对比**。所以每一行都给出可复现命令，
而不是只写一个当时的值。

起点：`83b59e8`（Phase 0 之前最后一版 fork/main）。本文件落盘时：`main` 见文末。

---

## 1. 结构基线（棘轮冻结的判据）

| 指标 | 起点 | 现在 | 复现命令 |
| --- | --- | --- | --- |
| `import-layer` 模块级边 / 目录对 | 473 / 78 | **472 / 78** | `python scripts/import_layer_ratchet.py` |
| ↳ 其中 mutual / minority / delayed | 17 / 46 / 307 | 17 / 46 / 307 | 同上 |
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

`import-layer` 唯一的变化（473 → 472）来自删掉 `registration/outcome.py` 里一条**从未被读取**的
`from ..kernel.error_classification import classify_error`；只减不增，理由写在
`tests/governance/test_import_layer_ratchet.py` 的固定数字注释里。

## 2. 技术债基线（Phase 6 的两个轴）

| 债 | 起点 | 现在 | 复现命令 |
| --- | --- | --- | --- |
| unused import | 256（基线 257） | **227**（55 文件） | `python scripts/unused_import_ratchet.py` |
| broad except | 959 / 158 silent（预算 960/158） | **891 / 158**（预算 891/158） | `python scripts/broad_except_ratchet.py` |

两条轴的推进方式与**边界**（都已写进方案）：

- **broad-except**：跨泳道的结构性回退（解析、类型强转、属性探测）已做完；剩下的 39 个候选
  逐个人工核对后**多数必须保留**（包的是调用 / 返回探针失败字典 / 自然元组是
  `INTERNAL_EXCEPTION_TYPES` 的子集）。再往下走是泳道级决策，不是 per-file 切片。
- **unused-import**：剩下的 227 条集中在六类**接缝**上，按类列出：

| 类 | 例子 | 判据（怎么识别） |
| --- | --- | --- |
| facade 重导出（`*` / `__all__`） | `upi_link/pipeline.py`（72）、`paypal_link/gen_link.py`（25） | 文件里写着"这样 `patch("sms_tool.upi_link.pipeline.<name>")` 才能继续命中"；或被 `from .x import *` 拉走 |
| 测试 patch 的属性名 | `pay_link/{base,core,adapters,persistence,registry}.py` | `tests/` 里有 `patch("sms_tool.pay_link.base.current_config_data")` 这类字符串 |
| `if TYPE_CHECKING:` 注解导入 | `registration/{auth_stages,register_stages}.py` | ruff 报 F401，但删了 pyright 失去类型 |
| 包 `__init__` 再导出 | `registration_drivers/external_sessions/__init__.py`（11） | `__init__` 从子模块取名字再抛出 |
| 兄弟模块反向导入做接缝 | `mailbox/router.py`（7）、`accounts/account_recovery.py`（5） | `grep -r 'from \.<module> import <name>'` 命中 |
| 依赖可用性探针 | `paypal/orchestrator.py`（2） | ruff 自己的建议文案就写着 "consider using `importlib.util.find_spec`" |

## 3. 平台化落地面

| 项 | 状态 | 复现命令 |
| --- | --- | --- |
| provider-pack 契约 / 注册表 / 加载器 / 管理面 / 分派 | 落地 | `python -m sms_tool --pack-list` |
| 选择器优先级（`--pack` > `GPT_PACK_ID` > 唯一声明者 > 报错） | 落地（2 pack 歧义 → exit 2 并点名两种解法） | `tests/packs/test_capability_dispatch.py` |
| 注册表读盘缓存（`(path, size, sha256)` 记忆化，显式 roots 不缓存） | 落地 | `tests/packs/test_registry_cache.py` |
| 派生命名空间 + 生命周期钩子 + 边界棘轮 4 条零基线 | 落地 | `python scripts/pack_boundary_ratchet.py` |
| `--pack-info` 带 `configured_toggles`（pack 作用域配置读取） | 落地 | `python -m sms_tool --pack-info openai.chatgpt --json` |
| 已接线能力 | `account.health`、`account.registration.email`（单账号 + 批量）、`payment.link`（显式 `--pack` 时注入） | `tests/packs/`（86 例） |
| 未接线能力 | `session.access_token`、`mailbox.otp` —— 消费方在 `sms_tool/registration`，该目录 import 预算已满，**Phase 4 迁移后自动解锁** | 方案 Phase 2 表 |

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
