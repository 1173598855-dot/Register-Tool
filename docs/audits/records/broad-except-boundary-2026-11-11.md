# broad-except 边界评审（2026-11-11）

配套文件：`docs/audits/records/baseline-2026-11-11-platform-rollout.md`（基线快照）、
方案 `docs/audits/plans/plan-2026-11-10-platform-rollout.md` 的 Phase 6。

**这份文件解决的问题**：broad-except 轴从 959 降到 864，但"降到多少"不是判据 ——
**剩下每一处为什么还宽着**才是。评审的目标是让下一个人不必重新推一遍：每一处都写明
它属于哪一类、为什么不能按形状收窄、以及**真要收窄得先动哪些测试**。

## 0. 怎么复现这份名单

扫描阈值（五条同时成立才进候选，与方案 Phase 6 记的一致）：

1. 文件不在 `sms_tool/auth_flow/` 或 `sms_tool/registration/`（协议泳道，宽 handler 有文档理由）；
2. handler 行没有 `# broad-except:` 标记；
3. handler 体是**单条 `return <默认值>`**；
4. 返回的 dict 字面量**不含** `ok` / `status` / `error` / `quota_status` / `retryable` /
   `error_stage` / `proxy_source`（那些是探针失败结果，本身就是传输判定）；
5. try 体前后 14 行内没有 `request_with_retry` / `curl_requests` / `session.get(` /
   `session.post(` / `requests.get(` / `requests.post(` / `.json()`。

当前计数（可复算）：

```text
python scripts/broad_except_ratchet.py
broad-except: 864 handlers (157 silent) across 181 files; whitelisted 9; budget 864/157
```

扫描得到 **17 个**候选（本轮开始时 38 个：§1 两处结构回退 + §1.1/§1.3–§1.10 九批泳道级决策已解决；§1.2 的四处本就不在候选里）。**A 类已清空**——剩下的全部是 B/C/D 类，即「按判据就不该动」的那些（元组子集 / 第三方错误类型 / never-raises 契约）。

## 1. 本轮**已经收窄**的 2 处（写在这里，免得被当成"还没做"）

| 位置 | 收窄成 | 判据 |
| --- | --- | --- |
| `upi_link/session.py:309` `_upi_account_id_from_token` | `(AttributeError, TypeError, ValueError)` | body 是 base64url + `json.loads` + 两次 `.get`：解码错是 ValueError，`json` 产出非 mapping 时 `.get` 是 AttributeError。含 ValueError → **不是** `INTERNAL_EXCEPTION_TYPES` 子集 |
| `sentinel_tokens.py:144` `_sentinel_device_id` | `(AttributeError, TypeError, ValueError)` | 同上：`json.loads` + `.get("id")` |

这两处证明了一件事：**"结构回退"这一类并没有被做完**，只是剩下的大多属于下面 §2 的五类。
以后拿到新代码，先按这五条扫，再按 §2 的类别表判 —— 不属于任何一类的，就该收窄。

### 1.1 已执行的**泳道级决策**：`payment/capability` 的补充读取（E 类 → 已解决）

§3 说的第一条路（"把探针失败变成结构化错误"）已在一个点位上落地。选它是因为它同时
满足三个条件：泳道自带错误类型（`CapabilityProbeError`）、调用方本来就有兜底、
而且它的"宽"正是这一类难点的教科书形状。

| 前 | 后 |
| --- | --- |
| `_read_payment_methods_signal` 里 `except Exception: return {}` | **不捕获**。传输错误向外抛；缺陷也向外抛 |
| 调用点 `except Exception: raw_signal = {}` | `_read_signal_or_reason(...)`：只捕 `(CapabilityProbeError, *TRANSPORT_ERRORS)`，把原因变成 `payment_methods_signal_error` |
| 公开方法 `payment_methods_signal` 直接调读者 | `_degrade_signal(...)`：同一个窄元组，仍然返回 `{}`（它的契约是"没有信号"） |

