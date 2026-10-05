import type { Metadata } from 'next';
import './globals.css';
export const metadata: Metadata = {title:'GeoPulse · Operations',description:'Realtime geospatial operations'};
export default function RootLayout({children}:{children:React.ReactNode}) {return <html lang="en"><body>{children}</body></html>;}
