# 美国站中文模板 + 三标签并发 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把美国站 `shein-extract` 换成中文表头 A–M 模板（A–E 手填 / F–M 程序填），抓取改成三标签并发，URL 之间固定 2–3 秒随机间隔。

**Architecture:** 先自底向上加**纯函数** helper（价格区间 / 库存串 / 变体过滤 / 行级覆盖），它们不碰浏览器所以可以直接 TDD。然后把 `scrape_shein()` 里的 per-URL 循环体抽成 `_scrape_one_url()`，把调度抽成 `_run_scrape_pool()`——调度器只依赖 `_scrape_one_url`，测试时打桩即可，不需要启动 Chrome。最后改 `run_excel.py` 的读写层和 `check_stock.py` 的保护。

**Tech Stack:** Python 3.11+、`openpyxl`、`concurrent.futures.ThreadPoolExecutor`、Chrome DevTools Protocol（`websocket-client`）。测试是仓库现有风格的独立脚本（裸 `assert` + `if __name__ == "__main__"` + 末尾 `print("ALL PASS")`），用 `python test_xxx.py` 运行，**没有 pytest**。

**Spec:** `docs/superpowers/specs/2026-08-02-us-template-parallel-design.md`
**分支:** `feat/us-template-refactor`（已创建，基于 `main` @ `fc26dd6`）

## Global Constraints

- 输出的**批次汇总 xlsx**（`{store}-{minSeq}-{maxSeq}-{YYYYMMDD}.xlsx`，英文表头、变体子行、嵌图）**不得改动**——`merge_master.py` / `merge_store_reports.py` 消费它。
- `图片-<sku>/` 文件夹与 `eBay上架描述.txt` 的内容和格式**不得改动**。
- `dashboard.py` / `state_tracker.py` / `merge_*.py` / `config.py` / `setup_wizard.py` **不得改动**。
- `EBAY_MARKUP = 1.4`；eBay 价公式 = `(C原价 或 抓到价 + D运费 或 推导运费) × 1.4`。**没有任何保底价。**
- `DEFAULT_SHIPPING_FEE = 2.99`；D 列为空时回退 `_calc_shipping()`（满免 → 0.0）。
- `MAX_PARALLEL_TABS = 3`，`IMAGE_DOWNLOAD_WORKERS = 4`，`RATE_LIMIT_CONSECUTIVE = 3`，`LOW_STOCK_THRESHOLD = 15`。
- CDP 端口保持 `9222`，`PERSISTENT_PROFILE_DIR` 不变。
- 中文列名固定为：`编号 链接 原价 运费 变体 日期 状态 图片 希音价格 希音标题 eBay标题 eBay价格 库存`（A–M）。
- 价格区间分隔符是 **en-dash `–` (U+2013)**，不是 hyphen。
- 版本号和 CHANGELOG **只在 Task 10 动一次**，中间任务不 bump。
- 所有测试文件放仓库根目录，命名 `test_*.py`，跑法 `python test_*.py`，必须以 `print("ALL PASS")` 结束。

## 与 spec 的两处偏离（已在计划中定案）

1. **`run_excel.py` 不需要 `threading.Lock`。** spec §4 出于谨慎要求给 Excel 写入加锁，但实际架构里并发**完全发生在 `scrape_shein()` 内部**：它返回全部 records 之后，`run_excel.py` 才在主线程里串行写单元格。没有并发写，锁是死代码。因此不加。
2. **变体过滤在计算 I 列价格之前执行。** spec 没规定顺序。定为：先按 E 列过滤 → 用过滤后的变体算 I 列价格区间 → 再套用 C 列覆盖。这样 I 列反映的是"用户实际要的那些变体"的网页价，核对起来才有意义。

## File Structure

| 文件 | 动作 | 职责 |
|---|---|---|
| `shein_scraper.py` | 改 | Task 1–6：新增 4 个纯函数 helper、改节奏常量、抽 `_scrape_one_url` / `_run_scrape_pool`、`scrape_shein` 新增两个参数 |
| `run_excel.py` | 改 | Task 7–8：中文模板 reader/writer + `process_excel` 重写，删除旧英文路径 |
| `check_stock.py` | 改 | Task 9：新模板上变成安全 no-op |
| `test_price_stock_format.py` | 新建 | Task 1：I 列价格区间 + M 列库存串 |
| `test_variant_filter.py` | 新建 | Task 2：E 列声明式过滤 |
| `test_pacing.py` | 新建 | Task 3：2–3 秒间隔，长歇常量已删除 |
| `test_row_overrides.py` | 新建 | Task 4：C/D/E 三列覆盖的合成逻辑 |
| `test_rate_limit.py` | 新建 | Task 5：线程安全限流计数器 |
| `test_scrape_pool.py` | 新建 | Task 6：并发度上限、结果排序、限流排空 |
| `test_template_io.py` | 新建 | Task 7–8：模板读写 + `process_excel` 端到端（打桩 `scrape_shein`） |
| `test_check_stock_skip.py` | 新建 | Task 9：新模板 no-op |
| `ARCHITECTURE.md` / `CHANGELOG.md` / `version.py` | 改 | Task 10 |

---

### Task 1: 价格区间 + 库存串 helper

**Files:**
- Modify: `shein_scraper.py`（在 `_ebay_listing_price()` 之后插入，约 line 1229 后）
- Test: `test_price_stock_format.py`

**Interfaces:**
- Consumes: 模块级常量 `LOW_STOCK_THRESHOLD`（已存在，值 15）
- Produces:
  - `_format_price_range(sku_prices: list) -> float | str | None`
  - `_format_stock_summary(sku_prices: list) -> str`

`sku_prices` 的元素形状（现有抓取结果，不要改）：
```python
{"sku_code": "sr2604...", "sale_price": 12.99, "stock": 42,
 "attrs": {"Color": "Black", "Size": "M"}}
```

- [ ] **Step 1: 写失败的测试**

创建 `test_price_stock_format.py`：

```python
"""Test: I 列价格区间 + M 列库存串的格式化。
Run: python test_price_stock_format.py
"""
from shein_scraper import _format_price_range, _format_stock_summary


def test_price_range_single_value_returns_number():
    skus = [{"sale_price": 12.99, "stock": 5, "attrs": {"Color": "Black"}}]
    assert _format_price_range(skus) == 12.99


def test_price_range_all_equal_returns_number():
    skus = [{"sale_price": 9.5}, {"sale_price": 9.5}, {"sale_price": 9.5}]
    assert _format_price_range(skus) == 9.5


def test_price_range_differing_returns_endash_string():
    skus = [{"sale_price": 9.99}, {"sale_price": 14.99}, {"sale_price": 12.0}]
    assert _format_price_range(skus) == "9.99–14.99"


def test_price_range_ignores_none_and_garbage():
    skus = [{"sale_price": None}, {"sale_price": "abc"}, {"sale_price": 7.25}]
    assert _format_price_range(skus) == 7.25


def test_price_range_empty_returns_none():
    assert _format_price_range([]) is None
    assert _format_price_range(None) is None


def test_stock_summary_labels_by_attrs():
    skus = [
        {"attrs": {"Color": "Black", "Size": "M"}, "stock": 42},
        {"attrs": {"Color": "Black", "Size": "L"}, "stock": 0},
        {"attrs": {"Color": "Red", "Size": "M"}, "stock": 3},
    ]
    assert _format_stock_summary(skus) == "Black-M: 42 / Black-L: 缺货 / Red-M: 少货 3"


def test_stock_summary_low_threshold_boundary():
    # LOW_STOCK_THRESHOLD == 15: 15 是少货，16 是普通数字
    skus = [{"attrs": {"Size": "M"}, "stock": 15},
            {"attrs": {"Size": "L"}, "stock": 16}]
    assert _format_stock_summary(skus) == "M: 少货 15 / L: 16"


def test_stock_summary_falls_back_to_sku_code():
    skus = [{"attrs": {}, "sku_code": "sr123", "stock": 8}]
    assert _format_stock_summary(skus) == "sr123: 少货 8"


def test_stock_summary_empty_returns_empty_string():
    assert _format_stock_summary([]) == ""


if __name__ == "__main__":
    test_price_range_single_value_returns_number()
    test_price_range_all_equal_returns_number()
    test_price_range_differing_returns_endash_string()
    test_price_range_ignores_none_and_garbage()
    test_price_range_empty_returns_none()
    test_stock_summary_labels_by_attrs()
    test_stock_summary_low_threshold_boundary()
    test_stock_summary_falls_back_to_sku_code()
    test_stock_summary_empty_returns_empty_string()
    print("ALL PASS")
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python test_price_stock_format.py`
Expected: `ImportError: cannot import name '_format_price_range' from 'shein_scraper'`

- [ ] **Step 3: 实现**

在 `shein_scraper.py` 的 `_ebay_listing_price()` 之后、`_merge_main_sale_attr_colors()` 之前插入：

```python
def _format_price_range(sku_prices: list):
    """I 列（希音价格）。所有变体价格相同 → 返回数字（让 Excel 当数值处理）；
    不同 → 返回字符串区间 'LO–HI'（en-dash U+2013，不带货币符号）；
    没有任何有效价格 → None。None / 非数字的 sale_price 直接忽略。"""
    prices = []
    for sp in sku_prices or []:
        p = sp.get("sale_price")
        if p is None:
            continue
        try:
            prices.append(float(p))
        except (TypeError, ValueError):
            continue
    if not prices:
        return None
    lo, hi = min(prices), max(prices)
    if lo == hi:
        return round(lo, 2)
    return f"{lo:.2f}–{hi:.2f}"


def _format_stock_summary(sku_prices: list) -> str:
    """M 列（库存）单行摘要。

    格式：'<标签>: <数量>'，条目之间用 ' / ' 连接。标签是属性值按插入顺序
    用连字符拼起来（如 'Black-M'）；没有属性时退回 sku_code。数量为 0 → 缺货，
    1..LOW_STOCK_THRESHOLD → '少货 N'，更大 → 纯数字。
    """
    def _label(sp: dict) -> str:
        vals = [str(v).strip() for v in (sp.get("attrs") or {}).values() if v]
        if vals:
            return "-".join(vals)
        return str(sp.get("sku_code") or "").strip() or "?"

    def _count(sp: dict) -> str:
        try:
            stk = int(sp.get("stock") or 0)
        except (TypeError, ValueError):
            stk = 0
        if stk == 0:
            return "缺货"
        if stk <= LOW_STOCK_THRESHOLD:
            return f"少货 {stk}"
        return str(stk)

    parts = [f"{_label(sp)}: {_count(sp)}" for sp in (sku_prices or [])]
    return " / ".join(parts)
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python test_price_stock_format.py`
Expected: `ALL PASS`

- [ ] **Step 5: 提交**

```bash
git add test_price_stock_format.py shein_scraper.py
git commit -m "feat(scraper): _format_price_range + _format_stock_summary for template I/M columns"
```

---

### Task 2: E 列变体声明过滤

**Files:**
- Modify: `shein_scraper.py`（在 Task 1 新增的两个函数之前插入）
- Test: `test_variant_filter.py`