**为什么这是对的**：`except Exception: return {}` 把三件不同的事压成同一句话 ——
请求死了、payload 形状变了、代码有缺陷 —— 全都读作"这个账号没有可用支付方式"。
现在传输失败仍然不改变探针结论（补充读取不能改变结果），但**原因被记下来了**；
而缺陷会走到外层的 `capability_probe_unexpected`，那才是它该去的地方。

**测试替身按判据更新了**（这正是泳道级决策要付的代价）：

| 测试 | 改动 |
| --- | --- |
| `test_read_payment_methods_signal_degrades_to_empty` | 拆成三个：传输失败（`OSError`，`TRANSPORT_ERRORS` 成员）在读者处**抛**、在公开方法处降级；`RuntimeError` **抛**（缺陷不是答案）；403 仍然返回 `{}` |
| 新增 `test_the_probe_records_why_the_signal_read_failed` | 断言 `ok is True` 且 `payment_methods_signal_error == "payment_methods_signal_transport"` |

**门禁代价（都是显式处理，不是绕过）**：`broad-except` 889 → **887**（本点位）；冻结函数
`payment_method_capability_probe` 从 272 行**缩到** 267（因此按规则收紧基线，而不是放宽）；
新增一条**有书面理由**的 deferred 边
（`payment/capability.py -> sms_tool.kernel.transport`，写进 `delayed_import_reasons.json`）。

### 1.2 第二个点位：`agent_identity` 的四处探针失败 handler

同一模板的第二次应用。这四处**不在 §2 的候选里** —— 扫描的第四条把"返回带
`ok`/`error` 的 dict"当作探针失败结果排除了，那个判断仍然正确：**返回带码的失败对象是对的**。
错的是它们**捕获了什么**。

| 位置 | 前 | 后 |
| --- | --- | --- |
| `create_agent_identity` 的 `session.post` | `except Exception:` → `agent_registration_request_failed` | `except TRANSPORT_ERRORS:` |
| 同函数的 `session.close()`（`finally` 里） | `except Exception: pass` | `except TRANSPORT_ERRORS: pass` |
| 同函数的 `response.json()` | `except Exception:` → `agent_registration_invalid_json` | `except (AttributeError, TypeError, ValueError):` |
| `register_agent_identity_task` 的 `curl_requests.post` / `response.json()` | 同上两处 | 同上两处 |

**为什么这批值得动**：`except Exception` 让"代理拒绝"和"本文件有 bug"产出**完全相同的**
`{"ok": False, "error": "agent_registration_request_failed"}` —— 排障时会去查代理，而问题在代码里。
现在：传输失败仍然是那个码（这是对的），缺陷则向外抛，由调用方按缺陷处理。

**副作用里有一个真实收益**：`session.close()` 那处从 `except Exception: pass` 收窄后，
`broad-except` 的 **silent 计数 158 → 157** —— 那是全仓 158 个静默 handler 里的一处。

**测试**：这四处此前**没有任何用例覆盖**（`grep` 四个错误码在 tests/ 下 0 命中）。新增四条，
替身按判据喂窄元组：

| 新测试 | 断言 |
| --- | --- |
| `..._a_transport_failure_at_registration_is_reported_as_request_failed` | `OSError`（`TRANSPORT_ERRORS` 成员）→ `agent_registration_request_failed` |
| `..._a_defect_at_registration_is_not_reported_as_request_failed` | `RuntimeError` → **向外抛**（`assertRaises`） |
| `..._an_unparseable_registration_body_is_invalid_json` | `json()` 抛 `ValueError` → `agent_registration_invalid_json` |
| `..._a_transport_failure_at_task_registration_is_reported_as_request_failed` | 任务注册路径同样返回 `agent_task_registration_request_failed` |

**门禁代价**：`broad-except` 887 → **882**（silent 158 → **157**）；两处**函数内**导入
`kernel.transport`（模块级会给已顶死的 `sms_tool -> sms_tool/kernel` 加边），理由写进
`delayed_import_reasons.json`，固定分解事实 `delayed_cross_dir_edges` 308 → 310。

