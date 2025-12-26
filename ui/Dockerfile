# Build stage
FROM node:20-alpine AS build
WORKDIR /app
COPY ui/package*.json ./
RUN npm ci
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