**Interfaces:**
- Consumes: 标准库 `re`（`shein_scraper.py` 顶部已 `import re`）
- Produces:
  `_filter_variants_by_declaration(declaration: str, sku_prices: list, variations: dict) -> tuple[list, dict, list]`
  返回 `(kept_sku_prices, filtered_variations, unknown_declared_values)`。
  声明为空 → 原样返回 `(sku_prices, variations, [])`。
  声明非空但零匹配 → 返回 `([], {}, 全部声明值排序后的列表)`。

- [ ] **Step 1: 写失败的测试**

创建 `test_variant_filter.py`：

```python
"""Test: 模板 E 列（变体）的声明式过滤。
Run: python test_variant_filter.py
"""
from shein_scraper import _filter_variants_by_declaration


def _skus():
    """8 个变体：Black/Red/Blue/Green × M/L 的一个子集。"""
    out = []
    for color in ("Black", "Red", "Blue", "Green"):
        for size in ("M", "L"):
            out.append({
                "sku_code": f"sk-{color}-{size}",
                "sale_price": 10.0,
                "stock": 5,
                "attrs": {"Color": color, "Size": size},
            })
    return out


_VARS = {"Color": ["Black", "Red", "Blue", "Green"], "Size": ["M", "L"]}


def test_empty_declaration_returns_inputs_unchanged():
    skus = _skus()
    kept, vars_, unknown = _filter_variants_by_declaration("", skus, _VARS)
    assert kept is skus and vars_ is _VARS and unknown == []
    kept, vars_, unknown = _filter_variants_by_declaration("   ", skus, _VARS)
    assert len(kept) == 8 and unknown == []


def test_two_groups_intersect():
    kept, vars_, unknown = _filter_variants_by_declaration(
        "Black, Red / M", _skus(), _VARS)
    codes = sorted(s["sku_code"] for s in kept)
    assert codes == ["sk-Black-M", "sk-Red-M"], codes
    assert vars_ == {"Color": ["Black", "Red"], "Size": ["M"]}, vars_
    assert unknown == []


def test_single_group_is_flat_allowlist():
    # 没有 "/" → 扁平白名单，Black 和 Red 的所有尺码都保留
    kept, vars_, unknown = _filter_variants_by_declaration(
        "Black, Red", _skus(), _VARS)
    codes = sorted(s["sku_code"] for s in kept)
    assert codes == ["sk-Black-L", "sk-Black-M", "sk-Red-L", "sk-Red-M"], codes


def test_matching_is_case_and_whitespace_insensitive():
    kept, _, unknown = _filter_variants_by_declaration(
        "  bLaCk  /   m ", _skus(), _VARS)
    assert [s["sku_code"] for s in kept] == ["sk-Black-M"]
    assert unknown == []


def test_no_match_returns_empty_and_reports_all_declared():
    kept, vars_, unknown = _filter_variants_by_declaration(
        "Purple / XXL", _skus(), _VARS)
    assert kept == [] and vars_ == {}
    assert unknown == ["Purple", "XXL"], unknown


def test_partial_match_keeps_matches_and_reports_unknown():
    # Black 存在、Purple 不存在；组内是 or，所以 Black-M 保留
    kept, vars_, unknown = _filter_variants_by_declaration(
        "Black, Purple / M", _skus(), _VARS)
    assert [s["sku_code"] for s in kept] == ["sk-Black-M"]
    assert unknown == ["Purple"], unknown


def test_flat_variations_key_preserved_when_not_in_kept_attrs():
    # variations 里有一个 sku_prices attrs 里没有的键，其值命中声明 → 保留
    skus = [{"sku_code": "a", "sale_price": 1.0, "stock": 1,
             "attrs": {"Color": "Black"}}]
    vars_in = {"Color": ["Black", "Red"], "Style": ["Plain", "Fancy"]}
    kept, vars_out, _ = _filter_variants_by_declaration(
        "Black, Fancy", skus, vars_in)
    assert kept and vars_out["Color"] == ["Black"]
    assert vars_out["Style"] == ["Fancy"], vars_out


if __name__ == "__main__":
    test_empty_declaration_returns_inputs_unchanged()
    test_two_groups_intersect()
    test_single_group_is_flat_allowlist()
    test_matching_is_case_and_whitespace_insensitive()
    test_no_match_returns_empty_and_reports_all_declared()
    test_partial_match_keeps_matches_and_reports_unknown()
    test_flat_variations_key_preserved_when_not_in_kept_attrs()
    print("ALL PASS")
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python test_variant_filter.py`
Expected: `ImportError: cannot import name '_filter_variants_by_declaration'`

- [ ] **Step 3: 实现**

在 `shein_scraper.py` 里 Task 1 新增的 `_format_price_range()` **之前**插入：

```python
def _filter_variants_by_declaration(
    declaration: str,
    sku_prices: list,
    variations: dict,
) -> tuple[list, dict, list]:
    """按模板 E 列（变体）的声明限制 sku_prices 和 variations。

    `declaration` 语法：
      - 空 / 全空白 → 不过滤，原样返回输入。
      - 不含 "/"    → 扁平白名单；SKU 的任一属性值命中即保留
                      （忽略大小写和首尾空格）。
      - 含 "/"      → 组之间用 "/" 分隔、组内用逗号分隔。SKU 只有在
                      **每个非空组**都至少命中一个值时才保留。

    返回 (kept_sku_prices, filtered_variations, unknown_values)。
    `unknown_values` 是声明里从未匹配上任何保留变体的值，调用方打 warning。
    声明非空但一个都没匹配上 → kept 为 []、filtered_variations 为 {}。
    """
    decl = (declaration or "").strip()
    if not decl:
        return sku_prices, variations, []

    def _norm(s: str) -> str:
        return re.sub(r"\s+", " ", (s or "")).strip().lower()

    groups = [
        [_norm(v) for v in grp.split(",") if _norm(v)]
        for grp in decl.split("/")
    ]
    groups = [g for g in groups if g]  # 丢掉空组
    if not groups:
        return sku_prices, variations, []

    # 归一化值 → 用户原始大小写，用于报告 unknown
    all_declared_norm: dict[str, str] = {}
    for grp in decl.split("/"):
        for v in grp.split(","):
            n = _norm(v)
            if n:
                all_declared_norm[n] = v.strip()

    def _sku_matches(sku: dict) -> bool:
        attr_values = {_norm(v) for v in (sku.get("attrs") or {}).values() if v}
        if len(groups) == 1:
            return bool(attr_values & set(groups[0]))
        return all(bool(attr_values & set(g)) for g in groups)

    kept = [s for s in sku_prices if _sku_matches(s)]

    # seen 只从 kept 里统计：出现在被拒变体上的声明值仍算 unknown
    seen_norm: set[str] = set()
    for sp in kept:
        for v in (sp.get("attrs") or {}).values():
            n = _norm(v)
            if n in all_declared_norm:
                seen_norm.add(n)

    unknown = sorted(all_declared_norm[n]
                     for n in set(all_declared_norm) - seen_norm)

    if not kept:
        return [], {}, sorted(all_declared_norm.values())

    # 用保留下来的 SKU 重建 variations，让下游（标题 / txt / M 列）只看到声明的值
    filtered_vars: dict[str, list] = {}
    for sp in kept:
        for k, v in (sp.get("attrs") or {}).items():
            if not v:
                continue
            filtered_vars.setdefault(k, [])
            if v not in filtered_vars[k]:
                filtered_vars[k].append(v)
    # 原 variations 里没被 SKU attrs 覆盖的键（罕见的扁平属性）：值命中声明就保留
    for k, vals in (variations or {}).items():
        if k in filtered_vars or not isinstance(vals, list):
            continue
        keep = [v for v in vals if _norm(v) in all_declared_norm]
        if keep:
            filtered_vars[k] = keep

    return kept, filtered_vars, unknown
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python test_variant_filter.py`
Expected: `ALL PASS`

- [ ] **Step 5: 提交**

```bash
git add test_variant_filter.py shein_scraper.py
git commit -m "feat(scraper): _filter_variants_by_declaration for template E column"
```

---

### Task 3: 节奏改成每 URL 之后随机 2–3 秒

**Files:**
- Modify: `shein_scraper.py:73-79`（常量块）、`shein_scraper.py:95-106`（`_inter_url_pause`）
- Test: `test_pacing.py`

**Interfaces:**
- Produces: `_inter_url_pause() -> None`（**无参数**，签名从 `(i, total)` 改掉）；
  常量 `INTER_URL_PAUSE_MIN = 2.0`、`INTER_URL_PAUSE_MAX = 3.0`
- 破坏性变更：`scrape_shein()` 里现有 6 处 `_inter_url_pause(i, len(urls))` 调用会因参数个数报错——本任务**一并改成无参调用**，Task 5 再把它们挪进 worker。

- [ ] **Step 1: 写失败的测试**

创建 `test_pacing.py`：

```python
"""Test: URL 之间的间隔固定在 2–3 秒，没有长歇。
Run: python test_pacing.py
"""
import time

import shein_scraper


def test_pause_always_between_2_and_3_seconds():
    slept = []
    orig = time.sleep
    time.sleep = lambda s: slept.append(s)
    try:
        for _ in range(200):
            shein_scraper._inter_url_pause()
    finally:
        time.sleep = orig
    assert len(slept) == 200, len(slept)
    assert all(2.0 <= s <= 3.0 for s in slept), (min(slept), max(slept))
    # 随机性确实存在（200 次不可能全同一个值）
    assert len(set(slept)) > 1


def test_pause_takes_no_arguments():
    orig = time.sleep
    time.sleep = lambda s: None
    try:
        shein_scraper._inter_url_pause()   # 不传参必须能调
    finally:
        time.sleep = orig


def test_long_pause_and_old_delay_constants_are_gone():
    for name in ("LONG_PAUSE_EVERY", "LONG_PAUSE_MIN", "LONG_PAUSE_MAX",
                 "INTER_URL_DELAY_MIN", "INTER_URL_DELAY_MAX"):
        assert not hasattr(shein_scraper, name), f"{name} 应该已被删除"


def test_new_pause_bounds_are_2_and_3():
    assert shein_scraper.INTER_URL_PAUSE_MIN == 2.0
    assert shein_scraper.INTER_URL_PAUSE_MAX == 3.0


if __name__ == "__main__":
    test_pause_always_between_2_and_3_seconds()
    test_pause_takes_no_arguments()
    test_long_pause_and_old_delay_constants_are_gone()
    test_new_pause_bounds_are_2_and_3()
    print("ALL PASS")
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python test_pacing.py`
Expected: `TypeError: _inter_url_pause() missing 2 required positional arguments: 'i' and 'total'`

- [ ] **Step 3: 实现**

把 `shein_scraper.py:73-79` 这 7 行：

```python
# Inter-URL pacing (anti-rate-limit). Random jitter + occasional long pauses
# look less robotic than a fixed delay.
INTER_URL_DELAY_MIN    = 4        # 每个商品之间最短间隔（秒）
INTER_URL_DELAY_MAX    = 12       # 每个商品之间最长间隔（秒）
LONG_PAUSE_EVERY       = 18       # 每处理 N 个商品后插一段长歇
LONG_PAUSE_MIN         = 30       # 长歇最短秒数
LONG_PAUSE_MAX         = 90       # 长歇最长秒数
```

替换成：

