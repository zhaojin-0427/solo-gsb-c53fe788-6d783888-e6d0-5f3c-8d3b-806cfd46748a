"""可返回给客户端（HTTP 422）的业务错误。

独立成模块以避免 ``png_codec`` 与 ``mosaic_service`` 之间的循环导入。
"""
from __future__ import annotations


class MosaicError(ValueError):
    """可返回给客户端的 422 业务错误。"""
