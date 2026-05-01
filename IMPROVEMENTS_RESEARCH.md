# 改进调研 — eBay 标题智能化 + 总表合并

> 状态：**纯调研，未改动任何代码**。Mike review 后挑选方案再实施。
> 每个改动点都列了"如何回滚"，你随时可以把改动撤销。

---

# 一、eBay 标题智能化

## 1.1 现状（v3.5 stage 1 之后）

prompt 在 `shein_scraper.py:1758-1772`，核心约束：

```
5. ALWAYS start with "NEW " and end with " FREE SHIPPING" if the total is ≤ 80 chars.
   If too long, try just "NEW " prefix. Drop tags only as a last resort.
```

**实际效果**：
- 80 字符里 16 字符（"NEW " 4 + " FREE SHIPPING" 12）被锁死给两个机械标签 → 仅剩 64 字符放真正的关键词
- 模型为了凑这两个标签，会牺牲掉一些有价值的修饰词
- "NEW" 和 "FREE SHIPPING" 都是高竞争词，eBay 搜索时 → 这俩词一搜满屏都是，相当于没用
- AI 没被引导去挖**真正有流量的长尾词**：人群标签（For Cats / For Men / Gift）、使用场景（Outdoor / Travel / Home Decor）、卖点形容词（Foldable / Washable / Heavy Duty）

## 1.2 哪些改动是高 ROI 的

按"工作量/收益"排序：

### 改动 A — 把 NEW/FREE SHIPPING 从"强制"改成"可选"（10 分钟，零风险）

把 prompt 第 5 条改成：

```
5. You MAY add "NEW" prefix or "FREE SHIPPING" suffix only if the title still has
   spare characters AND the original product is genuinely new / actually ships free.
   DO NOT add them just to fill space — prioritize keywords buyers search for.
```

**预期**：80 字符全部用于真正描述商品的词。NEW/FREE SHIPPING 在该出现时还会出现，不在该出现时省下来 16 字符给关键词。

**风险**：极低。模型本来在凑这俩词时会主动放弃一些好词，松绑后只会更好。

**回滚**：把 `_EBAY_TITLE_PROMPT` 字符串改回去（一次 git revert 就行）。

---

### 改动 B — 在 prompt 里加"流量关键词类别"提示（30 分钟，低风险）

在 prompt 里追加一段指导，告诉 AI 哪些类别的词是 eBay 高流量搜索词：

```
HIGH-TRAFFIC keywords to inject when relevant (only if the original title implies them):
- Audience: For Men / For Women / For Kids / For Pets / For Cats / For Dogs
- Use case: Outdoor / Indoor / Travel / Home / Office / Gift / Wedding / Christmas / Birthday
- Quality cues: Heavy Duty / Premium / Adjustable / Foldable / Waterproof / Washable / Portable
- Style cues: Modern / Vintage / Cute / Luxury / Minimalist
NEVER invent attributes that aren't supported by the original title.
```

**预期**：输出会从

```
NEW Cute Cat Bed Soft Plush Sleeping Cushion FREE SHIPPING
```

变成

```
Cute Cat Bed Soft Plush Washable Sleeping Cushion Indoor Pet Gift Home Decor
```

后者每个词都是真正有人会搜的，且利用了 80 字符的全部空间。

**风险**：低，但要小心模型"过度自由"乱加属性。需要 prompt 里强调 "NEVER invent"。

**回滚**：删掉新加的那段 prompt。

---

### 改动 C — A/B 跑 3 个候选 + 自动选最优（2 小时，中风险）

每个商品调 Haiku 3 次（temperature=0.5/0.7/0.9 各一次），按以下规则选最佳：

1. 长度优先（接近 80 字符的得分高，但不能超过 80）
2. 唯一关键词数量（去掉停用词后剩多少独特名词/形容词）
3. 不含禁用词（避免 SHEIN/sheIn 这类品牌污染）

**预期收益**：标题质量再上一个台阶，但调用成本 × 3（每个标题约 $0.001 → 100 个商品 ≈ $0.10，仍很便宜）。

**风险**：
- 如果选优规则有 bug，可能选出一个最差的版本
- 多调 2 次 API → 多 2-4 秒延迟，单 URL 总耗时不变（媒体下载是大头）

**回滚**：把 `_make_ebay_title_ai()` 函数恢复成单次调用版（git revert）。

---

### 改动 D — 升级模型到 Claude Sonnet 4.6（5 分钟，零风险但贵）

把 model 字段从 `claude-haiku-4-5-20251001` 改成 `claude-sonnet-4-6`。

**预期收益**：标题质量明显上一档（Sonnet 比 Haiku 在创意性、文案质感、关键词嗅觉上都更强）。

