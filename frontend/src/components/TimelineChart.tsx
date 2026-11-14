import {useEffect,useMemo,useState} from 'react';
import {useTranslation} from 'react-i18next';
import {api} from '../api';
import {useStudio} from '../store';
import {filteredSelection,highlightOption} from '../selection';
import {Plot} from './Chart';
export function TimelineChart({time,field}:{time:string;field:string}){
 const {dataset,selection,selectionMode,setSelection}=useStudio();const {t,i18n}=useTranslation();const [data,setData]=useState<{labels:string[];values:(number|null)[];ids:number[];sampled:boolean;invalidDates:number}|null>(null),[error,setError]=useState('');const query=filteredSelection(selection,selectionMode);
 useEffect(()=>{if(!dataset||!time||!field)return;let active=true;setError('');api.analyze<typeof data>(dataset.id,{kind:'timeline',spec:{time,field,timezone:'utc'},selection:query}).then(d=>{if(active)setData(d)}).catch(e=>{if(active)setError(e.code)});return()=>{active=false}},[dataset?.id,dataset?.revision,time,field,query]);
 const option=useMemo(()=>highlightOption({color:['#67B8B0'],tooltip:{trigger:'axis',renderMode:'richText'},grid:{left:65,right:30,top:35,bottom:60,containLabel:true},xAxis:{type:'time',name:time,nameLocation:'middle',nameGap:30},yAxis:{type:'value',name:field,splitLine:{lineStyle:{color:'#edf2f1'}}},toolbox:{feature:{brush:{type:['lineX','clear'],title:{lineX:t('brushSelection'),clear:t('clearSelection')}}}},brush:{xAxisIndex:0,brushType:'lineX',brushMode:'single',throttleType:'debounce',throttleDelay:200},dataZoom:[{type:'inside'},{type:'slider',height:12,bottom:8}],series:[{name:field,type:'line',showSymbol:true,symbolSize:5,connectNulls:false,data:data?.labels.map((v,i)=>({value:[v,data.values[i]],id:data.ids[i]}))}]},selectionMode==='temporary'?null:selection),[data,selection,selectionMode,time,field,i18n.language]);
 if(error)return <p role="alert" className="inline-error">{t('error.'+error)}</p>;
 return <section className="card timeline-chart"><div className="card-heading"><h2>{t('timeBrush')}</h2><span className="subtle-badge">{time} × {field}</span></div><Plot option={option} height={280} onBrush={p=>{const range=p.batch?.[0]?.areas?.[0]?.coordRange;if(!range||!dataset)return;api.analyze<{ids:number[]}>(dataset.id,{kind:'select',field:time,temporal:true,lower:Math.min(...range),upper:Math.max(...range),includeUpper:true,selection:query}).then(d=>setSelection(d.ids)).catch(useStudio.getState().fail)}}/>{data?.sampled&&<p className="chart-note">{t('selectionCap')}</p>}{!!data?.invalidDates&&<p className="chart-note">{t('invalidDates')}: {data.invalidDates}</p>}</section>
}
