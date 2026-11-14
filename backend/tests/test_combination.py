import pandas as pd
import numpy as np
import pytest
from app.engine import apply_operation,DataError
def run(df,other,op,**p):return apply_operation(df,op,p,other)[0]

def test_merge_key_names_do_not_collide_with_estimation_columns():
    a=pd.DataFrame({'l':['A','A','B']});b=pd.DataFrame({'r':['A','A','C']})
    out=run(a,b,'join',left='l',right='r',how='outer')
    assert len(out)==6 and out.attrs['visual']['quality']['rowsAfterJoin']==6

def test_asof_reports_invalid_and_duplicate_times_separately():
    a=pd.DataFrame({'date':['2025-01-01','invalid']});b=pd.DataFrame({'date':['2025-01-01','2025-01-01'],'v':[1,2]})
    out=run(a,b,'merge_asof',left='date',right='date',duplicates='last',invalid='drop')
    assert out.attrs['visual']['quality']['invalidDates']==1 and out.attrs['visual']['quality']['duplicateTimes']==1
def test_compare_alignment_added_deleted_modified_and_missing_equality():
    a=pd.DataFrame({'key':['A','B','C'],'v':[1.,2.,np.nan]})
    b=pd.DataFrame({'id':['C','A','D'],'v':[np.nan,9.,4.]})
    out=run(a,b,'compare',left='key',right='id')
    assert out.attrs['visual']['quality']=={'addedRows':1,'removedRows':1,'modifiedRecords':1,'modifiedValues':1}
    assert out.attrs['visual']['added']['rows']==[{'key':'D','v':4.}]
    assert out.attrs['visual']['changed']['rows']==[{'key':'A','v | before':1.,'v | after':9.}]
    pd.testing.assert_frame_equal(out,a)
@pytest.mark.parametrize('overwrite',[False,True])
def test_update_preserves_rows_and_alignment(overwrite):
    a=pd.DataFrame({'key':['A','B','C'],'v':[1.,np.nan,3.]},index=[9,6,2])
    b=pd.DataFrame({'key':['B','A','D'],'v':[2.,9.,4.]})
    out=run(a,b,'update',left='key',right='key',overwrite=overwrite)
    expected=a.set_index('key');expected.update(b.set_index('key'),overwrite=overwrite);expected=expected.reset_index();expected.index=a.index
    pd.testing.assert_frame_equal(out,expected)
def test_combine_first_and_duplicate_keys():
    a=pd.DataFrame({'key':['A','B'],'v':[1.,np.nan]});b=pd.DataFrame({'key':['B','C'],'v':[2.,3.]})
    out=run(a,b,'combine_first',left='key',right='key')
    pd.testing.assert_frame_equal(out,a.set_index('key').combine_first(b.set_index('key')).reset_index())
    with pytest.raises(DataError,match='unique_key_required'):run(pd.concat([a,a]),b,'update',left='key',right='key')
@pytest.mark.parametrize('direction',['backward','forward','nearest'])
def test_asof_sorted_time_tolerance(direction):
    a=pd.DataFrame({'date':['2025-01-03','2025-01-01'],'v':[3.,1.]})
    b=pd.DataFrame({'time':['2025-01-01T12:00:00Z','2025-01-02T12:00:00Z'],'extra':[10,20]})
    out=run(a,b,'merge_asof',left='date',right='time',direction=direction,tolerance='1D')
    aa=a.assign(date=pd.to_datetime(a.date,utc=True)).sort_values('date');bb=b.assign(time=pd.to_datetime(b.time,utc=True),matched_time=pd.to_datetime(b.time,utc=True)).sort_values('time')
    expected=pd.merge_asof(aa,bb,left_on='date',right_on='time',direction=direction,tolerance=pd.Timedelta('1D'),suffixes=('','_right'))
    pd.testing.assert_frame_equal(out,expected)
    assert out.attrs['visual']['quality']['rowsAfterJoin']==2
def test_join_quality_many_to_many_and_unmatched():
    a=pd.DataFrame({'key':['A','A','B']});b=pd.DataFrame({'key':['A','A','A','C']})
    out=run(a,b,'join',left='key',right='key',how='outer')
    assert len(out)==8
    q=out.attrs['visual']['quality']
    assert q['matchedLeftRows']==2 and q['matchedRightRows']==3 and q['unmatchedLeftRows']==1 and q['unmatchedRightRows']==1
    assert q['duplicateLeftKeys']==2 and q['duplicateRightKeys']==3 and q['expansionRatio']==2.667
def test_asof_duplicate_tolerance_errors_are_atomic():
    a=pd.DataFrame({'date':['2025-01-01'],'v':[1.]});b=pd.DataFrame({'date':['2025-01-01']*2,'v':[2.,3.]})
    with pytest.raises(DataError,match='duplicate_time'):run(a,b,'merge_asof',left='date',right='date')
    with pytest.raises(DataError,match='invalid_tolerance'):run(a,b,'merge_asof',left='date',right='date',duplicates='last',tolerance='-2h')
    assert a.v.tolist()==[1.]
