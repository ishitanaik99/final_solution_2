import asyncio, json, sys, time
sys.path.insert(0, '.')
from app.core.llm import NoLLM
from app.core.runtime import Session
from app.server.snapshot import build_snapshot
from app.sim.constants import HORIZON

async def main(seed, demo):
    s = Session(NoLLM(), seed, {"ondemand": True, "slotting": True, "etaDrift": True})
    t0 = time.time()
    await s.reset(480 if demo else 840, demo)
    while s.smart.t < HORIZON - 5:
        await s.tick()
    snap = build_snapshot(s)
    out = {"ms": round((time.time()-t0)*1000), "stats": snap["stats"], "staticStats": snap["staticStats"], "bus": snap["busCounts"],
           "logs": [[l["t"], l["agent"], l["text"]] for l in s.logs], "agents": {k: {x: v[x] for x in ("decisions","rules","actions","blocked")} for k, v in snap["agents"].items()},
           "skus": [[x["id"], x["shelf"], x["record"], x["trust"], x["status"]] for x in snap["skus"]]}
    print(json.dumps(out, ensure_ascii=False))
asyncio.run(main(int(sys.argv[1]), sys.argv[2] == '1'))
