"""可取消、限定响应大小的公开 JSON 接口客户端。"""

import json
import logging
from threading import Event
from time import monotonic
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, urlopen

from src.shared.tasks import check_cancelled

LOGGER = logging.getLogger("workbench.http")


def get_json(endpoint: str, parameters: dict, timeout: int, cancelled: Event) -> dict:
    parsed = urlsplit(endpoint)
    LOGGER.debug("准备 JSON 请求，参数数量 %d（不记录参数值）", len(parameters))
    if parsed.scheme not in ("https", "http") or not parsed.hostname or parsed.username or parsed.password or parsed.fragment:
        raise ValueError("服务地址必须是有效 HTTP(S) URL，不能包含用户名密码或片段")
    separator = "&" if parsed.query else "?"
    url = endpoint + separator + urlencode(parameters)
    check_cancelled(cancelled)
    request = Request(url, headers={"User-Agent": "GraphicalWorkbench/0.1", "Accept": "application/json"})
    chunks = []
    count = 0
    deadline = monotonic() + timeout * 2
    started = monotonic()
    LOGGER.info("HTTP 请求开始：主机 %s，超时 %d 秒", parsed.hostname, timeout)
    with urlopen(request, timeout=timeout) as response:
        LOGGER.debug("HTTP 响应状态：%s", response.status)
        while True:
            check_cancelled(cancelled)
            if monotonic() > deadline:
                raise TimeoutError("数据读取超时")
            chunk = response.read(65536)
            if not chunk:
                break
            count += len(chunk)
            if count > 4 * 1024 * 1024:
                raise ValueError("服务器响应超过允许大小")
            chunks.append(chunk)
    check_cancelled(cancelled)
    document = json.loads(b"".join(chunks))
    if not isinstance(document, dict):
        raise ValueError("服务器未返回 JSON 对象")
    if document.get("error"):
        raise ValueError(str(document.get("reason", "服务返回错误")))
    LOGGER.info("HTTP JSON 请求完成：%d 字节，耗时 %.2f 秒", count, monotonic() - started)
    return document