```python
# Inter-URL pacing. 每个 URL 抓完之后睡 2–3 秒，没有长歇。
INTER_URL_PAUSE_MIN    = 2.0      # 间隔下限（秒）
INTER_URL_PAUSE_MAX    = 3.0      # 间隔上限（秒）
```

把 `_inter_url_pause()` 整个函数替换成：

```python
def _inter_url_pause() -> None:
    """每抓完一条 URL 之后睡 2–3 秒。worker 无条件调用——包括它手上的最后一条。
    并发下判断「谁是最后一条」不可靠，代价只是整批多等 ≤3 秒。"""
    delay = random.uniform(INTER_URL_PAUSE_MIN, INTER_URL_PAUSE_MAX)
    print(f"  [节奏] 间隔 {delay:.1f}s")
    time.sleep(delay)
```

然后把 `scrape_shein()` 里全部 6 处 `_inter_url_pause(i, len(urls))` 改成 `_inter_url_pause()`：

```bash
grep -n "_inter_url_pause(" shein_scraper.py
```
预期改完后只剩定义处 + 6 处无参调用（原行号 2471 / 2506 / 2516 / 2577 / 2729，以及可能因编辑漂移的位置——以 grep 结果为准）。

- [ ] **Step 4: 跑测试确认通过**

Run: `python test_pacing.py && python test_variant_merge.py`
Expected: 两个都 `ALL PASS`

- [ ] **Step 5: 提交**

```bash
git add test_pacing.py shein_scraper.py
git commit -m "perf(scraper): fixed 2-3s inter-URL pause; drop long-pause hedging"
```

---

### Task 4: C/D/E 三列覆盖的合成逻辑

**Files:**
- Modify: `shein_scraper.py`（在 Task 2 的 `_filter_variants_by_declaration()` 之后插入）
- Test: `test_row_overrides.py`

**Interfaces:**
- Consumes: `_filter_variants_by_declaration`（Task 2）、`_format_price_range` / `_format_stock_summary`（Task 1）、`_calc_shipping`、`_ebay_listing_price`（均已存在）
- Produces:
  `_apply_row_overrides(data: dict, override_price, override_shipping, variant_filter_decl: str) -> dict`
  **就地修改** `data`（写 `data["sku_prices"]`、`data["variations"]`、`data["price"]`），并返回：
  ```python
  {"price": float, "shipping": float, "ebay_price": float,
   "web_price_display": float | str | None, "stock_summary": str,
   "unknown_variants": list[str], "variant_filter_no_match": bool}
  ```
  `variant_filter_no_match=True` 时调用方必须把该商品判为 `Failed`，不写任何数据。

**执行顺序（不可调换）：** 过滤 → 算 `web_price_display` → 套 C 列覆盖 → 定 shipping → 算 eBay 价 → 算库存串。

- [ ] **Step 1: 写失败的测试**

创建 `test_row_overrides.py`：

```python
"""Test: 模板 C（原价）/ D（运费）/ E（变体）三列对抓取结果的覆盖合成。
Run: python test_row_overrides.py
"""
from shein_scraper import _apply_row_overrides


def _data():
    return {
        "price": 10.00,
        "free_threshold": None,
        "unconditional_free": False,
        "variations": {"Color": ["Black", "Red"], "Size": ["M", "L"]},
        "sku_prices": [
            {"sku_code": "a", "sale_price": 10.00, "stock": 20,
             "attrs": {"Color": "Black", "Size": "M"}},
            {"sku_code": "b", "sale_price": 12.00, "stock": 0,
             "attrs": {"Color": "Black", "Size": "L"}},
            {"sku_code": "c", "sale_price": 14.00, "stock": 3,
             "attrs": {"Color": "Red", "Size": "M"}},
        ],
    }


def test_no_overrides_uses_scraped_price_and_derived_shipping():
    d = _data()
    out = _apply_row_overrides(d, None, None, "")
    assert out["price"] == 10.00
    assert out["shipping"] == 2.99          # DEFAULT_SHIPPING_FEE
    assert out["ebay_price"] == round((10.00 + 2.99) * 1.4, 2) == 18.19
    assert out["web_price_display"] == "10.00–14.00"
    assert out["variant_filter_no_match"] is False


def test_c_column_overrides_price_and_every_sku_sale_price():
    d = _data()
    out = _apply_row_overrides(d, 20.00, None, "")
    assert out["price"] == 20.00
    assert d["price"] == 20.00
    assert [sp["sale_price"] for sp in d["sku_prices"]] == [20.0, 20.0, 20.0]
    # I 列显示的是覆盖 *之前* 的网页价，用来核对 C 列填得对不对
    assert out["web_price_display"] == "10.00–14.00"
    assert out["ebay_price"] == round((20.00 + 2.99) * 1.4, 2)


def test_d_column_overrides_shipping_including_zero():
    d = _data()
    out = _apply_row_overrides(d, None, 0.0, "")
    assert out["shipping"] == 0.0
    assert out["ebay_price"] == round(10.00 * 1.4, 2) == 14.00
    d2 = _data()
    out2 = _apply_row_overrides(d2, None, 7.50, "")
    assert out2["shipping"] == 7.50
    assert out2["ebay_price"] == round((10.00 + 7.50) * 1.4, 2)


def test_free_shipping_threshold_still_honored_when_d_blank():
    d = _data()
    d["unconditional_free"] = True
    out = _apply_row_overrides(d, None, None, "")
    assert out["shipping"] == 0.0


def test_e_column_filters_before_price_range_and_stock():
    d = _data()
    out = _apply_row_overrides(d, None, None, "Black / M")
    assert [sp["sku_code"] for sp in d["sku_prices"]] == ["a"]
    assert d["variations"] == {"Color": ["Black"], "Size": ["M"]}
    assert out["web_price_display"] == 10.00     # 只剩一个变体 → 数字，不是区间
    assert out["stock_summary"] == "Black-M: 20"
    assert out["unknown_variants"] == []


def test_e_column_no_match_flags_failure():
    d = _data()
    out = _apply_row_overrides(d, None, None, "Purple")
    assert out["variant_filter_no_match"] is True
    assert out["unknown_variants"] == ["Purple"]


def test_e_column_partial_match_reports_unknown_but_succeeds():
    d = _data()
    out = _apply_row_overrides(d, None, None, "Black, Purple / M")
    assert out["variant_filter_no_match"] is False
    assert out["unknown_variants"] == ["Purple"]
    assert out["stock_summary"] == "Black-M: 20"


def test_c_override_applies_to_filtered_skus_only():
    d = _data()
    out = _apply_row_overrides(d, 99.0, None, "Black / M")
    assert [sp["sale_price"] for sp in d["sku_prices"]] == [99.0]
    assert out["price"] == 99.0


def test_stock_summary_marks_out_of_stock_and_low():
    d = _data()
    out = _apply_row_overrides(d, None, None, "")
    assert out["stock_summary"] == \
        "Black-M: 20 / Black-L: 缺货 / Red-M: 少货 3"


if __name__ == "__main__":
    test_no_overrides_uses_scraped_price_and_derived_shipping()
    test_c_column_overrides_price_and_every_sku_sale_price()
    test_d_column_overrides_shipping_including_zero()
    test_free_shipping_threshold_still_honored_when_d_blank()
    test_e_column_filters_before_price_range_and_stock()
    test_e_column_no_match_flags_failure()
    test_e_column_partial_match_reports_unknown_but_succeeds()
    test_c_override_applies_to_filtered_skus_only()
    test_stock_summary_marks_out_of_stock_and_low()
    print("ALL PASS")
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python test_row_overrides.py`
Expected: `ImportError: cannot import name '_apply_row_overrides'`

- [ ] **Step 3: 实现**

在 `shein_scraper.py` 的 `_format_stock_summary()` 之后插入：

```python
def _apply_row_overrides(data: dict, override_price, override_shipping,
                         variant_filter_decl: str) -> dict:
    """把模板 C / D / E 三列的覆盖套到刚抓下来的 `data` 上（就地修改），
    返回写 Excel 需要的一组派生值。

    顺序不可调换：过滤 → 网页价区间 → C 列覆盖 → 运费 → eBay 价 → 库存串。
    网页价区间必须在 C 列覆盖 *之前* 算，因为 I 列的用途就是核对 C 列填得对不对。
    """
    decl = (variant_filter_decl or "").strip()
    sku_prices = data.get("sku_prices") or []
    variations = data.get("variations") or {}

    kept, filtered_vars, unknown = _filter_variants_by_declaration(
        decl, sku_prices, variations)

    if decl and not kept:
        return {
            "price": data.get("price") or 0.0,
            "shipping": 0.0,
            "ebay_price": 0.0,
            "web_price_display": None,
            "stock_summary": "",
            "unknown_variants": unknown,
            "variant_filter_no_match": True,
        }

    data["sku_prices"] = kept
    if decl:
        data["variations"] = filtered_vars

    # I 列：覆盖之前的网页价
    web_price_display = _format_price_range(kept)
    if web_price_display is None:
        web_price_display = data.get("price")

    if override_price is not None:
        op = float(override_price)
        data["price"] = op
        for sp in kept:
            sp["sale_price"] = op
        print(f"  [price override] C列=${op:.2f} "
              f"(网页={web_price_display}, sku_prices×{len(kept)} 同步)")

    price = data.get("price") or 0.0
    if override_shipping is not None:
        shipping = float(override_shipping)
        print(f"  [shipping override] D列=${shipping:.2f}")
    else:
        shipping = _calc_shipping(data)

    return {
        "price": price,
        "shipping": shipping,
        "ebay_price": _ebay_listing_price(price, shipping),
        "web_price_display": web_price_display,
        "stock_summary": _format_stock_summary(kept),
        "unknown_variants": unknown,
        "variant_filter_no_match": False,
    }
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python test_row_overrides.py`
Expected: `ALL PASS`

- [ ] **Step 5: 提交**

```bash
git add test_row_overrides.py shein_scraper.py
git commit -m "feat(scraper): _apply_row_overrides composes C/D/E column overrides"
```

---

### Task 5: 抽出 `_scrape_one_url` + 线程安全限流计数器

本任务是**纯重构 + 接线**：抓取仍然是串行的，行为必须和改之前一致。并发在 Task 6。

**Files:**
- Modify: `shein_scraper.py`（`RateLimitError` 定义之后加计数器；`scrape_shein()` 的循环体抽成新函数）
- Test: `test_rate_limit.py`

**Interfaces:**
- Consumes: `_apply_row_overrides`（Task 4）、`_inter_url_pause`（Task 3）
- Produces:
  - `_rate_limit_lock: threading.Lock`、`_rate_limit_state: dict`
  - `_record_result_for_rate_limit(rec_status: str) -> bool`（返回 True 表示已触发限流）
  - `_reset_rate_limit_state() -> None`
  - `_scrape_one_url(url: str, index: int, total: int, seq_num: int, override_price, override_shipping, variant_filter_decl: str) -> dict`
    —— 自己开 tab、`finally` 关 tab、**返回前无条件调 `_inter_url_pause()`**、绝不 raise（异常包成 `rec["status"] = f"ERROR: {e}"`）
  - `scrape_shein()` 新增两个关键字参数 `shipping_list=None, variant_filter_list=None`
  - 记录 `rec` 新增字段：`web_price_display`、`stock_summary`（`first_image_path` 已存在）

