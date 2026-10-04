"""可返回给客户端的业务错误（HTTP 422）。"""
from __future__ import annotations


class MosaicError(ValueError):
    """请求数据无法用于拼接（类型不合法、像元越界、几何不对齐等）。"""
