import {afterEach,describe,expect,it,vi} from 'vitest';
import {webcrypto} from 'node:crypto';
import {createId} from './id';

afterEach(()=>{vi.unstubAllGlobals();vi.restoreAllMocks();vi.resetModules()});

describe('IDs on HTTP and HTTPS deployments',()=>{
 it('uses the native UUID API when available',()=>{
  const native=vi.fn(()=> 'ab13012d-064b-49b6-a7e8-3b8d614b5d10');
  vi.stubGlobal('crypto',{randomUUID:native});
  expect(createId()).toBe('ab13012d-064b-49b6-a7e8-3b8d614b5d10');
  expect(native).toHaveBeenCalledOnce();
 });
 it('creates independent valid UUIDs without randomUUID or Math.random',()=>{
  vi.stubGlobal('crypto',{getRandomValues:webcrypto.getRandomValues.bind(webcrypto)});
  vi.spyOn(Math,'random').mockImplementation(()=>{throw new Error('Weak randomness must not be used')});
  const ids=Array.from({length:100},()=>createId());
  for(const id of ids)expect(id).toMatch(/^[a-f0-9]{8}-[a-f0-9]{4}-4[a-f0-9]{3}-[89ab][a-f0-9]{3}-[a-f0-9]{12}$/);
  expect(new Set(ids).size).toBe(ids.length);
 });
 it('initializes an HTTP session and preserves it after a reload',async()=>{
  const saved=new Map<string,string>();
  vi.stubGlobal('localStorage',{getItem:(key:string)=>saved.get(key)||null,setItem:(key:string,value:string)=>saved.set(key,value)});
  vi.stubGlobal('crypto',{getRandomValues:webcrypto.getRandomValues.bind(webcrypto)});
  const first=await import('./api');
  expect(first.session).toBe(saved.get('vps-session'));
  expect(first.session).toHaveLength(36);
  vi.resetModules();
  const reloaded=await import('./api');
  expect(reloaded.session).toBe(first.session);
 });
});
