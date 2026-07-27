"""Token 计数与上下文截断工具。

封装独立工具类，供对话链路与会话总结使用。
优先尝试 tiktoken，不可用时回退到字符启发式估算。
"""

from typing import Sequence

from app.core.logger import get_logger

log = get_logger("utils.token")


class TokenCounter:
    """Token 计数与截断工具。"""

    def __init__(self, encoding_name: str = "cl100k_base") -> None:
        self._encoding = None
        try:
            import tiktoken

            self._encoding = tiktoken.get_encoding(encoding_name)
        except Exception as e:
            log.warning(f"tiktoken 不可用，使用启发式估算: {e}")

    def count_text(self, text: str) -> int:
        """计算单段文本的 token 数。

        Args:
            text: 文本内容

        Returns:
            估算 token 数量
        """
        if not text:
            return 0
        if self._encoding is not None:
            return len(self._encoding.encode(text))
        # 启发式：中文约 1.5 字/token，英文约 4 字符/token，取保守估算
        return max(1, len(text) // 2)

    def count_messages(self, messages: Sequence[dict]) -> int:
        """计算消息列表总 token（含角色开销近似）。

        Args:
            messages: [{"role": "...", "content": "..."}, ...]
        """
        total = 0
        for msg in messages:
            total += 4  # 每条消息角色/分隔符开销近似
            total += self.count_text(str(msg.get("content", "")))
        return total

    def should_trigger_summary(
        self,
        messages: Sequence[dict],
        max_context: int,
        ratio: float = 0.8,
    ) -> bool:
        """判断当前上下文是否达到总结触发比例。

        Args:
            messages: 当前待发送消息
            max_context: 模型最大上下文
            ratio: 触发比例，默认 80%
        """
        if max_context <= 0:
            return False
        used = self.count_messages(messages)
        return used >= int(max_context * ratio)


# 全局单例
token_counter = TokenCounter()