**成本对比**：
| 模型 | 每标题成本 | 100 个商品 | 1000 个商品 |
|---|---|---|---|
| Haiku 4.5 | ~$0.0003 | $0.03 | $0.30 |
| Sonnet 4.6 | ~$0.003 | $0.30 | $3.00 |

**风险**：零（API 完全兼容），就是贵 10 倍。

**回滚**：改回 model 字段。

## 1.3 我推荐的组合

**执行 A + B + D**，跳过 C。

理由：
- A 几乎零成本立竿见影，必做
- B 给模型一个"流量词典"，相比 C 的 A/B 测试更可控
- D 用 Sonnet 一个月也就十几美金，对小团队完全可接受，且 Sonnet 比 Haiku 在创意性写作上差距不小
- C 工作量大但收益不明显（B 已经覆盖了大部分增益）

**预计实施时间**：1 小时（包括跑 5-10 个真实 URL 对比新老标题质量）

---

# 二、定期合并总表

## 2.1 你的需求拆解

> 把 `D:\共享云端硬盘\02 希音\Auto Pipeline\Listing - completed 2nd\C4` 里的 3 个 excel 合并成一个总表

每个店铺文件夹下有这种结构：

```
Listing - completed 2nd/
└─ C4/
   ├─ C4-1-50-20260415.xlsx       ← 4/15 跑的批次（seq 1-50）
   ├─ C4-51-100-20260420.xlsx     ← 4/20 跑的批次（seq 51-100）
   ├─ C4-1-30-20260425.xlsx       ← 4/25 跑的 retry，seq 1-30 里有重叠
   ├─ 1/  2/  3/  ...             ← 每个 seq 的媒体文件夹
   └─ screenshots/
```

**合并目标**：
- 一个店铺一个总表（C4 → `C4_master.xlsx` 或类似）
- **去重**：同一个 seq 出现多次时保留**有效那条**（失败的 seq price=0，重跑成功后 price 才有值）
- **按 seq 排序**：行从 seq 1 开始，依次往下
- **图片**：跟现有表格格式一致 —— 从 seq 文件夹的 `img_001.webp` 读，插入 D 列（Picture）

## 2.2 关键设计问题

### Q1：去重规则怎么定？

同一个 seq 可能在多个 excel 里出现，要决定保留哪一行。我的方案：

```
对每个 seq：
  1. 收集所有出现过的行
  2. 按以下顺序选最优：
     a. 有效 SKU + price > 0 的行（成功的）
     b. status == 'DELISTED' 的行（确认下架）
     c. 其它失败行（兜底，让总表里也能看到这个 seq 失败过）
  3. 同一类多行时，取**最新 date** 的那条
```

❓ **要不要加"主行 + 变体子行"成对处理**？
现在每个 seq 在 Excel 里可能占多行（一个商品有多个颜色/尺寸变体）。去重时要把**同一 seq 的所有相关行**作为一组保留/丢弃，否则会拆散变体表。

我推荐：**整组保留**。判定逻辑是"主行（A 列有 seq 数字）+ 它后面所有 A 列为空的变体子行 = 一组"。

### Q2：合并触发时机？

三种选项：
- **(a) 手动**：你需要的时候双击 `merge_master.cmd`，扫描所有店铺合并
- **(b) 跑完 run_excel.py 自动触发**：每次跑完后顺便合并
- **(c) 单独的定时任务**：每周日晚上自动合并（类似旧的 SheinListing-WeeklyMerge）

我推荐 **(a) 手动**：
- (b) 会让正常流程变慢（合并大表很耗时）
- (c) 你之前定时任务都被 captcha 整没了，不想再加定时任务
- (a) 最直接、最可控

### Q3：总表放哪里？

❓ 三个候选：
- 各店铺文件夹根目录：`Listing - completed 2nd\C4\C4_master.xlsx`（图片相对路径最稳）
- 单独总表目录：`Listing - completed 2nd\_master\C4_master.xlsx`
- 备份云盘里：`Backup\Shein\总表\C4_master.xlsx`

我推荐 **第一个** —— 跟原始 Excel 同目录，图片插入用相对路径，挪动文件夹不会断图。

### Q4：要不要保留多张图？

现在每个 seq 文件夹里有 `img_001.webp`、`img_002.webp` …可能十几张。当前每个 Excel 只插主图（`img_001`）。

❓ 总表是否也只插主图？我推荐**保持一致 = 只插主图**，否则文件会变得非常大（一个商品 10 张图就是几 MB，1000 个商品就 GB 级）。

### Q5：合并后的命名 + 续合并策略？

❓ 两种思路：
- **每次重新合并**：`C4_master.xlsx`，每次合并都覆盖旧的（文件名固定）
- **加日期戳**：`C4_master_20260501.xlsx`，每次新文件不覆盖

