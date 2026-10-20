# Shein Product Scraper - CHANGELOG

## v3.9.1 — 2026-10-20
- **AUTH_URL 迁到 public gist**。原来挂在 `raw.githubusercontent.com/MikeLiu93/shein-extract/main/auth.json`，仓库一旦转 private 匿名请求 404 → 员工 exe 启动失败。现在改成 `gist.githubusercontent.com/.../23718a882e2a53a35a6fee52d1e71b84/raw/auth.json`。gist 本身是 public、与 code 仓库解耦，之后 code 仓库可以转 private 而不影响身份校验。撤销账户的操作改成「`gh gist edit <id>` 或 gist web UI 编辑后保存」。

## v3.9.0 — 2026-10-19（事后补）
- **Excel 保存硬化 + 端口自动试探**。见 `0b2f86e`。

## v3.8.3 — 2026-08-17
- **修复保存失败 `BadZipFile: File is not a zip file`**。v3.8.2 修掉了图片被 close 的问题，但保存又栽在另一处：临时文件直接写在**目标目录**（Google Drive 虚拟盘 `D:\共享云端硬盘`）里，`wb.save(tmp)` 刚返回就 `zipfile.ZipFile(tmp)` 读回来自检 —— 文件其实是好的，是云盘上「写完马上读回」这一眼不可靠，57MB 的总表尤其明显。现在**自检在本地盘做完，目标盘只接一次已经验证过的整文件拷贝**，再原子替换。小文件（批次表、备份）一直没事也是这个原因。
- **嵌进 Excel 的图片大幅压缩**。以前存的是整张原图的 PNG（一张 0.7–2MB），可显示尺寸只有 168px 高 —— 纯浪费。现在按显示尺寸的 2 倍重采样后存 JPEG（quality 80），一张 20–30KB。**真表实测：57.7MB → 2.4MB**，Web 版 Excel 打得开了，保存也从 17s 降到 4s。
- **历史大图自动瘦身**：打开旧表保存时，超过 60KB 的图会顺手重新压一遍（`_harden_workbook_images`）。员工手上那份 57MB 的总表跑一次就瘦下来，不用手动处理。已经小于 60KB 的图不动，反复保存不会越压越糊。
- **保存不进去不再白干一轮**：`safe_save` 以前只在 `PermissionError`（Excel 开着）时退回 `<名字>2.xlsx`，其他错误直接抛 —— 抓好的结果只在内存里，一抛就全没了。现在任何保存失败都会先试写副本。

## v3.8.2 — 2026-08-17
- **修复：多个 sheet 一次跑不完 + 最后保存失败**（同一个根因）。openpyxl 的 `Image._data()` 读完图片字节就 `fp.close()`，而那个 fp 就是图片持有的 `BytesIO` —— 无论是程序嵌进去的，还是 `load_workbook` 从已有文件里读出来的。第一个 sheet 存完，工作簿里所有图片就废了，第二个 sheet 保存直接抛 `ValueError: I/O operation on closed file` → `ExcelSaveError` 冲出 sheet 循环，后面的 sheet 一个都没跑。现在保存前把每张图的字节缓存下来（`_harden_workbook_images`），存多少次都行；顺带把读不出来的图摘掉而不是拖垮整次保存。
- **备份路径默认 = 输入目录**。老默认值 `{DRIVE}\我的云端硬盘\Backup\Shein\总表` 指向多数机器上不存在的盘符，而 `backup_excel` 的 `mkdir` 在 try 外面 —— 没配好备份路径的员工整轮跑不起来。现在：不配 `SHEIN_BACKUP_DIR` 就备份到输入 Excel 所在目录；备份目录建不出来时自动退回输入目录；再不行就跳过备份。**备份绝不会再挡住开跑**。向导里备份目录留空 = 同输入文件夹。
- **人机验证改成静默等人工**。不再截图、不再发通知，检测到就在控制台提示一句，然后每 15 秒回头看一眼，最多等 10 分钟（`CAPTCHA_WAIT_SEC`）。人工过了就接着抓；等满 10 分钟没人处理就**结束此轮** —— 其余并发 tab 立刻停手，没抓到的行**日期/状态留空**（不标 Failed），下次重跑照样能挑到它们，剩下的 sheet 留到下次。
- **限流/验证码提前收工不再丢结果**：`RateLimitError` / `CaptchaAbort` 现在带 `records`，已经抓好的行照常写回表。以前异常一抛，整批抓好的商品会被当成 Failed 全部作废。