### 1.3 第三个点位：`proxy/admin._health_rank` 的两处 handler

这一次的判据来自**被调方自己的收窄**，而不是猜：`ProxyHealthTracker.__init__` 已经把日志读取
收窄成 `(OSError, ValueError, TypeError)`，`resolve_registration` 对未知泳道抛 `ValueError`。
所以 `_health_rank` 只需要照抄这个面。

| 位置 | 前 | 后 |
| --- | --- | --- |
| `ProxyHealthTracker(...)` + `resolve_registration(...)` | `except Exception: return {}` | `except (OSError, TypeError, ValueError): return {}` |
| `tracker.rank(pool)` | `except Exception: return {}` | 同上 |

**为什么值得动**：`--proxy-list` 的输出里，"日志还没有数据"和"解析器有 bug"此前给出的是
**同一个空排名**。现在前者仍然空，后者直接抛出来。

**测试**：`_health_rank` 此前**零覆盖**。新增五条，替身喂窄元组：正常排序、日志不可解析
（`ValueError`）→ `{}`、未知泳道（`ValueError`）→ `{}`、`rank` 中途日志消失（`OSError`）→ `{}`、
解析器缺陷（`RuntimeError`）→ **向外抛**。

**门禁代价**：`broad-except` 882 → **880**（silent 不变）。这一次**没有新增任何 import** ——
`(OSError, TypeError, ValueError)` 是字面量元组，不是 `INTERNAL_EXCEPTION_TYPES` 的子集
（有 OSError 与 ValueError 两个外部成员），所以元组归属门禁放行，耦合数一分未动。

### 1.4 第四批：`upi_link` 两处 + `proxy/admin._cached_geo`（共四个 handler）

四个点位一起做，因为它们是同一类：**被调方已经把异常面收窄了，或者本来就是"降级"语义**。

| 位置 | 收窄成 | 依据 |
| --- | --- | --- |
| `upi_link/config._upi_retarget_region` | `(ImportError, TypeError, ValueError)` | 惰性导入 + `retarget_region` 自己把 `urlsplit` 收窄成 TypeError/ValueError 并返回入参 |
| `upi_link/india_exit._upi_exit_country` | `(OSError, TypeError, ValueError)` | 地理查询是**网络读**：传输失败是 OSError，解析拒绝是 TypeError/ValueError |
| `upi_link/india_exit._upi_rotate_region_session` | 同上 | 换会话同样解析凭证模板（TypeError/ValueError）也可能走线（OSError） |
| `proxy/admin._cached_geo` | `(ImportError, OSError, TypeError, ValueError)` | 惰性导入 + 缓存文件读（OSError）+ 缓存键解析（TypeError/ValueError） |

**这批的共同点**：四个 handler 的 `return` 值（原样代理 / 空国家 / 原代理 / 空 geo）都是
**"没有答案"**，而缺陷此前也被塞进同一个返回值里。现在缺陷向外抛。

**测试（这一步是泳道级决策的真实代价）**：

| 文件 | 处理 |
| --- | --- |
| `tests/payment/test_upi_india_exit.py` | **两处既有替身从 `RuntimeError` 换成 `OSError`**（`test_exit_country_is_empty_when_geo_fails`、`test_a_raising_rotate_keeps_the_candidate_instead_of_crashing`）——它们要验的是"传输失败降级"，就必须喂 `TRANSPORT_ERRORS` 成员；另新增两条缺陷外抛测试 |
| `tests/payment/test_upi_config_region.py` | **新文件**（此前零覆盖）：5 条 —— 重定向成功、无模板不动、国家码非法短路、解析拒绝保留原值、**缺陷外抛** |
| `tests/proxy/test_proxy_admin.py` | 新增 4 条 `_cached_geo`：缓存命中、未测过为空、缓存读失败为空、**缺陷外抛** |

