"""可取消、限定响应大小的公开 JSON 接口客户端。"""

from src.shared.errors import ui_error

import json
import logging
from threading import Event
from time import monotonic
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, urlopen

from src.shared.tasks import check_cancelled

LOGGER = logging.getLogger("workbench.http")


def get_json(endpoint: str, parameters: dict, timeout: int, cancelled: Event, *, allow_list: bool = False, user_agent: str | None = None) -> dict | list:
    parsed = urlsplit(endpoint)
    LOGGER.debug("准备 JSON 请求，参数数量 %d（不记录参数值）", len(parameters))
    if parsed.scheme not in ("https", "http") or not parsed.hostname or parsed.username or parsed.password or parsed.fragment:
        raise ui_error(ValueError, "errors.http_url")
    separator = "&" if parsed.query else "?"
    url = endpoint + separator + urlencode(parameters)
    check_cancelled(cancelled)
    request = Request(url, headers={"User-Agent": user_agent or "GraphicalWorkbench/0.1", "Accept": "application/json"})
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
                raise ui_error(TimeoutError, "errors.http_timeout")
            chunk = response.read(65536)
            if not chunk:
                break
            count += len(chunk)
            if count > 4 * 1024 * 1024:
                raise ui_error(ValueError, "errors.http_size")
            chunks.append(chunk)
    check_cancelled(cancelled)
    document = json.loads(b"".join(chunks))
    if not isinstance(document, dict) and not (allow_list and isinstance(document, list)):
        raise ui_error(ValueError, "errors.http_object")
    if isinstance(document, dict) and document.get("error"):
        raise ValueError(str(document["reason"])) if document.get("reason") else ui_error(ValueError, "errors.service")
    LOGGER.info("HTTP JSON 请求完成：%d 字节，耗时 %.2f 秒", count, monotonic() - started)
    return document
