# 计划：多架构平台化收口（2026-11-10）

> 状态：**待批准**。这是一次性完整方案，不是逐条推进的清单——按 Phase 顺序执行，
> 每个 Phase 结束后全量门禁 + 全量测试必须是绿的，否则不进下一个 Phase。
>
> 起点：`fork/main` 已推送；工作区 24 个文件未提交（Phase 0 处理）。

## 0. 现状基线（开始前的事实）

| 项 | 值 |
| --- | --- |
| Python 全量 | 7526 passed / 10 skipped / 0 failed |
| .NET | 752 passed / 0 failed，0 警告 |
| 仓库门禁 | 30+ 个，全部 exit 0 |
| pyright | 0 error / 0 warning / 0 information |
| `sms_tool` 模块 | 336 tracked，包根 79 个冻结名 |
| 入口 | 9 个已声明（CLI / 桌面 / compat / 2 operator / 2 service / scripts / build） |
| `scripts/` | 65 文件，7 组已声明并执法 |
| provider pack | 1 个（`openai.chatgpt`），声明 6 个能力，**已接线 1 个** |
| 未解问题 | 账号级风控没有样本（住宅池仍是模板占位符） |

---

## Phase 0 — 收口（必须先做，0.5 个工作日）

**目标**：把现有工作落地成可回滚的历史，之后每一步都从干净起点开始。

| # | 动作 | 涉及 | 验收 |
| --- | --- | --- | --- |
| 0.1 | 拆 4 个 commit：packs 选择器+批处理接线 / 台账分片 / 入口清单+分组 / 全量修复+仓库整理 | 24 个文件 | `git log` 四个主题清晰，每个 commit 树可 import |
| 0.2 | 推 `fork/main` | — | 远端哈希 = 本地 |
| 0.3 | 记录基线快照到 `docs/audits/records/` | 新文件 | 上述表格成为可比对的数字 |

**风险**：无。**回滚**：`git reset --hard` 到 `83b59e8`。

---

## Phase 1 — 补完"分类-执法"这条线（1–2 个工作日，纯增量）

这一 Phase 不加任何行为，只让"以后不会越来越多"从口号变成门禁。

### 1.1 包根 79 个模块的分组归类

**问题**：`root_module_ratchet` 只冻结 79 个**名字**，`directory-map.md` 的 43 组声称
覆盖全部 336 个模块，但**没有人管这 79 个文件各属于哪一组**——一个冻结集合没有分类，
读了还是不知道它是干嘛的。

**做法**：
- `scripts/root_module_manifest.json` 新增 `groups`，每组 `purpose` + 文件列表
- `scripts/root_module_ratchet.py` 加规则：每个包根模块恰好属于一组；组声明的文件必须存在
- `docs/directory-map.md` 增加"包根模块分组"表
- 测试：`tests/governance/test_root_module_ratchet.py` 补 5 例（未归组 / 归两组 / 组缺 purpose / 声明了不存在的文件 / 全声明通过）

**验收**：棘轮绿；`--detail` 能打印 79 个模块的组别。

### 1.2 `dispatch` 的进程内缓存

**问题**：`dispatch.resolve_capability_entrypoint()` 每次都 `load_registry()` = 读 + 校验
manifest。100 个账号的批处理会读 100 次（每次约 1–2 ms，合计 100–200 ms 纯开销）。

**做法**：`packs/loader.py` 加 `load_registry` 的进程内缓存，key 用「builtin 目录 +
`GPT_PACK_PATH` + 每个 manifest 的 `(mtime, size)`」，命中直接返回；文件一变自动失效。
**不能用无 key 的全局缓存**——测试要 monkeypatch 注册表，必须能绕过。

**验收**：新增测试证明「第二次调用不再读文件」「manifest 改动后失效」「显式传入
registry 时永不缓存」；性能上批处理里 `load_registry` 调用次数降到 1。

### 1.3 `--pack` 打通到桌面

**问题**：CLI 有 `--pack`，但 `SmsWorkbench.Contracts/BackendCommandPlanner.cs` 没有
对应参数，桌面端无法选择架构。`tests/workbench/test_backend_cli_contract.py` 只断言
**C#→Python** 方向，所以这个缺口不会被现有门禁发现。

**做法**：
- `BackendCommandPlanner` 增加 `withPack(plan, packId)`（唯一允许拼 `--pack` 的地方）
- 设置页"注册与接码"分类下加"注册架构"下拉，数据源改成 `--pack-list` 的 IPC payload
- 补测试：C# 侧断言 planner 产出正确参数；契约测试覆盖新 flag

