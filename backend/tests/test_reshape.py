import pandas as pd
import numpy as np
import pytest
from app.engine import apply_operation,DataError,pack,unpack

def run(df,op,**p):return apply_operation(df,op,p)[0]

def test_melt_stack_pivot_and_unstack_preserve_relationships():
    df=pd.DataFrame({'id':['A','B'],'v1':[1.,2.],'v2':[3.,4.]})
    melt=run(df,'melt',ids=['id'],values=['v1','v2'],variableName='variable',valueName='measure')
    pd.testing.assert_frame_equal(melt,df.melt(id_vars=['id'],value_vars=['v1','v2'],var_name='variable',value_name='measure'))
    stack=run(df,'stack',ids=['id'],values=['v1','v2'],variableName='variable',valueName='measure')
    assert stack.groupby('id').measure.sum().tolist()==[4.,6.]
    assert stack.attrs['visual']['hierarchy']['A']=={'v1':{},'v2':{}}
    for op,ids in [('pivot_strict',['id']),('unstack',['id','variable'])]:
        out=run(melt,op,ids=ids,levels=['variable'],values=['measure'])
        assert out.columns.tolist()==['id','measure | v1','measure | v2']
        assert out.iloc[1].tolist()==['B',2.,4.]
        pd.testing.assert_frame_equal(out,unpack(pack(out)))
    with pytest.raises(DataError,match='duplicate_index'):run(pd.concat([melt,melt]),'pivot_strict',ids=['id'],levels=['variable'],values=['measure'])

def test_explode_json_empty_null_delimited_and_bounds():
    df=pd.DataFrame({'items':['[1,2]','[]',None,'[3]'],'id':['a','b','c','d']})
    out=run(df,'explode',field='items',mode='json',sourceName='source_row')
    assert len(out)==5 and out.source_row.tolist()==[0,0,1,2,3]
    assert out['items'].iloc[:2].tolist()==[1,2]
    assert run(pd.DataFrame({'x':['a|b','c']}),'explode',field='x',mode='delimiter',delimiter='|').x.tolist()==['a','b','c']
    with pytest.raises(DataError,match='list_required'):run(pd.DataFrame({'x':["__import__('os')"]}),'explode',field='x')

@pytest.mark.parametrize('drop',[False,True])
@pytest.mark.parametrize('missing',[False,True])
def test_encoding_matches_pandas(drop,missing):
    df=pd.DataFrame({'c':['A','B',None],'v':[1,2,3]})
    out=run(df,'dummies',columns=['c'],dropFirst=drop,dummyNa=missing,retain=True)
    expected=pd.concat([df,pd.get_dummies(df[['c']].astype('string'),columns=['c'],drop_first=drop,dummy_na=missing,dtype=int)],axis=1)
    pd.testing.assert_frame_equal(out,expected)

@pytest.mark.parametrize('method',['mean','min','max','zscore','rank'])
def test_group_transform_alignment(method):
    df=pd.DataFrame({'g':['B','A','B','A','C'],'v':[2.,3.,4.,7.,5.]},index=[8,2,6,1,9])
    out=run(df,'group_transform',groups=['g'],field='v',name='new',method=method)
    group=df.groupby('g').v
    expected=(df.v-group.transform('mean'))/group.transform('std').replace(0,np.nan) if method=='zscore' else group.rank() if method=='rank' else group.transform(method)
    pd.testing.assert_series_equal(out.new,expected,check_names=False)
    assert out.index.tolist()==df.index.tolist()

@pytest.mark.parametrize('method',['rank','diff','shift','pct_change'])
def test_ordered_calculations(method):
    df=pd.DataFrame({'order':[3,1,2],'v':[4.,1.,2.]},index=[12,15,3])
    out=run(df,'window_calc',field='v',name='new',method=method,sort='order',periods=1)
    ordered=df.sort_values('order').v
    expected=ordered.rank() if method=='rank' else ordered.pct_change(fill_method=None) if method=='pct_change' else getattr(ordered,method)(periods=1)
    pd.testing.assert_series_equal(out.new,expected,check_names=False)
