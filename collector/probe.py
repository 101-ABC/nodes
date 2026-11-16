"""TCP 连通性探测：判断端口是否还活着，顺带测 RTT。只用标准库。"""
import asyncio
import time


async def _one(host: str, port: int, timeout: float, sem: asyncio.Semaphore):
    async with sem:
        t0 = time.perf_counter()
        writer = None
        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(host, port), timeout=timeout
            )
            rtt = int((time.perf_counter() - t0) * 1000)
            return max(1, rtt)
        except (OSError, asyncio.TimeoutError):
            return None
        finally:
            if writer is not None:
                try:
                    writer.close()
                    await writer.wait_closed()
                except Exception:
                    pass


def probe_all(nodes, timeout: float = 2.0, concurrency: int = 512):
    """返回与 nodes 同序的 RTT 列表，连不通为 None。"""

    async def run():
        sem = asyncio.Semaphore(concurrency)
        return await asyncio.gather(
            *[_one(n["server"], n["port"], timeout, sem) for n in nodes]
        )

    if not nodes:
        return []
    return asyncio.run(run())
