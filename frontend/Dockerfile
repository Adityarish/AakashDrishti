# Build from the repo root:  docker build -f frontend/Dockerfile .
FROM node:20-slim AS deps
WORKDIR /app
COPY frontend/package*.json ./
RUN npm ci

FROM node:20-slim AS build
WORKDIR /app
COPY --from=deps /app/node_modules node_modules
COPY frontend .
# NEXT_PUBLIC_* values are inlined at build time: set this to the public URL of the API.
ARG NEXT_PUBLIC_API_BASE_URL=http://localhost:8000
ENV NEXT_PUBLIC_API_BASE_URL=$NEXT_PUBLIC_API_BASE_URL NEXT_TELEMETRY_DISABLED=1
RUN npm run build

FROM node:20-slim AS run
WORKDIR /app
ENV NODE_ENV=production NEXT_TELEMETRY_DISABLED=1 PORT=3000 HOSTNAME=0.0.0.0
COPY --from=build /app/.next/standalone ./
COPY --from=build /app/.next/static .next/static
COPY --from=build /app/public public
USER node
EXPOSE 3000
CMD ["node", "server.js"]