**门禁代价**：`broad-except` 880 → **876**（files 184 → 182），silent 不变；同样**零新增 import**
（四个元组都是字面量，都含外部成员 → 不是 `INTERNAL_EXCEPTION_TYPES` 子集），
`sunk-copy parity` 3 对仍一致（`upi_link` 是沉底副本泳道，改前改后都跑了）。

### 1.5 第五批：两处"读缓存/探测"包装（`batch_runner._cached_exit_ip`、`payment/qualification._measured_country`）

§1.4 的直接同构，所以一起做：

| 位置 | 收窄成 | 依据 |
| --- | --- | --- |
| `batch_runner._cached_exit_ip` | `(OSError, TypeError, ValueError)` | 只读共享 geo 缓存：缓存文件读（OSError）+ 缓存键解析（TypeError/ValueError） |
| `payment/qualification._measured_country` | `(ImportError, OSError, TypeError, ValueError)` | 惰性导入 + `resolve_proxy_geo` 的真实网络探测 |

**为什么值得动**：两处都返回 `""`，而 `""` 在调用方的语义是**"这个出口没测过"**。
一个 bug 此前和"没测过"完全同义 —— 现在只有真的失败才是 `""`。

**测试**：`_cached_exit_ip` 新增两条（缓存读失败 → `""`、`RuntimeError` → 外抛）；
`_measured_country` 新增一条（探测缺陷 → 外抛，先 `monkeypatch.undo()` 绕开 autouse fixture）。

**门禁代价**：`broad-except` 876 → **874**，silent 不变，**零新增 import**。

### 1.6 第六批：两处"惰性导入 + 读取配置"的池解析（`codex_oauth`、`proxy/registry`）

| 位置 | 收窄成 | 依据 |
| --- | --- | --- |
| `codex_oauth._configured_mailbox_index` | `(ImportError, OSError, TypeError, ValueError)` | 惰性导入 + `load_mailbox_pool()`（**无参调用**，只读配置与 token 文件，不购买不轮询） |
| `proxy/registry.resolve_mailbox` | 同上 | 惰性导入（拉 provider 适配器）+ 配置读取 + 候选解析 |

两处的 `{}` / `[]` 在调用方的语义都是**"没有配置邮箱池"**，而缺陷此前同义。

**测试**：`_configured_mailbox_index` 带 `@lru_cache(maxsize=1)`，所以两个用例都先
`cache_clear()` 并用 `addCleanup` 复原 —— 否则第一次缓存的 `{}` 会让"缺陷是否外抛"永远
测不出来（**这正是我第一次写这两条时踩到的**）。`resolve_mailbox` 的两条走 legacy 路径
（无 canonical lane）才有那个 handler。

**门禁代价**：`broad-except` 874 → **872**，silent 不变，**零新增 import**。

### 1.7 第七批：两处"惰性导入 + 配置读取"（`paypal/protocol._load_config`、`payment/qualification_batch._dedicated_pool`）

| 位置 | 收窄成 | 依据 |
| --- | --- | --- |
| `paypal/protocol._load_config` | `(ImportError, OSError, TypeError, ValueError)` | 惰性导入 + 分片读/合并 |
| `payment/qualification_batch._dedicated_pool` | 同上 | 被调方 `configured_qualification_proxy_pool` 自己惰性导入 config + routing，再解析 lane 池 |

**这一批有一处刻意的"不捕获"**：`_load_config` **不捕 `ConfigError`**。理由是它唯一的调用方
`_paypal_redirect_impersonate` 已经把任何异常降级成 `"chrome136"`，而在这里返回 `{}` 会把
"配置坏了"伪装成"什么都没配"。**同一份失败，交给本来就知道该怎么降级的那一层处理。**

**测试**：`_load_config` 新增两条（分片读失败 → `{}`、合并缺陷 → 外抛）；
`_dedicated_pool` 新增两条（lane 池读失败 → `[]`、缺陷 → 外抛），都通过 patch 模块级名字
（`pqb.configured_qualification_proxy_pool` / `sms_tool.config.load_merged_config`）注入。

