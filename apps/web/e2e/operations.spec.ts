import {writeFile} from 'node:fs/promises';
import {test,expect} from '@playwright/test';
test('Actual GPS ingestion reaches the authenticated dashboard',async({page,request})=>{
 const workerErrors:string[]=[];page.on('console',message=>{if(message.type()==='error'&&message.text().includes('Worker failed'))workerErrors.push(message.text());});
 const url=process.env.E2E_API_URL||'http://localhost:8000';
 const email=`browser-${Date.now()}@example.test`,password='browser-test-passphrase-123';
 const registered=await request.post(url+'/api/v1/auth/register',{data:{email,password,name:'QA dispatcher',organization:'Browser QA fleet'}});expect(registered.status()).toBe(201);
 const auth=await registered.json();
 const created=await request.post(url+'/api/v1/devices',{headers:{Authorization:'Bearer '+auth.access_token,'X-Workspace-ID':auth.workspace_id},data:{name:'Browser test tracker'}});expect(created.status()).toBe(201);const device=await created.json();
 const navigation=await page.goto('/');expect(navigation?.headers()['referrer-policy']).toBe('strict-origin-when-cross-origin');await page.getByLabel('Email',{exact:true}).fill(email);await page.getByLabel('Password',{exact:true}).fill(password);await page.getByRole('button',{name:'Open dashboard'}).click();await expect(page.getByRole('heading',{name:'Your fleet, in focus.'})).toBeVisible();
 await expect(page.getByText('LIVE CONNECTION',{exact:true})).toBeVisible();
 await expect(page.getByTestId('live-map')).toHaveAttribute('data-ready','true',{timeout:30000});
 const point={event_id:crypto.randomUUID(),recorded_at:new Date().toISOString(),lng:34.46,lat:31.51,speed:8,bearing:45,accuracy:5,battery_level:80,source:'simulator'};
 const ingested=await request.post(url+'/api/v1/locations',{headers:{Authorization:'Bearer '+device.token},data:point});expect(ingested.status()).toBe(202);
 await page.getByRole('button',{name:/Browser test tracker/}).click();await expect(page.getByText('34.46000',{exact:false})).toBeVisible();
 // Disable device-list resync so the second position can arrive only via WebSocket.
 await page.route('**/api/v1/devices?*',route=>route.abort());
 const second=await request.post(url+'/api/v1/locations',{headers:{Authorization:'Bearer '+device.token},data:{...point,event_id:crypto.randomUUID(),recorded_at:new Date().toISOString(),lng:34.461,speed:12}});
 expect(second.status()).toBe(202);
 await expect(page.getByText('34.46100',{exact:false})).toBeVisible({timeout:5000});
 await expect(page.getByTestId('live-map')).toHaveAttribute('data-ready','true',{timeout:30000});
 await expect(page.getByTestId('live-map')).toHaveAttribute('data-fleet-features',/^[1-9]\d*$/);
 expect(workerErrors).toEqual([]);
 await page.screenshot({path:'../../docs/screenshots/live-operations.png',fullPage:true});
 await page.getByLabel('Device type',{exact:true}).selectOption('asset');
 await expect(page.getByRole('status')).toHaveText('0 of 1 loaded devices');
 await expect(page.getByTestId('live-map')).toHaveAttribute('data-fleet-features','0');
 await page.getByRole('button',{name:'Clear filters'}).click();
 await expect(page.getByTestId('live-map')).toHaveAttribute('data-fleet-features',/^[1-9]\d*$/);
 await page.getByRole('button',{name:'Replay this device'}).click();await expect(page.getByRole('button',{name:'Load history'})).toBeVisible();
});
test('Responsive sign-in form is usable on a phone',async({page})=>{await page.setViewportSize({width:390,height:844});await page.goto('/');await expect(page.getByRole('button',{name:'Open dashboard'})).toBeVisible();await expect(page.getByLabel('Email',{exact:true})).toBeVisible();});

