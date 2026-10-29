const E=require('./engine.js');
(async()=>{const seed=+process.argv[2], demo=process.argv[3]==='1';
const s=new E.Session(new E.NoLLM(),seed,{ondemand:true,slotting:true,etaDrift:true});const t0=Date.now();
await s.reset(demo?480:840,demo);while(s.smart.t<E.HORIZON-5)await s.tick();const snap=E.buildSnapshot(s);
const ag={};for(const k in snap.agents){const v=snap.agents[k];ag[k]={decisions:v.decisions,rules:v.rules,actions:v.actions,blocked:v.blocked};}
console.log(JSON.stringify({ms:Date.now()-t0,stats:snap.stats,staticStats:snap.staticStats,bus:snap.busCounts,logs:s.logs.map(l=>[l.t,l.agent,l.text]),agents:ag,skus:snap.skus.map(x=>[x.id,x.shelf,x.record,x.trust,x.status])}));})();
