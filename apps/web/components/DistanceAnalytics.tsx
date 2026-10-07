'use client';

import {useEffect,useState} from 'react';
import {api,type Device} from '../lib/api';

type Day={date:string;distance_m:number;pending_devices:number};

export default function DistanceAnalytics({devices,revision}:{devices:Device[];revision:number}){
 const [start,setStart]=useState(()=>new Date(Date.now()-6*86400000).toISOString().slice(0,10));
 const [end,setEnd]=useState(()=>new Date().toISOString().slice(0,10));
 const [device,setDevice]=useState(''),[days,setDays]=useState<Day[]>([]),[error,setError]=useState(''),[busy,setBusy]=useState(false);
 useEffect(()=>{
  let active=true;
  const load=async()=>{setBusy(true);setError('');try{
   const params=new URLSearchParams({start,end});if(device)params.set('device_id',device);
   const rows=await api<Day[]>('/analytics/distance?'+params);
   if(active)setDays(rows);
  }catch(e){if(active){setDays([]);setError(String(e));}}finally{if(active)setBusy(false);}};
  setDays([]);void load();const timer=setInterval(load,30000);
  return()=>{active=false;clearInterval(timer);};
 },[start,end,device,revision]);
 const maximum=Math.max(1,...days.map(d=>d.distance_m));
 return <section className="distance-analytics" aria-label="Daily distance analytics">
  <div className="distance-heading"><div><h3>Distance over time</h3><p className="muted">Recorded GPS distance · UTC days · connectivity gaps excluded</p></div>
   <label>From<input aria-label="Distance start UTC" type="date" value={start} onChange={e=>setStart(e.target.value)}/></label>
   <label>To<input aria-label="Distance end UTC" type="date" value={end} onChange={e=>setEnd(e.target.value)}/></label>
   <label>Device<select aria-label="Distance device" value={device} onChange={e=>setDevice(e.target.value)}><option value="">Entire workspace</option>{devices.map(d=><option key={d.id} value={d.id}>{d.name}</option>)}</select></label>
  </div>
  {error&&<p role="alert" className="error">{error}</p>}
  {busy&&<p role="status" className="muted">Loading distance…</p>}
  {days.some(d=>d.pending_devices>0)&&<p role="status" className="replay-notice">Late GPS samples are queued for recalculation. Pending totals may change.</p>}
  <table><thead><tr><th>UTC day</th><th>Distance</th><th>Activity</th><th>Recalculation</th></tr></thead><tbody>{days.map(d=><tr key={d.date} data-testid="distance-day"><td>{d.date}</td><td>{(d.distance_m/1000).toFixed(2)} km</td><td><meter aria-label={'Relative distance on '+d.date} min={0} max={maximum} value={d.distance_m}/></td><td>{d.pending_devices?`${d.pending_devices} pending`:'Current'}</td></tr>)}</tbody></table>
 </section>;
}
