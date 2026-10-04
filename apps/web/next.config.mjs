const tileOrigin = new URL(process.env.NEXT_PUBLIC_TILE_URL || 'https://tile.openstreetmap.org/{z}/{x}/{y}.png').origin;
const api = process.env.API_INTERNAL_URL || 'http://localhost:8000';
export default {
  output: 'standalone',
  async rewrites() { return [{source:'/api/:path*', destination:`${api}/api/:path*`}]; },
  async headers() { return [{source:'/:path*',headers:[
    {key:'X-Content-Type-Options',value:'nosniff'},
    {key:'Referrer-Policy',value:'strict-origin-when-cross-origin'},
    {key:'X-Frame-Options',value:'DENY'},
    {key:'Permissions-Policy',value:'geolocation=(self), camera=(), microphone=()'},
    {key:'Content-Security-Policy',value:`default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; worker-src 'self' blob:; img-src 'self' data: blob: https:; connect-src 'self' ws: wss: ${tileOrigin}; font-src 'self'; frame-ancestors 'none'; base-uri 'self'; object-src 'none'`}
  ]}]; }
};
