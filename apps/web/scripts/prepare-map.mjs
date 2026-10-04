import {copyFile, mkdir} from 'node:fs/promises';
import {fileURLToPath} from 'node:url';

// Keep the worker and its relative shared import aligned with the installed package.
const target = new URL('../public/maplibre/', import.meta.url);
const source = new URL('../node_modules/maplibre-gl/dist/', import.meta.url);
await mkdir(fileURLToPath(target), {recursive: true});
await Promise.all(['maplibre-gl-worker.mjs', 'maplibre-gl-shared.mjs'].map(
  name => copyFile(new URL(name, source), new URL(name, target))
));
await copyFile(new URL('../LICENSE.txt', source), new URL('LICENSE.txt', target));
