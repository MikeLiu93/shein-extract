# Future Work — Shein Extract

Captured 2026-04-28. Items here are deferred enhancements, not bugs.
Pick up when current pipeline shows symptoms that warrant the extra
complexity, or when current mitigations stop being enough.

## Anti-Detection / Rate Limiting

### C. 加强 stealth JS（mask 更多 bot 指纹）

**当前**: `_JS_ANTI_DETECT` 只 4 行，仅 mask `navigator.webdriver` 和 `window.chrome`。

**改进**: 移植开源 puppeteer-extra-plugin-stealth 的 JS 等价品（约 200 行），
mask `navigator.plugins`、`navigator.languages`、`navigator.permissions`、
WebGL vendor、Notification.permission、PluginArray 等 20+ 个常见 bot 指纹。

**预期收益**: captcha 触发频率下降一档；某些"无理由 OOPS"减少。

**风险**: 可能让某些 Shein JS 出错（罕见，但要 smoke test）。

**触发信号**: 当前 A+B 之后还经常 captcha；或 OOPS-retry 成功率 < 50%。

---

### D. Warmup 升级：首页 → 随机分类 → 搜索 → 进商品

**当前**: 首次启动只访问一次 `https://us.shein.com/` 等 5s。

**改进**: 30-60s 假浏览序列：
- 首页停留 8-15s（滚动、悬停一两个分类）
- 随机点一个分类（例如 Women, Men, Sports）
- 在分类页随机滚动 / 看 1-2 个商品略读
- 然后开始正式爬

**预期收益**: session 评分更高，整体 captcha/OOPS 率下降。

**风险**: 首次启动慢 30-60s；脚本要跟 Shein 改版（分类 selector 可能变）。

---

### E. 周期性"假浏览"插入

**当前**: 商品到商品之间已有随机 4-12s 间隔 + 每 18 个商品长歇 30-90s（v3.2 已加）。

**改进**: 每 N 个商品后跳进首页/分类逛 20s 再回来，模拟真人"刷一会儿别的"。

**预期收益**: 长批次（500+ 条）尾段触发率下降。

**风险**: 复杂度上升；总耗时再 +20-30%。

**触发信号**: A+B+C+D 都做了，但跑大批次后半段仍频繁触发；或我们要常态化跑 1000+ 条。

---

## Operational Notes

### Cookie / 浏览历史

**不要**手动清掉 `~/shein-cdp-profile` 的 cookie/history 来"换换运气"。
这个 profile 的 cookie 不是垃圾，是**信誉积累**：每次成功访问都让 Shein 的
session 评分更高。清掉相当于把账号回到 day 0，反而更可疑。

如果觉得 profile 受污染了（比如反复触发 captcha），**重建**比清更好：
```cmd
rmdir /s /q "%USERPROFILE%\shein-cdp-profile"
```
然后让脚本走完整 warmup（v3.2 之后是 5s 首页，C/D 之后会更长）。

### IP 轮换 / 代理

不推荐。Shein 也防代理 IP 池；引入会增加复杂度、延迟、成本，且开源代理
池信誉极差。**真要解决 IP 限流再考虑住宅代理服务**（Bright Data 等），但目
前的症状（同 IP，个人 Chrome 通、scraper 不通）证明问题不在 IP 层。

### 切换框架（puppeteer-extra / undetected-chromedriver）

不推荐。当前 CDP 直连方案已经够灵活，切框架等于重写。需要的反检测能力
都可以在现有架构上加（见 C/D）。
