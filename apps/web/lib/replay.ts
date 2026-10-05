import type {Point} from './api';
export function interpolate(points:Point[], timestamp:number):Point|null {
  if(!points.length) return null;
  if(timestamp<=Date.parse(points[0].recorded_at)) return points[0];
  for(let i=1;i<points.length;i++) {
    const end=Date.parse(points[i].recorded_at);
    if(timestamp<=end) {
      const a=points[i-1],b=points[i]; if(timestamp===end)return b; const start=Date.parse(a.recorded_at);
      // Don't invent travel across long connectivity gaps.
      if(end-start>120000) return a;
      const t=(timestamp-start)/(end-start || 1);
      return {...a,lng:a.lng+(b.lng-a.lng)*t,lat:a.lat+(b.lat-a.lat)*t,speed:a.speed+(b.speed-a.speed)*t};
    }
  }
  return points[points.length-1];
}
