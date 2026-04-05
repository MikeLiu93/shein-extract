"""
邮件通知模块：Shein 爬虫遇到验证码/登录拦截时发送告警邮件。
"""

import smtplib
import os
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.image import MIMEImage
from pathlib import Path
from datetime import datetime


# ── 配置 ──────────────────────────────────────────────────────────────────────
GMAIL_USER = "dracarys001mike@gmail.com"
GMAIL_APP_PASSWORD = os.environ.get("GMAIL_APP_PASSWORD", "cwde kuik qngh gsgu")
NOTIFY_TO = "dracarys001mike@gmail.com"  # 收件人（可以和发件人一样）
SMTP_SERVER = "smtp.gmail.com"
SMTP_PORT = 587


def send_alert(subject: str, body: str, screenshot_path: str | None = None) -> bool:
    """
    发送告警邮件。可选附带截图。
    返回 True 表示发送成功。
    """
    if not GMAIL_APP_PASSWORD:
        print(f"  [通知] GMAIL_APP_PASSWORD 未设置，无法发送邮件")
        print(f"  [通知] 主题: {subject}")
        print(f"  [通知] 内容: {body}")
        return False

    msg = MIMEMultipart()
    msg["From"] = GMAIL_USER
    msg["To"] = NOTIFY_TO
    msg["Subject"] = subject

    # 正文
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    full_body = f"{body}\n\n时间: {timestamp}\n发送自: Shein Scraper 自动监控"
    msg.attach(MIMEText(full_body, "plain", "utf-8"))

    # 附带截图（如果有）
    if screenshot_path and Path(screenshot_path).is_file():
        with open(screenshot_path, "rb") as f:
            img = MIMEImage(f.read(), name=Path(screenshot_path).name)
            msg.attach(img)

    try:
        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT, timeout=30) as server:
            server.starttls()
            server.login(GMAIL_USER, GMAIL_APP_PASSWORD)
            server.send_message(msg)
        print(f"  [通知] 邮件已发送: {subject}")
        return True
    except Exception as e:
        print(f"  [通知] 邮件发送失败: {e}")
        return False


def alert_captcha(url: str, screenshot_path: str | None = None) -> bool:
    """验证码拦截告警"""
    return send_alert(
        subject="⚠ Shein 爬虫被验证码拦截",
        body=f"爬虫在以下页面遇到验证码/人机验证，5分钟内未能自动绕过，需要人工处理。\n\n页面: {url}",
        screenshot_path=screenshot_path,
    )


def alert_signin(url: str, screenshot_path: str | None = None) -> bool:
    """登录要求告警"""
    return send_alert(
        subject="⚠ Shein 要求登录",
        body=f"爬虫在以下页面被要求登录/注册，自动关闭失败，需要人工处理。\n\n页面: {url}",
        screenshot_path=screenshot_path,
    )


def alert_generic(url: str, message: str, screenshot_path: str | None = None) -> bool:
    """通用告警"""
    return send_alert(
        subject="⚠ Shein 爬虫异常",
        body=f"{message}\n\n页面: {url}",
        screenshot_path=screenshot_path,
    )
