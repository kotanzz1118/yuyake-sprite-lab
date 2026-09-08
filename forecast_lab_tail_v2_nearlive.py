from pathlib import Path
import pandas as pd, numpy as np, json, time, hashlib, gzip, base64, io
import yfinance as yf
OUT=Path('near_live'); OUT.mkdir(exist_ok=True)
EPS=1e-12
# Technical amendment before outcome acquisition: use the already-frozen pre-extension union code list.
# Source SHA256 of decompressed CSV: 30baf3a515967f49963a6162c2f766e99fc1a4ea9091c7ac5d1bfbb16dfca502
enc=Path('forecast_lab_frozen_union_codes_b64.txt').read_text().strip()
raw=gzip.decompress(base64.b64decode(enc))
assert hashlib.sha256(raw).hexdigest()=='30baf3a515967f49963a6162c2f766e99fc1a4ea9091c7ac5d1bfbb16dfca502'
cu=pd.read_csv(io.BytesIO(raw),dtype={'security_code':str})
codes=sorted(cu.security_code.astype(str).str.replace(r'\.0$','',regex=True).str.zfill(4).unique())
print('Frozen pre-extension union codes',len(codes))
frames=[]; attempts=[]
for start in range(0,len(codes),80):
    batch=codes[start:start+80]; tick=[c+'.T' for c in batch]
    try:
        x=yf.download(tick,start='2026-05-01',end='2026-09-09',auto_adjust=False,actions=True,group_by='ticker',threads=True,progress=False,timeout=30)
        for c,t in zip(batch,tick):
            try:
                z=x[t].copy() if isinstance(x.columns,pd.MultiIndex) else x.copy()
                z=z.reset_index(); z['security_code']=c; frames.append(z); attempts.append((c,'OK',len(z)))
            except Exception: attempts.append((c,'PARSE_FAIL',0))
    except Exception: attempts.extend((c,'BATCH_FAIL',0) for c in batch)
    time.sleep(.15)
pd.DataFrame(attempts,columns=['security_code','status','rows']).to_csv(OUT/'acquisition_attempts.csv',index=False)
if not frames: raise RuntimeError('no data')
d=pd.concat(frames,ignore_index=True); d['Date']=pd.to_datetime(d['Date']).dt.tz_localize(None)
for c in ['Open','High','Low','Close','Volume','Stock Splits']:
    if c not in d: d[c]=0.0 if c=='Stock Splits' else np.nan
d=d.sort_values(['security_code','Date']).reset_index(drop=True)
def adj(g):
    sp=pd.to_numeric(g['Stock Splits'],errors='coerce').fillna(0).replace(0,1).astype(float)
    fut=sp.iloc[::-1].cumprod().iloc[::-1]/sp
    for c in ['Open','High','Low','Close']: g[c+'A']=pd.to_numeric(g[c],errors='coerce')/fut
    g['VolumeA']=pd.to_numeric(g.Volume,errors='coerce')*fut
    return g
d=d.groupby('security_code',group_keys=False).apply(adj).reset_index(drop=True)
cal=sorted(d.loc[d.CloseA.notna(),'Date'].unique()); cmap={pd.Timestamp(x):i for i,x in enumerate(cal)}; d['ci']=d.Date.map(cmap)
g=d.groupby('security_code',sort=False,group_keys=False)
prevci=g.ci.shift(1); d['r1']=np.where((d.ci-prevci)==1,d.CloseA/g.CloseA.shift(1)-1,np.nan)
d['mom20']=np.where((d.ci-g.ci.shift(20))==20,d.CloseA/g.CloseA.shift(20)-1,np.nan)
d['vmed_prev20']=g.VolumeA.transform(lambda s:s.shift(1).rolling(20,min_periods=10).median()); d['vratio']=d.VolumeA/d.vmed_prev20
d['vol20']=g.r1.transform(lambda s:s.rolling(20,min_periods=10).std()); turn=d.CloseA*d.VolumeA; d['turn20']=turn.groupby(d.security_code).transform(lambda s:s.rolling(20,min_periods=10).median())
elig=d[['mom20','vratio','vol20','turn20']].replace([np.inf,-np.inf],np.nan).notna().all(axis=1)
for v,o in [('mom20','mom_pct'),('vratio','vratio_pct'),('vol20','vol_pct'),('turn20','liq_pct')]:
    d[o]=np.nan; d.loc[elig,o]=d.loc[elig].groupby('Date')[v].rank(pct=True)
