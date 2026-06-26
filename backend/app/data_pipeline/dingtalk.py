"""
钉钉通知模块

使用钉钉自定义机器人 Webhook 推送告警消息。
配置方式：在 .env 中设置 DINGTALK_WEBHOOK_URL 和 DINGTALK_SECRET（加签模式）
"""

import base64
import hashlib
import hmac
import logging
import time

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

# 钉钉 Webhook URL（从环境变量或配置读取）
DINGTALK_WEBHOOK_URL = getattr(settings, "dingtalk_webhook_url", "") or ""
DINGTALK_SECRET = getattr(settings, "dingtalk_secret", "") or ""


# 消息类型
class MsgType:
    TEXT = "text"
    MARKDOWN = "markdown"


def is_configured() -> bool:
    """检查是否已配置钉钉"""
    return bool(DINGTALK_WEBHOOK_URL and DINGTALK_WEBHOOK_URL.startswith("https://"))


def _generate_sign(secret: str) -> tuple[str, str]:
    """
    生成钉钉加签

    Returns:
        (timestamp, sign) - 时间戳和签名
    """
    timestamp = str(round(time.time() * 1000))
    secret_enc = secret.encode("utf-8")
    string_to_sign = f"{timestamp}\n{secret}"
    string_to_sign_enc = string_to_sign.encode("utf-8")
    hmac_code = hmac.new(secret_enc, string_to_sign_enc, digestmod=hashlib.sha256).digest()
    sign = base64.b64encode(hmac_code).decode("utf-8")
    return timestamp, sign


def _get_webhook_url() -> str:
    """获取带签名的 Webhook URL（如果配置了 secret）"""
    if not DINGTALK_SECRET:
        return DINGTALK_WEBHOOK_URL

    timestamp, sign = _generate_sign(DINGTALK_SECRET)
    separator = "&" if "?" in DINGTALK_WEBHOOK_URL else "?"
    return f"{DINGTALK_WEBHOOK_URL}{separator}timestamp={timestamp}&sign={sign}"


def send_text(content: str, at_mobiles: list[str] = None) -> bool:
    """
    发送文本消息

    Args:
        content: 消息内容
        at_mobiles: 需要 @ 的手机号列表

    Returns:
        是否发送成功
    """
    if not is_configured():
        logger.debug("钉钉未配置，跳过推送")
        return False

    payload = {
        "msgtype": MsgType.TEXT,
        "text": {
            "content": content,
        },
    }

    if at_mobiles:
        payload["at"] = {
            "atMobiles": at_mobiles,
            "isAtAll": False,
        }

    return _send(payload)


def send_markdown(title: str, content: str, at_mobiles: list[str] = None) -> bool:
    """
    发送 Markdown 消息

    Args:
        title: 标题
        content: Markdown 格式内容（支持 ###、-、** 等）

    Returns:
        是否发送成功
    """
    if not is_configured():
        logger.debug("钉钉未配置，跳过推送")
        return False

    payload = {
        "msgtype": MsgType.MARKDOWN,
        "markdown": {
            "title": title,
            "content": content,
        },
    }

    if at_mobiles:
        payload["at"] = {
            "atMobiles": at_mobiles,
            "isAtAll": False,
        }

    return _send(payload)


def _send(payload: dict) -> bool:
    """发送请求到钉钉"""
    try:
        webhook_url = _get_webhook_url()
        with httpx.Client(timeout=10) as client:
            response = client.post(
                webhook_url,
                json=payload,
                headers={"Content-Type": "application/json"},
            )
            result = response.json()

            if result.get("errcode") == 0:
                logger.info("钉钉推送成功")
                return True
            else:
                logger.error("钉钉推送失败: %s", result.get("errmsg"))
                return False

    except Exception as e:
        logger.error("钉钉推送异常: %s", e)
        return False


# ── 快捷函数 ─────────────────────────────────────────────


def notify_task_start(task_name: str) -> bool:
    """通知任务开始"""
    return send_text(f"🔄 数据同步任务开始\n任务: {task_name}")


def notify_task_success(task_name: str, total: int, success: int, fail: int) -> bool:
    """通知任务成功"""
    emoji = "✅" if fail == 0 else "⚠️"
    content = f"""**{emoji} 数据同步完成**

**任务**: {task_name}
**总数**: {total}
**成功**: {success}
**失败**: {fail}"""
    return send_markdown(f"{emoji} {task_name} 完成", content)


def notify_task_failed(task_name: str, error: str) -> bool:
    """通知任务失败"""
    content = f"""**❌ 数据同步失败**

**任务**: {task_name}
**错误**: {error}

请及时检查！"""
    return send_markdown(f"❌ {task_name} 失败", content)


def notify_alert(level: str, task_name: str, message: str) -> bool:
    """通知告警"""
    level_emoji = {"error": "🔴", "warning": "🟡", "info": "🔵"}.get(level, "📢")
    content = f"""**{level_emoji} 数据同步告警**

**级别**: {level.upper()}
**任务**: {task_name}
**详情**: {message}"""
    return send_markdown(f"{level_emoji} 告警: {task_name}", content)