我推荐**每次重新合并**：每次合并都是从所有 daily excel 重新读，幂等，不需要保留多版本。

## 2.3 我推荐的实施方案

### 文件结构

新建一个独立脚本 `merge_master.py`（**不动现有的 `merge_store_reports.py`**，那个是给老 TXT 流程的）：

```
Listing - completed 2nd/
└─ C4/
   ├─ C4_master.xlsx          ← NEW: 这个店铺的总表（按 seq 排序，去重后）
   ├─ C4-1-50-20260415.xlsx   ← daily excels 不动
   ├─ C4-51-100-20260420.xlsx
   ├─ ...
   └─ 1/  2/  3/  ...
```

启动方式：
```cmd
python merge_master.py              # 合并所有店铺
python merge_master.py C4           # 只合并 C4
```

或双击 `merge_master.cmd`（包到安装包里给员工用）。

### 算法

```
对每个店铺文件夹 {store}/：
  1. 扫描所有 {store}-*-*-*.xlsx（daily excels，按文件名里的 date 排序）
  2. 排除 *_master.xlsx 自身
  3. 读所有 daily 的所有数据行，组装成 (seq, date, row_data, 是否变体子行) 元组
  4. 把变体子行归到它前面那个主行的 group 里（一个 group = 一个 seq 的所有行）
  5. 同一 seq 的多个 group 选最优（见 Q1 规则）
  6. 按 seq 升序排列
  7. 写入新 wb：
     - header 用最近一个 daily excel 的 header 当模板
     - 数据行原样复制（cell value + 字体 + 填充色 + 边框 + 数字格式）
     - Picture 列从 {store}/{seq}/img_001.webp 重新插入
  8. 保存为 {store}_master.xlsx
```

复用 `merge_store_reports.py` 里的 `_add_picture()` 和 `_find_first_image()`（两者 90% 通用，加一个 `seq_dir` 参数即可）。

### 风险 + 回滚

| 风险 | 应对 |
|---|---|
| 合并误判，把成功的行替换成失败行 | 加详细日志：每个 seq 输出"选中：xxx 来源 xxx，丢弃：xxx 来源 xxx"；先用 `--dry-run` 模式只打不写 |
| 图片找不到（比如媒体被删了） | 单元格留空 + 日志警告，不报错 |
| daily excel 列结构不一致 | 用最新 daily 的 header 当基准，旧 excel 多余/缺失列时填空 |
| 总表写入时被打开锁住 | 同 `safe_save()`：失败则改名 `{store}_master2.xlsx` |

**回滚**：删掉 `merge_master.py` 文件即可，daily excels 完全没动过。

## 2.4 工作量估计

- 写 `merge_master.py`：3-4 小时
- 单元测试 + 用现有真实数据跑通：1-2 小时
- 写一个简单的 `merge_master.cmd`：5 分钟
- 文档（员工怎么用）：30 分钟
- **合计：约半天到一天**

---

# 三、整体执行建议

## 3.1 推荐的执行顺序

1. **现在**：你 review 这份文档，告诉我对各方案的取舍
2. **下一轮**：先做改动 A + B + D（eBay 标题，1 小时） → 用 5-10 个真实 URL 对比新老标题，你看效果
3. **同一轮**：写 `merge_master.py`（半天） → 用 C4 实际目录跑一次，你 review 总表
4. **再下一轮**：合并到 v3.5 主线 → 进阶段二打包

## 3.2 决策（Mike 确认 2026-05-01）

### eBay 标题方向
- [x] **T1**：改动 A（NEW/FREE SHIPPING 改成可选）→ **执行**
- [x] **T2**：改动 B（加流量关键词类别提示）→ **执行**
- [x] **T3**：改动 C（A/B 测试）→ **不做**
- [x] **T4**：改动 D（升级到 Sonnet 4.6）→ **不做** —— 保留 Haiku，省成本
- [x] **T5**：打包前做 → **是**

### 总表合并方向
- [x] **M1**：整组保留主行+变体子行 → **是**
- [x] **M2**：手动触发 → **是**
- [x] **M3**：总表放店铺文件夹根目录 → **是**
- [x] **M4**：只插主图 → **是**
- [x] **M5**：打包给员工 → **是**，但运行前要输入店铺代号（如 C4）
- [x] **M6**：先 dry-run → **是**（`--dry-run` 已支持）

## 3.3 实施状态

阶段 1.5（标题改进 + 总表合并）已实施：
- `shein_scraper.py` `_EBAY_TITLE_PROMPT` 已更新（A+B）
- `merge_master.py` 新文件：per-store 合并器，CLI 或交互式输入店铺代号
- `merge_master.cmd` 新文件：员工双击入口，提示输入店铺代号

阶段二打包时 `merge_master.py` 和 `merge_master.cmd` 都纳入分发。
