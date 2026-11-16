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
 await page.getByLabel('Search devices',{exact:true}).fill(' STORED ');
 await expect(page.locator('tbody tr')).toHaveCount(1);await expect(page.locator('tbody')).toContainText('Stored asset');
 await page.getByRole('button',{name:'Clear filters'}).click();await expect(page.locator('tbody tr')).toHaveCount(3);
 await page.getByLabel('Team',{exact:true}).selectOption('unassigned');
 await page.getByRole('button',{name:'Sign out'}).click();
 await page.getByLabel('Email',{exact:true}).fill(email);await page.getByLabel('Password',{exact:true}).fill(password);await page.getByRole('button',{name:'Open dashboard'}).click();
 await expect(page.getByRole('status')).toHaveText('3 of 3 loaded devices');await expect(page.getByLabel('Team',{exact:true})).toHaveValue('all');
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

test('Replay uses real stop/fence events, seeks on its timeline and clears changed ranges',async({page,request})=>{
 const url=process.env.E2E_API_URL||'http://localhost:8000';
 const email=`replay-${crypto.randomUUID()}@example.test`,password='replay-test-passphrase-123';
 const registered=await request.post(url+'/api/v1/auth/register',{data:{email,password,name:'Replay QA',organization:'Replay QA fleet'}});
 expect(registered.status()).toBe(201);const auth=await registered.json();
 const headers={Authorization:'Bearer '+auth.access_token,'X-Workspace-ID':auth.workspace_id};
 expect((await request.patch(url+'/api/v1/settings',{headers,data:{retention_days:90,offline_seconds:120,moving_speed:1.5,stop_seconds:30}})).ok()).toBeTruthy();
 const created=await request.post(url+'/api/v1/devices',{headers,data:{name:'Replay tracker'}});expect(created.status()).toBe(201);const device=await created.json();
 expect((await request.post(url+'/api/v1/geofences',{headers,data:{name:'Replay depot',center:[34.46,31.51],radius_m:100,dwell_seconds:10}})).status()).toBe(201);
 const start=Date.now()-100000;
 const points=[{seconds:0,speed:8,lng:34.46},{seconds:20,speed:0,lng:34.46},{seconds:60,speed:0,lng:34.46},{seconds:90,speed:8,lng:34.47}].map(p=>({event_id:crypto.randomUUID(),recorded_at:new Date(start+p.seconds*1000).toISOString(),lat:31.51,lng:p.lng,speed:p.speed,bearing:90,accuracy:5}));
 expect((await request.post(url+'/api/v1/locations/batch',{headers:{Authorization:'Bearer '+device.token},data:{points}})).status()).toBe(202);
 const params=new URLSearchParams({start:new Date(start-1000).toISOString(),end:new Date(start+100000).toISOString()});
 await expect.poll(async()=>{const r=await request.get(url+'/api/v1/devices/'+device.id+'/replay/events?'+params,{headers});return r.ok()?(await r.json()).items.map((e:{kind:string})=>e.kind):[];},{timeout:15000}).toContain('stop.departure');
 await page.goto('/');await page.getByLabel('Email',{exact:true}).fill(email);await page.getByLabel('Password',{exact:true}).fill(password);await page.getByRole('button',{name:'Open dashboard'}).click();
 await page.getByRole('button',{name:/Replay tracker/}).click();await page.getByRole('button',{name:'Replay this device'}).click();
 const day=new Date(start).toISOString().slice(0,10);await page.getByLabel('Replay UTC date').fill(day);
 // Reload explicitly so the same scenario works across UTC midnight.
 await page.getByRole('button',{name:'Load history',exact:true}).click();
 await expect(page.locator('.replay-event-heading')).toContainText('4 points');
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
});
