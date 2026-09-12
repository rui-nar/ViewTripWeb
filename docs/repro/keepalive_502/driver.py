import argparse
import collections
import http.client
import threading
import time

CADDY = ("127.0.0.1", 8080)
UVLOG = "/tmp/uvicorn.log"


def conns_made():
    try:
        with open(UVLOG) as f:
            return sum(1 for l in f if "HTTP connection made" in l)
    except FileNotFoundError:
        return 0


class Client:
    def __init__(self):
        self.c = http.client.HTTPConnection(*CADDY, timeout=60)

    def _reset(self):
        self.c.close()
        self.c = http.client.HTTPConnection(*CADDY, timeout=60)

    def get(self, path):
        try:
            self.c.request("GET", path)
            r = self.c.getresponse()
            r.read()
            return r.status
        except Exception as e:
            self._reset()
            return f"EXC:{type(e).__name__}"

    def post(self, path, body):
        try:
            self.c.request("POST", path, body=body,
                           headers={"Content-Type": "application/octet-stream"})
            r = self.c.getresponse()
            r.read()
            return r.status
        except Exception as e:
            self._reset()
            return f"EXC:{type(e).__name__}"


def summarize(name, results):
    c = collections.Counter(r for _, r in results)
    bad = [(d, r) for d, r in results if not str(r).startswith("200")]
    print(f"[{name}] trials={len(results)} outcomes={dict(c)}")
    if bad:
        print(f"[{name}] non-200 at: {bad[:40]}")
    return c


def s_idle(T, spread, steps, reps, post=False):
    """One pooled upstream conn idle ~T s, then reused right around uvicorn's timer."""
    cl = Client()
    results = []
    deltas = [T - spread + 2 * spread * i / (steps - 1) for i in range(steps)] * reps
    for d in deltas:
        cl.get("/ping")
        n0 = conns_made()
        time.sleep(d)
        r = cl.post("/echo", b"x" * 100) if post else cl.get("/ping")
        n1 = conns_made()
        results.append((round(d, 4), f"{r}+dial" if n1 > n0 else r))
    return summarize("idle-post" if post else "idle", results)


def s_starved(T, spread, steps, reps, blocker, probe="get"):
    """Two pooled conns; block the loop across one conn's timer expiry, reuse that conn during the block."""
    a, b = Client(), Client()
    results = []
    xs = [-spread + 2 * spread * i / (steps - 1) for i in range(steps)] * reps
    for x in xs:
        ta = threading.Thread(target=a.get, args=("/slow?s=0.3",))
        tb = threading.Thread(target=b.get, args=("/slow?s=0.3",))
        ta.start()
        time.sleep(0.05)
        tb.start()
        ta.join()
        tb.join()
        t0 = time.monotonic()
        n0 = conns_made()
        time.sleep(max(0, T + x - (time.monotonic() - t0)))
        tblk = threading.Thread(target=a.get, args=(f"/{blocker}?s=1.5",))
        tblk.start()
        time.sleep(0.08)  # now inside the block; the other pooled conn's timer is due / overdue
        r = b.post("/echo", b"x" * 100) if probe == "post" else b.get("/ping")
        tblk.join()
        n1 = conns_made()
        results.append((round(x, 3), f"{r}+dial{n1 - n0}" if n1 > n0 else r))
    return summarize(f"starved/{blocker}/{probe}", results)


def s_burst(T, spread, steps, reps, n):
    """n parallel GETs (a client opening a project), all pooled, all reused ~T later at once."""
    cls = [Client() for _ in range(n)]
    results = []
    deltas = [T - spread + 2 * spread * i / (steps - 1) for i in range(steps)] * reps
    for d in deltas:
        ths = [threading.Thread(target=c.get, args=("/slow?s=0.3",)) for c in cls]
        [t.start() for t in ths]
        [t.join() for t in ths]
        time.sleep(d)
        out = [None] * n

        def go(i):
            out[i] = cls[i].get("/ping")
        ths = [threading.Thread(target=go, args=(i,)) for i in range(n)]
        [t.start() for t in ths]
        [t.join() for t in ths]
        results.extend((round(d, 4), r) for r in out)
    return summarize(f"burst{n}", results)


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--T", type=float, default=5.0, help="uvicorn keep-alive timeout being probed")
    p.add_argument("--spread", type=float, default=0.06)
    p.add_argument("--steps", type=int, default=25)
    p.add_argument("--reps", type=int, default=2)
    p.add_argument("--probe", default="get")
    p.add_argument("--scenarios", default="idle,idle-post,starved-block,starved-cpu,burst")
    a = p.parse_args()
    for s in a.scenarios.split(","):
        if s == "idle":
            s_idle(a.T, a.spread, a.steps, a.reps)
        elif s == "idle-post":
            s_idle(a.T, a.spread, a.steps, a.reps, post=True)
        elif s == "starved-block":
            s_starved(a.T, a.spread, a.steps, a.reps, "block", a.probe)
        elif s == "starved-cpu":
            s_starved(a.T, a.spread, a.steps, a.reps, "cpu", a.probe)
        elif s == "burst":
            s_burst(a.T, a.spread, a.steps, a.reps, 6)
    print("total upstream connections made:", conns_made())