- [ ] **Step 1: 写失败的测试**

创建 `test_rate_limit.py`：

```python
"""Test: 线程安全的限流计数器。
Run: python test_rate_limit.py
"""
import threading

import shein_scraper
from shein_scraper import (_record_result_for_rate_limit,
                           _reset_rate_limit_state, RATE_LIMIT_CONSECUTIVE)


def test_ok_results_never_trip():
    _reset_rate_limit_state()
    for _ in range(50):
        assert _record_result_for_rate_limit("OK") is False


def test_three_consecutive_failures_trip():
    _reset_rate_limit_state()
    assert RATE_LIMIT_CONSECUTIVE == 3
    assert _record_result_for_rate_limit("BLOCKED") is False
    assert _record_result_for_rate_limit("TIMEOUT") is False
    assert _record_result_for_rate_limit("ERROR: boom") is True


def test_ok_resets_the_streak():
    _reset_rate_limit_state()
    _record_result_for_rate_limit("BLOCKED")
    _record_result_for_rate_limit("BLOCKED")
    _record_result_for_rate_limit("OK")          # 清零
    assert _record_result_for_rate_limit("BLOCKED") is False
    assert _record_result_for_rate_limit("BLOCKED") is False
    assert _record_result_for_rate_limit("BLOCKED") is True


def test_stays_tripped_once_tripped():
    _reset_rate_limit_state()
    for _ in range(3):
        _record_result_for_rate_limit("BLOCKED")
    assert _record_result_for_rate_limit("OK") is True    # 已触发就一直是 True


def test_reset_clears_tripped():
    _reset_rate_limit_state()
    for _ in range(3):
        _record_result_for_rate_limit("BLOCKED")
    _reset_rate_limit_state()
    assert _record_result_for_rate_limit("OK") is False


def test_concurrent_updates_do_not_lose_counts():
    """20 个线程各报 1 次失败：必须触发，且不出现竞态导致的漏计。"""
    _reset_rate_limit_state()
    results = []

    def worker():
        results.append(_record_result_for_rate_limit("BLOCKED"))

    threads = [threading.Thread(target=worker) for _ in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert any(results), "20 次连续失败必须触发限流"
    assert shein_scraper._rate_limit_state["tripped"] is True


def test_scrape_one_url_exists_with_expected_signature():
    import inspect
    params = list(inspect.signature(shein_scraper._scrape_one_url).parameters)
    assert params == ["url", "index", "total", "seq_num",
                      "override_price", "override_shipping",
                      "variant_filter_decl"], params


def test_scrape_shein_accepts_new_lists():
    import inspect
    params = inspect.signature(shein_scraper.scrape_shein).parameters
    assert "shipping_list" in params
    assert "variant_filter_list" in params


if __name__ == "__main__":
    test_ok_results_never_trip()
    test_three_consecutive_failures_trip()
    test_ok_resets_the_streak()
    test_stays_tripped_once_tripped()
    test_reset_clears_tripped()
    test_concurrent_updates_do_not_lose_counts()
    test_scrape_one_url_exists_with_expected_signature()
    test_scrape_shein_accepts_new_lists()
    print("ALL PASS")
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python test_rate_limit.py`
Expected: `ImportError: cannot import name '_record_result_for_rate_limit'`

- [ ] **Step 3a: 加限流计数器**

在 `shein_scraper.py` 的 `class RateLimitError` 定义之后插入：

```python
_rate_limit_lock  = threading.Lock()
_rate_limit_state = {"consecutive_fails": 0, "tripped": False}


def _record_result_for_rate_limit(rec_status: str) -> bool:
    """更新共享的限流计数器。返回 True 表示已触发限流
    （调用方应放弃剩余 URL）。一旦触发就一直返回 True，直到 reset。"""
    with _rate_limit_lock:
        if _rate_limit_state["tripped"]:
            return True
        if rec_status != "OK":
            _rate_limit_state["consecutive_fails"] += 1
            if _rate_limit_state["consecutive_fails"] >= RATE_LIMIT_CONSECUTIVE:
                _rate_limit_state["tripped"] = True
                return True
        else:
            _rate_limit_state["consecutive_fails"] = 0
        return False


def _reset_rate_limit_state() -> None:
    with _rate_limit_lock:
        _rate_limit_state["consecutive_fails"] = 0
        _rate_limit_state["tripped"] = False
```

- [ ] **Step 3b: 把循环体抽成 `_scrape_one_url`**

在 `scrape_shein()` **之前**新建 `_scrape_one_url()`。它的函数体就是现在 `scrape_shein()` 里 `for i, url in enumerate(urls, 1):` 循环体（原 line 2448–2710），照下面这些规则机械改写：

1. 函数头：
```python
def _scrape_one_url(
    url: str, index: int, total: int, seq_num: int,
    override_price, override_shipping, variant_filter_decl: str,
) -> dict:
    """在自己的 CDP tab 里抓一个商品 URL，返回 record dict。
    线程安全：每次调用开自己的 tab、用自己的 WebSocket。
    绝不向外抛异常；返回前无条件睡 2–3 秒。"""
    print(f"[{index}/{total}] {url[:80]}...")
    rec = {"url": url, "status": "OK", "seq_num": seq_num}
    tab_id = None
    _url_start_time = time.monotonic()
    try:
        ...  # 原循环体
    except Exception as e:
        rec["status"] = f"ERROR: {e}"
        print(f"  ERROR: {e}")
    finally:
        if tab_id is not None:
            _close_tab(CDP_PORT, tab_id)
        _inter_url_pause()
    return rec
```
2. 所有 `records.append(rec); _inter_url_pause(...); continue` 的提前退出（BLOCKED / DELISTED / NO_DATA / TIMEOUT 四处）改成 **`return rec`**——`finally` 会负责关 tab 和睡觉。
3. `seq_list[i - 1] if seq_list else start_seq + (i - 1)` 两处替换成 `seq_num`。
4. `state_tracker` 的进度上报从这里**移除**（Task 6 由调度器统一上报）。
5. 原来 line 2588–2613 那段「手动售价覆盖 + `_calc_shipping` + `_ebay_listing_price` + `ship_note`」整段删掉，换成：
```python
                derived = _apply_row_overrides(
                    data, override_price, override_shipping, variant_filter_decl)
                if derived["unknown_variants"]:
                    print(f"  [变体] 声明里这些值在页面上找不到: "
                          f"{', '.join(derived['unknown_variants'])}")
                if derived["variant_filter_no_match"]:
                    rec["status"] = "variant_filter_no_match"
                    print("  [跳过] E列声明的变体一个都没匹配上")
                    return rec

                price      = derived["price"]
                shipping   = derived["shipping"]
                ebay       = derived["ebay_price"]
                sku_prices = data.get("sku_prices") or []
```
6. `rec.update({...})` 里追加两个字段：
```python
                    "web_price_display": derived["web_price_display"],
                    "stock_summary":     derived["stock_summary"],
```
   并把 `"seq_num": seq_list[i - 1] ...` 改成 `"seq_num": seq_num`。
7. 打印 `shipping` 那行的 `ship_note` 已随第 5 步删除，改成：
```python
                print(f"  shipping   : ${shipping:.2f}")
```

- [ ] **Step 3c: `scrape_shein()` 改成调用它（仍串行）**

`scrape_shein()` 签名加两个参数，循环体换成一次调用：

```python
def scrape_shein(urls, output="shein_products.xlsx", start_seq=1, seq_list=None,
                 price_list=None, shipping_list=None, variant_filter_list=None):
```
docstring 里补上：
```
    shipping_list       : list[float|None] | None  每个 URL 的手动运费（模板 D 列）
    variant_filter_list : list[str] | None         每个 URL 的变体声明（模板 E 列）
```

循环体（原 2447–2729）整体替换成：

```python
        _reset_rate_limit_state()
        for i, url in enumerate(urls, 1):
            if _st is not None:
                try:
                    _st.url_progress(done=i - 1, total=len(urls), current_url=url)
                except Exception:
                    pass
            rec = _scrape_one_url(
                url, i, len(urls),
                seq_list[i - 1] if seq_list else start_seq + (i - 1),
                price_list[i - 1] if price_list else None,
                shipping_list[i - 1] if shipping_list else None,
                variant_filter_list[i - 1] if variant_filter_list else "",
            )
            records.append(rec)
            if _record_result_for_rate_limit(rec.get("status") or "OK"):
                print(f"\n  [限流] 连续 {RATE_LIMIT_CONSECUTIVE} 个 URL 失败，"
                      f"判定为 Shein 限流，停止当前批次")
                for j in range(i + 1, len(urls) + 1):
                    records.append({
                        "url": urls[j - 1],
                        "status": "RATE_LIMITED",
                        "seq_num": seq_list[j - 1] if seq_list else start_seq + (j - 1),
                    })
                _rate_limited = True
                break
```

同时删掉不再使用的局部变量 `_consecutive_fails`。

- [ ] **Step 4: 跑测试确认通过**

Run: `python test_rate_limit.py && python test_pacing.py && python test_row_overrides.py && python test_variant_filter.py && python test_price_stock_format.py && python test_variant_merge.py`
Expected: 6 个都 `ALL PASS`

再做一次导入自检（确保重构没写坏语法）：
Run: `python -c "import shein_scraper; print('import ok')"`
Expected: `import ok`

- [ ] **Step 5: 提交**

```bash
git add test_rate_limit.py shein_scraper.py
git commit -m "refactor(scraper): extract _scrape_one_url; thread-safe rate-limit counter"
```

---

### Task 6: 三标签并发调度器

**Files:**
- Modify: `shein_scraper.py`（`MAX_PARALLEL_TABS` 常量、`IMAGE_DOWNLOAD_WORKERS` 8→4、新增 `_run_scrape_pool()`、`scrape_shein()` 改成调它）
- Test: `test_scrape_pool.py`

**Interfaces:**
- Consumes: `_scrape_one_url`、`_record_result_for_rate_limit`、`_reset_rate_limit_state`（Task 5）
- Produces:
  `_run_scrape_pool(urls: list, seq_list, price_list, shipping_list, variant_filter_list, start_seq: int, progress_cb=None) -> tuple[list, bool]`
  返回 `(records, rate_limited)`；`records` 按 `seq_num` 升序；`progress_cb(done, total, url)` 可为 None。
  常量 `MAX_PARALLEL_TABS = 3`。

- [ ] **Step 1: 写失败的测试**

创建 `test_scrape_pool.py`：

