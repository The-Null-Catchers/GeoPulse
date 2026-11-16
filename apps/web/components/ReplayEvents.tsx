'use client';
import {useEffect,useState} from 'react';
import type {ReplayEvent} from '../lib/replay';

export default function ReplayEvents({events,cursor,onSeek,busy,note,pointCount}: {
  events:ReplayEvent[];cursor:number;onSeek:(timestamp:number)=>void;busy:boolean;note:string;pointCount:number;
}) {
  const [filter,setFilter]=useState('all'),[offset,setOffset]=useState(0);
  useEffect(()=>{setOffset(0);},[events]);
  const matching=events.filter(event=>filter==='all'||event.kind.startsWith(filter));
  const visible=matching.slice(offset,offset+50);
  return <section className="replay-events" aria-label="Replay events">
    <div className="replay-event-heading"><h3>Recorded activity</h3><span>{busy?'Loading history…':`${pointCount.toLocaleString()} points · ${events.length.toLocaleString()} events`}</span>
      <label>Show<select aria-label="Replay event filter" value={filter} onChange={e=>{setFilter(e.target.value);setOffset(0);}}><option value="all">All events</option><option value="stop.">Stops</option><option value="geofence.">Geofences</option><option value="alert.">Alerts</option></select></label></div>
    {note&&<p className="replay-notice" role="status">{note}</p>}
    {!busy&&!events.length&&<p className="muted">No persisted events loaded for this device and UTC day.</p>}
    <div className="replay-event-list">{visible.map(event=><button key={event.id} data-testid="replay-event" className={Date.parse(event.recorded_at)<=cursor?'occurred':''} onClick={()=>onSeek(Date.parse(event.recorded_at))}>
      <time>{new Date(event.recorded_at).toLocaleTimeString()}</time><strong>{event.kind.replaceAll('.',' ')}</strong><span>{event.label}</span>
      {event.duration_seconds!==null&&<small>{Math.round(event.duration_seconds/60)} min stopped</small>}{event.severity&&<small>{event.severity}</small>}
      {event.kind==='alert.created'&&event.location_recorded_at&&event.location_recorded_at!==event.recorded_at&&<small>Last known GPS: {new Date(event.location_recorded_at).toLocaleTimeString()}</small>}
    </button>)}</div>
    <div className="replay-event-paging">{offset>0&&<button onClick={()=>setOffset(Math.max(0,offset-50))}>Previous events</button>}{offset+50<matching.length&&<button onClick={()=>setOffset(offset+50)}>Next events</button>}</div>
  </section>;
}
