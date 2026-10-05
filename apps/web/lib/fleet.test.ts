import {test} from 'node:test';
import assert from 'node:assert/strict';
import {emptyFilters,filterDevices} from './fleet';
import type {Device} from './api';

const base:Device={id:'1',name:'Delivery Van',device_type:'vehicle',active:true,team_id:'north',state:'moving',lng:34.46,lat:31.51,speed:10,bearing:90,battery_level:80,recorded_at:null,last_seen:null,distance_today_m:0};
const fleet=[base,{...base,id:'2',name:'Field Person',device_type:'person',team_id:null,state:'idle'}, {...base,id:'3',name:'Warehouse Asset',device_type:'asset',active:false,team_id:'south',state:'unknown',lng:null,lat:null}];
test('Combined filters intersect rather than widening the fleet',()=>{
  assert.deepEqual(filterDevices(fleet,{...emptyFilters,query:' VAN ',team:'north',type:'vehicle',state:'moving',activation:'active'}).map(d=>d.id),['1']);
  assert.equal(filterDevices(fleet,{...emptyFilters,team:'north',type:'person'}).length,0);
});
test('Unassigned and disabled devices remain explicitly discoverable without GPS',()=>{
  assert.deepEqual(filterDevices(fleet,{...emptyFilters,team:'unassigned'}).map(d=>d.id),['2']);
  assert.deepEqual(filterDevices(fleet,{...emptyFilters,activation:'inactive',state:'unknown'}).map(d=>d.id),['3']);
});
test('Reset returns all devices and filtering does not mutate the snapshot',()=>{
  assert.deepEqual(filterDevices(fleet,emptyFilters),fleet);
  assert.equal(fleet.length,3);
  assert.deepEqual(filterDevices([{...base,state:'offline'}],{...emptyFilters,state:'offline'}).map(d=>d.id),['1']);
});