## v3.8.1 — 2026-08-06
- **只剩一个桌面图标**: 去掉了单独的「配置 SHEIN 上架工具」快捷方式。启动后在控制台里选 `[1] 配置目标路径` / `[2] 直接跑` / `[Q] 退出`。命令行 `--config` 和 `--run` 仍然可用。升级时会自动删掉旧的第二个图标。
- **向导不再扫盘符**: 以前会扫 D~K 盘找「共享云端硬盘\02 希音\Auto Pipeline」自动填路径。那个目录结构不用了，扫描只会永远失败 —— 现在直接让员工点【浏览...】选文件夹。
- **向导不再因路径不存在而卡住**: 输入文件夹不存在从「报错挡住」改成「问一句，可以继续」（共享盘还在同步时照样能存配置）。只有 Chrome 没装才会真的挡住。
- **输出根目录留空 = 同输入文件夹**: 汇总表和输出文件夹在同一个目录时（ZR 就是这样），少填一栏。店铺名（sheet 名）仍然自动作为子文件夹。

## v3.8.0 — 2026-08-02
- **新表格格式（中文表头 A–M）**: A 编号 / B 链接 / C 原价 / D 运费 / E 变体 由员工填；F 日期 / G 状态 / H 图片 / I 希音价格 / J 希音标题 / K eBay标题 / L eBay价格 / M 库存 由程序填。旧的英文输入格式（Seq/Website/Price/Date/Status）**已彻底移除**，B1 不是「链接」的 sheet 会被跳过。
- **E 列变体声明**: 填 `黑色, 红色 / M, L` 只抓这些变体（`/` 分组、组内逗号分隔、忽略大小写和空格）。全都匹配不上 → 该行判 Failed。
- **D 列手填运费**: 空则回退原来的满免/2.99 推导。eBay 价公式 = `(C原价 或 抓到价 + D运费 或 推导运费) × 1.4`。
- **三标签并发**: `ThreadPoolExecutor(max_workers=3)`，图片下载池 8→4。限流触发时会先排空已完成的任务再停，不再整批丢结果。
- **节奏**: 每个 URL 抓完之后随机 2–3 秒，删除了原来的 4–12 秒随机 + 每 18 个 30–90 秒长歇。
- **$22 保底移除**: 低价商品不再被抬到 $30.80，`(原价+运费)×1.4` 直接算。
- **M 列库存格式**: `黑色-M: 12 / 黑色-L: 缺货 / 红色-M: 少货 3`。单变体且无属性的商品只写数量（`20` / `缺货` / `少货 8`），不再显示 `I0xw62z3a2cr` 这类内部编码。
- **`check_stock.py` 暂停**: 新模板上是安全 no-op（连 Chrome 都不启动），等 S 重跑日期 / T 更新价格 / U 更新库存 三列上线后再支持。

