# 发版 SOP

> 给老板（Mike）看的发版流程。员工版指南是 `INSTALL_GUIDE_CN.md`。

---

## 一次性准备（每台 build 机器装一次）

1. **Python 3.10+**
2. **PyInstaller**：`pip install pyinstaller`
3. **运行依赖**：`pip install -r requirements.txt`
4. **Inno Setup 6**：https://jrsoftware.org/isdl.php （把 `iscc.exe` 加 PATH，或装到默认路径 `C:\Program Files (x86)\Inno Setup 6\`）
5. **生成 `.build_key.txt`** 在项目根目录，里面**单行**填你的 Anthropic API key（这文件 `.gitignore` 已排除，不会进 commit）：
   ```
   sk-ant-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
   ```

---

## 每次发版（5 步）

### 1. 改版本号

`version.py`：
```python
VERSION = "3.5.1"   # 改这一行
```

`installer.iss`：
```pascal
#define MyAppVersion "3.5.1"   ; 改成同一个版本
```

`build.bat` 的最后提示信息（可选，不改也能跑）。

### 2. 在干净 Windows 环境验证

如果代码改动较大，建议在测试机或 VM 上：
```cmd
git pull
python run_excel.py     # 先确认源代码能跑
```

### 3. Build

```cmd
build.bat
```

3 步自动完成：
1. `make_key_store.py` 生成 `key_store.py`
2. `pyinstaller pyinstaller.spec` 生成 `dist\SheinExtract.exe`
3. `iscc installer.iss` 生成 `dist\SheinExtract-Setup-3.5.1.exe`

如果只想要裸 .exe（不需要安装包）：`build.bat exe`

### 4. 在干净 Windows 上测试安装包

强烈建议在一台**没装过这个工具**的电脑（或 VM）上：
1. 双击 `SheinExtract-Setup-3.5.1.exe` 安装
2. 双击桌面图标 → 走完一遍向导
3. 输入测试 Excel 跑 5-10 个 URL → 看图片/标题/Excel 都正常
4. 测一遍 `merge_master.cmd`
5. 卸载 → 重装 → 确认配置和 SHEIN 登录都还在

### 5. 发布到 GitHub Release

```cmd
git add version.py installer.iss
git commit -m "release: v3.5.1"
git tag v3.5.1
git push origin main --tags
```

然后在 GitHub 网页：
1. https://github.com/MikeLiu93/shein-extract/releases/new
2. **Choose a tag**: `v3.5.1`
3. **Release title**: `v3.5.1` （tag 必须以 `v` 开头，update_check.py 解析的就是这个 tag）
4. **Description**: 列改了什么（员工会在更新弹窗里看到这段）
5. **Upload binary**: 把 `dist\SheinExtract-Setup-3.5.1.exe` 拖进 attachments
6. 点 **Publish release**

发版完成。员工下次启动工具时（24 小时窗口内）会自动看到更新提示。

---

## 通知员工

老板群里发：

> SHEIN 上架工具更新了 v3.5.1。
> 大家不用动，下次启动工具时会弹更新提示，点【立即更新】就好。
> 改了什么：[列改动]

---

## 紧急回滚

如果新版本有 bug：

1. **从 GitHub Release 删除有问题的版本**（点 release → Edit → Delete release）
2. 这样新启动的工具检测不到那个版本，员工保持在老版本
3. 修好 bug 后发新版本（version 号要继续递增，不能回退）

如果某个员工已经更新到坏版本：
- 直接发给他**老的 .exe**，让他覆盖到 `%LOCALAPPDATA%\SheinExtract\SheinExtract.exe`
- 或者重新装老版本的 `SheinExtract-Setup-3.5.0.exe`，配置和登录都不会丢（向导只在没 config.env 时跑）

---

## API Key 月度上限设置

记得去 Anthropic 控制台 https://console.anthropic.com/ 给共用 key 设月度 budget：
- 一个 100 商品的批次约 $0.03（Haiku 4.5）
- 团队 5 个员工每人每天 100 → $0.15/天 → $5/月
- **建议月限设 $20**，足够正常使用 + 留 buffer，泄露损失也封顶 $20

---

## 改 API Key

任意时候要换 key（轮换、之前的疑似泄露）：

1. 把新 key 写进 `.build_key.txt`
2. 把 `version.py` 里的版本号 +1（哪怕只是 patch 号）
3. `build.bat`
4. 发新 release

员工自动更新拿到的就是带新 key 的 .exe。
