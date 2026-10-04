import {defineConfig} from '@playwright/test';
export default defineConfig({testDir:'./e2e',use:{baseURL:process.env.E2E_WEB_URL||'http://localhost:3000',trace:'retain-on-failure'},workers:1,timeout:60000});