**验收**：桌面能选 pack；`pack-list` 的 JSON 被 C# 反序列化（新 DTO 进 Contracts）。

### 1.4 文档索引补漏

`docs/README.md` 的 Core documents 没有 `provider-packs.md` 和 `entry-points.md`。

---

## Phase 2 — 把能力真正接线（P2 收尾，3–5 个工作日）

**问题**：manifest 声明 6 个能力，只有 `account.health` 有生产调用方。这是"骨架没通电"
的根源。入口点也已有 4 个（`register_email` / `register_batch` / `account_liveness` /
`registration_preflight`），但只有 1 个被 dispatch 使用。

| # | 能力 | dispatch 点 | 状态 |
| --- | --- | --- | --- |
| 2.1 | `session.access_token` | AT 探活阶段 | **阻塞**：消费方是 `registration/account_stages.py`，而 `sms_tool/registration -> sms_tool` 的 import 预算已满；**Phase 4 之后自动解锁**（实现搬进 `platforms/chatgpt/` 后就与 `packs` 同目录节点，导入免费） |
| 2.2 | `mailbox.otp` | `registration/otp_stages.py` 取码阶段 | **同上阻塞、同上解锁路径** |
| 2.3 | `payment.link` | `--generate-ba-link` → `commands/payment_links.py` | **已完成**：只在显式给了 `--pack` 时注入 `link_factory`；默认保留支付泳道自己的方法注册表（不然就是第二套注册表） |
| 2.4 | `account.registration.email` | `cli._load_heavy_deps` 解析 `run_email` | **已完成**：manifest 决定注册入口，不再是 import；单 pack 时是同对象 |
| 2.5 | `payment.batch` + 批量注册 | `cli._main_registration_pipeline` | 待做（依赖 2.4 的批量路径） |
| 2.6 | 台账 code↔ledger 双向 | 新增 pack 作用域 flag reader | 待做 |

**已完成的 §2.3/2.4 都没有新增 import 边**：`import-layer` 仍是 473 边 / 78 对，
`delayed` 仍是 473/362 —— 这是"命令层解析 + 关键字注入"这条约束的直接证据。

**2.1/2.2 的决策已明确，不必现在拍板**：它们不是"做不做"的问题，而是"什么时候"。
Phase 4 把实现搬进 `platforms/chatgpt/` 之后，该目录与 `packs` 同属 `sms_tool` 目录节点，
导入不计边，两处 dispatch 点可以零成本接上。**所以 P4 不是可选项，它是 2.1/2.2 的前置。**

**每个能力的固定三件套测试**（照 `account.health` 的样子）：
1. 对象同一性：解析出的 callable `is` 工作流原本 import 的那个
2. 注入生效：`probe_fn=`/对应参数注入后被真正调用
3. 歧义：两个 pack 声明同能力 → 报错并点名 `--pack` / `GPT_PACK_ID`

**约束（重要）**：`import-layer` 每个目录对的 import 条数冻结，只许降。新增 dispatch
点一律走**「命令层解析 + 关键字注入」**，不新增跨目录 import 边。若某处必须新增边，
先做一次显式的预算决策，不允许 `importlib` 绕静态图。

### 2.6 台账的 code↔ledger 双向校验（pack 作用域）

现在 `packs.<id>.toggles` 只有形状与 pack 存在性校验，**证明不了代码真的读了开关**。
补一个 pack 作用域的 flag reader（例如 `packs/flags.py`，读 `packs.<id>.<key>`），
然后把 `experiment_ratchet` 的 `code_reads` 扫到 pack 目录，双向对齐。

---

## Phase 3 — 第二套架构（P4，唯一能证明抽象成立的事，5–8 个工作日）

**为什么必须做**：只有一个 pack 时，任何"通用工作流"都是按一个样本猜的抽象。P3 之前
必须有第二套跑通，否则迁移是在给未验证的抽象交学费（ADR-0015 已写明）。

| # | 动作 |
| --- | --- |
| 3.1 | 选目标平台：需能自助注册 + 有邮件验证 + 可接受自动化。要同时评估**合规边界**（见"不做的事"） |
| 3.2 | `python scripts/pack_new.py --id <vendor>.<platform>` 生成骨架 |
| 3.3 | 填 `platforms/<short>/flow.py`：`preflight`（verify 钩子）+ `register_email`，返回共享结果形状 |
| 3.4 | 风险词汇接进 `failure_registry`（现在 `risk_signals` 只是数据，没进分类器） |
| 3.5 | 对等测试：同一批邮箱在 `--pack openai.chatgpt` 与 `--pack <new>` 下互不干扰 |
| 3.6 | 真实跑 3–5 个账号，证明不是纸面架构 |