test('Fleet filters combine team, type, activation and search in the registry',async({page,request})=>{
 const url=process.env.E2E_API_URL||'http://localhost:8000';
 const email=`filters-${crypto.randomUUID()}@example.test`,password='filter-test-passphrase-123';
 const registered=await request.post(url+'/api/v1/auth/register',{data:{email,password,name:'Filter QA',organization:'Filter QA fleet'}});
 expect(registered.status()).toBe(201);const auth=await registered.json();
 const headers={Authorization:'Bearer '+auth.access_token,'X-Workspace-ID':auth.workspace_id};
 const teamResponse=await request.post(url+'/api/v1/teams',{headers,data:{name:'North team'}});expect(teamResponse.status()).toBe(201);const team=await teamResponse.json();
 for(const data of [{name:'North van',device_type:'vehicle',team_id:team.id},{name:'Field person',device_type:'person'},{name:'Stored asset',device_type:'asset'}]){
  const response=await request.post(url+'/api/v1/devices',{headers,data});expect(response.status()).toBe(201);
  if(data.device_type==='asset'){const d=await response.json();expect((await request.patch(url+'/api/v1/devices/'+d.id,{headers,data:{active:false}})).ok()).toBeTruthy();}
 }
 await page.goto('/');await page.getByLabel('Email',{exact:true}).fill(email);await page.getByLabel('Password',{exact:true}).fill(password);await page.getByRole('button',{name:'Open dashboard'}).click();
 await page.getByRole('button',{name:'Devices',exact:true}).click();
 await expect(page.getByRole('status')).toHaveText('3 of 3 loaded devices');
 await page.getByLabel('Team',{exact:true}).selectOption(team.id);
 await expect(page.locator('tbody tr')).toHaveCount(1);await expect(page.locator('tbody')).toContainText('North van');
 await page.getByLabel('Device type',{exact:true}).selectOption('person');await expect(page.locator('tbody tr')).toHaveCount(0);
 await page.getByRole('button',{name:'Clear filters'}).click();
 await page.getByLabel('Team',{exact:true}).selectOption('unassigned');await page.getByLabel('Activation',{exact:true}).selectOption('inactive');
 const search=page.waitForResponse(response=>{
  const params=new URL(response.url()).searchParams;
  return params.get('q')==='STORED'&&params.get('active')==='false'&&params.get('unassigned')==='true';
 });
 await page.getByLabel('Search devices',{exact:true}).fill(' STORED ');
 expect((await search).ok()).toBeTruthy();
 await expect(page.getByRole('status')).toHaveText('1–1 workspace search results');
 await expect(page.locator('tbody tr')).toHaveCount(1);await expect(page.locator('tbody')).toContainText('Stored asset');
 await page.getByRole('button',{name:'Clear filters'}).click();await expect(page.locator('tbody tr')).toHaveCount(3);
 await page.getByLabel('Team',{exact:true}).selectOption('unassigned');
 await page.getByRole('button',{name:'Sign out'}).click();
 await page.getByLabel('Email',{exact:true}).fill(email);await page.getByLabel('Password',{exact:true}).fill(password);await page.getByRole('button',{name:'Open dashboard'}).click();
 await expect(page.getByRole('status')).toHaveText('3 of 3 loaded devices');await expect(page.getByLabel('Team',{exact:true})).toHaveValue('all');
});

test('Registry search finds and opens devices beyond the loaded snapshot',async({page,request})=>{
 const url=process.env.E2E_API_URL||'http://localhost:8000';
 const email=`registry-${crypto.randomUUID()}@example.test`,password='registry-test-passphrase-123';
 const registration=await request.post(url+'/api/v1/auth/register',{data:{email,password,name:'Registry QA',organization:'Registry QA fleet'}});
 expect(registration.status()).toBe(201);
 const auth=await registration.json();
 const headers={Authorization:'Bearer '+auth.access_token,'X-Workspace-ID':auth.workspace_id};
 for(const name of ['Alpha tracker','Zebra tracker']){
  expect((await request.post(url+'/api/v1/devices',{headers,data:{name}})).status()).toBe(201);
 }

 await page.route('**/api/v1/devices?limit=1000',async route=>{
  // Request a short snapshot from the same backend to put Zebra beyond it.
  const snapshot=new URL(route.request().url());
  snapshot.searchParams.set('limit','1');
  await route.fulfill({response:await route.fetch({url:snapshot.href})});
 });
 await page.goto('/');
 await page.getByLabel('Email',{exact:true}).fill(email);
 await page.getByLabel('Password',{exact:true}).fill(password);
 await page.getByRole('button',{name:'Open dashboard'}).click();
 await page.getByRole('button',{name:'Devices',exact:true}).click();
 await expect(page.getByRole('status')).toHaveText('1 of 1 loaded devices');
 await expect(page.locator('tbody')).toContainText('Alpha tracker');
 await page.getByLabel('Search devices',{exact:true}).fill('zebra');
 const result=page.getByRole('button',{name:'Zebra tracker',exact:true});
 await expect(result).toBeVisible();
 await result.press('Enter');
 await expect(page.getByRole('heading',{name:'Zebra tracker',exact:true})).toBeVisible();
 await page.getByRole('button',{name:'Clear filters'}).click();
 await expect(page.locator('tbody')).toContainText('Alpha tracker');
});

