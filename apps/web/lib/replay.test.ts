import test from 'node:test';
import assert from 'node:assert/strict';
import {interpolate} from './replay';
const p=(t:number,lng:number)=>({event_id:String(t),recorded_at:new Date(t).toISOString(),lng,lat:0,speed:10,bearing:90});
test('Replay follows timestamps and interpolates',()=>assert.equal(interpolate([p(0,0),p(10000,10)],5000)?.lng,5));
test('Replay holds position across connectivity gaps',()=>assert.equal(interpolate([p(0,0),p(300000,10)],100000)?.lng,0));
test('Empty replay is safe',()=>assert.equal(interpolate([],1),null));

test('Exact endpoint after a long gap reaches the recorded sample',()=>assert.equal(interpolate([p(0,0),p(300000,10)],300000)?.lng,10));
