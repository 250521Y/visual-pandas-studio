import {describe,it,expect} from 'vitest';
import {filteredSelection,histogramRange,highlightOption,uniqueSelection} from './selection';
import type {ChartData} from './types';
describe('linked selection semantics',()=>{
 it('filters only temporary views',()=>{expect(filteredSelection([3,7],'temporary')).toEqual([3,7]);expect(filteredSelection([3,7],'highlight')).toBeNull();expect(filteredSelection([3,7],'apply')).toBeNull();expect(filteredSelection([], 'temporary')).toEqual([])});
 it('maps selected histogram bins to exact closed boundaries',()=>{const data={groups:[{edges:[0,2,4,6]}]} as ChartData;expect(histogramRange(data,[0,1])).toEqual({lower:0,upper:4,includeUpper:false});expect(histogramRange(data,[2])).toEqual({lower:4,upper:6,includeUpper:true});expect(histogramRange(data,[])).toBeNull()});
 it('highlights row and aggregate memberships without changing values or mutating input',()=>{const option={series:[{data:[{id:1,value:[2,3]},{id:9,value:[4,5]},{ids:[1,2],value:100},{ids:[8,9],value:200}]}]};const out=highlightOption(option,[1]);expect(out.series[0].data.map((d:any)=>d.itemStyle.opacity)).toEqual([1,.18,1,.18]);expect(out.series[0].data.map((d:any)=>d.value)).toEqual([[2,3],[4,5],100,200]);expect(option.series[0].data[0]).not.toHaveProperty('itemStyle')});
 it('deduplicates and enforces the documented selection cap',()=>{expect(uniqueSelection([3,3,1])).toEqual([3,1]);expect(uniqueSelection(Array.from({length:6000},(_,i)=>i))).toHaveLength(5000)});
});