```python
"""Test: 并发调度器 —— 并发度上限 3、结果按 seq 排序、限流时不丢已完成结果。
Run: python test_scrape_pool.py
"""
import threading
import time

import shein_scraper
from shein_scraper import _run_scrape_pool, _reset_rate_limit_state


def _install_fake_worker(behavior):
    """behavior(index) -> status 字符串。返回 (restore, peak_holder)。"""
    orig = shein_scraper._scrape_one_url
    live = {"now": 0, "peak": 0}
    lock = threading.Lock()

    def fake(url, index, total, seq_num,
             override_price, override_shipping, variant_filter_decl):
        with lock:
            live["now"] += 1
            live["peak"] = max(live["peak"], live["now"])
        time.sleep(0.05)
        with lock:
            live["now"] -= 1
        return {"url": url, "seq_num": seq_num, "status": behavior(index),
                "_ov": (override_price, override_shipping, variant_filter_decl)}

    shein_scraper._scrape_one_url = fake

    def restore():
        shein_scraper._scrape_one_url = orig

    return restore, live


def test_concurrency_never_exceeds_three():
    _reset_rate_limit_state()
    restore, live = _install_fake_worker(lambda i: "OK")
    try:
        urls = [f"http://x/{i}" for i in range(12)]
        records, limited = _run_scrape_pool(
            urls, list(range(1, 13)), None, None, None, 1)
    finally:
        restore()
    assert shein_scraper.MAX_PARALLEL_TABS == 3
    assert live["peak"] <= 3, live["peak"]
    assert live["peak"] > 1, "应该真的并发起来了"
    assert len(records) == 12
    assert limited is False


def test_results_sorted_by_seq():
    _reset_rate_limit_state()
    restore, _ = _install_fake_worker(lambda i: "OK")
    try:
        urls = [f"http://x/{i}" for i in range(8)]
        seqs = [11, 3, 7, 1, 22, 5, 9, 2]
        records, _ = _run_scrape_pool(urls, seqs, None, None, None, 1)
    finally:
        restore()
    assert [r["seq_num"] for r in records] == sorted(seqs)


def test_per_url_overrides_are_passed_through():
    _reset_rate_limit_state()
    restore, _ = _install_fake_worker(lambda i: "OK")
    try:
        records, _ = _run_scrape_pool(
            ["u0", "u1"], [1, 2], [None, 9.5], [0.0, None], ["", "Black / M"], 1)
    finally:
        restore()
    by_seq = {r["seq_num"]: r["_ov"] for r in records}
    assert by_seq[1] == (None, 0.0, "")
    assert by_seq[2] == (9.5, None, "Black / M")


def test_rate_limit_marks_remaining_and_keeps_completed():
    """前 3 条全失败 → 触发限流。已完成的 3 条必须在 records 里，
    剩下的标 RATE_LIMITED，一条都不能丢。"""
    _reset_rate_limit_state()
    restore, _ = _install_fake_worker(lambda i: "BLOCKED")
    try:
        urls = [f"http://x/{i}" for i in range(9)]
        records, limited = _run_scrape_pool(
            urls, list(range(1, 10)), None, None, None, 1)
    finally:
        restore()
    assert limited is True
    assert len(records) == 9, [r["seq_num"] for r in records]
    assert [r["seq_num"] for r in records] == list(range(1, 10))
    statuses = {r["seq_num"]: r["status"] for r in records}
    assert sum(1 for s in statuses.values() if s == "BLOCKED") >= 3
    assert sum(1 for s in statuses.values() if s == "RATE_LIMITED") >= 1


def test_worker_exception_becomes_error_record_not_a_crash():
    _reset_rate_limit_state()
    orig = shein_scraper._scrape_one_url

    def boom(url, index, total, seq_num, *a):
        if seq_num == 2:
            raise RuntimeError("kaboom")
        return {"url": url, "seq_num": seq_num, "status": "OK"}

    shein_scraper._scrape_one_url = boom
    try:
        records, limited = _run_scrape_pool(
            ["u1", "u2", "u3"], [1, 2, 3], None, None, None, 1)
    finally:
        shein_scraper._scrape_one_url = orig
    assert len(records) == 3
    bad = next(r for r in records if r["seq_num"] == 2)
    assert bad["status"].startswith("ERROR:"), bad


def test_progress_callback_fires_once_per_url():
    _reset_rate_limit_state()
    restore, _ = _install_fake_worker(lambda i: "OK")
    seen = []
    try:
        _run_scrape_pool(["a", "b", "c"], [1, 2, 3], None, None, None, 1,
                         progress_cb=lambda done, total, url: seen.append(done))
    finally:
        restore()
    assert sorted(seen) == [1, 2, 3], seen


def test_image_pool_reduced_for_parallelism():
    assert shein_scraper.IMAGE_DOWNLOAD_WORKERS == 4


if __name__ == "__main__":
    test_concurrency_never_exceeds_three()
    test_results_sorted_by_seq()
    test_per_url_overrides_are_passed_through()
    test_rate_limit_marks_remaining_and_keeps_completed()
    test_worker_exception_becomes_error_record_not_a_crash()
    test_progress_callback_fires_once_per_url()
    test_image_pool_reduced_for_parallelism()
    print("ALL PASS")
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python test_scrape_pool.py`
Expected: `ImportError: cannot import name '_run_scrape_pool'`

- [ ] **Step 3a: 改常量**

`shein_scraper.py` 常量块里，把
```python
IMAGE_DOWNLOAD_WORKERS = 8        # 并行下载线程数
```
改成
```python
IMAGE_DOWNLOAD_WORKERS = 4        # 并行下载线程数（3 并发商品 × 4 = 12 sockets）
```
并在 `RATE_LIMIT_CONSECUTIVE` 那行下面加：
```python
MAX_PARALLEL_TABS      = 3        # 同时打开多少个 CDP tab 抓取（保守）
```

- [ ] **Step 3b: 写调度器**

在 `scrape_shein()` 之前插入：

```python
def _run_scrape_pool(urls, seq_list, price_list, shipping_list,
                     variant_filter_list, start_seq, progress_cb=None):
    """用 MAX_PARALLEL_TABS 个并发 tab 跑完 `urls`，返回 (records, rate_limited)。

    一个持久的 ThreadPoolExecutor 覆盖整个列表（不分批）。每个 worker 抓完
    自己那条之后会睡 2–3 秒（在 `_scrape_one_url` 的 finally 里），所以池子
    自然把整体速率压到约 MAX_PARALLEL_TABS / 2.5s。

    限流触发时：不再提交新任务，但**先排空所有已经完成的 future**，
    把它们的结果收进来——否则整批已经抓好的商品会被一起丢掉。
    剩下的没跑到的 URL 标成 RATE_LIMITED。records 按 seq_num 升序返回。
    """
    total = len(urls)
    _reset_rate_limit_state()

    def _seq(i):
        return seq_list[i] if seq_list else start_seq + i

    records = []
    rate_limited = False
    done_count = 0
    lock = threading.Lock()

    with ThreadPoolExecutor(max_workers=MAX_PARALLEL_TABS) as ex:
        fut_to_seq = {}
        for i in range(total):
            fut = ex.submit(
                _scrape_one_url,
                urls[i], i + 1, total, _seq(i),
                price_list[i] if price_list else None,
                shipping_list[i] if shipping_list else None,
                variant_filter_list[i] if variant_filter_list else "",
            )
            fut_to_seq[fut] = (i, _seq(i))

        for fut in as_completed(fut_to_seq):
            i, seq_num = fut_to_seq[fut]
            try:
                rec = fut.result()
            except Exception as e:
                rec = {"url": urls[i], "status": f"ERROR: {e}", "seq_num": seq_num}
            records.append(rec)
            with lock:
                done_count += 1
                done = done_count
            if progress_cb is not None:
                try:
                    progress_cb(done, total, rec.get("url", ""))
                except Exception:
                    pass
            if _record_result_for_rate_limit(rec.get("status") or "OK"):
                rate_limited = True
                print(f"\n  [限流] 连续 {RATE_LIMIT_CONSECUTIVE} 个 URL 失败，"
                      f"判定为 Shein 限流，停止提交后续 URL")
                # 取消还没开始的任务；已在跑的让它跑完（tab 得关掉）
                for other in fut_to_seq:
                    if not other.done():
                        other.cancel()
                break

    # 排空：上面 break 之后（以及 with 块退出时）陆续完成的 future
    collected = {r.get("seq_num") for r in records}
    for fut, (i, seq_num) in fut_to_seq.items():
        if seq_num in collected or fut.cancelled() or not fut.done():
            continue
        try:
            rec = fut.result()
        except Exception as e:
            rec = {"url": urls[i], "status": f"ERROR: {e}", "seq_num": seq_num}
        records.append(rec)
        collected.add(seq_num)

    if rate_limited:
        for i in range(total):
            if _seq(i) not in collected:
                records.append({"url": urls[i], "status": "RATE_LIMITED",
                                "seq_num": _seq(i)})
                collected.add(_seq(i))

    records.sort(key=lambda r: (r.get("seq_num") or 0))
    return records, rate_limited
```

- [ ] **Step 3c: `scrape_shein()` 改成调用调度器**

把 Task 5 Step 3c 写的那段串行 for 循环整体替换成：

> **为什么必须显式预热**：`_ensure_shein_session()` 已经被 `_navigate_and_wait()` 调用，
> 靠模块级 `_SESSION_WARMED` 标志去重，但那个标志没有加锁。三个 worker 同时起来会
> 一起看到 `False` 从而重复预热。在建池之前先跑一次把标志置上，race 就不存在了。

```python
        _ensure_shein_session(CDP_PORT)      # 会话预热一次，在建池之前（见上）

        def _progress(done, total_n, url_hint):
            if _st is not None:
                try:
                    _st.url_progress(done=done, total=total_n, current_url=url_hint)
                except Exception:
                    pass

        records, _rate_limited = _run_scrape_pool(
            urls, seq_list, price_list, shipping_list, variant_filter_list,
            start_seq, progress_cb=_progress,
        )
```

注意：`records = []` 那行初始化保留（`finally` 之后的 `_expand_records(records)` 依赖它在异常路径下也有定义）。

- [ ] **Step 4: 跑测试确认通过**

Run: `python test_scrape_pool.py`
Expected: `ALL PASS`

Run: `python test_rate_limit.py && python test_pacing.py && python test_row_overrides.py && python test_variant_filter.py && python test_price_stock_format.py && python test_variant_merge.py`
Expected: 全部 `ALL PASS`

- [ ] **Step 5: 提交**

```bash
git add test_scrape_pool.py shein_scraper.py
git commit -m "feat(scraper): 3-tab parallelism via _run_scrape_pool; image pool 8->4"
```

---

### Task 7: `run_excel.py` 中文模板读写层

**Files:**
- Modify: `run_excel.py`（顶部 docstring、import、新增常量与 3 个函数）
- Test: `test_template_io.py`

**Interfaces:**
- Consumes: `shein_scraper._add_picture_to_cell(ws, row, col, image_path) -> int`（已存在，返回建议行高）
- Produces:
  - 列号常量 `COL_SEQ=1 COL_URL=2 COL_PRICE=3 COL_SHIPPING=4 COL_VARIANT_FILTER=5 COL_DATE=6 COL_STATUS=7 COL_PICTURE=8 COL_WEB_PRICE=9 COL_SHEIN_TITLE=10 COL_EBAY_TITLE=11 COL_EBAY_PRICE=12 COL_STOCK=13`
  - `EXPECTED_HEADERS: list[str]`
  - `_sheet_matches_template(ws) -> bool`
  - `_read_pending_rows(ws) -> list[dict]`，元素键为 `row / seq / url / price / shipping / variant_filter`
  - `_write_result_row(ws, row, date, status, picture_path=None, web_price=None, shein_title=None, ebay_title=None, ebay_price=None, stock=None) -> None`

- [ ] **Step 1: 写失败的测试**

创建 `test_template_io.py`：