## v3.7.0 — 2026-05-20
- **Excel C 列新增 "Price"，手动售价覆盖网页爬到的 sale_price**: 输入 Excel 列右移一位 (A=Seq, B=Website, C=Price 新, D=Date, E=Status, F=Stock, G=Last Checked)。C 列填了价就以 C 为准，否则回退到网页价。
- **价格一致性**: 不只主商品 price，每个 sku_prices 变体的 sale_price 也同步覆盖，"各变体价格"段、变体子行、Variation 2 单元格全部使用 C 列价格，避免"主行 eBay $37.11 / 变体 eBay $30.80"这种 confusing 输出。
- **eBay 价公式不变**: `max(C列价格 + shipping, $22) × 1.4`，只是 price 来源换成 C 列。
- **`run_excel.py` / `check_stock.py` 列号偏移**: Date→D, Status→E, Stock→F, Last Checked→G。Header 自动补齐 ("Price" / "Date")。

## v3.6.0 — 2026-05-06
- **密码门 + 中央撤销 (`auth.py` + `auth.json`)**: 启动时强制要求密码。哈希列表放在 GitHub raw URL（`/main/auth.json`），员工电脑拉取并和本地输入的 SHA-256 比对。撤销访问 = 编辑 auth.json 删除/置 `active:false` 那一行 + push commit，~5min CDN 缓存生效后 24h 内全员验证失败。
- **本地 24h 缓存 + 离线降级**: 验证成功后写 `%APPDATA%\shein-extract\auth_cache.json`，24h 内静默放行。如果 GitHub 暂时连不上但本地缓存还在 24h 内，警告但允许跑（员工偶发断网不阻塞工作）。缓存过期且离线则拒绝。
- **forward-compatible schema**: auth.json 用 list-of-dicts，每条带 `label`/`active` 字段。当前只有一条 `"shared"`，将来加按团队密码只需 append 一行；某团队走人就改/删那一条，其他团队完全不受影响。
- **`SheinExtract.exe --config` 重开设置向导**: 安装时一次性输入的路径/Excel 文件名/Anthropic key 现在可以随时重新编辑。`setup_wizard.Wizard.__init__` 加 `_load_existing_config()`，启动时读 `config.env` 预填所有 entry——员工再次打开看到的就是上次的值，改哪改哪。
- **桌面/开始菜单 "配置 SHEIN 上架工具" 快捷方式**: `installer.iss` 加两条 `[Icons]` 调 `--config`。员工双击即可改设置，不用记命令行。
- **owner-side 工具 `make_password_hash.py`**: 输入密码两次，输出 64 位 SHA-256，复制到 auth.json 即可。

## v3.4.1 — 2026-04-29
- **修复 v3.4 的 Page.navigate 不生效**: `Page.navigate(url, referrer="")` 被 Chrome 解析为"空字符串作为 Referer URL"，整个 navigate 命令被吞掉，新 tab 卡在 `chrome://newtab/` 不动。
- **改用 `PUT /json/new?<url>`**: CDP 原生支持，单步完成"开新 tab + 加载 URL"，等同于用户地址栏粘贴。`_new_tab(port, url=None)` 加 url 参数，URL 用 `urllib.parse.quote` 转义。
- **`_navigate_and_wait` 简化**: 不再需要 `Page.addScriptToEvaluateOnNewDocument` + `Page.navigate` 两步。anti-detect 暂时去掉（仅 3 行 mask `navigator.webdriver` 等，Chrome 启动参数 `--disable-blink-features=AutomationControlled` 已经覆盖大部分），如果 captcha 频率上升再加回来。

## v3.4 — 2026-04-29
- **每个 URL 开新 tab + 粘贴模式**：彻底等同于"用户手动新建 tab + 地址栏粘贴 URL + 回车"。`_navigate_and_wait` 现在每条 URL 调用 `_new_tab(port)` 开新 tab，再用 `Page.navigate(url, referrer="", transitionType="typed")` 加载，scrape 完成后在 finally 块关闭 tab。
- **保留 v3.3 的空 Referer**：每个新 tab 的导航都不发 Referer，仍能避开 Shein 的 src_identifier vs Referer 对账软封禁（OOPS 假页面）。
- **缓解 v3.0 之前的"新 tab 风暴"风险**：v3.2 引入的随机 4-12s 间隔 + 每 18 条长歇 30-90s 已经把"开 tab 频率"压到接近真人节奏，不会触发原来 commit 2ac56f5 担心的 API 限流。
- **session 预热重构**：`_ensure_shein_tab`（拿一个可复用 tab）→ `_ensure_shein_session`（只确保首页访问过、cookies 暖了）。预热 tab 不关闭，做"session 锚点"。
- **Tab 清理**：scrape 主循环 finally 块统一关 tab；移除 TIMEOUT 分支里冗余的 close 调用。

