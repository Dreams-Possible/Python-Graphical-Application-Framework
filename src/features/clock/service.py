"""SNTP 客户端，只返回采样结果，不修改系统时间。"""

from dataclasses import dataclass
import socket
import logging
import struct
from threading import Event
import time

from src.shared.tasks import check_cancelled

NTP_EPOCH = 2208988800
LOGGER = logging.getLogger("workbench.clock.network")


@dataclass(frozen=True)
class TimeSample:
    utc_seconds: float
    monotonic_seconds: float
    offset_seconds: float
    round_trip_seconds: float


def _timestamp(raw: bytes, reference: float) -> float:
    seconds, fraction = struct.unpack("!II", raw)
    # NTP 的 32 位秒字段在 2036 年回绕，按本机当前年代选择最近一代。
    era = round((reference + NTP_EPOCH - seconds) / (2 ** 32))
    return seconds + era * 2 ** 32 - NTP_EPOCH + fraction / 2 ** 32


def query_time(settings: dict, cancelled: Event) -> TimeSample:
    host = settings["server"].strip()
    if "://" in host or "/" in host:
        raise ValueError("NTP 服务器请填写主机名，不包含 URL 协议或路径")
    check_cancelled(cancelled)
    addresses = socket.getaddrinfo(host, settings["port"], type=socket.SOCK_DGRAM)
    LOGGER.debug("NTP 地址解析完成，候选数 %d", len(addresses))
    if not addresses:
        raise OSError("无法解析时间服务器")
    family, kind, protocol, _, address = addresses[0]
    with socket.socket(family, kind, protocol) as connection:
        connection.settimeout(settings["timeout_seconds"])
        connection.connect(address)
        sent = time.time()
        elapsed_start = time.monotonic()
        request = bytearray(48)
        request[0] = 0x23  # NTP v4，客户端模式。
        ntp = sent + NTP_EPOCH
        request[40:48] = struct.pack("!II", int(ntp) % 2 ** 32, int((ntp % 1) * 2 ** 32))
        connection.send(request)
        response = connection.recv(512)
        LOGGER.debug("NTP 响应已接收：%d 字节", len(response))
        elapsed_end = time.monotonic()
    check_cancelled(cancelled)
    received = sent + elapsed_end - elapsed_start
    if len(response) < 48 or response[0] & 7 != 4 or response[0] >> 6 == 3:
        raise ValueError("服务器返回了无效或未同步的 NTP 报文")
    if not 1 <= response[1] <= 15 or response[24:32] != request[40:48]:
        raise ValueError("时间服务器拒绝请求，或返回的请求标识不匹配")
    if response[32:40] == b"\0" * 8 or response[40:48] == b"\0" * 8:
        raise ValueError("服务器没有提供有效时间戳")
    server_received = _timestamp(response[32:40], sent)
    server_sent = _timestamp(response[40:48], received)
    offset = ((server_received - sent) + (server_sent - received)) / 2
    return TimeSample(received + offset, elapsed_end, offset, elapsed_end - elapsed_start)
