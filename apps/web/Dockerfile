FROM node:22-alpine AS deps
WORKDIR /app
COPY apps/web/package*.json ./
RUN npm ci
FROM deps AS build
COPY apps/web ./
ENV NEXT_TELEMETRY_DISABLED=1 API_INTERNAL_URL=http://api:8000
RUN npm run build
FROM node:22-alpine AS runtime
WORKDIR /app
ENV NODE_ENV=production NEXT_TELEMETRY_DISABLED=1 HOSTNAME=0.0.0.0 PORT=3000
COPY --from=build --chown=node:node /app/.next/standalone ./
COPY --from=build --chown=node:node /app/.next/static ./.next/static
USER node
EXPOSE 3000
CMD ["node", "server.js"]
