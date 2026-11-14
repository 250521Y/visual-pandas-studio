import type {ChartData} from './types';
export type SelectionMode='highlight'|'temporary'|'apply';
export function filteredSelection(selection:number[]|null,mode:SelectionMode){return mode==='temporary'?selection:null}
export function uniqueSelection(ids:number[]){return [...new Set(ids)].slice(0,5000)}
export function histogramRange(data:ChartData,indexes:number[]){
 const edges=data.groups?.[0]?.edges;if(!edges||!indexes.length)return null;
 const first=Math.max(0,Math.min(...indexes)),last=Math.min(edges.length-2,Math.max(...indexes));
 if(first>last)return null;return {lower:edges[first],upper:edges[last+1],includeUpper:last===edges.length-2};
}
export function highlightOption(option:any,selection:number[]|null){
 if(selection===null)return option;const chosen=new Set(selection);
 return {...option,series:(option.series||[]).map((series:any)=>({...series,data:(series.data||[]).map((item:any)=>{if(!item||Array.isArray(item)||typeof item!=='object')return item;const ids=item.id!==undefined?[item.id]:item.ids;if(!ids)return item;const active=ids.some((id:number)=>chosen.has(id));return {...item,itemStyle:{...item.itemStyle,opacity:active?1:.18,borderColor:active?'#D999AC':undefined,borderWidth:active?2:0}}})}))};
}
