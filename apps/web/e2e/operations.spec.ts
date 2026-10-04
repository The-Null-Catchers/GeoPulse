import {test,expect} from '@playwright/test';
test('Actual GPS ingestion reaches the authenticated dashboard',async({page,request})=>{
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
 await page.screenshot({path:'../../docs/screenshots/live-operations.png',fullPage:true});
 await page.getByRole('button',{name:'Replay this device'}).click();await expect(page.getByRole('button',{name:'Load history'})).toBeVisible();
});
test('Responsive sign-in form is usable on a phone',async({page})=>{await page.setViewportSize({width:390,height:844});await page.goto('/');await expect(page.getByRole('button',{name:'Open dashboard'})).toBeVisible();await expect(page.getByLabel('Email',{exact:true})).toBeVisible();});
