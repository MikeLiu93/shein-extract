# 新电脑安装指南（Windows）

## 1. 装 Python
推荐 Anaconda（https://www.anaconda.com/download）或官方 Python 3.10+。
安装时勾选 **Add Python to PATH**。

验证：
```cmd
python --version
```

## 2. 装 Google Chrome
https://www.google.com/chrome/

代码会自动找 Chrome，搜索路径：
- `C:\Program Files\Google\Chrome\Application\chrome.exe`
- `C:\Program Files (x86)\Google\Chrome\Application\chrome.exe`
- `%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe`

## 3. 装 Google Drive for Desktop
https://www.google.com/drive/download/

登录你那个有"02 希音"共享云端硬盘的 Google 账号，等同步完成。
**默认会挂在 `G:\` 盘**。如果你的不是 G:，记下盘符，下面要改 `.env`。

确认这两个目录存在：
- `G:\共享云端硬盘\02 希音\Auto Pipeline\Listing - web links (submitted)`
- `G:\我的云端硬盘\Backup\Shein\总表`（首次跑会自动创建）

## 4. Clone 代码
```cmd
cd %USERPROFILE%\Desktop
git clone https://github.com/MikeLiu93/claude-projects.git
cd claude-projects\shein extract
```

## 5. 装 Python 依赖
```cmd
pip install -r requirements.txt
```

依赖很小：`openpyxl` + `requests` + `websocket-client`。

## 6. 配 `.env`
复制模板：
```cmd
copy .env.example .env
notepad .env
```

填这几个：
- `ANTHROPIC_API_KEY` —— 从老电脑 `.env` 拷贝（**不要发邮件/聊天，用密码管理器或 U 盘**）
- `GMAIL_APP_PASSWORD` —— 从老电脑 `.env` 拷贝；建议**先在 Google 账号里撤销旧的、生成新的**
- `SHEIN_DRIVE` —— 默认 `G:`。Google Drive 装在别的盘符就改成那个

## 7. 首次运行
```cmd
run_excel.cmd
```

或：
```cmd
python run_excel.py
```

**首次运行会**：
- 启动 Chrome（带专属 profile：`%USERPROFILE%\shein-cdp-profile`）
- 你需要在那个 Chrome 窗口里**手动登录 Shein 卖家账号**（Profile 持久化，以后不用再登）
- 可能遇到验证码 → 邮件会发到 `dracarys001mike@gmail.com`，你手动过一下即可

## 8. （可选）Dashboard
```cmd
run_dashboard.cmd
```
浏览器开 http://localhost:5055 看进度。

---

## 故障排查

| 症状 | 可能原因 / 解决 |
|---|---|
| `Chrome not found. Searched: ...` | Chrome 没装或装在非标准路径。装到默认位置即可 |
| `ModuleNotFoundError: openpyxl` | 没跑 `pip install -r requirements.txt` |
| `[通知] GMAIL_APP_PASSWORD 未设置` | `.env` 里没填 `GMAIL_APP_PASSWORD`，邮件告警不可用（但爬虫照跑） |
| `Default file not found: G:\...\Shein Submited Links.xlsx` | Google Drive 还没同步完，或 `SHEIN_DRIVE` 配错 |
| 路径里中文乱码 | 用 cmd 而不是 Git Bash 跑；或终端 `chcp 65001` |
