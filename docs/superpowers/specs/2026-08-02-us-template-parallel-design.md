# 美国站升级 — 中文模板 A–M、三标签并发、2–3 秒节奏

**日期:** 2026-08-02
**范围:** `shein-extract`（美国站）
**分支:** `feat/us-template-refactor`（基于 `main` @ `fc26dd6`）
**状态:** 已批准，进入实施计划。

## 动机

三条改进，一次发布。参照 `shein-extract-au` 在 2026-08-01 完成的同类重构
（commits `115018e` `846bba1` `1c5dc4d` `a4e469d` `79360ac` `cde7b20` `735137a`），
但**不做 cherry-pick**：两个仓库没有共同 git 历史，本次在美国仓库对照重写等价代码。

| # | 诉求 | 现状 | 本 spec |
|---|---|---|---|
| 1 | 三个页面同时抓 | 串行单标签循环 | `ThreadPoolExecutor(max_workers=3)`，每 worker 独占 tab |
| 2 | 间隔 2–3 秒，不要随机长等待 | 每 URL 随机 4–12 s，每 18 个插 30–90 s 长歇 | 每 URL 之间 `random.uniform(2, 3)`，长歇常量删除 |
| 3 | 新表格格式（A–E 手填 / F–M 程序填） | 旧英文 5 列（A=Seq B=Website C=Price D=Date E=Status） | 中文表头 A–M，旧格式彻底删除 |

参考模板：`D:\共享云端硬盘\02 希音\01 店铺资料\99 ZR\美国希音链接汇总 - ZR.xlsx`
（sheet 名 = 店铺名，如 `ZR1`；该文件 N–U 列属于澳洲未合并的比价功能，本次不涉及）。

## §1 新模板 schema

**列定义（A–M，中文表头）：**

| 列 | 表头 | 方向 | 语义 |
|----|------|------|------|
| A | 编号 | 读 | 序号，同时是输出子文件夹名（等同旧 `Seq`） |
| B | 链接 | 读 | Shein 商品 URL |
| C | 原价 | 读 | 手填售价 (USD)。空 → 回退网页抓到的 `data['price']` |
| D | 运费 | 读 | 手填运费 (USD)。空 → 回退 `_calc_shipping()` 推导（满免 → $0，否则 `DEFAULT_SHIPPING_FEE` = $2.99） |
| E | 变体 | 读 | 空 = 抓全部变体。填了 = 只抓/只输出列出的值 |
| F | 日期 | 写 | 运行日期 `YYYY-MM-DD` |
| G | 状态 | 写 | `Done` / `Failed` / `Delisted` |
| H | 图片 | 写 | 嵌入首张商品图（复用 `_add_picture_to_cell`） |
| I | 希音价格 | 写 | 抓到的售价。单值 → 数字（不带 `$`）；多变体价格不同 → 区间字符串 `9.99–14.99`。**纯核对用，不进任何公式** |
| J | 希音标题 | 写 | 原始 h1 标题，不加工 |
| K | eBay标题 | 写 | AI 生成（Claude Haiku 4.5），失败回退 `_make_ebay_title()` 规则 |
| L | eBay价格 | 写 | `(C原价 或 抓到价 + D运费 或 推导运费) × EBAY_MARKUP`，`EBAY_MARKUP` = 1.4。单一标量 |
| M | 库存 | 写 | 单行、变体斜杠分隔：`黑色-M: 12 / 黑色-L: 缺货 / 红色-M: 少货 3` |

**行为规则：**

- **触发方式不变**：`run_excel.py` 读 `SUBMITTED_DIR / INPUT_FILENAME`（或命令行传入的文件）。
- **行选择**：`B (链接)` 有值 **且** `F (日期)` 与 `G (状态)` 都为空。
- **重跑**：清空 F + G 即可重新处理该行（与现状一致）。
- **非模板 sheet**：`B1` 不等于「链接」的工作表警告后跳过，不写任何单元格。
- **表头补齐**：程序不再改写表头（旧代码里 `col C → "Price"` / `col D → "Date"` 的补齐逻辑删除）。
- **eBay 标题**：K 列与 `图片-<sku>/eBay上架描述.txt` 里的标题保持同一个值。
- **L 列取值来源**：`C` 与 `D` 各自独立回退。C 填了 D 空 → `(C + 推导运费) × 1.4`；两个都空 → `(抓到价 + 推导运费) × 1.4`。
- **C 列价格的传播**（沿用 v3.7.0 已有行为）：C 填了不只覆盖主商品 price，`sku_prices` 里每个变体的 `sale_price` 同步覆盖，使批次 xlsx 的变体子行、txt 的「各变体价格」段与主行一致。

