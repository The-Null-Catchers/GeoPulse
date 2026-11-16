import test from 'node:test';
import assert from 'node:assert/strict';
import {interpolate} from './replay';
const p=(t:number,lng:number)=>({event_id:String(t),recorded_at:new Date(t).toISOString(),lng,lat:0,speed:10,bearing:90});
test('Replay follows timestamps and interpolates',()=>assert.equal(interpolate([p(0,0),p(10000,10)],5000)?.lng,5));
test('Replay holds position across connectivity gaps',()=>assert.equal(interpolate([p(0,0),p(300000,10)],100000)?.lng,0));
test('Empty replay is safe',()=>assert.equal(interpolate([],1),null));

test('Exact endpoint after a long gap reaches the recorded sample',()=>assert.equal(interpolate([p(0,0),p(300000,10)],300000)?.lng,10));

import {pointIndexAt,replayTrail,loadReplayPages} from './replay';
test('Equal GPS timestamps resolve consistently to the final recorded sample',()=>{
 const points=[p(0,0),p(1000,1),{...p(1000,2),event_id:'second'},p(2000,3)];
 assert.equal(pointIndexAt(points,1000),2);assert.equal(interpolate(points,1000)?.lng,2);
 assert.equal(pointIndexAt(points,-1),-1);assert.equal(pointIndexAt([],0),-1);
});
test('Replay bearing takes the short turn through north',()=>{
 assert.equal(interpolate([{...p(0,0),bearing:350},{...p(10000,10),bearing:10}],5000)?.bearing,0);
});
test('Trail splits GPS gaps instead of inventing connecting travel',()=>{
 const trail=replayTrail([p(0,0),p(10000,1),p(300000,20),p(310000,21)],310000);
 assert.equal(trail.features.length,2);
 assert.deepEqual(trail.features.map(f=>(f.geometry as GeoJSON.LineString).coordinates),[[[0,0],[1,0]],[[20,0],[21,0]]]);
 assert.equal(replayTrail([p(0,0),p(300000,20)],100000).features.length,0);
});
test('Page loader passes keyset cursors and reports its memory cap',async()=>{
 const paths:string[]=[];let count=0;
 const fetchPage=async<T>(path:string):Promise<T>=>{paths.push(path);count++;return {items:count===1?[p(0,0),p(1000,1)]:[p(2000,2)],next_cursor:{recorded_at:new Date(count===1?1000:2000).toISOString(),id:String(count)}} as T;};
 const result=await loadReplayPages(fetchPage,'/points?start=day',3,2);
 assert.equal(result.items.length,3);assert.equal(result.truncated,true);
 assert.equal(new URLSearchParams(paths[1].split('?')[1]).get('after_id'),'1');
 assert.equal(new URLSearchParams(paths[1].split('?')[1]).get('limit'),'1');
});
test('Page loader finishes exact-size terminal pages without claiming truncation',async()=>{
 const fetchPage=async<T>():Promise<T>=>({items:[p(0,0)],next_cursor:null} as T);
 const result=await loadReplayPages(fetchPage,'/points?start=day',1,1);
 assert.equal(result.truncated,false);assert.equal(result.items.length,1);
});
test('Page loader stops stale loads and rejects non-advancing cursors',async()=>{
 let active=true,calls=0;
 const fetchPage=async<T>():Promise<T>=>{calls++;active=false;return {items:[p(0,0)],next_cursor:null} as T;};
 await assert.rejects(loadReplayPages(fetchPage,'/points?start=day',5,1,()=>active),/superseded/);assert.equal(calls,1);
 const repeating=async<T>():Promise<T>=>({items:[p(0,0)],next_cursor:{recorded_at:new Date(0).toISOString(),id:'same'}} as T);
 await assert.rejects(loadReplayPages(repeating,'/points?start=day',5,1),/did not advance/);
});