**门禁代价**：`broad-except` 872 → **870**，silent 不变，**零新增 import**。

### 1.8 第八批：`smsbower` 两处网络调用收窄，以及一处**判定为不可收窄**的站点

**收窄（E 类 · 2 处 → 0）**：

| 位置 | 前 | 后 |
| --- | --- | --- |
| `smsbower.complete` | `except Exception: return False` | `except _requests.RequestException:` |
| `smsbower.request_additional` | 同上 | 同上 |

依据是**调用链本身就写明了异常面**：`set_status` → `_do` → `_requests.get(...)` +
`raise_for_status()`。所以 `requests.RequestException` 同时覆盖传输失败与 HTTP 4xx/5xx，
而 `requests` 在本文件已经是**模块级别名 `_requests`** —— **零新增 import、零耦合代价**。
测试四条（`ConnectionError` / `Timeout` 降级为 `False`，`RuntimeError` 外抛）。

**判定为不可收窄（一个 A 类长相、其实是 never-raises 契约的站点）**：

`upi_link/dump._upi_dump_http` 曾在 A 类表里（「文件 IO」）。核对 docstring 后**保持宽**：

> **绝不抛异常**：dump 是诊断辅助，不能因为它自己的问题（磁盘满、权限不足、
> **响应对象没有 `.text`**）把主流程带崩。所有失败都吞掉并返回 `""`。

第三条枚举的正是 `AttributeError` —— 收窄成 `(OSError, TypeError, ValueError)` 会把它放出去，
**违反 docstring 写下的契约**；而把 `AttributeError` 加进元组又会让元组变成
`INTERNAL_EXCEPTION_TYPES` 的子集（元组归属门禁拒绝）。所以它归 **D 类（never-raises 契约）**，
与 `http_client._is_edge_challenge` 同类。

⇒ **这一批的意义不只是 −2**：它给出了模板的**否定判据** —— 当 docstring 明确承诺「绝不抛出」、
并且枚举了 `AttributeError` 这类内部异常时，**宽是对的**，硬收窄才是 bug。

### 1.9 第九批：ASN 台账与注册亲和（`proxy/asn_registry` 两处 + `proxy/routing`）

| 位置 | 收窄成 | 依据 |
| --- | --- | --- |
| `asn_registry._proxy_key` | `(ImportError, OSError, TypeError, ValueError)` | 两个惰性导入（`parse_proxy` / `ProxyHealthTracker`）+ 解析与 key 计算的拒绝 |
| `asn_registry.record_registration_outcome` | `(OSError, TypeError, ValueError)` | `AsnRegistry.from_config` 只建路径并**惰性**开日志库：OSError + 路径构造的 TypeError/ValueError |
| `routing._saved_registration_proxy` | `(ImportError, OSError, TypeError, ValueError)` | 惰性导入 + 账号身份查询 + URL 归一化 |

三处的返回值（`""`）在调用方都是**「这个出口/账号没有可用的身份」**，而缺陷此前同义。
`_proxy_key` 尤其重要：它给台账写 key，一个被吞掉的 bug 会变成"这个出口没有 ASN 归属记录"。

**测试**六条（三处各降级 + 外抛）：`parse_proxy` 抛 `ValueError` → `""`、`RuntimeError` → 外抛；
`AsnRegistry.from_config` 抛 `OSError` → `""`、`RuntimeError` → 外抛；`resolve_account_proxy`
抛 `ValueError` → `""`、`RuntimeError` → 外抛（后两条先 monkeypatch
`_use_registration_affinity` 让前置条件成立）。

**门禁代价**：`broad-except` 868 → **865**（files 182 → 181），silent 不变，**零新增 import**；
`extractor_parity` 与 `sunk_copy parity` 都复核过（`_proxy_key` 与 services 侧的
`shared_proxy_key` 是**同名分歧实现**，不是沉底副本，parity 数字未变）。