**E 列变体过滤 — 语法与匹配：**

- **语法**：组之间用 `/` 分隔，组内用逗号分隔。`"黑色, 红色 / M, L"` = 2 组 × 2 值 = 4 个组合。组的顺序不重要；匹配时忽略大小写与首尾空格。
- **单组（无 `/`）**：当作扁平白名单，与任意属性值比对。`"黑色, 红色"` 在「颜色+尺码」商品上保留黑色和红色的**所有**尺码。
- **对 `sku_prices` 的匹配**：一个变体被保留，当且仅当 E 里**每个非空组**都至少有一个值等于该 SKU 的某个属性值。
- **零匹配**：E 填了但扫到的变体一个都不匹配 → 该商品判为 `Failed`，原因 `variant_filter_no_match`（写进 debug log），**不写半截数据**。
- **部分匹配**：E 里有些值页面上不存在、但至少有一个存在 → 保留匹配到的，日志 warning 列出找不到的值。

## §2 旧英文格式移除

`run_excel.py` 里旧英文输入路径（`A=Seq / B=Website / C=Price / D=Date / E=Status`）整体删除，
包括表头补齐逻辑和按英文列号读写的所有调用点。

**保持不变的输出**（不属于本次改动）：

- **批次汇总 xlsx** `{store}-{minSeq}-{maxSeq}-{YYYYMMDD}.xlsx`（写在 `OUTPUT_ROOT/{store}/` 下）：
  仍是原来的英文表头布局、变体子行展开、嵌入图片。`merge_master.py` /
  `merge_store_reports.py` 消费的是它，因此**必须保持不变**。
- **每 SKU 文件夹** `图片-<sku>/` 及其 `eBay上架描述.txt`：内容和格式不变。
- `backup_excel()`（运行前备份输入表到 `BACKUP_DIR`）：保留。

## §3 路径配置

**不改动。** 现有模型已经满足需求，员工通过 `setup_wizard.py` 配置四项：

| 环境变量 | 向导里的名字 | ZR 的填法 |
|---|---|---|
| `SHEIN_SUBMITTED_DIR` | 输入 Excel 文件夹 | `D:\共享云端硬盘\02 希音\01 店铺资料\99 ZR` |
| `SHEIN_INPUT_FILENAME` | 输入 Excel 文件名 | `美国希音链接汇总 - ZR.xlsx` |
| `SHEIN_OUTPUT_DIR` | 输出根目录 | `D:\共享云端硬盘\02 希音\01 店铺资料\99 ZR` |
| `SHEIN_BACKUP_DIR` | 备份目录 | （员工自己的备份盘） |

输出落在 `SHEIN_OUTPUT_DIR / {sheet名} / {编号}/`，子目录不存在时自动创建（现状即如此）。

## §4 三标签并发

**架构：**

- 把现在 `scrape_shein()` 里 per-URL 的循环体抽成
  `_scrape_one_url(url, seq, override_price, override_shipping, variant_filter, index, total) -> record`。
- 用**一个** `ThreadPoolExecutor(max_workers=3)` 覆盖整个 URL 列表（不分批），
  `as_completed` 收集结果，最后按 `seq_num` 排序还原顺序。
- 每个 worker 自己 `_new_tab()` 拿 `tab_id` / `ws_url`，在 `finally` 里关闭。
- CDP 在 WebSocket 层是线程安全的（每次 `_cdp_once` 新开一条 WS），Chrome 侧无共享状态争用。

**并发安全：**

- **Excel 写入**：`run_excel.py` 里所有 `ws.cell(...).value = ...` 与 `safe_save()` 用同一把
  `threading.Lock` 串行化。
- **图片下载池**：`IMAGE_DOWNLOAD_WORKERS` 8 → 4（3 并发商品 × 4 = 12 sockets）。
- **限流计数器**：`RATE_LIMIT_CONSECUTIVE = 3` 改成 `threading.Lock` 保护的共享计数。
  触发时 `executor.shutdown(cancel_futures=True)` 后抛 `RateLimitError`，
  **但先排空已经在途的 future**，把已完成的记录并入返回值（对应澳洲 `cde7b20` 修的坑：
  否则整批已抓好的结果会一起丢掉）。
- **会话预热**：`_ensure_shein_session()` 仍然只跑一次，在创建 executor **之前**。
- **验证码 / 登录墙**：检测逻辑不变，仍是 per-tab。被验证码挡住的 tab 走它原有的 300 s 轮询等待，
  不阻塞另外两个 worker——代价是并发度临时降到 2。