test('Spatial searches render persisted GPS and containing geofences in native layers',async({page,request})=>{
 const url=process.env.E2E_API_URL||'http://localhost:8000';
 const email=`spatial-${crypto.randomUUID()}@example.test`,password='spatial-test-passphrase-123';
 const registered=await request.post(url+'/api/v1/auth/register',{data:{email,password,name:'Spatial QA',organization:'Spatial QA fleet'}});
 expect(registered.status()).toBe(201);const auth=await registered.json();
 const headers={Authorization:'Bearer '+auth.access_token,'X-Workspace-ID':auth.workspace_id};
 const created=await request.post(url+'/api/v1/devices',{headers,data:{name:'Spatial tracker'}});expect(created.status()).toBe(201);const device=await created.json();
 const fence=await request.post(url+'/api/v1/geofences',{headers,data:{name:'Spatial depot',center:[34.46,31.51],radius_m:100}});expect(fence.status()).toBe(201);const area=await fence.json();
 const point={event_id:crypto.randomUUID(),recorded_at:new Date().toISOString(),lng:34.46,lat:31.51,speed:8,bearing:45,accuracy:5};
 expect((await request.post(url+'/api/v1/locations',{headers:{Authorization:'Bearer '+device.token},data:point})).status()).toBe(202);
 await page.goto('/');await page.getByLabel('Email',{exact:true}).fill(email);await page.getByLabel('Password',{exact:true}).fill(password);await page.getByRole('button',{name:'Open dashboard'}).click();
 await page.getByRole('button',{name:/Spatial tracker/}).click();await expect(page.getByText('34.46000',{exact:false})).toBeVisible();
 await page.getByRole('button',{name:'Spatial Search',exact:true}).click();
 await page.getByRole('button',{name:'Search area',exact:true}).click();
 await expect(page.getByTestId('spatial-summary')).toContainText('1 results on this page');
 await expect(page.locator('.spatial-results')).toContainText('Spatial tracker');
 await expect(page.getByTestId('live-map')).toHaveAttribute('data-spatial-features',/^[1-9]\d*$/);
 await page.getByLabel('Spatial query').selectOption('fences');
 await page.getByRole('button',{name:'Search area',exact:true}).click();
 await expect(page.locator('.spatial-results')).toContainText('Spatial depot');
 await expect(page.getByTestId('live-map')).toHaveAttribute('data-spatial-features',/^[1-9]\d*$/);
 await page.getByLabel('Spatial query').selectOption('polygon');await page.getByLabel('Search area',{exact:true}).selectOption(area.id);
 await page.getByRole('button',{name:'Search area',exact:true}).click();
 await expect(page.locator('.spatial-results')).toContainText('Spatial tracker');
 await page.getByLabel('Spatial query').selectOption('closest');
 // Changing the search point invalidates old hits and the native result layer.
 const map=page.getByTestId('live-map');await map.click({position:{x:80,y:80}});
 await expect(page.getByTestId('spatial-summary')).toHaveCount(0);
 await page.getByLabel('Spatial radius').fill('1');await page.getByRole('button',{name:'Search area',exact:true}).click();
 await expect(page.getByTestId('spatial-summary')).toContainText('0 results on this page');
 await expect(map).toHaveAttribute('data-spatial-features','0');
});

