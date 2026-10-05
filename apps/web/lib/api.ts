export type Device = {id:string; name:string; device_type:string; active:boolean; team_id:string|null; state:string; lng:number|null; lat:number|null; speed:number|null; bearing:number|null; battery_level:number|null; recorded_at:string|null; last_seen:string|null; distance_today_m:number|null};
export type Point = {event_id:string; recorded_at:string; lng:number; lat:number; speed:number; bearing:number};
export type Alert = {id:string; device_id:string; device_name:string; kind:string; severity:string; state:string; created_at:string};
let access = '';
let workspace = '';
let refreshing: Promise<void>|null = null;
export function configure(token:string,wid:string) {access=token; workspace=wid;}
export async function api<T>(path:string, method='GET', body?:unknown, retry=true):Promise<T> {
  const res=await fetch('/api/v1'+path,{method,credentials:'include',headers:{'Content-Type':'application/json',...(access?{'Authorization':'Bearer '+access}:{}),...(workspace?{'X-Workspace-ID':workspace}:{})},body:body===undefined?undefined:JSON.stringify(body)});
  if (res.status===401 && retry && !path.startsWith('/auth/')) {
    refreshing ??= (async()=>{const r=await fetch('/api/v1/auth/refresh',{method:'POST',credentials:'include',headers:{'Content-Type':'application/json'},body:'{}'}); if(!r.ok) throw new Error('Session expired. Sign in again.'); access=(await r.json()).access_token;})().finally(()=>{refreshing=null;});
    await refreshing; return api<T>(path,method,body,false);
  }
  if(!res.ok) {const error=await res.json().catch(()=>({detail:res.statusText})); throw new Error(typeof error.detail==='string'?error.detail:JSON.stringify(error.detail));}
  return res.status===204 ? undefined as T : res.json();
}
export async function downloadTrips() {
  const r=await fetch('/api/v1/reports/trips.csv',{headers:{Authorization:'Bearer '+access,'X-Workspace-ID':workspace}});
  if(!r.ok) throw new Error('Export failed');
  const url=URL.createObjectURL(await r.blob()); const a=document.createElement('a');a.href=url;a.download='geopulse-trips.csv';a.click();URL.revokeObjectURL(url);
}