## v3.3 — 2026-04-29
- **修复 Senmeo 等小店 URL 触发 Oops 假页面**: `_navigate_and_wait` 从 `window.location.href` 改回 `Page.navigate(url, referrer="", transitionType="typed")`，等同于地址栏粘贴，不发 Referer。Shein 的反爬会对账 URL 里的 `src_identifier=...thirdPartyStoreHome...` 与实际 Referer，不一致就发 Oops；空 Referer 则跳过对账。
- **保留**：仍是单 tab 复用（v3.0 引入），不退回"每个 URL 新 tab"模式（那个会触发 API 限流）。
- **诊断 log**：每次导航后打印 `document.referrer` 实际值，方便确认是否真的发空。

## v3.2 — 2026-04-28
- **OOPS 退避重试**: 检测到 "Oops" 页面后先退避 30-60s 再重试一次，仍 OOPS 才判 DELISTED。原因：Shein 软封禁经常返回 Oops 假页面，立即标 DELISTED 会误杀真商品（同 URL 你自己点开正常显示）。
- **随机化间隔**: `DELAY_BETWEEN_PAGES = 2`（固定）改成每个商品间随机 4-12s + 每 18 个商品插一次 30-90s 长歇。新 helper `_inter_url_pause(i, total)` 替换所有原来的 `time.sleep(DELAY_BETWEEN_PAGES)`。代价：1000 条耗时约从 3h 增到 6h；收益：行为评分下降一档。
- **未来工作**: 见 `FUTURE_WORK.md` —— 更强 stealth JS、warmup 升级、周期性假浏览。

## v3.1 — 2026-04-27
- **退役老 .txt 流程**: 删除 `take_orders_worker.py` / `run_scheduled.cmd` / `run.cmd` / `run_once_from_txt.py` / `setup_schedule.ps1` / `_register_task.ps1` / `_register_merge_task.ps1` / `SheinTask.xml`
- **Windows 计划任务清理**: `SheinListing-TakeOrders` 和 `SheinListing-WeeklyMerge` 已 unregister（之前每天 14:00/20:00 触发老 worker，并误建 `Listing - web links (processed)` / `(failed)` 文件夹）
- **统一入口**: 唯一活跃流程为 `run_excel.py`（Excel 提交），Date/Status 写回输入 Excel，不再产生 processed/failed 文件夹

## v3.0 — 2026-04-26
- **Excel 管道 (run_excel.py)**: 从 TXT 输入切换到 Excel 输入（worksheet = 店铺），显式 Seq 列，Date/Status 自动回写
- **库存检查 (check_stock.py)**: 轻量脚本，只加载页面提取库存，不下载图片。~8s/URL，1000 条约 2-4 小时
- **自动备份**: 每次读取 Excel 前备份到 `D:\我的云端硬盘\Backup\Shein\总表\{名字}_{日期}.xlsx`
- **写入保护**: 文件被其他人打开时自动保存为 `{名字}2.xlsx`，不报错不丢数据
- **默认文件**: `python run_excel.py` 直接读 `Shein Submited Links.xlsx`，Test 文件需手动指定
- **列名标准化**: `Execute Date` 自动改为 `Date`
- **[goods_name] 秒跳**: 检测到标题为模板占位符立即标 Failed 跳过，不等 60 秒超时
- **Seq 始终记录**: 即使 Failed 的行，output Excel 的 No. 列也正确填写 seq
- **取消定时任务**: 删除 `SheinListing-TakeOrders`，改为手动运行
- **停用 _retry.txt**: 失败记录直接在输入 Excel 追踪，不再生成 retry 文件
- **超时缩短**: `EXTRACTION_TIMEOUT_SEC` 从 240s 降到 60s
- **Output 命名**: `{store}-{seq_min}-{seq_max}-{date}.xlsx`
- **截图归档**: captcha/block/timeout 截图自动移到 `screenshots/` 子文件夹

