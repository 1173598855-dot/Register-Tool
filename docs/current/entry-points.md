# 入口分类（Entry Points）

这个仓库有多个入口。它们的**唯一清单**是
`scripts/entry_point_manifest.json`，由 `scripts/entry_point_ratchet.py` 执法：
根目录多一个 `.py`、`services/` 多一个项目、或者根目录出现打包产物，都会直接失败。

本文是那张清单的人读版本。改清单必须同时改这里，否则两边对不上。

## 入口表

| 入口 | 类型 | 状态 | 实现归属 | 怎么跑 | 用来干什么 |
| --- | --- | --- | --- | --- | --- |
| **CLI** | `cli` | **authoritative** | `sms_tool/cli.py` | `python -m sms_tool ...` | 唯一受支持的命令面：注册、账号、支付、包管理、诊断 |
| **桌面端** | `desktop` | **authoritative** | `SmsWorkbench/App.xaml.cs` | `dist/net10/SmsWorkbench.exe` | WPF 外壳：拼命令、起后端进程、渲染结果；不拥有协议行为 |
| `chatgpt_phone_reg.py` | `compat` | `compat` | 同名脚本 | `python chatgpt_phone_reg.py` | 历史入口名，转调 CLI。**不要再往里加逻辑** |
| `start_proxy_pool.py` | `operator` | internal | 同名脚本 | `python start_proxy_pool.py` | 本地 SOCKS5 池，按会话轮换上游 |
| `verify_proxy.py` | `operator` | internal | 同名脚本 | `python verify_proxy.py --chatgpt` | 只读代理连通性/边缘探测 |
| `services/mail-otp-web/` | `service` | internal | `app.py` | 见其 README | 可选本地邮箱/OTP 服务，独立进程边界 |
| `services/protocol-payment/` | `service` | internal | 每支付方式一个目录 | 由 CLI 以子进程驱动 | 协议支付提取器。**规则 10 禁止从这里 import `sms_tool`** |
| `scripts/` | `tool` | internal | 64 个脚本 | 按文件名调用（CI / git hook / pytest） | 门禁、棘轮、脚手架、一次性运维助手 |
| 构建 | `tool` | internal | `SmsWorkbench/build_dotnet.ps1` | 见 README 部署方式 | 桌面产物与安装包的**唯一**构建路径（输出到 `dist/`） |

## 新增入口放哪（决策树）

```text
你想加的东西是…
├─ 用户会直接调的命令/子命令        → 加 --flag 到 sms_tool/cli_parsers/ + commands/
├─ 桌面端的按钮/窗口                → SmsWorkbench（只拼命令，不写协议）
├─ 一套新的注册架构                 → sms_tool/platforms/<short>/ + packs/builtin/<short>/manifest.json
│                                      （用 python scripts/pack_new.py 生成）
├─ 一套新的支付方式                 → sms_tool/pay_link/（legacy lane 已冻结）
├─ 门禁/棘轮/脚手架/一次性助手      → scripts/
├─ 需要独立进程边界的服务           → services/<name>/（并在清单里声明）
└─ 一次性本地验证脚本               → runtime/tmp/（Git 忽略），或直接用 --flag 加进 CLI
```

**根目录不放新代码。** 例外只有历史上已经在那里的三个脚本，它们已声明、已冻结。

## `scripts/` 的七组（65 个文件）

`scripts/` 在入口清单里是一行，但里面 65 个文件的"杀伤半径"完全不同：只读棘轮、
会重写源码的工具、会碰真实凭据的运维脚本。所以它们必须分组声明，且**每个文件只能
属于一组**（棘轮执法）。

| 组 | 数量 | 干什么 | 能不能自动跑 |
| --- | --- | --- | --- |
| `gate` | 38 | 只读门禁/棘轮/守卫/扫描，非零退出即红 | ✅ CI、git hook、pytest 包装器都跑它 |
| `report` | 4 | 生成已提交的产物（依赖图、CLI 参考、文档数字、符号行号） | ⚠️ 会写文件，产物按 diff 审阅 |
| `operator` | 14 | 碰凭据/账号/邮箱/网络：测活、装箱、剪枝、探测、库存 | ❌ 手工跑，几个还需要显式 flag 才会动手 |
| `build` | 4 | 构建、打包、运行时固化、环境预检 | ✅ 构建流程里跑 |
| `refactor` | 3 | **重写源码**：模块搬迁、idiom 改写、注解修复 | ❌ 传路径执行，diff 必须人读 |
| `scaffold` | 1 | 生成新的平台单元（`pack_new.py`） | ❌ 一次性 |
| `package` | 1 | 包标记 `__init__.py`，让门禁能被 pytest 以 `scripts.x` 导入 | — |

新增脚本 → 先在 `script_groups` 里选一组并登记，否则 `entry_point_ratchet.py` 直接失败。
判据很简单：**它会不会写、会不会碰真实凭据**。

## 三条硬规则

| 规则 | 为什么 |
| --- | --- |
| 根目录 `*.py` 必须已在清单里声明 | 根目录是"顺手放一下"的默认垃圾桶；`root_module_ratchet` 只冻了包根，这里是仓库根 |
| 根目录不得出现 `*.exe` / `*.msi` / `*.zip` / `*.7z` | 构建产物属于 `dist/`。曾有一个 57 MB 的运行时安装包长期躺在根目录 |
| `services/<dir>/` 与 `SmsWorkbench*` 项目必须声明 | 它们是独立进程/独立构建面，漏一个就少一个可追踪的边界 |

## 执法

```powershell
python scripts/entry_point_ratchet.py            # 检查
python scripts/entry_point_ratchet.py --detail   # 打印已声明的入口面
python -m pytest -q tests/governance/test_entry_point_ratchet.py
```

`tests/governance/test_entry_point_ratchet.py` 对每条规则都用一棵一次性目录树做变异，
证明它会失败——只在真树上通过的门禁不是门禁。