### 1.10 第十批：一处收窄，七处**降级为"判据上不该动"并附文档依据**

**收窄 1 处**：`auth_headers._timezone_offset_minutes` → `(ImportError, TypeError, ValueError)`。
被调方 `geo.clock.offset_minutes_for_timezone` **自己就会降级**（空白/未知名字返回 `default`，
缺 tzdata 时警告一次），所以这层剩下的只有惰性导入。此前一个 bug 会被读成"UTC"。

**其余 7 处重新分类**（从 A 类移出，不再算"待收窄"）：

| 位置 | 移入 | 依据（文件自己写的） |
| --- | --- | --- |
| `batch_runner._hold_environment_lease` | D · never-fatal | 注释：租约是观测通道，**绝不能拖垮批次** |
| `chatgpt_bootstrap._timezone_offset_minutes` | C · 第三方错误类型 | `page.evaluate` 抛的是浏览器驱动自己的 `Error`，不是 ValueError |
| `doctor._phone_provider_rows` | D · advisory | `# pragma: no cover - advisory only`：配置坏掉时正是 doctor 被用来诊断的时候 |
| `doctor._phone_key_collisions` | D · advisory | 同上 |
| `doctor.unread_config_keys_safe` | D · advisory | 同上 |
| `http_client._is_edge_challenge` | D · never-raises | 注释：**观测绝不能把传输回包变成崩溃**（且有 `class Exploding` 替身钉住） |
| `http_client._report_edge_challenge` | D · never-raises | 注入的 hook 可以抛任何东西；失败必须退回今天的行为 |
| `payment/wire._checkout_sentinel_headers` | D · never-fatal | docstring：**Never fatal**，缺本地 runner 就降级成无 header，调用方保留自己的重试/分类路径 |

⇒ **A 类清空**。这不是"剩下的不做了"，而是**判据用完了**：这 8 处要么其 docstring/注释就是
"绝不抛出/绝不能失败"的契约（D 类），要么异常类型来自第三方且不是 Python 内建层（C 类）。
硬收窄它们不是改进，是把「契约」改成「偶尔崩」。

⇒ **这就是下一个泳道级点位的模板**：找出泳道自带的错误类型 → 读者不再吞 → 调用方用窄元组
记原因 → 更新喂 `object()`/`RuntimeError` 的替身 → 三条棘轮各自记录代价。

## 2. 剩下 17 处：为什么必须宽着

> 表的"收窄要先动"一列是**测试文件**，不是"改一行代码"：这些 handler 的宽度被行为测试
> 或注入的替身钉住，改之前得先确认那些替身喂进去的东西是否还成立。

### A. try 体调用的是别处的函数（异常面不在本文件里）— 0 处

**已清空**：本类最后 8 处经核对全部属于「docstring/注释就是 never-raises 或 never-fatal 契约」（移入 D 类）或「第三方错误类型」（移入 C 类），逐条依据见 §1.10。

| 位置 | try 体调用的东西 | 为什么宽着 | 收窄要先动 |
| --- | --- | --- | --- |
| ~~`upi_link/config` + `india_exit` 两处 + `proxy/admin._cached_geo`~~ | 见 §1.4 | **已按 §1.4 解决**：被调方已收窄或本就是降级语义，照抄即可 | — |
| ~~`batch_runner._cached_exit_ip` + `payment/qualification._measured_country`~~ | 见 §1.5 | **已按 §1.5 解决**（读缓存/探测包装，与 §1.4 同构） | — |
| ~~`codex_oauth._configured_mailbox_index` + `proxy/registry.resolve_mailbox`~~ | 见 §1.6 | **已按 §1.6 解决**（惰性导入 + 配置读取，照抄被调方面） | — |
| ~~`paypal/protocol._load_config` + `payment/qualification_batch._dedicated_pool`~~ | 见 §1.7 | **已按 §1.7 解决**；`_load_config` 刻意不捕 `ConfigError`，交给已知如何降级的调用方 | — |
| ~~`proxy/asn_registry._proxy_key` + `record_registration_outcome` + `proxy/routing._saved_registration_proxy`~~ | 见 §1.9 | **已按 §1.9 解决**：被调方异常面明确，照抄即可 | — |
| ~~`proxy/admin.py` `_health_rank` 两处~~ | `ProxyHealthTracker` / `resolve_registration` / `rank` | **已按 §1.3 解决**：被调方自己文档化了 `(OSError, TypeError, ValueError)`，照抄即可 | — |

