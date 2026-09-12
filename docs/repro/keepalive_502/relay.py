# Stand-in for docker-proxy (the userland proxy Docker uses for loopback-published
# ports such as 127.0.0.1:8000:8000): a byte relay 127.0.0.1:8000 -> 127.0.0.1:8001
# that closes one side when the other side closes.
import asyncio


async def pump(r, w):
    try:
        while True:
            d = await r.read(65536)
            if not d:
                break
            w.write(d)
            await w.drain()
    except Exception:
        pass
    finally:
        try:
            w.close()
        except Exception:
            pass


async def handle(cr, cw):
    try:
        ur, uw = await asyncio.open_connection("127.0.0.1", 8001)
    except Exception:
        cw.close()
        return
    await asyncio.gather(pump(cr, uw), pump(ur, cw))


async def main():
    s = await asyncio.start_server(handle, "127.0.0.1", 8000)
    async with s:
        await s.serve_forever()

asyncio.run(main())
