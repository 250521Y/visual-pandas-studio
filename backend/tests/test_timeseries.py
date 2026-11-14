import numpy as np
import pandas as pd
import pytest
from app.engine import apply_operation,DataError,analyze
def run(df,op,**p):return apply_operation(df,op,p)[0]
@pytest.fixture
def frame():return pd.DataFrame({'time':['2025-01-03','2025-01-01','2025-01-02','2025-01-05'],'v':[3.,1.,2.,5.]})
@pytest.mark.parametrize('frequency',['D','W','ME','QE','YE'])
@pytest.mark.parametrize('agg',['sum','mean','count','min','max'])
def test_resample_all_frequencies_and_aggregates(frame,frequency,agg):
    out=run(frame,'resample',time='time',field='v',frequency=frequency,agg=agg)
    s=frame.assign(time=pd.to_datetime(frame.time,utc=True)).set_index('time').v.resample(frequency)
    expected=s.sum(min_count=1) if agg=='sum' else getattr(s,agg)()
    pd.testing.assert_frame_equal(out,expected.rename('v').reset_index())
@pytest.mark.parametrize('method',['mean','std','min','max'])
def test_rolling_sorted_edges(frame,method):
    out=run(frame,'rolling',time='time',field='v',name='new',method=method,window=3,minPeriods=3)
    expected=getattr(pd.Series([1.,2.,3.,5.]).rolling(3,min_periods=3),method)()
    np.testing.assert_allclose(out.new.to_numpy(),expected.to_numpy(),equal_nan=True)
    assert out.attrs['visual']['diagnostics']['irregularIntervals'] is True
def test_ewm_growth_and_regular_grid_are_real(frame):
    out=run(frame,'ewm',time='time',field='v',name='new',alpha=.5,window=2,minPeriods=1)
    np.testing.assert_allclose(out.new,pd.Series([1.,2.,3.,5.]).ewm(alpha=.5,adjust=True).mean())
    out=run(frame,'growth',time='time',field='v',name='new',periods=2)
    np.testing.assert_allclose(out.new,[np.nan,np.nan,2.,1.5],equal_nan=True)
    out=run(frame,'time_gaps',time='time',field='v',frequency='D',fill='linear')
    assert out.v.tolist()==[1.,2.,3.,4.,5.]
    assert out.attrs['visual']['diagnostics']['missingTimePoints']==1
def test_invalid_duplicate_and_timezone_policies(frame):
    df=pd.concat([frame,pd.DataFrame({'time':['2025-01-01','bad'],'v':[5.,7.]})],ignore_index=True)
    with pytest.raises(DataError,match='valid_time_required'):run(df,'resample',time='time',field='v')
    with pytest.raises(DataError,match='duplicate_time'):run(df,'resample',time='time',field='v',invalid='drop')
    out=run(df,'resample',time='time',field='v',invalid='drop',duplicates='mean')
    assert out.v.iloc[0]==3.
    assert out.attrs['visual']['diagnostics']['invalidDates']==1
    assert out.attrs['visual']['diagnostics']['duplicateTimes']==1
    mixed=pd.DataFrame({'time':['2025-01-01T00:00:00+08:00','2025-01-01T00:00:00+00:00'],'v':[1.,2.]})
    out=run(mixed,'rolling',time='time',field='v',name='new',window=1,minPeriods=1,timezone='utc')
    assert str(out.time.dt.tz)=='UTC'
    with pytest.raises(DataError,match='timezone_required'):run(mixed,'resample',time='time',field='v',timezone='naive')
def test_timeline_preserves_sorted_original_ids(frame):
    out=analyze(frame,{'kind':'timeline','spec':{'time':'time','field':'v'}})
    assert out['ids']==[1,2,0,3] and out['values']==[1.,2.,3.,5.]
