"""Deterministic conversation routing rules shared by every pipeline mode."""
from __future__ import annotations

import re


_HANDOFF_NEGATIONS = re.compile(
    r"(?:不转(?:接)?人工|不想转(?:接)?人工|"
    r"(?:不需要|不用|无需|无须|不必|没必要|不是(?:要|想|希望)|不想|不要|别|暂不|暂时不|先不).{0,6}"
    r"(?:转(?:接)?人工|人工客服|真人客服|人工坐席|人工介入|人工处理|真人|人工))"
)
_HANDOFF_REQUESTS = (
    re.compile(r"(?:转(?:接)?(?:给我)?|接通|联系|找|叫|切换到|换成|安排).{0,6}(?:人工客服|人工坐席|真人客服|真人|人工)"),
    re.compile(r"(?:我需要|我要(?:找|转|联系|接)?|我想(?:找|转|联系|接|和|要)|请(?:帮我|给我)?转(?:接)?|麻烦(?:帮我|给我)?转(?:接)?|给我转(?:接)?).{0,5}(?:人工客服|人工坐席|真人客服|真人|人工)"),
    re.compile(r"(?:给我|帮我)(?:转(?:接)?到?|联系|找|接通)(?:一下)?(?:人工客服|人工坐席|真人客服|真人|人工)"),
    re.compile(r"(?:人工客服|人工坐席|真人客服|真人|人工).{0,6}(?:帮我|给我|接待|处理|介入|沟通|说话|服务)"),
    re.compile(r"(?:请|麻烦|让|要求|需要|我要|我想).{0,8}(?:人工客服|人工坐席|真人客服|真人|人工).{0,8}(?:跟进|处理|联系|介入|接待|沟通|帮忙|帮我)"),
    re.compile(r"(?:请|麻烦|让|要求|需要|我要|我想).{0,8}卖家本人.{0,5}(?:联系|回复|处理|沟通)"),
    re.compile(r"(?:不要|别用|不想和)(?:智能)?机器人.{0,6}(?:人工|真人|客服|聊|说话|沟通)"),
)
_HANDOFF_ONLY = re.compile(r"(?:人工|真人|人工客服|真人客服|人工坐席)[!！。,.，\s]*")
_ORDER_STATUS_MARKERS = (
    "订单现在", "快递实时位置", "物流显示", "包裹今天", "订单号", "收货地址",
    "什么时候揽收", "快递员联系", "物流停", "订单有没有发出", "订单是否发出",
)
ORDER_STATUS_REPLY = "我这边查不到实时订单或物流信息，您可以在订单详情或快递官方渠道查看物流轨迹。"
KNOWLEDGE_GAP_REPLY = "这个问题我暂时无法从现有资料确认，请人工客服继续为您核实。"


def explicitly_requests_human(message: str) -> bool:
    """Return true only for a direct human-agent request, excluding negations."""
    text = re.sub(r"\s+", "", str(message or ""))
    if not text or _HANDOFF_NEGATIONS.search(text):
        return False
    return bool(_HANDOFF_ONLY.fullmatch(text) or any(pattern.search(text) for pattern in _HANDOFF_REQUESTS))


def is_realtime_order_query(message: str) -> bool:
    """Keep order/parcel status questions on the self-service AI path."""
    text = re.sub(r"\s+", "", str(message or ""))
    return any(marker in text for marker in _ORDER_STATUS_MARKERS)