## v2.7.1 — 2026-04-25
- **根治限流**: 不再每个 URL 创建新标签（机器人特征），改为**复用单个标签 + JS `window.location.href` 导航**（与真人点击链接完全一致）
- **Session 预热**: 新 Chrome 首次自动访问 Shein 首页建立 cookies/session，后续导航不再被 API 限流
- **反检测脚本**: 注入 JS 隐藏 `navigator.webdriver` 和 CDP 自动化痕迹
- **限流等待恢复**: sleep 恢复为 2 小时
- **验证通过**: 新 Chrome + 3 个 URL 连续跑通，每个 3 秒加载完成
- **下架商品检测**: 识别 Oops/404 页面标记为 `DELISTED`，不计入连续失败（避免下架商品触发限流误判）

## v2.7 — 2026-04-23
- **AI 验证码自动解决**: 检测到 GeeTest 图标点选验证码时，自动截图发给 Claude Vision API 识别图标位置，CDP 模拟鼠标按顺序点击（带随机偏移 +-3px + 随机间隔 300-800ms）
- **三层防御**: AI 自动解决（最多 3 次） → 刷新页面后再 AI → 邮件通知等待人工
- **调试截图**: 每次 AI 尝试保存截图 `_captcha_ai_attempt_{n}.png` 方便分析失败原因
- **验证码样本收集**: 收集 29 张历史验证码截图到 `exam pics/collected/`，全部为 GeeTest 图标点选类型

## v2.6 — 2026-04-22
- **AI 标题生成**: 调用 Claude Haiku API 生成 eBay 标题，品牌识别更准确（Pempet/EastVita 等规则难覆盖的品牌也能删），智能去重（Dog Cage Dog Kennel → Dog Crate Kennel），单位和标点完整保留
- **自动 fallback**: API 调用失败（超时/无 key/返回异常）自动回退到规则引擎，不影响爬虫主流程
- **后处理修复**: 截断的 "FREE SH"/"FREE SHIP" 等残缺标签自动清除
- **eBay 描述文件复用**: `eBay上架描述.txt` 直接使用已生成的 AI 标题，不重复调 API
- **API key 配置**: 从 `.env` 文件读取 `ANTHROPIC_API_KEY`（已 gitignore）
- **成本**: Haiku 每个标题约 $0.0003，100 个商品约 $0.03

## v2.5.3 — 2026-04-20
- **eBay 标题重构**: 从"拆词重组关键词"改为"保留原文结构按段截断"，不再扭曲含义
- **标点保留**: 英寸 `"` (`29"-45"`)、斜杠 `/` (`24"/30"/36"`)、括号 `()` (`(0.25LB/0.5LB)`)、连字符 `-` (`Type-C`) 全部原样保留
- **语义保留**: `Set Of 8` 不再丢 `Of`，`2 In 1` 不再丢 `In`，介词和上下文关系保持完整
- **分段截断**: 按逗号/破折号/分号分段，从前往后拼接直到 80 字符，最后一段可部分截入
- **轻量清理**: 仅删除冠词 (the/a/an) 和营销噪声短语 (Shop Online/Free Shipping 等)，不做暴力去重