**验收**：`--pack-list` 两个 active pack；`--pack-verify` 全绿；两套架构各自的测试
互不 import。

---

## Phase 4 — 迁移存量（P3，5–10 个工作日，高风险）

**目标**：把 ChatGPT 的实现从 `registration/` 迁进 `platforms/chatgpt/`，manifest 改指向。

**分步**（每步独立可回滚）：
1. `auth_flow/` 整包平移（纯移动 + import 重写，`import_layer_baseline` 会变，需显式重建基线并记录理由）
2. `registration/` 的阶段体（bootstrap/identity/auth/register/otp/account/sentinel/resume）逐个平移
3. `sentinel/` 保持原位（它是共享的签发器，不是某套架构私有）
4. manifest 的 `entrypoints` 改指向新位置 + 对等测试
5. 删除 `registration/orchestrator.py` 的兼容 re-export？**不**——保留为 facade

**风险**：这是全仓最大的结构变更，`import_layer_ratchet` / `delayed_import_ratchet` /
`provider_decoupling_ratchet` 三张基线都会动。**必须每个子步一个 commit**，全量绿
才继续。

---

## Phase 5 — 产品面（P5，3–5 个工作日）

| # | 动作 | 状态 |
| --- | --- | --- |
| 5.1 | 桌面按 `capabilities` 渲染：声明 `payment.link` 才显示支付页，声明 `mailbox.otp` 才显示接码 | 待做（依赖 P3 的多 pack 才有意义） |
| 5.2 | 命名收敛：`--pack` 与 `--provider` 二选一 | **✅ 已完成（2026-11-11 核实）**：`--provider` 从未存在。`grep '"--provider"'` 唯一命中是 `--provider-proxy`，那是 Stripe 第二阶段代理，与"选哪套架构"不是一个概念，不动它（改它会连带 C# Contracts 与文档）。所以架构选择器的词汇就是 **`--pack` / `GPT_PACK_ID` / `--pack-*`** 三个，无需收敛 |
| 5.3 | `docs/current/cli-reference.md` / `ui-architecture.md` 同步 | cli-reference 是生成物且已 current（每片都跑 `--check`）；`ui-architecture.md` 等 5.1 落地时同步 |

---

## Phase 6 — 技术债退坡（持续，按仓库既有节奏）

**只按单文件退，不批量**——仓库审计已记录批量清理失败两次并整批回滚。

| 债 | 现状 | 目标 |
| --- | --- | --- |
| unused import | 256（基线 257） | 每轮拿 1–2 个文件清零，`--update-baseline` 降 |
| broad except | 959 / 158 silent（预算 960/158） | 按 lane 逐条窄化到 `TRANSPORT_ERRORS`，标记 `# broad-except:` |
| deferred import | 212 | 能提到模块级的提；提不了的保持并留理由 |
| same-named divergent | 34 | 逐对判断是"分层"还是"复制" |

### unused import 退坡实测（2026-11-11）：剩下的多数是**接缝**，不是死代码

本轮把 256 降到 **238**（61 个文件），每片都先 grep 兄弟模块的 re-export
（`from .<module> import <name>`）再动。过程中撞到两次**ruff F401 误判活接缝**：

| 误判 | 真相 |
| --- | --- |
| `account_recovery` 的 `account_identity` / `browser_fetch_for_account` / `mailbox_relogin_allowed` / `proxy_pool_for` / `clear_stale_promotion_at_marker` | `recovery_batch` 故意 `from .account_recovery import ...`，好让测试 patch `account_recovery.*` 生效。删掉后 pyright 立刻报 5 个 unknown import symbol，已全部回滚 |
| `pay_link/base.py` 的 `current_config_data`、`pay_link/normalize.py` 的 10 余个名字 | 这些文件存在的目的就是**让测试能 patch 这个属性名**；仓库自己的报错文案写明要 patch `sms_tool.pay_link.base.current_config_data` |
| `mailbox/router.py` 的 7 个私有名 | `mailbox/__init__.py` 与 `strategies.py` 都从 `router` 再导出/导入它们 |

⇒ **剩余 238 条的主体是刻意的 re-export / patch 面，不是债。** 继续批量删会破坏
行为，这正是这个仓库用冻结基线而不是批量自动修复的原因。

**每一片的固定做法**（四步，缺一不可）：

