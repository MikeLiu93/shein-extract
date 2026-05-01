# 阶段二：打包与分发设计草稿

> 状态：**草稿，待 Mike 确认**。所有 ❓ 处都是我的假设，你确认或修改后我开始写代码。
> 阶段一改动：v3.5 stage 1 commit（已 staged，待 Mike 在 Windows 手动 commit）。

---

## 1. 总体架构

```
你的开发机 (C:\Users\ak\Desktop\Claude\shein-extract\)
  │
  │  (1) 你写代码 + git push
  ▼
GitHub: MikeLiu93/shein-extract  ❓public 还是 private？
  │
  │  (2) 你跑 build.bat → PyInstaller 打 onefile → Inno Setup 套壳
  ▼
SheinExtract-Setup-v3.5.X.exe  (~80MB)
  │
  │  (3) 你 git tag v3.5.X + 上传到 GitHub Release
  ▼
GitHub Release: v3.5.X 资产
  │
  │  (4) 员工首次：你发链接，员工下载安装；
  │      日常：员工双击快捷方式，自动检查更新
  ▼
员工电脑 Windows 10/11
  ├─ %LOCALAPPDATA%\SheinExtract\        程序本体（Inno Setup 装这里）
  │   ├─ SheinExtract.exe                PyInstaller 打包好的主程序
  │   ├─ python\                         嵌入式 Python（被 PyInstaller 内嵌）
  │   └─ resources\                      JS 脚本、prompt 等资源
  │
  ├─ %APPDATA%\shein-extract\            员工配置（向导写入）
  │   ├─ config.env                      路径、首次完成标记
  │   └─ last_update_check.json          上次检查更新时间
  │
  ├─ %USERPROFILE%\shein-cdp-profile\    Chrome 持久化 profile（cookies/SHEIN 登录）
  │
  └─ Desktop\Shein 上架.lnk              桌面快捷方式
```

---

## 2. 打包工具链

| 工具 | 用途 | 版本 |
|---|---|---|
| **PyInstaller** | 把 .py + 嵌入式 Python 打成一个 .exe | 6.x |
| **Inno Setup** | 套一个 Windows 安装包外壳（写桌面快捷方式、卸载、注册表） | 6.x |
| **GitHub Actions** | 可选：你 push tag 自动 build .exe + 上传 release ❓**做不做？** |  |

**简化方案**（如果你嫌 GitHub Actions 麻烦）：本地 build.bat，每次发版你手动跑 + 手动上传 release。

**我推荐**：先纯本地 build，跑顺了再考虑 GitHub Actions。

---

## 3. 首次运行向导（Tkinter GUI）

启动逻辑（`SheinExtract.exe` 是 PyInstaller 包出来的入口）：

```python
def main():
    if not is_first_run_complete():
        run_setup_wizard()    # Tkinter GUI
    else:
        check_for_updates()   # 静默
        run_excel_pipeline()  # 现有 run_excel.py 逻辑
```

向导流程（5 步，每步一个 Tkinter 窗口）：

### Step 1 — 欢迎 + 系统检查
- 检查 Chrome 是否已装 → 没装就显示下载链接 + 阻断 ❓
- 检查 Google Drive for Desktop 是否在跑 → 没跑就显示下载链接 + 警告（**允许跳过**让员工先装 Drive 完后回来）

### Step 2 — 路径配置
- 自动扫描 G:/D:/E:/F: 看哪个底下有"共享云端硬盘\02 希音\Auto Pipeline\Listing - web links (submitted)"
- 三个输入框（带"浏览..."按钮）：
  - 输入 Excel 所在目录（自动填扫描到的路径）
  - 输入文件名（默认 "Shein Submited Links.xlsx"）
  - 输出根目录（自动填）
  - 备份目录（员工要单独选 —— 你说会建独立的备份共享盘）
- 实时校验：路径是否存在 + 输入 Excel 文件是否存在

### Step 3 — SHEIN 登录（强制走一次）
- 显示说明："接下来会打开一个 Chrome 窗口，请在里面登录你的 SHEIN 卖家账号。**登完之后直接关掉那个 Chrome 窗口**，向导会自动继续。"
- 大按钮"打开 Chrome 登录 SHEIN" → 启动 Chrome with `--user-data-dir=%USERPROFILE%\shein-cdp-profile`
- 后台轮询 Chrome 进程：进程退出后检查 profile 里的 cookies 是否包含 `shein.com` 的关键 session cookie（如 `armorEuid`、`memberId` 之类）
- 如果检测到登录成功 → 进入下一步；失败 → 提示"似乎没登录成功，再试一次？"

