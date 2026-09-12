import time
from fastapi import FastAPI, Request
from fastapi.responses import PlainTextResponse
app = FastAPI()


@app.get("/ping")
def ping():                    # sync def -> threadpool, like /meta and /low-res
    return PlainTextResponse("ok")


@app.get("/slow")
def slow(s: float = 0.2):      # threadpool sleep: overlaps, does not block the loop
    time.sleep(s)
    return PlainTextResponse("ok")


@app.get("/block")
async def block(s: float = 1.0):   # async def + time.sleep: fully blocks the event loop
    time.sleep(s)
    return PlainTextResponse("ok")


@app.get("/cpu")
def cpu(s: float = 1.0):       # sync def CPU burn in threadpool: GIL contention, like a geo build
    t = time.perf_counter()
    x = 0
    while time.perf_counter() - t < s:
        x += sum(i * i for i in range(2000))
    return PlainTextResponse("ok")


@app.post("/echo")
async def echo(req: Request):
    return PlainTextResponse(str(len(await req.body())))