1. `grep` 三处，光看 import 语句不够：
   - 兄弟模块 `from .<module> import <name>`（含 `tests/`）；
   - 该名字作为**字符串**出现（facade 的惰性再导出表，例如
     `orchestrator._MODULE_EXPORTS` 里的 `"<name>": ("sms_tool.<mod>", "<name>")`）；
   - `patch(` / `patch.object(` 的参数。
2. 只删**整句 stdlib 导入**或无接缝的单个名字；
3. `pyright` 必须仍是 0 error —— 它解析惰性再导出表，是唯一能看见第二类接缝的检查器
   （2026-11-11 实测：`account_creation._minimal_chatgpt_cookie_header` 被
   `orchestrator` 的字符串表引用，ruff 报 F401、grep import 语句找不到、pyright 报
   `unknown import symbol`）；
4. `unused_import_ratchet --update-baseline` + `refresh_doc_symbol_lines --apply`
   （删一行会让该文件之后所有 `file.py:NNN` 指针漂移）。

### broad except 退坡实测（2026-11-11）：只有一类是安全的

本轮把 959 降到 **956**（191 个文件），预算是独立的 `max_broad`，只许降。

**安全的类：结构性回退，与传输无关。** `http_utils` 的三处就是这一类 ——
`response.json()` 的解析回退、cookie jar 迭代回退。它们没有 `# broad-except:` 标记、
不在协议泳道、也不做传输判定，按实际能抛的类型收窄即可：

```python
except (AttributeError, TypeError, ValueError):   # body 不是 JSON / 没有 .json / 形状不对
except (AttributeError, TypeError):               # cookie jar 不可迭代 / 没有 get_dict
```

**不安全的类（实测踩到）：协议泳道里那些"宽"是有原因的。**

| 候选 | 结果 |
| --- | --- |
| `auth_flow/login.py:287`（`_follow_continue_url` 后面，handler 只打印 "transport warning"，且该文件已导入 `TRANSPORT_ERRORS`，零新增边） | 收窄后 **16 个测试失败**：`AttributeError: 'object' object has no attribute 'get'`（`http_client.py:237`）。测试用裸 `object()` 当响应替身，正是靠这个宽 handler 吞掉。已回滚 |
| `auth_flow/{login,otp,signup}` 其余带 `# broad-except: compat` 的 | 注释写明"must never fail the stage"；收窄会破坏它们自己的契约 |
| `registration/preflight.py` 的几处 | 同一类：cleanup 与 probe 兜底，收窄会让探针缺陷变成代理降级 |

⇒ **结论：协议泳道的宽 handler 不是"懒"，是"有理由"**（Rule 26 允许的 keep，且都在
基线里）。要动它们必须同时改被钉住的测试（把 `object()` 替身换成真响应形状），
那是一次 lane 级决策，不是一次 per-file 切片。所以这条轴的推进顺序是：
**先做跨泳道的结构回退类，再单独立项处理泳道内的宽 handler。**

### 安全类的筛选口径（可复算）

一次 AST 扫描把这批候选挑出来，五个条件同时成立才算：

1. 文件不在 `sms_tool/auth_flow/` 或 `sms_tool/registration/`；
2. handler 行没有 `# broad-except:` 标记；
3. handler 体是**单条 `return <默认值>`**（`None` / `""` / `0` / `False` / 空容器 / 字面量 dict）；
4. 返回的 dict 字面量**不含** `ok` / `status` / `error` / `quota_status` / `retryable` /
   `error_stage` / `proxy_source` —— 那些是探针失败结果，属于传输判定，不能收窄；
5. try 体前后 14 行内没有 `request_with_retry` / `curl_requests` / `session.get(` /
   `session.post(` / `requests.get(` / `requests.post(`。

用它得到 **101 个候选**（175 → 101）。已收窄的 8 处来自 `http_utils`（3）、
`wham_usage`、`account_seed`、`geo/clock`（4）、`k12_identity`、`codex_sentinel`——
**959 → 948**。收窄时按"这个形状实际能抛什么"写元组，并在注释里说明为什么
传输错误故意不在里面。

### 收窄时还会撞到的两道门禁（2026-11-11 实测）

选目标只是第一步，写下去时还有两条约束，都必须**在提交前**撞过一次才知道：