### Step 4 — 测试运行
- 自动跑一个**小测试**：用一个固定的公开 SHEIN URL（比如某个常年在售的商品）跑一次完整流程
- 如果成功（页面能加载、AI 标题生成、文件能写到员工指定的输出路径）→ 显示绿勾 + 文件路径
- 如果失败 → 显示具体错误（例如"AI key 失效"/"路径无写权限"/"被验证码拦截"）+ 提示重试或联系管理员

### Step 5 — 完成
- 写 `%APPDATA%\shein-extract\config.env` 标记首次完成
- 提示员工日常用桌面快捷方式启动
- 关闭向导

❓ **要不要 Step 4 的"测试运行"？** 多 1 分钟但能立刻发现问题。我推荐保留。

---

## 4. API Key 处理（你的决策：1-a）

**你的方案**：公司公用一个 key，每个员工 .exe 里都有。Anthropic 后台设月度上限。

**塞进 .exe 的方式**（按推荐排序）：

### 4a. 轻度混淆（推荐）
```python
# build 时：
import base64
KEY = "sk-ant-real-key-here"
PASSPHRASE = "shein-extract-2026"
encoded = base64.b64encode(bytes(c ^ ord(PASSPHRASE[i % len(PASSPHRASE)])
                                   for i, c in enumerate(KEY.encode()))).decode()
# 把 encoded 写进 secrets.py，PyInstaller 一起打包

# 运行时：解码后用
def _get_api_key():
    encoded = "..."  # from secrets.py
    PASSPHRASE = "shein-extract-2026"
    raw = base64.b64decode(encoded)
    return ''.join(chr(b ^ ord(PASSPHRASE[i % len(PASSPHRASE)]))
                   for i, b in enumerate(raw))
```
**门槛**：员工要会装反编译工具+读 Python bytecode 才能挖出来。普通员工挖不出，但懂技术的员工 30 分钟内能挖出。**够你的需求吗？**

### 4b. 真安全方案（不推荐，工作量大）
你部署一个最小的代理（Cloudflare Workers 免费档够用），员工 .exe 调代理，代理才有真 key + 鉴权。多花 1 天工作量，但 key 永远不在员工电脑上。

❓ **选 4a 还是 4b？** 默认 4a。

❓ **还是干脆直接明文 .env 塞进 .exe？** 这样最简单但门槛是 0，员工解压 .exe 就能拿到。

---

## 5. 自动更新机制（你的决策：3-a）

### 启动时检查（限频每天一次）
```
SheinExtract.exe 启动
  ├─ 读 %APPDATA%\shein-extract\last_update_check.json
  ├─ 如果距上次检查 < 24 小时 → 跳过
  └─ 否则：
      ├─ GET https://api.github.com/repos/MikeLiu93/shein-extract/releases/latest
      ├─ 比较 tag_name 和当前版本（写在 SheinExtract.exe 内部 const VERSION）
      ├─ 如果有新版：弹 Tkinter 对话框：
      │   ┌────────────────────────────────────┐
      │   │  发现新版本 v3.5.2                  │
      │   │  当前版本 v3.5.0                    │
      │   │                                    │
      │   │  更新内容：                         │
      │   │  - 修复 captcha 检测...             │
      │   │  - 加快图片下载...                  │
      │   │                                    │
      │   │  [立即更新]  [本次跳过]              │
      │   └────────────────────────────────────┘
      ├─ 立即更新 → 下载新 .exe 到临时目录 → 启动一个 helper 脚本替换主 .exe → 启动新版
      └─ 本次跳过 → 写 last_update_check.json，正常启动
```

❓ **要不要"跳过此版本"按钮**（点了之后这个版本一直不再提示）？我建议不要 —— 你迭代很频繁，新版本里可能有重要修复。

### GitHub repo 可见性

❓ **MikeLiu93/shein-extract 现在是 public 还是 private？**
- **Public** → 直接 `GET /releases/latest` 不用 token，最简单
- **Private** → 需要 PAT 塞进 .exe（**新增一个泄露点**），不推荐
- **建议**：把 repo 设为 public，反正代码里没有真正机密（API key 不在代码里）

---

## 6. 日常运行体验