### B. 形状的自然元组是 `INTERNAL_EXCEPTION_TYPES` 的子集 — 3 处

`scripts` 的门禁（`tests/governance/test_internal_exception_owner.py`）禁止手抄内核常量，
**子集也算抄**。要么导入常量（本仓多数这几处是 root 模块，会给已冻结的
`sms_tool -> sms_tool/kernel` 边 +1），要么保留宽 + 标记。目前保留宽。

| 位置 | try 体 | 自然元组 | 收窄要先动 |
| --- | --- | --- | --- |
| `account_creation.py:154` `_is_wrong_email_otp_code` | `(data or {}).get("body", {}).get("error", {})` 链 | `(AttributeError, TypeError)` → 子集 | `tests/registration/test_registration_operations.py` 等 3 个文件 |
| `auth_headers.py:470` `_auth_fingerprint_config` | 惰性导入 + `CFG.get` 链 | `(AttributeError, ImportError, TypeError)` → 子集 | `tests/registration/test_auth_headers_and_classification.py` |
| `sentinel_tokens.py:132` `_cookie_jar_header` | 供应商 cookie jar 的属性探测 | `(AttributeError, TypeError)` → 子集 | `tests/registration/test_registration_concurrency.py` |

### C. 第三方解析器的错误类型不是 `ValueError` — 3 处

| 位置 | try 体 | 为什么宽着 | 收窄要先动 |
| --- | --- | --- | --- |
| `chatgpt_bootstrap.py:116` `_timezone_offset_minutes` | `page.evaluate(...)` | 浏览器驱动抛的是它自己的 `Error`，**不是** ValueError | — |
| `providers/cfworker_client.py:436` `_decode_rfc822_body` | `Parser(policy=...).parsestr(...)` | `email.errors.MessageError` **不是** ValueError 的子类；按 `(TypeError, ValueError)` 收窄会漏掉真正的畸形邮件 | — |
| `providers/cfworker_client.py:465` `_decode_header_value` | `make_header(decode_header(...))` | `email.errors.HeaderParseError`，同上 | `tests/mailbox/test_cfworker_client.py` |

### D. 外部资源 / 宿主数据库 / never-raises 契约 — 11 处

