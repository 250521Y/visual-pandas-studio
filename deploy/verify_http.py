"""Production smoke test against Nginx. Use --require-https for a public URL."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import io
import json
from pathlib import Path
import re
import time
import uuid
import httpx
import pandas as pd

def verify(origin, *, require_https=False, output=None):
    if require_https and not origin.startswith('https://'):
        raise ValueError('A public deployment must use HTTPS')
    checks=[]
    token=str(uuid.uuid4())
    with httpx.Client(base_url=origin.rstrip('/'),headers={'X-Studio-Session':token},timeout=60,trust_env=False,follow_redirects=True) as client:
        home=client.get('/')
        assert home.status_code==200 and '<div id="root">' in home.text
        assert home.headers.get('x-content-type-options')=='nosniff'
        assert 'no-cache' in home.headers.get('cache-control','')
        for route in ['/datasets','/cleaning','/transform','/statistics','/visualization','/reports']:
            r=client.get(route);assert r.status_code==200 and r.content==home.content
        checks.append('SPA deep-route refresh: all 7 routes')
        assets=re.findall(r'(?:src|href)="(/assets/[^" ]+)"',home.text)
        assert len(assets)>=2
        for asset in assets:
            r=client.get(asset);assert r.status_code==200 and 'max-age=31536000' in r.headers.get('cache-control','')
        checks.append('Built JS/CSS assets and immutable cache')
        health=client.get('/api/health');assert health.json()['engine']=='pandas'
        assert client.get('/api/nonexistent').status_code==404
        checks.append('API prefix, health and API 404')
        file={'file':('production-check.csv',b'team,value\nA,1\nA,\nB,3\nB,5\n','text/csv')}
        r=client.post('/api/upload',files=file);assert r.status_code==200,r.text
        d=r.json();ident=d['id']
        try:
            assert d['overview']['missing']==1
            op={'operation':'missing','params':{'columns':['value'],'method':'median'},'revision':d['revision']}
            pre=client.post(f'/api/datasets/{ident}/preview',json=op);assert pre.status_code==200,pre.text
            assert pre.json()['diff']['modifiedCells']==1
            assert client.get(f'/api/datasets/{ident}').json()['overview']['missing']==1
            applied=client.post(f'/api/datasets/{ident}/operations',json=op).json();assert applied['overview']['missing']==0
            undone=client.post(f'/api/datasets/{ident}/history/undo',json={'revision':applied['revision']}).json();assert undone['overview']['missing']==1
            redone=client.post(f'/api/datasets/{ident}/history/redo',json={'revision':undone['revision']}).json();assert redone['overview']['missing']==0
            csv=client.get(f'/api/datasets/{ident}/export/csv');assert pd.read_csv(io.BytesIO(csv.content)).value.tolist()==[1,3,3,5]
            plotted=client.post(f'/api/datasets/{ident}/analysis',json={'kind':'chart','revision':redone['revision'],'spec':{'type':'bar','x':'team','y':'value','agg':'sum'}}).json()
            assert sum(v['value'] for v in plotted['series'][0]['data'])==12
            assert client.get(f'/api/datasets/{ident}',headers={'X-Studio-Session':str(uuid.uuid4())}).status_code==404
            checks.append('CSV, real cleaning, preview, undo/redo, chart, export and session isolation')
        finally:
            assert client.delete(f'/api/datasets/{ident}').status_code==200
        stream=io.BytesIO()
        with pd.ExcelWriter(stream,engine='openpyxl') as writer:
            pd.DataFrame({'name':['中文','English'],'value':[1,2]}).to_excel(writer,sheet_name='Orders',index=False)
            pd.DataFrame({'key':['East'],'value':[3]}).to_excel(writer,sheet_name='Lookup',index=False)
        excel={'file':('worksheets.xlsx',stream.getvalue())}
        assert client.post('/api/upload/sheets',files=excel).json()['sheets']==['Orders','Lookup']
        d=client.post('/api/upload',files=excel,data={'sheet':'Lookup'}).json();assert d['overview']['rows']==1
        assert client.delete('/api/datasets/'+d['id']).status_code==200
        checks.append('Multi-sheet XLSX selection')
        fixture=Path(__file__).resolve().parents[1]/'backend/tests/fixtures/legacy.xls'
        if fixture.exists():
            files={'file':('legacy.xls',fixture.read_bytes())}
            assert client.post('/api/upload/sheets',files=files).json()['sheets']==['Sheet1','Sheet2','Sheet3']
            d=client.post('/api/upload',files=files,data={'sheet':'Sheet1'}).json();assert d['overview']['rows']==4
            assert client.delete('/api/datasets/'+d['id']).status_code==200
            checks.append('Legacy XLS worksheets and import')
        time.sleep(1)
        over=client.post('/api/upload',files={'file':('oversized.csv',b'x\n'+b'1'*(22*1024**2))})
        assert over.status_code==413,(over.status_code,over.text[:200])
        checks.append('Nginx upload limit: 22 MiB rejected with 413')
        def burst(_):return client.get('/api/health').status_code
        with ThreadPoolExecutor(max_workers=12) as pool: statuses=list(pool.map(burst,range(65)))
        assert 429 in statuses and all(s in (200,429) for s in statuses),statuses
        checks.append('Nginx rate limit: explicit 429, no 5xx')
        time.sleep(2)
        assert client.get('/api/health').status_code==200
    result={'origin':origin,'passed':True,'tlsCertificateVerified':require_https,'checks':checks}
    if output:
        target=Path(output)
        target.parent.mkdir(parents=True,exist_ok=True)
        target.write_text(json.dumps(result,indent=2),encoding='utf-8')
    return result

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('origin');parser.add_argument('--require-https',action='store_true');parser.add_argument('--output',type=Path)
    args=parser.parse_args();print(json.dumps(verify(args.origin,require_https=args.require_https,output=args.output),indent=2))