test('Replay verifies the synthetic route and deduplicates retried GPS points',async({page,request},testInfo)=>{
 const url=process.env.E2E_API_URL||'http://localhost:8000';
 const email=`replay-${crypto.randomUUID()}@example.test`,password='replay-test-passphrase-123';
 const registered=await request.post(url+'/api/v1/auth/register',{data:{email,password,name:'Replay QA',organization:'Replay QA fleet'}});
 expect(registered.status()).toBe(201);const auth=await registered.json();
 const headers={Authorization:'Bearer '+auth.access_token,'X-Workspace-ID':auth.workspace_id};
 expect((await request.patch(url+'/api/v1/settings',{headers,data:{retention_days:90,offline_seconds:120,moving_speed:1.5,stop_seconds:30}})).ok()).toBeTruthy();
 const created=await request.post(url+'/api/v1/devices',{headers,data:{name:'Replay tracker'}});expect(created.status()).toBe(201);const device=await created.json();
 expect((await request.post(url+'/api/v1/geofences',{headers,data:{name:'Replay depot',center:[34.46,31.51],radius_m:100,dwell_seconds:10}})).status()).toBe(201);
 const routeDate=new Date();routeDate.setUTCDate(routeDate.getUTCDate()-1);routeDate.setUTCHours(12,0,0,0);
 const start=routeDate.getTime();
 const points=[{seconds:0,speed:8,lng:34.45},{seconds:10,speed:8,lng:34.4595},{seconds:20,speed:0,lng:34.46},{seconds:60,speed:0,lng:34.46},{seconds:90,speed:8,lng:34.47}].map(p=>({event_id:crypto.randomUUID(),recorded_at:new Date(start+p.seconds*1000).toISOString(),lat:31.51,lng:p.lng,speed:p.speed,bearing:90,accuracy:5}));
 const ingest=()=>request.post(url+'/api/v1/locations/batch',{headers:{Authorization:'Bearer '+device.token},data:{points}});
 const first=await ingest();expect(first.status()).toBe(202);
 expect(await first.json()).toMatchObject({inserted:5,duplicates:0});
 const repeated=await ingest();expect(repeated.status()).toBe(202);
 expect(await repeated.json()).toMatchObject({inserted:0,duplicates:5});

 const params=new URLSearchParams({start:new Date(start-1000).toISOString(),end:new Date(start+100000).toISOString()});
 const replayUrl=url+'/api/v1/devices/'+device.id+'/replay/';
 const expectedEvents=[
  {kind:'geofence.enter',time:start+10000},
  {kind:'geofence.dwell',time:start+20000},
  {kind:'stop.arrival',time:start+20000},
  {kind:'geofence.exit',time:start+90000},
  {kind:'stop.departure',time:start+90000},
 ];
 await expect.poll(async()=>{
  const r=await request.get(replayUrl+'events?'+params,{headers});
  if(!r.ok())return [];
  const {items}=await r.json() as {items:{kind:string;recorded_at:string}[]};
  return items.filter(e=>e.kind.startsWith('geofence.')||e.kind.startsWith('stop.')).map(e=>({kind:e.kind,time:Date.parse(e.recorded_at)}));
 },{timeout:15000}).toEqual(expectedEvents);
 const stored=await request.get(replayUrl+'points?'+params,{headers});
 expect(stored.ok()).toBeTruthy();
 const replayPoints=(await stored.json()).items as {event_id:string;recorded_at:string;lng:number;lat:number}[];
 expect(replayPoints.map(p=>[p.event_id,Date.parse(p.recorded_at),p.lng,p.lat])).toEqual(
  points.map(p=>[p.event_id,Date.parse(p.recorded_at),p.lng,p.lat]),
 );
 await writeFile(testInfo.outputPath('synthetic-trip-evidence.json'),JSON.stringify({
  source:'Synthetic browser fixture',startUtc:routeDate.toISOString(),
  inserted:5,duplicatesIgnored:5,points,replayEvents:expectedEvents.map(e=>({...e,time:new Date(e.time).toISOString()})),
 },null,2)+'\n');
 await page.goto('/');await page.getByLabel('Email',{exact:true}).fill(email);await page.getByLabel('Password',{exact:true}).fill(password);await page.getByRole('button',{name:'Open dashboard'}).click();
 await page.getByRole('button',{name:/Replay tracker/}).click();await page.getByRole('button',{name:'Replay this device'}).click();
 const day=new Date(start).toISOString().slice(0,10);await page.getByLabel('Replay UTC date').fill(day);
 // Reload explicitly so the same scenario works across UTC midnight.
 await page.getByRole('button',{name:'Load history',exact:true}).click();
 await expect(page.locator('.replay-event-heading')).toContainText('5 points');
 await expect(page.getByTestId('replay-event').filter({hasText:'geofence enter'})).toContainText('Replay depot');
 const departure=page.getByTestId('replay-event').filter({hasText:'stop departure'});await expect(departure).toBeVisible();await departure.click();
 await expect(page.getByLabel('Replay timeline')).toHaveValue(String(start+90000));
 await expect(page.getByTestId('live-map')).toHaveAttribute('data-replay-events',/^[1-9]\d*$/);
 await page.evaluate(()=>window.scrollTo(0,0));
 await page.screenshot({path:'../../docs/screenshots/historical-replay.png',fullPage:true});
 await page.getByLabel('Replay event filter').selectOption('stop.');await expect(page.getByTestId('replay-event')).toHaveCount(2);
 await page.getByLabel('Replay start UTC').fill('23:59:58');
 await expect(page.getByTestId('replay-event')).toHaveCount(0);
 await expect(page.getByTestId('live-map')).toHaveAttribute('data-replay-events','0');
 await page.getByLabel('Replay end UTC').fill('12:00:00');
 await page.getByRole('button',{name:'Load history',exact:true}).click();
 await expect(page.getByRole('alert').filter({hasText:'Replay end time must be at or after the start time.'})).toBeVisible();
});
test('Late offline GPS repairs daily analytics without moving the live marker backwards',async({page,request})=>{
 const url=process.env.E2E_API_URL||'http://localhost:8000';
 const email=`distance-${crypto.randomUUID()}@example.test`,password='qa-'+crypto.randomUUID()+'-passphrase';
 const registered=await request.post(url+'/api/v1/auth/register',{data:{email,password,name:'Distance QA',organization:'Offline QA fleet'}});
 expect(registered.status()).toBe(201);const auth=await registered.json();
 const headers={Authorization:'Bearer '+auth.access_token,'X-Workspace-ID':auth.workspace_id};
 const created=await request.post(url+'/api/v1/devices',{headers,data:{name:'Offline queue tracker'}});
 expect(created.status()).toBe(201);const device=await created.json(),dh={Authorization:'Bearer '+device.token};
 const at=new Date();at.setUTCDate(at.getUTCDate()-1);at.setUTCHours(12,0,0,0);const start=at.getTime(),day=at.toISOString().slice(0,10);
 const point=(seconds:number,lat=31.51)=>({event_id:crypto.randomUUID(),recorded_at:new Date(start+seconds*1000).toISOString(),lat,lng:34.46,speed:5,bearing:90,accuracy:5});
 for(const seconds of [0,40])expect((await request.post(url+'/api/v1/locations',{headers:dh,data:point(seconds)})).status()).toBe(202);
 await expect.poll(async()=>{const r=await request.get(url+'/api/v1/devices',{headers});return Date.parse((await r.json())[0]?.recorded_at||'');},{timeout:15000}).toBe(start+40000);
 await page.goto('/');await page.getByLabel('Email',{exact:true}).fill(email);await page.getByLabel('Password',{exact:true}).fill(password);await page.getByRole('button',{name:'Open dashboard'}).click();
 await page.getByRole('button',{name:'Analytics',exact:true}).click();
 const row=page.getByTestId('distance-day').filter({hasText:day});await expect(row).toContainText('0.00 km');
 const late=point(20,31.511);expect((await request.post(url+'/api/v1/locations',{headers:dh,data:late})).status()).toBe(202);
 await expect(row).toContainText('0.22 km',{timeout:20000});await expect(row).toContainText('Current');
 const snapshot=(await (await request.get(url+'/api/v1/devices',{headers})).json())[0];expect(snapshot.lat).toBe(31.51);
 expect((await (await request.post(url+'/api/v1/locations',{headers:dh,data:late})).json()).duplicates).toBe(1);
 await page.getByRole('button',{name:/Offline queue tracker/}).click();
 await expect(page.getByText('31.51000, 34.46000',{exact:true})).toBeVisible();
 await page.evaluate(()=>window.scrollTo(0,0));
 await page.screenshot({path:'../../docs/screenshots/offline-distance.png',fullPage:true});
});