## v2.5.2 — 2026-04-17
- **断点续传**: worker 重跑时自动检测输出文件夹中已完成的 seq 子文件夹（含文件即为完成），跳过已完成的 URL，只跑剩余部分
- **复用原文件夹**: 不再创建 `-2` 新文件夹，直接在已有目录续写
- **恢复 Excel**: 续传结果单独写入 `shein_products_{store}_{seq}_resumed.xlsx`，与 retry 的 `2nd run` 逻辑一致
- **全部已完成检测**: 如果所有 seq 都已完成，直接标 done，不启动 Chrome
- **新增 `_detect_completed_seqs()`**: 扫描 run_dir 下纯数字命名的非空子文件夹

## v2.5.1 — 2026-04-16
- **eBay 标题去品牌**: 自动剥离开头 1-2 个全大写品牌词（UMAY/NIKE PRO 等）或首位 PascalCase 品牌词（EastVita/SheGlam 等）
- **白名单保护**: DIY/USA/USB/LED/PCS/OZ/ML/LB/CM/RGB/PVC 等缩写/单位不会被误删
- **数字+单位保留**: token 正则加点号支持，`0.25LB / 0.5LB / 1.5oz / 3.5ft` 等整体保留，不再被句号断成 `0` 和 `25LB`
- **示例对比**:
  - `UMAY 8 Shape Resistance Bands...` → 删 UMAY，输出 `8 Shape Resistance Bands Handles Figure Exercise Band Full Body Workout Gym Yoga`
  - `EastVita ... (0.25LB/0.5LB/0.75LB/1LB)` → 删 EastVita 且单位完整：`Fractional Weight Plates 8 0.25LB 0.5LB 0.75LB 1LB Micro Barbell Strength`

## v2.5 — 2026-04-16
- **本地 Dashboard**: 新增 `dashboard.py`（stdlib 零依赖，端口 5055），自动刷新 3s，显示健康徽章（OK/WARN/DEAD）、当前 txt 文件、URL 进度条 x/y、最近 8 条事件、最新 debug log 尾部 25 行
- **卡住判定**: 心跳 >60s 黄色 WARN，>5min 红色 DEAD；PID 死掉直接 DEAD
- **心跳/事件模块**: 新增 `state_tracker.py`，原子写 `state/state.json` + append `state/events.jsonl`
- **Worker 插桩**: `take_orders_worker.py` 在 start/stop/set_file/file_done/error/idle 六处发心跳
- **Scraper URL 级进度**: `shein_scraper.py` 每个 URL 开始时上报 `done/total/current_url`，graceful import（无 state_tracker 也能跑）
- **一键启动**: 新增 `run_dashboard.cmd`
- **备份**: `shein_scraper.py.bak.20260416` 为本次修改前备份

## v2.4 — 2026-04-11
- **周报合并脚本** (`merge_store_reports.py`): 按员工+店铺合并 shein_products Excel，去重（按 No. 列），图片从磁盘 seq 文件夹直接插入确保位置正确
- **严格周日期过滤**: 只合并当周（周一~周日）的文件夹，避免跨周重复。支持 `--week YYYYMMDD` 指定周、`--all` 合并全部
- **文件命名**: `shein_products_{store}_{weekrange}_{seqrange}_merged.xlsx`
- **每周自动运行**: 定时任务 `SheinListing-WeeklyMerge`，每周日 23:00 自动合并所有员工所有店铺