双击桌面"Shein 上架"图标后：

```
1. SheinExtract.exe 启动
2. 黑底命令行窗口出现，前 2 秒：
     "正在检查更新... 已是最新版"
3. 然后开始跑 run_excel.py 主流程，stdout 实时打印：
     "Sheet: B4"
     "  3 pending URL(s): seq [12, 13, 14]"
     "[1/3] https://us.shein.com/..."
     "  navigating..."
     "  页面就绪..."
     "  eBay title : NEW Cute Cat Bed... FREE SHIPPING (AI)"
     ...
4. 全部跑完后：
     "All done."
     "Press any key to close..."
```

❓ **运行结果能不能用 GUI 显示**（一个简单进度条 + 错误列表）？比黑窗口友好但多 1 天工作量。**默认黑窗口 + pause**。

---

## 7. 卸载

Inno Setup 自动建卸载入口（控制面板/Settings 里能找到）。卸载会：
- 删 `%LOCALAPPDATA%\SheinExtract\`
- 删桌面快捷方式
- **不动** `%APPDATA%\shein-extract\`（保留员工配置，重装时复用）❓
- **不动** `~\shein-cdp-profile`（保留 SHEIN 登录） ❓

❓ 卸载时要不要给个选项"是否同时清除我的配置和 SHEIN 登录"？

---

## 8. 文件清单（我会创建的新文件）

| 文件 | 用途 |
|---|---|
| `setup_wizard.py` | Tkinter GUI 向导（5 步） |
| `update_check.py` | 检查 GitHub release + 限频 + 下载替换逻辑 |
| `secrets.py` | 编译时生成，存混淆后的 API key |
| `app_main.py` | PyInstaller 入口：决定 wizard / update / pipeline |
| `version.py` | `VERSION = "3.5.0"` 一行 |
| `build.bat` | 本地一键 build：调 PyInstaller + Inno Setup |
| `installer.iss` | Inno Setup 脚本 |
| `pyinstaller.spec` | PyInstaller 配置（隐藏 import、资源文件等） |
| `INSTALL_GUIDE_CN.md` | 给员工看的简体中文安装指南（截图版） |
| `RELEASE_PROCESS.md` | 给你看的发版 SOP |

需要打包进 .exe / 安装包的现有文件：
- `run_excel.py` — 主流程（被 `app_main.py` 调用）
- `merge_master.py` — 总表合并工具（员工自己跑）
- `merge_master.cmd` — 总表合并双击入口
- `shein_scraper.py` / `notify.py` / `config.py` — 核心模块
- `requirements.txt` — 运行时依赖

需要修改的现有文件：
- `shein_scraper.py`：`_get_api_key` 加上"先尝试从 secrets.py 解码"的逻辑
- `requirements.txt`：build 时加 `pyinstaller`（运行时不需要）

---

## 9. 时间估计

| 步骤 | 工作量 |
|---|---|
| 写 setup_wizard.py + 测试 | 1 天 |
| 写 update_check.py + 测试 | 0.5 天 |
| API key 混淆 + secrets.py 生成脚本 | 0.5 天 |
| PyInstaller spec + 解决隐藏 import | 0.5-1 天（最玄学的一步） |
| Inno Setup 脚本 | 0.5 天 |
| 端到端测试（在干净 Win 虚拟机上跑） | 1 天 |
| 写员工指南 + 你的发版 SOP | 0.5 天 |
| **合计** | **4.5-5 天** |

---

## 10. 决策（Mike 已全部确认 2026-05-01）

- [x] **Q1**：API key 混淆方案 → **4a (XOR + base64)**
- [x] **Q2**：更新检查频率 → **每天最多 1 次**
- [x] **Q3**："跳过此版本"按钮 → **不做**
- [x] **Q4**：GitHub repo 改成 **public**（Mike 自行操作）
- [x] **Q5**：向导第 4 步"测试运行" → **保留**
- [x] **Q6**：日常运行 → **黑窗口 + pause**（不做 GUI 进度条）
- [x] **Q7**：卸载时不清除配置 → **保留 %APPDATA% 和 ~\shein-cdp-profile**
- [x] **Q8**：本地 **build.bat**（不用 GitHub Actions）
- [x] **Q9**：Drive 没装时 → **允许向导跳过 Step 1**

接下来：等 Mike 在 Windows 上 commit 阶段一 + 验证现有功能没被破坏，我就开工写 Stage 2 代码。
