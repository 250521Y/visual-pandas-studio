// Checks the single paired resource catalogue, including operation/error terms.
import {describe,it,expect} from 'vitest';
import fs from 'node:fs';
const source=fs.readFileSync(new URL('./i18n.ts',import.meta.url),'utf8');
const keys=new Set([...source.matchAll(/(?:'([^']+)'|([\w]+)):\[\s*'([^']*)'\s*,\s*'([^']*)'\s*\]/g)].map(m=>m[1]||m[2]));
function sources(dir:URL):string[]{return fs.readdirSync(dir,{withFileTypes:true}).flatMap(entry=>entry.isDirectory()?sources(new URL(entry.name+'/',dir)):/\.(tsx?|py)$/.test(entry.name)&&!entry.name.includes('.test.')?[fs.readFileSync(new URL(entry.name,dir),'utf8')]:[])}
describe('resource coverage',()=>{
 it('translates static interface labels and backend error codes',()=>{
  for(const code of sources(new URL('./',import.meta.url)))for(const m of code.matchAll(/\bt\('([^']+)'\)/g))expect(keys.has(m[1]),m[1]).toBe(true);
  for(const code of sources(new URL('../../backend/app/',import.meta.url)))for(const m of code.matchAll(/DataError\(['"]([\w]+)['"]/g))expect(keys.has('error.'+m[1]),m[1]).toBe(true);
 });
 it('translates all newly added operation names, including history labels',()=>{
  for(const op of ['sample','topn','bin','mapping','string','date','cumulative','interpolate','select_rows','melt','pivot_strict','stack','unstack','explode','dummies','group_transform','window_calc','resample','rolling','ewm','growth','time_gaps','compare','update','combine_first','merge_asof'])expect(keys.has(op),op).toBe(true);
 });
});
describe('bilingual resource catalogue',()=>{it('provides paired text for each resource',()=>{const source=fs.readFileSync(new URL('./i18n.ts',import.meta.url),'utf8');const pairs=[...source.matchAll(/(?:'([^']+)'|([\w]+)):\[\s*'([^']*)'\s*,\s*'([^']*)'\s*\]/g)];expect(pairs.length).toBeGreaterThan(250);for(const pair of pairs){expect(pair[3].length).toBeGreaterThan(0);expect(pair[4].length).toBeGreaterThan(0);const zhVars=[...pair[3].matchAll(/\{\{(\w+)\}\}/g)].map(x=>x[1]).sort();const enVars=[...pair[4].matchAll(/\{\{(\w+)\}\}/g)].map(x=>x[1]).sort();expect(zhVars).toEqual(enVars)}})});
