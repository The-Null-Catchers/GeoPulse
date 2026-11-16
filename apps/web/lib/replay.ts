import type {Point} from './api';

export type ReplayEvent = {id:string;kind:string;recorded_at:string;label:string;
  lng:number|null;lat:number|null;location_recorded_at:string|null;duration_seconds:number|null;severity:string|null};
type Cursor = {recorded_at:string;id:string};
type Page<T> = {items:T[];next_cursor:Cursor|null};
type FetchPage = <T>(path:string)=>Promise<T>;

// A bounded client load makes truncation explicit rather than silently showing a whole day.
export async function loadReplayPages<T>(fetchPage:FetchPage, path:string, maxItems:number, pageSize:number,
  isCurrent:()=>boolean=()=>true):Promise<{items:T[];truncated:boolean}> {
  const items:T[]=[];let cursor:Cursor|null=null;
  do {
    if(!isCurrent())throw new Error('Replay request superseded');
    const params=new URLSearchParams({limit:String(Math.min(pageSize,maxItems-items.length))});
    if(cursor){params.set('after_time',cursor.recorded_at);params.set('after_id',cursor.id);}
    const page=await fetchPage<Page<T>>(path+'&'+params);
    if(!isCurrent())throw new Error('Replay request superseded');
    if(page.next_cursor&&(!page.items.length||JSON.stringify(page.next_cursor)===JSON.stringify(cursor)))throw new Error('Replay cursor did not advance');
    items.push(...page.items);cursor=page.next_cursor;
  } while(cursor&&items.length<maxItems);
  return {items,truncated:cursor!==null};
}

// Upper bound: last point recorded at or before the cursor. Equal timestamps are deterministic.
export function pointIndexAt(points:Point[], timestamp:number):number {
  let low=0,high=points.length;
  while(low<high){const mid=(low+high)>>>1;if(Date.parse(points[mid].recorded_at)<=timestamp)low=mid+1;else high=mid;}
  return low-1;
}

export function interpolate(points:Point[], timestamp:number):Point|null {
  if(!points.length) return null;
  const index=pointIndexAt(points,timestamp);
  if(index<0)return points[0];
  const a=points[index],b=points[index+1];
  if(!b)return a;
  const start=Date.parse(a.recorded_at),end=Date.parse(b.recorded_at);
  if(end-start>120000)return a;
  const t=(timestamp-start)/(end-start);
  const turn=((b.bearing-a.bearing+540)%360)-180;
  return {...a,lng:a.lng+(b.lng-a.lng)*t,lat:a.lat+(b.lat-a.lat)*t,speed:a.speed+(b.speed-a.speed)*t,
    bearing:(a.bearing+turn*t+360)%360};
}

export function replayTrail(points:Point[], timestamp:number):GeoJSON.FeatureCollection {
  const index=pointIndexAt(points,timestamp),lines:number[][][]=[];
  let line:number[][]=[];
  for(let i=0;i<=index;i++){
    if(i>0&&Date.parse(points[i].recorded_at)-Date.parse(points[i-1].recorded_at)>120000){if(line.length>1)lines.push(line);line=[];}
    line.push([points[i].lng,points[i].lat]);
  }
  const current=interpolate(points,timestamp);
  if(current&&index>=0&&timestamp>Date.parse(points[index].recorded_at)&&points[index+1]
    &&Date.parse(points[index+1].recorded_at)-Date.parse(points[index].recorded_at)<=120000)line.push([current.lng,current.lat]);
  if(line.length>1)lines.push(line);
  return {type:'FeatureCollection',features:lines.map(coordinates=>({type:'Feature',properties:{},geometry:{type:'LineString',coordinates}}))};
}
