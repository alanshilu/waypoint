# Waypoint frontend: the Vite build, served by nginx, which also proxies /api to the backend.
FROM node:22-alpine AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
# Baked in at build time. /api is same-origin: nginx forwards it to the backend container.
ARG VITE_USE_MOCK=false
ARG VITE_API_BASE=/api
ARG VITE_PUBLIC_DEMO=false
ENV VITE_USE_MOCK=$VITE_USE_MOCK VITE_API_BASE=$VITE_API_BASE VITE_PUBLIC_DEMO=$VITE_PUBLIC_DEMO
RUN npm run build

# Runs as a non-root user and listens on 8080
FROM nginxinc/nginx-unprivileged:1.27-alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s --retries=3 CMD wget -q -O /dev/null http://localhost:8080/ || exit 1