## v2.3 — 2026-04-09 ~ 2026-04-10
- **2026-04-10 修复**: rollback 误用旧备份导致 `RateLimitError` 等 v2.3 功能丢失，定时任务 `--once` 无法启动。已全部恢复并更新备份为 `shein_scraper.py.bak.20260410`
- **Retry 序号保留**: `_retry.txt` 记录原始 seq 号，retry 时用 `seq_list` 传入，媒体文件夹按原始序号命名（如 25, 28）
- **Retry 文件夹去重**: 媒体文件夹已存在时自动加 `-2` 后缀（如 `25-2`）
- **Retry 独立 Excel**: retry 结果写入 "2nd run" Excel，不覆盖原始表格
- **限流自动检测**: 连续 3 个 URL 失败自动判定限流，停止当前批次，等待 2 小时后自动继续剩余文件
- **页面超时提高**: EXTRACTION_TIMEOUT_SEC 从 120s 提高到 240s（4 分钟）
- **Stock 列 (col 14)**: 新增库存列，显示具体数量；缺货显示"缺货"，少货显示"少货 only X left"
- **变体 SKU 修正**: 变体子行 C 列改用 `mainSaleAttribute` 的 `goods_sn`（与商品 SKU 格式一致），不再使用内部 `sku_code`
- **mainSaleAttribute 提取**: JS 新增从 `gbRawData.modules.saleAttr.mainSaleAttribute` 提取颜色变体对应的独立 goods_sn
- **Retry 机制**: 失败的 URL 记录到输出文件夹 `_retry.txt`，`--retry` 模式只重跑失败项，原地更新已有 Excel
- **Excel URL 匹配**: `_save_excel` 支持通过 URL 列匹配覆盖错误占位行，retry 不再产生 -2/-3 重复文件夹
- **定时任务自动 retry**: `run_scheduled.cmd` 在 `--once` 之后自动运行 `--retry`
- **processed 员工分流**: 处理完的 txt 文件也按员工代号分流到子文件夹

## v2.2 — 2026-04-08
- **图片插入修复**: 安装 Pillow 依赖，Excel 中图片现在正常嵌入
- **Variant SKU 改到 C 列**: 变体子行的 SKU 列 (C) 直接显示该变体的 sku_code，取消独立 Variant SKU 列
- **eBay Title 列 (col 13)**: 自动生成的 eBay 上架标题（从 col 14 调整到 col 13）
- **员工分流输出**: completed 和 processed 文件夹按员工代号 (NA/TT/YAN/ZQW/LUMEI) 自动分流到子文件夹
- **move_file 容错**: 源文件已被 Google Drive 同步移走时不再崩溃，跳过并继续处理后续文件
- **定时任务更新**: 触发时间改为每天 14:00 和 20:00，脚本路径指向新项目目录
- **项目清理**: 删除旧测试文件、调试脚本、缓存，精简项目结构

## v2.1 — 2026-04-07
- **单值变体也显示**: 即使某个属性只有一个值（如 Size: Double），也会出现在 Variation 列
- **变体子行 No. 留空**: 同一商品的多个变体行，第一行保留编号，后续行 No. 列为空
- **变体子行 V1 也填充**: 之前变体子行只填 V2，现在 V1/V2 都填各自的具体值
- **variations 自动补全**: 从 sku_prices attrs 补充页面 JS 提取遗漏的变体属性
- **eBay Title**: 自动生成的 eBay 上架标题写入 Excel
- **Rollback**: `shein_scraper.py.bak.20260407` 为修改前备份

## v2.0 — 2026-03-31 ~ 2026-04-04 (Initial commit)
- Chrome CDP 远程调试协议抓取 Shein 商品数据
- 智能等待页面就绪（轮询 goods_sn，替代固定 sleep）
- 并行图片下载（ThreadPoolExecutor，8 线程）
- goods_imgs JSON 解析：从页面内嵌 JSON 提取有序主图
- 页面滚动触发懒加载
- 关闭用完标签页，避免 Chrome 堆积
- 验证码/登录弹窗检测与自动重试
- 超时保护 + 邮件通知
- Excel 输出：12 列（No./Date/SKU/Picture/Price/Shipping/URL/Store/Title/eBay price/V1/V2）
- 变体展开：多 SKU 商品按变体展开为多行，含库存标注
- eBay 上架资料 TXT 自动生成（标题/价格/变体明细）
- 媒体下载：商品图片 + 视频，自动过滤/去重/升级分辨率
- take_orders_worker：从 Google Drive submitted 文件夹自动取单处理
- 定时任务支持（Windows Task Scheduler）