```python
"""Test: run_excel.py 的中文模板读写层。
Run: python test_template_io.py
"""
from openpyxl import Workbook

import run_excel
from run_excel import (_sheet_matches_template, _read_pending_rows,
                       _write_result_row, EXPECTED_HEADERS,
                       COL_DATE, COL_STATUS, COL_WEB_PRICE, COL_SHEIN_TITLE,
                       COL_EBAY_TITLE, COL_EBAY_PRICE, COL_STOCK)


def _template_sheet():
    wb = Workbook()
    ws = wb.active
    ws.title = "ZR1"
    for c, h in enumerate(EXPECTED_HEADERS, 1):
        ws.cell(1, c).value = h
    return wb, ws


def test_expected_headers_are_the_thirteen_chinese_names():
    assert EXPECTED_HEADERS == [
        "编号", "链接", "原价", "运费", "变体",
        "日期", "状态", "图片", "希音价格", "希音标题",
        "eBay标题", "eBay价格", "库存"], EXPECTED_HEADERS


def test_sheet_matches_only_when_b1_is_lianjie():
    wb, ws = _template_sheet()
    assert _sheet_matches_template(ws) is True
    ws.cell(1, 2).value = "Website"
    assert _sheet_matches_template(ws) is False


def test_old_english_sheet_is_rejected():
    wb = Workbook()
    ws = wb.active
    for c, h in enumerate(["Seq", "Website", "Price", "Date", "Status"], 1):
        ws.cell(1, c).value = h
    assert _sheet_matches_template(ws) is False
    assert _read_pending_rows(ws) == []


def test_reads_only_rows_with_url_and_empty_date_status():
    wb, ws = _template_sheet()
    ws.append([1, "http://a", 10.0, 2.99, "Black / M"])           # 待处理
    ws.append([2, "http://b", None, None, None])                  # 待处理，C/D/E 空
    ws.append([3, "http://c", None, None, None, "2026-08-01", "Done"])  # 已完成
    ws.append([4, None, None, None, None])                        # 没链接
    ws.append([5, "http://e", None, None, None, "2026-08-01", None])    # 只有日期
    ws.append([6, "http://f", None, None, None, None, "Failed"])        # 只有状态
    pending = _read_pending_rows(ws)
    assert [p["seq"] for p in pending] == [1, 2], pending
    assert pending[0] == {"row": 2, "seq": 1, "url": "http://a",
                          "price": 10.0, "shipping": 2.99,
                          "variant_filter": "Black / M"}
    assert pending[1]["price"] is None
    assert pending[1]["shipping"] is None
    assert pending[1]["variant_filter"] == ""


def test_skips_rows_with_bad_seq_or_bad_numbers():
    wb, ws = _template_sheet()
    ws.append([None, "http://a", None, None, None])        # 没编号
    ws.append(["abc", "http://b", None, None, None])       # 编号非数字
    ws.append([3, "http://c", "十块", None, None])          # 原价非数字
    ws.append([4, "http://d", None, "免运费", None])         # 运费非数字
    ws.append([5, "http://e", 9.9, 0, None])               # 好行
    pending = _read_pending_rows(ws)
    assert [p["seq"] for p in pending] == [5], pending
    assert pending[0]["shipping"] == 0.0


def test_url_is_stripped():
    wb, ws = _template_sheet()
    ws.append([1, "  http://a  ", None, None, None])
    assert _read_pending_rows(ws)[0]["url"] == "http://a"


def test_write_result_row_writes_f_through_m():
    wb, ws = _template_sheet()
    ws.append([1, "http://a", None, None, None])
    _write_result_row(ws, row=2, date="2026-08-02", status="Done",
                      picture_path=None, web_price="9.99–14.99",
                      shein_title="Raw Title", ebay_title="eBay Title",
                      ebay_price=18.19, stock="Black-M: 12")
    assert ws.cell(2, COL_DATE).value == "2026-08-02"
    assert ws.cell(2, COL_STATUS).value == "Done"
    assert ws.cell(2, COL_WEB_PRICE).value == "9.99–14.99"
    assert ws.cell(2, COL_SHEIN_TITLE).value == "Raw Title"
    assert ws.cell(2, COL_EBAY_TITLE).value == "eBay Title"
    assert ws.cell(2, COL_EBAY_PRICE).value == 18.19
    assert ws.cell(2, COL_STOCK).value == "Black-M: 12"


def test_write_result_row_failed_writes_only_date_and_status():
    wb, ws = _template_sheet()
    ws.append([1, "http://a", None, None, None])
    _write_result_row(ws, row=2, date="2026-08-02", status="Failed")
    assert ws.cell(2, COL_DATE).value == "2026-08-02"
    assert ws.cell(2, COL_STATUS).value == "Failed"
    for col in (COL_WEB_PRICE, COL_SHEIN_TITLE, COL_EBAY_TITLE,
                COL_EBAY_PRICE, COL_STOCK):
        assert ws.cell(2, col).value is None, col


def test_numeric_web_price_stays_numeric():
    wb, ws = _template_sheet()
    ws.append([1, "http://a", None, None, None])
    _write_result_row(ws, row=2, date="2026-08-02", status="Done",
                      web_price=12.99)
    v = ws.cell(2, COL_WEB_PRICE).value
    assert isinstance(v, float) and v == 12.99, repr(v)


if __name__ == "__main__":
    test_expected_headers_are_the_thirteen_chinese_names()
    test_sheet_matches_only_when_b1_is_lianjie()
    test_old_english_sheet_is_rejected()
    test_reads_only_rows_with_url_and_empty_date_status()
    test_skips_rows_with_bad_seq_or_bad_numbers()
    test_url_is_stripped()
    test_write_result_row_writes_f_through_m()
    test_write_result_row_failed_writes_only_date_and_status()
    test_numeric_web_price_stays_numeric()
    print("ALL PASS")
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python test_template_io.py`
Expected: `ImportError: cannot import name '_sheet_matches_template' from 'run_excel'`

- [ ] **Step 3: 实现**

把 `run_excel.py:1-19` 的模块 docstring 换成：

```python
"""
Excel-based pipeline: 从中文表头模板读待处理 URL，抓取后把结果写回 F–M 列，
并在 OUTPUT_ROOT/{sheet名}/ 下产出媒体文件夹和批次汇总 xlsx。

Usage:
    python run_excel.py                          # 默认 SUBMITTED_DIR/INPUT_FILENAME
    python run_excel.py "path/to/file.xlsx"      # 指定文件

Columns (strict, 中文表头模板):
    A: 编号       — 序号，同时是输出子文件夹名。READ.
    B: 链接       — Shein 商品 URL。READ.
    C: 原价       — 手填售价 (USD)。READ. 空 → 用网页抓到的价。
    D: 运费       — 手填运费 (USD)。READ. 空 → 用扫描推导的运费。
    E: 变体       — 变体过滤声明。READ. 空 → 抓全部变体。
    F: 日期       — 运行日期。WRITE.
    G: 状态       — Done / Failed / Delisted。WRITE.
    H: 图片       — 嵌入首张商品图。WRITE.
    I: 希音价格   — 网页售价；多变体不同价时是 "9.99–14.99" 区间串。WRITE.
    J: 希音标题   — 原始 h1 标题。WRITE.
    K: eBay标题   — AI 生成（Haiku），失败回退规则。WRITE.
    L: eBay价格   — (C或抓到价 + D或推导运费) × 1.4。WRITE.
    M: 库存       — 单行变体库存摘要。WRITE.

只处理「链接有值 且 日期/状态都为空」的行。B1 不是「链接」的 sheet 直接跳过。
"""
```

import 那行改成（加 `_add_picture_to_cell`）：
```python
from shein_scraper import scrape_shein, RateLimitError, _add_picture_to_cell
```

在 `DEBUG_LOG_DIR = ...` 之后插入常量和三个函数：

```python
# ── 中文表头模板 schema（A–M）────────────────────────────────────────────────
# 见 docs/superpowers/specs/2026-08-02-us-template-parallel-design.md §1
COL_SEQ, COL_URL, COL_PRICE, COL_SHIPPING, COL_VARIANT_FILTER = 1, 2, 3, 4, 5
COL_DATE, COL_STATUS, COL_PICTURE = 6, 7, 8
COL_WEB_PRICE, COL_SHEIN_TITLE = 9, 10
COL_EBAY_TITLE, COL_EBAY_PRICE, COL_STOCK = 11, 12, 13

EXPECTED_HEADERS = ["编号", "链接", "原价", "运费", "变体",
                    "日期", "状态", "图片", "希音价格", "希音标题",
                    "eBay标题", "eBay价格", "库存"]


def _sheet_matches_template(ws) -> bool:
    """只有 B1 == 「链接」的 sheet 才按新 schema 处理。"""
    return str(ws.cell(1, COL_URL).value or "").strip() == "链接"


def _read_pending_rows(ws) -> list[dict]:
    """返回 [{row, seq, url, price, shipping, variant_filter}, ...]。

    只挑「链接有值 且 日期/状态都为空」的行。非模板 sheet 返回 []。
    原价/运费为空 → None（交给 scraper 回退）。编号或原价/运费非数字 → 跳过并记日志。
    """
    if not _sheet_matches_template(ws):
        return []
    pending = []
    for r in range(2, ws.max_row + 1):
        seq = ws.cell(r, COL_SEQ).value
        url = ws.cell(r, COL_URL).value
        if not url or ws.cell(r, COL_DATE).value or ws.cell(r, COL_STATUS).value:
            continue
        if seq is None:
            logger.info("  row %d: skip (无编号)", r)
            continue
        try:
            seq_int = int(seq)
        except (TypeError, ValueError):
            logger.info("  row %d: skip (编号 '%s' 非数字)", r, seq)
            continue
        raw_price = ws.cell(r, COL_PRICE).value
        raw_ship = ws.cell(r, COL_SHIPPING).value
        try:
            price = float(raw_price) if raw_price not in (None, "") else None
        except (TypeError, ValueError):
            logger.info("  row %d: skip (原价 '%s' 非数字)", r, raw_price)
            continue
        try:
            shipping = float(raw_ship) if raw_ship not in (None, "") else None
        except (TypeError, ValueError):
            logger.info("  row %d: skip (运费 '%s' 非数字)", r, raw_ship)
            continue
        pending.append({
            "row": r,
            "seq": seq_int,
            "url": str(url).strip(),
            "price": price,
            "shipping": shipping,
            "variant_filter": str(ws.cell(r, COL_VARIANT_FILTER).value or "").strip(),
        })
    return pending


def _write_result_row(
    ws, row: int, date: str, status: str,
    picture_path=None,
    web_price=None,
    shein_title=None,
    ebay_title=None,
    ebay_price=None,
    stock=None,
) -> None:
    """写结果列 F–M。日期(F) 和 状态(G) 总是写；其余为 None 就不写
    （Failed / Delisted 的行只留日期和状态）。picture_path 是真实文件时
    把图嵌进 H 并把行高撑到放得下。"""
    ws.cell(row, COL_DATE).value = date
    ws.cell(row, COL_STATUS).value = status
    if picture_path and Path(picture_path).is_file():
        row_h = _add_picture_to_cell(ws, row, COL_PICTURE, Path(picture_path))
        if row_h:
            existing = ws.row_dimensions[row].height or 0
            ws.row_dimensions[row].height = max(existing, row_h)
    if web_price is not None:
        ws.cell(row, COL_WEB_PRICE).value = web_price
    if shein_title is not None:
        ws.cell(row, COL_SHEIN_TITLE).value = shein_title
    if ebay_title is not None:
        ws.cell(row, COL_EBAY_TITLE).value = ebay_title
    if ebay_price is not None:
        ws.cell(row, COL_EBAY_PRICE).value = ebay_price
    if stock is not None:
        ws.cell(row, COL_STOCK).value = stock
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python test_template_io.py`
Expected: `ALL PASS`

