import json, subprocess, sys
def run(cmd): return json.loads(subprocess.check_output(cmd, text=True))
bad = 0
for seed, demo in [(7,'0'),(7,'1'),(1001,'0'),(1002,'1'),(42,'0')]:
    js = run(['node','tools/js_shift.js',str(seed),demo]); py = run([sys.executable,'tools/py_shift.py',str(seed),demo])
    diffs = []
    for k in ('stats','staticStats','bus','agents','skus'):
        if json.dumps(js[k], sort_keys=True) != json.dumps(py[k], sort_keys=True):
            if isinstance(js[k], dict):
                for kk in set(js[k])|set(py[k]):
                    a, b = js[k].get(kk), py[k].get(kk)
                    if a != b and not (isinstance(a,(int,float)) and isinstance(b,(int,float)) and abs(a-b) < 1e-6): diffs.append((k,kk,a,b))
            else: diffs.append((k, js[k][:3], py[k][:3]))
    if len(js['logs']) != len(py['logs']): diffs.append(('nlogs', len(js['logs']), len(py['logs'])))
    else:
        for a, b in zip(js['logs'], py['logs']):
            if a != b: diffs.append(('log', a, b)); break
    bad += bool(diffs)
    print('seed', seed, 'demo', demo, 'js', js['ms'], 'ms  py', py['ms'], 'ms ', 'MATCH' if not diffs else 'DIFF')
    for d in diffs[:6]: print('   ', d)
sys.exit(1 if bad else 0)
