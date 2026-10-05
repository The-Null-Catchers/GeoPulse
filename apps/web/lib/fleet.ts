import type {Device} from './api';

export type FleetFilters = {query:string; state:string; team:string; type:string; activation:string};
export const emptyFilters: FleetFilters = {query:'',state:'all',team:'all',type:'all',activation:'all'};

// The same snapshot drives markers, fit bounds, the list and registry.
export function filterDevices(devices:Device[], filters:FleetFilters):Device[] {
  const query=filters.query.trim().toLocaleLowerCase();
  return devices.filter(device=>
    device.name.toLocaleLowerCase().includes(query) &&
    (filters.state==='all'||device.state===filters.state) &&
    (filters.team==='all'||(filters.team==='unassigned'?device.team_id===null:device.team_id===filters.team)) &&
    (filters.type==='all'||device.device_type===filters.type) &&
    (filters.activation==='all'||device.active===(filters.activation==='active'))
  );
}