- [ ] **Step 5: 提交**

```bash
git add test_template_io.py run_excel.py
git commit -m "feat(run_excel): Chinese-header template reader/writer helpers"
```

---

### Task 8: 重写 `process_excel()`，删除旧英文路径

**Files:**
- Modify: `run_excel.py`（`process_excel()` 整个函数体）
- Test: `test_template_io.py`（追加一组端到端测试）

**Interfaces:**
- Consumes: Task 7 的读写层；`scrape_shein(urls, output, seq_list, price_list, shipping_list, variant_filter_list)`（Task 5/6）
- Produces: `process_excel(xlsx_path: Path) -> None` —— 遍历所有 sheet，非模板的跳过
- 记录字段依赖：`rec["web_price_display"]`、`rec["stock_summary"]`、`rec["original_title"]`、`rec["ebay_title"]`、`rec["ebay_price"]`、`rec["first_image_path"]`、`rec["seq_num"]`、`rec["status"]`、`rec["sku"]`、`rec["title"]`

- [ ] **Step 1: 追加失败的测试**

在 `test_template_io.py` 的 `if __name__ == "__main__":` **之前**追加：

```python
# ── process_excel 端到端（打桩 scrape_shein，不碰浏览器）────────────────────
import os
import shutil
import tempfile
from pathlib import Path


def _fake_results(seqs):
    return [{
        "seq_num": s, "status": "OK", "sku": f"sku{s}",
        "title": f"Title {s}", "original_title": f"Raw Title {s}",
        "ebay_title": f"eBay Title {s}", "ebay_price": 18.19 + s,
        "web_price_display": "9.99–14.99", "stock_summary": f"Black-M: {s}",
        "first_image_path": "",
    } for s in seqs]


def _run_process_excel(rows, results_factory, tmp_root):
    """在临时目录里建模板 xlsx + 输出目录，打桩 scrape_shein 后跑 process_excel。
    返回 (加载回来的 ws, 传给 scrape_shein 的参数字典)。"""
    from openpyxl import load_workbook

    wb, ws = _template_sheet()
    for row in rows:
        ws.append(row)
    xlsx = Path(tmp_root) / "input.xlsx"
    wb.save(xlsx)

    captured = {}

    def fake_scrape(urls, output=None, seq_list=None, price_list=None,
                    shipping_list=None, variant_filter_list=None, **kw):
        captured.update(urls=urls, output=output, seq_list=seq_list,
                        price_list=price_list, shipping_list=shipping_list,
                        variant_filter_list=variant_filter_list)
        # 造出 seq 文件夹，process_excel 用它判断"有没有产出文件"
        for s in seq_list:
            d = Path.cwd() / str(s)
            d.mkdir(parents=True, exist_ok=True)
            (d / "img_001.webp").write_bytes(b"x")
        return results_factory(seq_list)

    orig_scrape = run_excel.scrape_shein
    orig_out = run_excel.OUTPUT_ROOT
    run_excel.scrape_shein = fake_scrape
    run_excel.OUTPUT_ROOT = Path(tmp_root) / "out"
    try:
        run_excel.process_excel(xlsx)
    finally:
        run_excel.scrape_shein = orig_scrape
        run_excel.OUTPUT_ROOT = orig_out

    return load_workbook(xlsx)["ZR1"], captured


def test_process_excel_fills_f_through_m_and_passes_cde():
    tmp = tempfile.mkdtemp()
    try:
        ws2, cap = _run_process_excel(
            [[1, "http://a", 10.0, 0.0, "Black / M"],
             [2, "http://b", None, None, None]],
            _fake_results, tmp)
        assert cap["urls"] == ["http://a", "http://b"]
        assert cap["seq_list"] == [1, 2]
        assert cap["price_list"] == [10.0, None]
        assert cap["shipping_list"] == [0.0, None]
        assert cap["variant_filter_list"] == ["Black / M", ""]
        assert ws2.cell(2, COL_STATUS).value == "Done"
        assert ws2.cell(2, COL_SHEIN_TITLE).value == "Raw Title 1"
        assert ws2.cell(2, COL_EBAY_TITLE).value == "eBay Title 1"
        assert ws2.cell(2, COL_EBAY_PRICE).value == 19.19
        assert ws2.cell(2, COL_WEB_PRICE).value == "9.99–14.99"
        assert ws2.cell(2, COL_STOCK).value == "Black-M: 1"
        assert ws2.cell(3, COL_STATUS).value == "Done"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_process_excel_marks_delisted_and_failed():
    tmp = tempfile.mkdtemp()
    try:
        def results(seqs):
            return [{"seq_num": 1, "status": "DELISTED"},
                    {"seq_num": 2, "status": "ERROR: boom"}]

        ws2, _ = _run_process_excel(
            [[1, "http://a", None, None, None],
             [2, "http://b", None, None, None]], results, tmp)
        assert ws2.cell(2, COL_STATUS).value == "Delisted"
        assert ws2.cell(3, COL_STATUS).value == "Failed"
        # 失败/下架的行只写日期和状态
        assert ws2.cell(2, COL_EBAY_PRICE).value is None
        assert ws2.cell(3, COL_EBAY_PRICE).value is None
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_process_excel_skips_non_template_sheet():
    tmp = tempfile.mkdtemp()
    try:
        from openpyxl import Workbook, load_workbook
        wb = Workbook()
        ws = wb.active
        ws.title = "OldSheet"
        for c, h in enumerate(["Seq", "Website", "Price", "Date", "Status"], 1):
            ws.cell(1, c).value = h
        ws.append([1, "http://a", 9.9, None, None])
        xlsx = Path(tmp) / "old.xlsx"
        wb.save(xlsx)

        called = []
        orig = run_excel.scrape_shein
        run_excel.scrape_shein = lambda *a, **k: called.append(1) or []
        try:
            run_excel.process_excel(xlsx)
        finally:
            run_excel.scrape_shein = orig
        assert called == [], "旧英文表不该被抓取"
        ws2 = load_workbook(xlsx)["OldSheet"]
        assert ws2.cell(2, 4).value is None and ws2.cell(2, 5).value is None
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
```

并把这三个新函数名加进 `if __name__ == "__main__":` 的调用列表（在 `print("ALL PASS")` 之前）。

- [ ] **Step 2: 跑测试确认失败**

Run: `python test_template_io.py`
Expected: `AssertionError` 或 `TypeError`（旧 `process_excel` 还在读英文列、也没传 `shipping_list`）

- [ ] **Step 3: 实现**

> **一处有意收紧**：判 `Done` 的条件从旧的 `if has_files and not is_bad_data:` 变成
> `if rec and has_files and not is_bad_data and rec.get("status") == "OK":`。
> 旧写法在 `results` 为 None（抓取整体异常）或该 seq 没有记录时，只要目录里还留着
> **上一次运行**的文件就会误判成 Done。加上 `rec` 和状态检查后，限流/异常批次会
> 老老实实标 Failed。

把 `run_excel.py` 的 `process_excel()` 整个函数替换成：

```python
def process_excel(xlsx_path: Path) -> None:
    """按中文表头模板处理 `xlsx_path` 里的每个 sheet。非模板 sheet 跳过。
    列定义见模块 docstring 和 design spec §1。"""
    logger.info("Opening: %s", xlsx_path.name)
    wb = load_workbook(xlsx_path)

    for ws_name in wb.sheetnames:
        ws = wb[ws_name]
        store = ws_name.strip()
        if not _sheet_matches_template(ws):
            logger.warning("  Sheet '%s': 不是中文模板（B1 不是「链接」），跳过", store)
            continue

        pending = _read_pending_rows(ws)
        if not pending:
            logger.info("  Sheet '%s': 没有待处理的行", store)
            continue

        logger.info("  Sheet '%s': %d 行待处理: seq %s",
                    store, len(pending), [p["seq"] for p in pending])

        store_dir = OUTPUT_ROOT / store
        store_dir.mkdir(parents=True, exist_ok=True)

        today = datetime.now().strftime("%Y-%m-%d")
        seqs = [p["seq"] for p in pending]
        seq_min, seq_max = min(seqs), max(seqs)
        batch_xlsx = f"{store}-{seq_min}-{seq_max}-{today.replace('-', '')}.xlsx"

        old_cwd = Path.cwd()
        results = None
        try:
            # Google Drive 同步偶尔会短暂锁住新建目录
            for _retry in range(5):
                try:
                    os.chdir(store_dir)
                    break
                except PermissionError:
                    time.sleep(2)
            else:
                os.chdir(store_dir)   # 最后一次，让它抛
            logger.info("  Scraping %d URLs → %s/%s", len(pending), store, batch_xlsx)
            results = scrape_shein(
                [p["url"] for p in pending],
                output=batch_xlsx,
                seq_list=seqs,
                price_list=[p["price"] for p in pending],
                shipping_list=[p["shipping"] for p in pending],
                variant_filter_list=[p["variant_filter"] for p in pending],
            )
        except RateLimitError:
            logger.warning("  [限流] Rate limited during '%s'", store)
        except Exception as e:
            logger.exception("  Error processing '%s': %s", store, e)
            try:
                tb = traceback.format_exc()
                (DEBUG_LOG_DIR / "last_traceback.txt").write_text(tb, encoding="utf-8")
            except OSError:
                pass
        finally:
            os.chdir(old_cwd)

        # 把结果扇回模板行
        for p in pending:
            row, seq = p["row"], p["seq"]
            seq_folder = store_dir / str(seq)
            has_files = seq_folder.is_dir() and any(seq_folder.iterdir())

            rec = None
            if results:
                rec = next((r for r in results if r.get("seq_num") == seq), None)

            # SKU 为空或标题里还带 [goods_name] 的，不算真成功
            is_bad_data = (rec and rec.get("status") == "OK"
                           and (not rec.get("sku")
                                or "[goods_name]" in (rec.get("title") or "")))

            if rec and has_files and not is_bad_data and rec.get("status") == "OK":
                _write_result_row(
                    ws, row=row, date=today, status="Done",
                    picture_path=rec.get("first_image_path") or None,
                    web_price=rec.get("web_price_display"),
                    shein_title=rec.get("original_title") or rec.get("title"),
                    ebay_title=rec.get("ebay_title"),
                    ebay_price=rec.get("ebay_price"),
                    stock=rec.get("stock_summary"),
                )
                logger.info("    seq %d → Done", seq)
            elif rec and rec.get("status") == "DELISTED":
                _write_result_row(ws, row=row, date=today, status="Delisted")
                logger.info("    seq %d → Delisted", seq)
            else:
                detail = rec.get("status", "") if rec else ""
                if is_bad_data:
                    detail = "no data loaded"
                _write_result_row(ws, row=row, date=today, status="Failed")
                logger.info("    seq %d → Failed %s", seq,
                            f"({detail})" if detail else "")

        safe_save(wb, xlsx_path)
        logger.info("  Saved progress to %s", xlsx_path.name)

    wb.close()
    logger.info("Done: %s", xlsx_path.name)
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python test_template_io.py`
Expected: `ALL PASS`