d['vol_q']=np.ceil(d.vol_pct*5).clip(1,5); d['liq_q']=np.ceil(d.liq_pct*5).clip(1,5)
d['EVENT']=elig&(d.mom_pct>.80)&(d.vratio_pct>.80); d['PULL']=d.EVENT&d.r1.between(-.05,0); d['TAIL_V2']=d.PULL&(d.mom_pct>=.98)
entry=g.OpenA.shift(-1).to_numpy(float); close5=g.CloseA.shift(-5).to_numpy(float); maxc=np.full(len(d),-np.inf); minl=np.full(len(d),np.inf); valid=np.ones(len(d),bool)
for k in range(1,6):
    valid &= g.ci.shift(-k).to_numpy(float)==d.ci.to_numpy()+k
    maxc=np.maximum(maxc,g.CloseA.shift(-k).to_numpy(float)); minl=np.minimum(minl,g.LowA.shift(-k).to_numpy(float))
valid &= np.isfinite(entry)&np.isfinite(close5)&np.isfinite(maxc)
d['ret5']=np.where(valid,close5/entry-1,np.nan); d['hit10']=np.where(valid,maxc/entry>=1.10-EPS,np.nan); d['tail20']=np.where(valid,close5/entry-1>=.20,np.nan); d['mae5']=np.where(valid,minl/entry-1,np.nan)
base=elig&valid&(d.Date>=pd.Timestamp('2026-06-16'))
keys=['Date','vol_q','liq_q']; metrics=['ret5','hit10','tail20','mae5']; rows=[]
for name,mask,parent in [('PULLBACK_V1',d.PULL,d.EVENT&~d.PULL),('TAIL_SPIKE_V2',d.TAIL_V2,d.PULL&~d.TAIL_V2)]:
    sig=mask&base; broad=(~mask)&base; par=parent&base
    bm=d.loc[broad,keys+metrics].groupby(keys,observed=True).mean().add_prefix('b_').reset_index(); pm=d.loc[par,keys+metrics].groupby(keys,observed=True).mean().add_prefix('p_').reset_index()
    z=d.loc[sig,keys+['security_code']+metrics].merge(bm,on=keys,how='left').merge(pm,on=keys,how='left').dropna(subset=['b_ret5','p_ret5'])
    for met in metrics:
        sv=z[met].mean(); bv=z['b_'+met].mean(); pv=z['p_'+met].mean(); rows.append({'candidate':name,'metric':met,'n':len(z),'signal':sv,'broad_matched':bv,'parent_matched':pv,'excess_broad':sv-bv,'excess_parent':sv-pv,'lift_broad':sv/bv if bv else np.nan,'lift_parent':sv/pv if pv else np.nan})
    z.to_csv(OUT/(name.lower()+'_rows.csv'),index=False)
res=pd.DataFrame(rows); res.to_csv(OUT/'near_live_metrics.csv',index=False)
coverage=d.groupby('Date').security_code.nunique().rename('price_codes').reset_index(); coverage.to_csv(OUT/'coverage.csv',index=False)
summary={'universe_source':'PRE_EXTENSION_UNION_CODES','universe_codes':len(codes),'universe_sha256':'30baf3a515967f49963a6162c2f766e99fc1a4ea9091c7ac5d1bfbb16dfca502','price_codes':int(d.security_code.nunique()),'price_rows':len(d),'eval_start':'2026-06-16','last_date':str(d.Date.max().date()),'complete_signal_last_date':str(d.loc[valid,'Date'].max().date()),'status':'PROVISIONAL_NEAR_LIVE_OOS_UNION_UNIVERSE'}
(OUT/'summary.json').write_text(json.dumps(summary,indent=2)); print(json.dumps(summary,indent=2)); print(res.to_string(index=False))
