# Build stage
FROM node:20-alpine AS build
WORKDIR /app

# Copy manifests first for better layer caching
COPY ui/package*.json ./

# Use npm ci when a lockfile exists; otherwise fall back to npm install
RUN if [ -f package-lock.json ]; then npm ci; else npm install; fi

COPY ui/ ./
RUN npm run build

# Runtime stage
FROM nginx:1.27-alpine

# SPA routing
COPY ui/docker/nginx.conf /etc/nginx/conf.d/default.conf

# Entrypoint to inject runtime config (API base URL)
COPY ui/docker/baseliner-ui-entrypoint /usr/local/bin/baseliner-ui-entrypoint
RUN chmod +x /usr/local/bin/baseliner-ui-entrypoint

COPY --from=build /app/dist /usr/share/nginx/html

EXPOSE 8080
ENTRYPOINT ["/usr/local/bin/baseliner-ui-entrypoint"]
CMD ["nginx", "-g", "daemon off;"]