Run: `python -c "import run_excel; print('import ok')"`
Expected: `import ok`

- [ ] **Step 5: 提交**

```bash
git add test_template_io.py run_excel.py
git commit -m "refactor(run_excel): rewrite process_excel for Chinese template; drop English input path"
```

---

### Task 9: `check_stock.py` 在新模板上变成安全 no-op

**Files:**
- Modify: `check_stock.py`（import 区；`check_stock_excel()` 里 `wb = load_workbook(...)` 之后；sheet 循环入口 `check_stock.py:135` 之前）
- Test: `test_check_stock_skip.py`

**Interfaces:**
- Consumes: `run_excel._sheet_matches_template`（Task 7）——`check_stock.py` 顶部 `from run_excel import _sheet_matches_template`
- Produces: 行为契约「新模板 sheet → 一个单元格都不写」；整份文件全是新模板时 **连 Chrome 都不启动**

**注意：函数叫 `check_stock_excel(xlsx_path)`，不是 `process_excel`。** 它在 `check_stock.py:127`
就调了 `_ensure_chrome(CDP_PORT)`（整个文件一次），所以只加 per-sheet 的 `continue` 还不够——
一份纯新模板的表仍然会白启动一次 Chrome。因此加**两道**保护：文件级早退 + sheet 级 continue。

- [ ] **Step 1: 写失败的测试**

创建 `test_check_stock_skip.py`：

```python
"""Test: check_stock.py 遇到中文新模板必须完全不写单元格，也不启动 Chrome。
新 schema 的 E/F/G 是 变体/日期/状态，老逻辑会把它们当 Status/Stock/Last Checked。
Run: python test_check_stock_skip.py
"""
import shutil
import tempfile
from pathlib import Path

from openpyxl import Workbook, load_workbook

import check_stock
import shein_scraper
from run_excel import EXPECTED_HEADERS


def _new_template_xlsx(tmp):
    wb = Workbook()
    ws = wb.active
    ws.title = "ZR1"
    for c, h in enumerate(EXPECTED_HEADERS, 1):
        ws.cell(1, c).value = h
    # 一行「已完成」——老逻辑正是拿这种行去复查库存的
    ws.append([1, "http://a", 10.0, 2.99, "Black / M",
               "2026-08-01", "Done", None, 12.99, "T", "eT", 18.19, "Black-M: 5"])
    p = Path(tmp) / "new.xlsx"
    wb.save(p)
    return p


def test_new_template_is_untouched_and_chrome_not_launched():
    tmp = tempfile.mkdtemp()
    try:
        p = _new_template_xlsx(tmp)
        before_row = [c.value for c in load_workbook(p)["ZR1"][2]]
        before_hdr = [c.value for c in load_workbook(p)["ZR1"][1]]

        # check_stock_excel 在函数体内部 from shein_scraper import _ensure_chrome，
        # 所以打桩模块属性即可拦住它。
        launched = []
        orig = shein_scraper._ensure_chrome

        def boom(*a, **k):
            launched.append(1)
            raise AssertionError("新模板不该启动 Chrome")

        shein_scraper._ensure_chrome = boom
        try:
            check_stock.check_stock_excel(p)
        finally:
            shein_scraper._ensure_chrome = orig

        assert launched == [], "Chrome 被启动了"
        after_row = [c.value for c in load_workbook(p)["ZR1"][2]]
        after_hdr = [c.value for c in load_workbook(p)["ZR1"][1]]
        assert before_row == after_row, f"数据行被改动\n{before_row}\n{after_row}"
        assert after_hdr == EXPECTED_HEADERS, after_hdr   # 没被塞 Stock/Last Checked
        assert before_hdr == after_hdr


if __name__ == "__main__":
    test_new_template_is_untouched_and_chrome_not_launched()
    print("ALL PASS")
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python test_check_stock_skip.py`
Expected: `AssertionError: 新模板不该启动 Chrome`（老逻辑无条件先 `_ensure_chrome`）

- [ ] **Step 3: 实现**

在 `check_stock.py` 的 `from config import ...` 那行下面加：
```python
from run_excel import _sheet_matches_template
```

在 `check_stock_excel()` 里 `wb = load_workbook(xlsx_path)`（`check_stock.py:124`）**之后**、
`_ensure_chrome(CDP_PORT)`（`check_stock.py:127`）**之前**插入：

```python
    # 中文新模板（A–M）里 E/F/G 是 变体/日期/状态，老的库存复查逻辑会写坏表。
    # 整份文件都是新模板 → 直接返回，连 Chrome 都不用起。
    # 等 S 重跑日期 / T 更新价格 / U 更新库存 三列定型后再支持。
    # 见 docs/superpowers/specs/2026-08-02-us-template-parallel-design.md §6
    if wb.sheetnames and all(_sheet_matches_template(wb[n]) for n in wb.sheetnames):
        logger.warning("%s: 全部是中文新模板，库存复查暂不支持（等 S/T/U 列上线），跳过",
                       xlsx_path.name)
        wb.close()
        return
```

再在 sheet 循环体最开头（`logger.info("Sheet: %s", store)` 之后、
`if ws.cell(1, 6).value != "Stock":` 那段表头补齐**之前**）插入 per-sheet 保护，
覆盖新旧混排的文件：

```python
        if _sheet_matches_template(ws):
            logger.warning("  Sheet '%s': 中文新模板，库存复查暂不支持，跳过", store)
            continue
```

- [ ] **Step 3b: 确认没有循环 import**

`run_excel.py` 不 import `check_stock`，所以 `check_stock → run_excel` 是单向的。验证：
```bash
grep -n "import check_stock" run_excel.py
```
Expected: 无输出。若有输出，改成把 `_sheet_matches_template` 挪进 `check_stock.py` 自己实现一份
（两行代码），不要制造循环依赖。

- [ ] **Step 4: 跑测试确认通过**

Run: `python test_check_stock_skip.py`
Expected: `ALL PASS`

Run: `python -c "import check_stock; print('import ok')"`
Expected: `import ok`

- [ ] **Step 5: 提交**

```bash
git add test_check_stock_skip.py check_stock.py
git commit -m "fix(check_stock): safe no-op on the new Chinese template"
```

---

### Task 10: 文档 + 版本 v3.8.0

**Files:**
- Modify: `ARCHITECTURE.md`、`CHANGELOG.md`、`version.py`、`installer.iss`
- Test: 全套回归

**Interfaces:**
- Consumes: 前 9 个任务的成果
- Produces: `VERSION = "3.8.0"`

- [ ] **Step 1: 跑全套回归**

Run:
```bash
python test_price_stock_format.py && python test_variant_filter.py && \
python test_pacing.py && python test_row_overrides.py && \
python test_rate_limit.py && python test_scrape_pool.py && \
python test_template_io.py && python test_check_stock_skip.py && \
python test_variant_merge.py
```
Expected: 9 个都 `ALL PASS`。任何一个失败就先修，不要继续。

- [ ] **Step 2: 更新 ARCHITECTURE.md**

把「Excel 列」那节（现在描述 A/B/C 只读 + C 列 Price 覆盖的那段，约 line 70–78）替换成新的 A–M 表；把 `EBAY_MARKUP` 环境变量表那节（约 line 147–154）补上 `MAX_PARALLEL_TABS = 3`、`IMAGE_DOWNLOAD_WORKERS = 4`、`INTER_URL_PAUSE_MIN/MAX = 2.0/3.0`，并删掉已不存在的长歇相关条目（如果表里有）。同时在文档里注明 `check_stock.py` 对新模板是 no-op。

- [ ] **Step 3: 写 CHANGELOG 条目**

在 `CHANGELOG.md` 顶部（`## v3.7.0` 之前）插入：

```markdown
## v3.8.0 — 2026-08-02
- **新表格格式（中文表头 A–M）**: A 编号 / B 链接 / C 原价 / D 运费 / E 变体 由员工填；F 日期 / G 状态 / H 图片 / I 希音价格 / J 希音标题 / K eBay标题 / L eBay价格 / M 库存 由程序填。旧的英文输入格式（Seq/Website/Price/Date/Status）**已彻底移除**，B1 不是「链接」的 sheet 会被跳过。
- **E 列变体声明**: 填 `黑色, 红色 / M, L` 只抓这些变体（`/` 分组、组内逗号分隔、忽略大小写和空格）。全都匹配不上 → 该行判 Failed。
- **D 列手填运费**: 空则回退原来的满免/2.99 推导。eBay 价公式 = `(C原价 或 抓到价 + D运费 或 推导运费) × 1.4`。
- **三标签并发**: `ThreadPoolExecutor(max_workers=3)`，图片下载池 8→4。限流触发时会先排空已完成的任务再停，不再整批丢结果。
- **节奏**: 每个 URL 抓完之后随机 2–3 秒，删除了原来的 4–12 秒随机 + 每 18 个 30–90 秒长歇。
- **$22 保底移除**: 低价商品不再被抬到 $30.80，`(原价+运费)×1.4` 直接算。
- **`check_stock.py` 暂停**: 新模板上是安全 no-op，等 S 重跑日期 / T 更新价格 / U 更新库存 三列上线后再支持。
```

- [ ] **Step 4: bump 版本**

`version.py`：`VERSION = "3.7.0"` → `VERSION = "3.8.0"`

`installer.iss`：把 `MyAppVersion` 改成 `3.8.0`（先 `grep -n "MyAppVersion" installer.iss` 确认当前值和行号）。

- [ ] **Step 5: 提交**

```bash
git add ARCHITECTURE.md CHANGELOG.md version.py installer.iss
git commit -m "release: v3.8.0 — Chinese template A-M, 3-tab parallelism, 2-3s pacing"
```

---

## 手工端到端验证（合并前必做）

代码完成后，在真实环境跑一遍。准备一个测试 sheet，至少包含：

1. **单变体商品** → `Done`，I 列是数字不是区间，M 列一条
2. **多变体 + E 列填了** → M 列只含声明的变体，J/K 列正常
3. **多变体 + E 列空** → M 列是完整清单，I 列是区间
4. **已下架商品** → `Delisted`，只写 F/G
5. **连续失败 3 次** → `Failed`，且**同批已完成的行结果没丢**

同时确认：

- [ ] C 列填了价 → L 列 = `(C + D或推导) × 1.4`，且 `图片-<sku>/eBay上架描述.txt` 的「各变体价格」段也用 C 列价
- [ ] D 列填 0 → L 列不含运费
- [ ] H 列图片嵌进去了，行高撑开
- [ ] 输出的批次 xlsx 仍是英文 14 列布局（拿旧文件对比）
- [ ] 日志里没有任何超过 3 秒的间隔打印
- [ ] 15 个 URL 的批次墙钟时间大约是原来串行的 1/3
- [ ] 拿一个旧英文表跑 `run_excel.py` → 警告跳过，表没被改
- [ ] 拿新模板表跑 `check_stock.py` → 提示跳过，表没被改