**不变：**

- CDP 端口仍是 `9222`，持久化 profile 目录不变（单个 Chrome 实例开多个标签）。

## §5 节奏：每 URL 之间随机 2–3 秒

- 删除常量：`INTER_URL_DELAY_MIN`、`INTER_URL_DELAY_MAX`、`LONG_PAUSE_EVERY`、
  `LONG_PAUSE_MIN`、`LONG_PAUSE_MAX`。
- `_inter_url_pause()` 改成无参数的 `time.sleep(random.uniform(2, 3))`，由 worker 在**完成一条 URL 之后
  无条件**调用——包括它手上的最后一条。并发下判断「谁是最后一条」不可靠且不值得，代价只是整批多等 ≤3 秒。
  三个 worker 各自计时，整体请求速率约 1.2 req/s。
- **没有任何长暂停。**

## §6 check_stock.py 本次停用

新 schema 里 `E=变体 / F=日期 / G=状态`，而 `check_stock.py` 现在读第 5 列当 Status、
写第 6/7 列当 Stock / Last Checked——不处理就会写坏表。

本次做法：

- `check_stock.py` 检测到新模板（`B1 == "链接"`）时，打印
  「新表格的库存复查等 S/T/U 列上线后再支持」并跳过该 sheet，**一个单元格都不写**。
- 旧的复查逻辑代码保留不删。
- 之后等澳洲 `feat/ebay-price-check` 分支的 `S 重跑日期 / T 更新价格 / U 更新库存`
  三列定型，再一起对齐实现。**不在本 spec 范围内。**

## §7 测试

**单元测试（新增）：**

- `test_template_io.py`：给一个混合了「已填 / 未填 / 缺编号 / 原价非数字」的模板 fixture，
  验证只挑出该处理的行；验证 F–M 写入落在正确列号。
- `test_variant_filter.py`：一个有 8 个变体的商品 + E 列 `"黑色, 红色 / M"`，
  验证只剩黑色-M 和红色-M；验证零匹配返回 `variant_filter_no_match`；验证部分匹配的 warning。
- `test_price_stock_format.py`：验证 I 列单值 → 数字、多价 → `9.99–14.99` 区间串；
  验证 M 列格式；验证 L 列公式对 C/D 各自的回退。

**现有测试：** `test_variant_merge.py` 必须继续通过。

**手工端到端验证**（跑一个 sheet）：

1. 单变体商品 → `Done`，I 列是数字不是区间
2. 多变体 + E 列填了 → M 列只含声明的变体
3. 多变体 + E 列空 → M 列是完整清单
4. 已下架商品 → `Delisted`
5. 连续失败 3 次的 URL → `Failed`，且同批已完成的行结果不丢

**并发验证：** 15 个 URL 的批次，墙钟时间大致降到串行的 1/3
（粗略验收——验证码和重试会造成离群值）。

## §8 迁移与兼容

- 员工手上没跑完的**旧英文表会停止被处理**（B1 不是「链接」→ 跳过并警告）。上线前需要通知。
- 输出批次 xlsx 消费方（`merge_master.py` 等）不受影响，英文格式原样保留。
- 库存复查功能本次暂时不可用（§6），需要一并通知。
- 版本号与 CHANGELOG 在整体完工后统一发 v3.8.0，不在实施过程中逐步 bump。

## §9 不做

- N–U 的 eBay 同类比价列（澳洲 `feat/ebay-price-check`，尚未合并）。
- `check_stock.py` 的 S/T/U 实现。
- 变体误关联的根因修复（澳洲记为已知问题；E 列声明可绕开大部分情况）。
- 每变体独立的 eBay 价格（L 列只写单一标量——用户承诺按行填 C 和 D）。
- `_EBAY_TITLE_PROMPT` 的提示词改动。
- `dashboard.py` / `state_tracker.py` / `merge_*.py` 的任何改动。

## §10 成功标准

- 员工填 A–E，跑 `run_excel.py`，F–M 正确填好；批次 xlsx 和 `图片-<sku>/` 文件夹照旧产出。
- L 列 = `(C + D) × 1.4`，$22 保底已在 `main` @ `fc26dd6` 移除，不再出现。
- 三标签并发生效，URL 之间间隔 2–3 秒，日志里没有任何长暂停。
- 旧英文表不再被处理，且不会被写坏。
- `check_stock.py` 对新表是安全的 no-op。
- §7 的新旧测试全部通过。
