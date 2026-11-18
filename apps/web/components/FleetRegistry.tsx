import {useEffect,useState} from 'react';
import {api,type Device} from '../lib/api';
import type {FleetFilters} from '../lib/fleet';

const pageSize=50;
type TableProps={colors:Record<string,string>;onSelect:(device:Device)=>void};
type SearchResult={devices:Device[];hasNext:boolean};

export function registrySearch(filters:FleetFilters):string {
  const query=filters.query.trim();
  if(!query)return '';
  const params=new URLSearchParams({q:query});
  if(filters.state!=='all')params.set('status',filters.state);
  if(filters.team==='unassigned')params.set('unassigned','true');
  else if(filters.team!=='all')params.set('team_id',filters.team);
  if(filters.type!=='all')params.set('device_type',filters.type);
  if(filters.activation!=='all')params.set('active',String(filters.activation==='active'));
  return params.toString();
}

export function DeviceTable({devices,colors,onSelect}:TableProps&{devices:Device[]}) {
  return <table>
    <thead><tr><th>Device</th><th>Status</th><th>Last signal</th><th>Battery</th></tr></thead>
    <tbody>{devices.map(device=><tr key={device.id} onClick={()=>onSelect(device)}>
      <td><button type="button" className="text-button" onClick={event=>{event.stopPropagation();onSelect(device);}}>{device.name}</button></td>
      <td><span style={{color:colors[device.state]}}>{device.state}</span></td>
      <td>{device.recorded_at?new Date(device.recorded_at).toLocaleString():'Awaiting signal'}</td>
      <td>{device.battery_level===null?'—':device.battery_level+'%'}</td>
    </tr>)}</tbody>
  </table>;
}

export default function FleetRegistry({search,...tableProps}:TableProps&{search:string}) {
  const [offset,setOffset]=useState(0);
  const [retry,setRetry]=useState(0);
  const [result,setResult]=useState<SearchResult|null>(null);
  const [error,setError]=useState(false);

  useEffect(()=>{
    let current=true;
    const timer=setTimeout(async()=>{
      try{
        const devices=await api<Device[]>(`/devices?${search}&limit=${pageSize+1}&offset=${offset}`);
        if(current)setResult({devices:devices.slice(0,pageSize),hasNext:devices.length>pageSize});
      }catch{
        if(current)setError(true);
      }
    },250);
    return ()=>{current=false;clearTimeout(timer);};
  },[search,offset,retry]);

  function openPage(nextOffset:number) {
    setResult(null);
    setOffset(nextOffset);
  }

  if(error)return <p className="empty" role="status">
    Device search failed. <button type="button" onClick={()=>{setError(false);setRetry(value=>value+1);}}>Retry search</button>
  </p>;
  if(!result)return <p className="empty" role="status">Searching the workspace…</p>;
  return <>
    <p className="empty" role="status">{result.devices.length?`${offset+1}–${offset+result.devices.length} workspace search results`:'No devices match your search.'}</p>
    {result.devices.length>0&&<DeviceTable {...tableProps} devices={result.devices}/>}
    {(offset>0||result.hasNext)&&<nav className="table-title" aria-label="Device search pages">
      <button type="button" disabled={offset===0} onClick={()=>openPage(offset-pageSize)}>Previous</button>
      <button type="button" disabled={!result.hasNext} onClick={()=>openPage(offset+pageSize)}>Next</button>
    </nav>}
  </>;
}
