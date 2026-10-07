'use client';

import {useEffect, useRef, useState} from 'react';
import type {Feature, FeatureCollection, MultiPolygon} from 'geojson';
import {api} from '../lib/api';

type Mode = 'closest' | 'polygon' | 'route' | 'fences' | 'stops';
type Hit = {id:string; name?:string; device_name?:string; lng?:number; lat?:number;
  distance_m?:number; recorded_at?:string; arrived_at?:string; geometry?:MultiPolygon};
type ResultPage = {items:Hit[]; has_more:boolean};
type Fence = {id:string; name:string; geometry:MultiPolygon};
const empty:FeatureCollection = {type:'FeatureCollection', features:[]};

export default function SpatialSearch({target, vertices, fences, onDraw, onResults, onLocate}: {
  target:[number,number]; vertices:[number,number][]; fences:Fence[];
  onDraw:()=>void; onResults:(data:FeatureCollection)=>void;
  onLocate:(point:[number,number])=>void;
}) {
  const [mode,setMode]=useState<Mode>('closest');
  const [radius,setRadius]=useState(1000),[routeId,setRouteId]=useState(''),[fenceId,setFenceId]=useState('');
  const [routes,setRoutes]=useState<{id:string;name:string}[]>([]);
  const [date,setDate]=useState(new Date().toISOString().slice(0,10));
  const [hits,setHits]=useState<Hit[]>([]),[hasMore,setHasMore]=useState(false),[offset,setOffset]=useState(0);
  const [busy,setBusy]=useState(false),[error,setError]=useState(''),[searched,setSearched]=useState(false);
  const request=useRef(0);
  useEffect(()=>{let active=true;api<{id:string;name:string}[]>('/routes').then(r=>{if(active)setRoutes(r);}).catch(e=>{if(active)setError(String(e));});return()=>{active=false;request.current++;};},[]);
  useEffect(()=>{
    request.current++;setHits([]);setHasMore(false);setOffset(0);setSearched(false);setBusy(false);setError('');onResults(empty);
  },[mode,target,vertices,fenceId,routeId,radius,date,onResults]);

  async function search(nextOffset=0) {
    const scope=++request.current;setBusy(true);setError('');
    try {
      const params=new URLSearchParams({lng:String(target[0]),lat:String(target[1]),radius:String(radius),limit:'100',offset:String(nextOffset)});
      let result:ResultPage;
      if(mode==='closest') {
        const hit=await api<Hit|null>('/spatial/devices/closest?'+params);
        result={items:hit?[hit]:[],has_more:false};
      } else if(mode==='polygon') {
        const fence=fences.find(f=>f.id===fenceId);
        if(!fence&&vertices.length<3)throw new Error('Draw at least three vertices or select a geofence.');
        const geometry=fence?.geometry||{type:'Polygon',coordinates:[[...vertices,vertices[0]]]};
        result=await api<ResultPage>(`/spatial/devices/in-polygon?limit=100&offset=${nextOffset}`,'POST',{geometry});
      } else if(mode==='route') {
        if(!routeId)throw new Error('Select a route first.');
        params.set('route_id',routeId);result=await api<ResultPage>('/spatial/devices/near-route?'+params);
      } else if(mode==='fences') {
        result=await api<ResultPage>('/spatial/geofences/containing?'+params);
      } else {
        if(!date)throw new Error('Choose a UTC date.');
        params.set('start',new Date(date+'T00:00:00Z').toISOString());
        params.set('end',new Date(date+'T23:59:59.999Z').toISOString());
        result=await api<ResultPage>('/spatial/stops/nearby?'+params);
      }
      if(scope!==request.current)return;
      setHits(result.items);setHasMore(result.has_more);setOffset(nextOffset);setSearched(true);
      onResults({type:'FeatureCollection',features:result.items.flatMap<Feature>(hit=>{
        if(hit.geometry)return [{type:'Feature' as const,properties:{id:hit.id},geometry:hit.geometry}];
        if(hit.lng===undefined||hit.lat===undefined)return [];
        return [{type:'Feature' as const,properties:{id:hit.id},geometry:{type:'Point' as const,coordinates:[hit.lng,hit.lat]}}];
      })});
    } catch(e) {if(scope===request.current)setError(String(e));}
    finally {if(scope===request.current)setBusy(false);}
  }

  return <section className="spatial-panel" aria-label="Spatial search">
    <div className="spatial-heading"><h3>Search the operating area</h3><p className="muted">Click the map to choose a search point. Results use persisted positions across the workspace.</p></div>
    <form className="spatial-form" onSubmit={e=>{e.preventDefault();void search();}}>
      <label>Find<select aria-label="Spatial query" value={mode} onChange={e=>setMode(e.target.value as Mode)}>
        <option value="closest">Closest device</option><option value="polygon">Devices in area</option><option value="route">Devices near route</option><option value="fences">Geofences at point</option><option value="stops">Nearby stops</option>
      </select></label>
      {!['polygon','route'].includes(mode)&&<output aria-label="Search coordinates">{target[1].toFixed(5)}, {target[0].toFixed(5)}</output>}
      {['closest','route','stops'].includes(mode)&&<label>Radius (meters)<input aria-label="Spatial radius" type="number" min="1" max="100000" required value={radius} onChange={e=>setRadius(Number(e.target.value))}/></label>}
      {mode==='polygon'&&<><label>Area<select aria-label="Search area" value={fenceId} onChange={e=>setFenceId(e.target.value)}><option value="">Drawn area ({vertices.length} vertices)</option>{fences.map(f=><option key={f.id} value={f.id}>{f.name}</option>)}</select></label><button type="button" onClick={()=>{setFenceId('');onDraw();}}>Draw search area</button></>}
      {mode==='route'&&<label>Route<select aria-label="Search route" value={routeId} onChange={e=>setRouteId(e.target.value)} required><option value="">Choose route</option>{routes.map(r=><option key={r.id} value={r.id}>{r.name}</option>)}</select></label>}
      {mode==='stops'&&<label>UTC date<input aria-label="Stop search date" type="date" value={date} onChange={e=>setDate(e.target.value)} required/></label>}
      <button className="primary" disabled={busy} type="submit">{busy?'Searching…':'Search area'}</button>
    </form>
    {error&&<p role="alert" className="error">{error}</p>}
    {searched&&<><p data-testid="spatial-summary">{hits.length} results on this page{hasMore?' · more available':''}. {mode==='stops'?'Stops are matched by arrival date.':mode==='fences'?'Enabled geofences only.':'Active devices with recorded GPS; positions may be stale.'}</p>
      <div className="spatial-results">{hits.map(hit=><article key={hit.id}><strong>{hit.name||hit.device_name}</strong>{hit.distance_m!==undefined&&<span>{hit.distance_m.toFixed(1)} m away</span>}<small>{hit.recorded_at||hit.arrived_at?new Date(hit.recorded_at||hit.arrived_at!).toLocaleString():''}</small>{hit.lng!==undefined&&hit.lat!==undefined&&<button onClick={()=>onLocate([hit.lng!,hit.lat!])}>Show location</button>}</article>)}</div>
      <div className="spatial-paging">{offset>0&&<button disabled={busy} onClick={()=>void search(Math.max(0,offset-100))}>Previous results</button>}{hasMore&&<button disabled={busy} onClick={()=>void search(offset+100)}>Next results</button>}</div></>}
  </section>;
}
