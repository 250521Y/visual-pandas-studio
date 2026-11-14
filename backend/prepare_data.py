"""Regenerate demo assets; the application itself never downloads datasets."""
from pathlib import Path
import urllib.request
import numpy as np
import pandas as pd
from sklearn.datasets import load_iris

root=Path(__file__).parent/'data'
root.mkdir(exist_ok=True)
iris=load_iris(as_frame=True)
frame=iris.data.rename(columns={'sepal length (cm)':'sepal_length','sepal width (cm)':'sepal_width','petal length (cm)':'petal_length','petal width (cm)':'petal_width'})
frame['species']=[iris.target_names[i] for i in iris.target]
frame.to_csv(root/'iris.csv',index=False)
rng=np.random.default_rng(42)
n=720
sales=pd.DataFrame({'order_id':[f'SO-{i+1001}' for i in range(n)],'date':pd.date_range('2025-01-01',periods=n,freq='12h'),'region':rng.choice(['East','West','North','South'],n),'category':rng.choice(['Technology','Furniture','Office'],n),'channel':rng.choice(['Online','Retail'],n),'quantity':rng.integers(1,12,n),'unit_price':rng.uniform(20,400,n).round(2),'discount':rng.choice([0,.05,.1,.15],n),'rating':rng.integers(1,6,n).astype(float)})
sales['revenue']=(sales.quantity*sales.unit_price*(1-sales.discount)).round(2)
sales['profit']=(sales.revenue*rng.uniform(.08,.35,n)).round(2)
sales.loc[rng.choice(n,36,replace=False),'rating']=np.nan
sales.loc[rng.choice(n,15,replace=False),'region']=None
sales.loc[rng.choice(n,20,replace=False),'profit']=np.nan
sales.loc[5,'revenue']=22000
sales=pd.concat([sales,sales.iloc[[12,45,78,100,250,350]]],ignore_index=True)
sales.to_csv(root/'sales.csv',index=False)
if not (root/'titanic.csv').exists():
    urllib.request.urlretrieve('https://raw.githubusercontent.com/mwaskom/seaborn-data/master/titanic.csv',root/'titanic.csv')
print({f.stem:len(pd.read_csv(f)) for f in root.glob('*.csv')})