| 门禁 | 现象 | 正确做法 |
| --- | --- | --- |
| `function_length_ratchet` | 在冻结函数里加 3 行解释性注释 → `check_account_promotion: 160 -> 163` 直接红 | 用**行尾注释**代替独立注释行，净行数不变（`except (…):  # 一句理由`） |
| `test_internal_exception_owner` | `(AttributeError, KeyError, TypeError)` 被判定为"手抄 `INTERNAL_EXCEPTION_TYPES`" | 该常量是 9 个类型的集合；**子集也算抄**。要么 import 常量（root 模块导入 `kernel` 要付一条已冻结的 import 边），要么保留 broad 并加 `# broad-except: compat`。本例选择后者 |

⇒ 所以一片的实际产出常比候选数少：**候选 5 个，能落 4 个**。

---

## Phase 7 — 回答最初的问题：账号级风控（1–2 个工作日 + 成本）

这是**唯一还没有数据支撑的结论**。仓库里有 4 份历史证据（10-11 掉号、10-12 修好、
10-23 存活 142 分钟、10-31 59 号曲线），但都不在你当前的出口/邮箱组合上。

| # | 动作 | 成本 |
| --- | --- | --- |
| 7.1 | 填真住宅代理（ipwo/proxylane）+ `python scripts/proxy_pool_probe.py --require-clean` | 代理订阅 |
| 7.2 | 备一个真邮箱源（ReMail 或 iCloud 接码） | 邮箱成本 |
| 7.3 | `--buy-remail-mailbox --target-at200 --count 3 --workers 1` | 3 个号 |
| 7.4 | `python scripts/at_survival_watch.py --ids <ids> --schedule-minutes 1,5,15,30,60,120` | — |
| 7.5 | 结论写 `docs/audits/scans/`，把"条件性风控"从推断变成实测 | — |

**注意**：仓库自己的记录说 `proxy.json` 里那三条 `YOUR_USER_custom_zone_*` 是 README
模板，不是真凭据；不换池子这一步做不了。

---

## Phase 8 — 可选：内核作为独立产品（长期）

三条产品线共享同一个内核，这件事在 Phase 3/4 之后才成立：

- 支付协议编排引擎（`payment/` + `services/protocol-payment/` + `pay_link/`）
- 浏览器与反风控研究台（驱动 + 指纹池 + 代理泳道 + A/B 台账 + 存活曲线）
- 通用多平台账号自动化（`packs/` + `platforms/` + 邮箱/接码/存储）

前提：内核能独立发版 = `packs/` 与 `platforms/` 的依赖方向必须干净（现在已经是），
且 `sms_tool` 这个名字要能改（涉及 336 个模块的 import 前缀，是一次大迁移）。

---

## 依赖关系

```text
Phase 0 ──► Phase 1 ──► Phase 2 ──► Phase 3 ──► Phase 4 ──► Phase 5
                │                      │
                └──────────► Phase 6（可与 2/3 并行，逐文件）
Phase 7 独立（随时可做，只差代理+邮箱）
Phase 8 在 Phase 3/4 之后
```

**Phase 1.2（dispatch 缓存）必须在 Phase 2 之前**，否则每接一个能力就多一份重复读盘。

---

## 明确不做的事

| 不做 | 理由 |
| --- | --- |
| 批量清理 256 个 unused import | 仓库审计记录：试过两次，每次整批回滚 |
| 用 `importlib` 绕过 import-layer 棘轮 | 那是骗自己的门禁；要么显式改预算，要么改结构 |
| 插件热重载 | 把"配置/代码版本错配"变成运行期随机故障 |
| manifest 签名 | 外部分发渠道还不存在，签名是装饰 |
| 在 P4（第二套架构）之前迁 ChatGPT 代码 | 给未验证的抽象交学费 |
| 把 `retryable`/`terminal` 写进重试策略 | 处置必须留在 `registration/policy.py` 与 `failure_registry` |

## 合规边界（Phase 3 选平台时先过这一关）

本项目 LICENSE 是 MIT，README 写明"仅在获得授权并符合相关服务条款、地区法规及组织
政策的场景中使用"。Phase 3 选第二套架构时，必须选**允许自动化注册**或**自有账号体系**
的目标；若目标平台 ToS 明令禁止自动化，那这一 Phase 的产品价值必须重新评估，而不是
默认继续。

---

## 每阶段的统一验收

```powershell
python -m pytest -q -n 4 --dist loadfile          # 全量
python -m pytest -q tests/registration tests/workbench   # 顺序敏感分片
dotnet test GPTRegisterTool.slnx -c Release
# 然后 scripts/ 里全部 gate 组：38 个脚本逐个 exit 0
```

数字必须与上一 Phase 相同（除非本 Phase 明确要动某个基线，且理由写进 commit message
与对应 baseline 的 `--reason`）。