| 位置 | try 体 | 为什么宽着 | 收窄要先动 |
| --- | --- | --- | --- |
| `batch_runner.py:230` `_hold_environment_lease` | `acquire_environment_lease` | 自己的注释：租约是观测通道，**绝不能拖垮批次** | `tests/accounts/test_batch_environment_lease.py` |
| `doctor.py:179` `_phone_provider_rows` | `provider_key_status(...)` | doctor 是 advisory 工具：配置坏掉时正是它被用来诊断的时候 | — |
| `doctor.py:212` `_phone_key_collisions` | `provider_key_collisions(...)` | 同上 | — |
| `doctor.py:473` `unread_config_keys_safe` | `cached_unread_config_keys()` | 同上（`# pragma: no cover - advisory only`） | — |
| `http_client.py:96` `_is_edge_challenge` | `edge_challenge_verdict(response)` | 注释：**观测绝不能把传输回包变成崩溃** | `tests/registration/test_edge_challenge_verdict.py`（含 `class Exploding` 替身，属性故意抛 RuntimeError） |
| `http_client.py:128` `_report_edge_challenge` | 注入的 `hook(...)` | 钩子是外部注入的，可以抛任何东西；失败必须退回今天的行为 | — |
| `payment/wire.py:312` `_checkout_sentinel_headers` | 惰性导入 + `checkout_sentinel_headers(...)` | docstring：**Never fatal** —— 缺本地 runner 就降级成无 header，调用方保留自己的重试/分类路径 | — |
| `browser_pool.py:145` `_browser_footprint_mb` | psutil 进程树遍历（内层已按 `_psutil.Error` 收窄） | 外层是 advisory 内存测量：`# noqa: BLE001 - advisory measurement only` | — |
| `upi_link/dump.py` `_upi_dump_http` | `directory.mkdir` + `path.write_text` + 格式化帮手 | docstring 承诺「绝不抛异常」，并明确枚举「响应对象没有 `.text`」——即 `AttributeError`；收窄会违反该契约，加进元组又成内部子集（见 §1.8） | — |
| `pp_link_helpers.py:692` `reserve_billing_variant` | 跨进程锁 + JSON 读写 | 自己的注释：`GateTimeoutError`、`OSError`、JSON 垃圾、**以及其它任何东西**都必须降级，因为身份是 advisory | `tests/payment/test_paypal_pp_link_helpers.py` |
| `batch_runner.py:688` `_prewarmed_sentinel` | `future.result()` | `result()` **会重新抛出 worker 的任意异常** —— 收窄在语义上不可能 | — |

### E. try 体里就是网络调用 — 0 处

| 位置 | try 体 | 为什么宽着 | 收窄要先动 |
| --- | --- | --- | --- |

*（注：`payment/capability.py` 的 `_read_payment_methods_signal` 曾是这一类的第二个点位，
现已按 §1.1 的泳道级决策解决，不再出现在候选里。）*

## 3. 想继续推进这条轴，只有两条路（都是泳道级决策）

1. **把"探针失败"变成结构化错误**：例如 `agent_identity` 那几处、`payment/capability`
   的读取点，改成返回一个有类型的失败对象而不是"任意异常 → 空字典"。这样 handler 才能收窄成
   `except TRANSPORT_ERRORS`。动它要连改注入这些替身的测试（典型是裸 `object()` 当响应），
   一次要动几十个用例，**必须单独立项**。
2. **给某个泳道单独放宽 import 预算**：C 类那三处若要导入 `INTERNAL_EXCEPTION_TYPES`，
   要给 `sms_tool -> sms_tool/kernel` 加边（现在 35 条顶死）。除非同时删掉别的边，否则不放。

两条都不该在"逐文件切片"里顺手做 —— 这正是方案 Phase 6 写的"先做跨泳道的结构回退类，
再单独立项处理泳道内的宽 handler"。**第一半已完成（959 → 864，十批泳道级决策，A 类清空）；第二半的第一个
点位已按 §1.1 落地，其余需要排期，不需要重新调研。**

## 4. 每次收窄的固定八步（沉淀下来）

1. 量：`python scripts/broad_except_ratchet.py`（记下 before）；
2. 判类：按 §2 的五类对号入座，不属任何一类才动手；
3. 写：按"这个形状实际能抛什么"写元组，**行尾注释**写理由（独立注释行会让冻结函数变长）；
4. 元组归属：不得是 `INTERNAL_EXCEPTION_TYPES` 的子集（`tests/governance/test_internal_exception_owner.py`）；
5. 沉底副本：碰 `upi_link` / `paypal_link` / `gen_pp_link` 先跑 `python scripts/sunk_copy_parity.py`；
6. 重冻：`python scripts/broad_except_ratchet.py --write`（lanes / whitelist / budget_history 会保留）；
7. 验：`pyright` 必须 0 error（它能看见惰性再导出表与跨模块属性），`function_length_ratchet` 0 tighten；
8. 指针与全量：`refresh_doc_symbol_lines.py --apply` → `pytest -q -n 4 --dist loadfile`。
