"""Time operations make sorting, duplicate and invalid-time policies explicit."""
import numpy as np
import pandas as pd
from .engine import DataError,numeric,check_columns,clean
from .extensions import choice,flag,integer,number,dates,output

OPERATIONS={'resample','rolling','ewm','growth','time_gaps'}
FREQUENCIES={'D','W','ME','QE','YE','h','12h'}

def prepare(df,p):
    time=p.get('time');check_columns(df,[time]);c=p.get('field');numeric(df,c)
    parsed=dates(df[time],p);invalid=parsed.isna();policy=choice(p,'invalid',{'reject','drop'},'reject')
    if invalid.any() and policy=='reject':raise DataError('valid_time_required',{'count':int(invalid.sum())})
    frame=df.loc[~invalid].copy();frame[time]=parsed.loc[~invalid];frame=frame.sort_values(time,kind='stable')
    if frame.empty:raise DataError('insufficient_data')
    duplicate=int(frame[time].duplicated().sum());duplicate_policy=choice(p,'duplicates',{'reject','first','last','mean','sum'},'reject')
    if duplicate:
        if duplicate_policy=='reject':raise DataError('duplicate_time')
        if duplicate_policy in {'first','last'}:frame=frame.drop_duplicates(time,keep=duplicate_policy)
        else:frame=frame.groupby(time,sort=True)[c].agg(duplicate_policy).reset_index()
    return frame,{'invalidDates':int(invalid.sum()),'duplicateTimes':duplicate,'timezoneUsed':str(frame[time].dt.tz or 'naive')}

def diagnostics(frame,time):
    delta=frame[time].drop_duplicates().diff().dropna().dt.total_seconds()
    return {'irregularIntervals':bool(delta.nunique()>1),'medianIntervalSeconds':float(delta.median()) if len(delta) else 0,'minIntervalSeconds':float(delta.min()) if len(delta) else 0,'maxIntervalSeconds':float(delta.max()) if len(delta) else 0}

def apply(df,op,p):
    frame,info=prepare(df,p);c=p['field'];time=p['time'];info.update(diagnostics(frame,time));visual={}
    s=frame.set_index(time)[c]
    if op in {'resample','time_gaps'}:
        freq=choice(p,'frequency',FREQUENCIES,'D');agg=choice(p,'agg',{'sum','mean','count','min','max'},'mean')
        # Guard before allocating a dense grid, including for hourly gap exploration.
        hours=(s.index.max()-s.index.min()).total_seconds()/3600
        units=hours/(1 if freq=='h' else 12 if freq=='12h' else 24 if freq=='D' else 168 if freq=='W' else 672 if freq=='ME' else 2016 if freq=='QE' else 8064)+3
        if units>100000:raise DataError('result_too_large')
        resampler=s.resample(freq);out=resampler.sum(min_count=1) if agg=='sum' else getattr(resampler,agg)()
        counts=resampler.size();info['missingTimePoints']=int((counts==0).sum());info['resultTimePoints']=len(out)
        visual['missingTimes']=[str(v) for v in counts.index[counts==0][:300]]
        if op=='time_gaps':
            visual['original']=clean(out.head(300).tolist())
            method=choice(p,'fill',{'none','linear','ffill','bfill'},'none')
            if method=='linear':out=out.interpolate(method='time',limit_area='inside')
            elif method in {'ffill','bfill'}:out=getattr(out,method)()
        result=out.rename(c).reset_index()
        visual.update(labels=[str(v) for v in out.index[:300]],values=clean(out.head(300).tolist()))
    else:
        result=frame.copy();name=output(df,p);window=integer(p,'window',7,1,1000)
        minimum=integer(p,'minPeriods',window,1,window)
        rolling=s.rolling(window=window,min_periods=minimum,center=flag(p,'center'))
        if op=='rolling':out=getattr(rolling,choice(p,'method',{'mean','std','min','max'},'mean'))()
        elif op=='ewm':out=s.ewm(alpha=number(p,'alpha',.3,.0001,1),adjust=flag(p,'adjust',True),min_periods=integer(p,'ewmMinPeriods',1,1,1000)).mean()
        else:out=s.pct_change(periods=integer(p,'periods',1,1,1000),fill_method=None).replace([np.inf,-np.inf],np.nan)
        result[name]=out.to_numpy()
        visual.update(labels=[str(v) for v in s.index[:300]],original=clean(s.head(300).tolist()),values=clean(out.head(300).tolist()),growth=op=='growth')
        if op=='ewm':visual['rolling']=clean(rolling.mean().head(300).tolist())
    anomalous=s.pct_change(fill_method=None).abs()>number(p,'anomalyThreshold',.5,0,100)
    info['anomalousChanges']=int(anomalous.sum())
    visual['anomalyLabels']=[str(v) for v in s.index[anomalous][:300]]
    visual['diagnostics']=info
    result.attrs['visual']=clean(visual)
    return result,[]

def timeline(df,p):
    time=p.get('time');c=p.get('field');check_columns(df,[time]);numeric(df,c)
    parsed=dates(df[time],p);frame=df.loc[parsed.notna()].copy();frame[time]=parsed[parsed.notna()];frame=frame.sort_values(time,kind='stable').head(5000)
    return {'labels':[str(v) for v in frame[time]],'values':clean(frame[c].tolist()),'ids':frame.index.tolist(),'invalidDates':int(parsed.isna().sum()),'sampled':len(df)>5000}
