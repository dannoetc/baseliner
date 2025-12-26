# Build stage
FROM node:20-alpine AS build
WORKDIR /app
COPY ui/package*.json ./
RUN npm ci
COPY ui/ ./
RUN npm run build

# Runtime stage
FROM nginx:1.27-alpine

# UI runtime config + SPA routing
COPY ui/docker/nginx.conf /etc/nginx/conf.d/default.conf
COPY ui/docker/baseliner-ui-entrypoint /usr/local/bin/baseliner-ui-entrypoint

# Ensure entrypoint is executable (git on Windows can drop +x bit)
RUN chmod +x /usr/local/bin/baseliner-ui-entrypoint

COPY --from=build /app/dist /usr/share/nginx/html

EXPOSE 8080
ENTRYPOINT ["/usr/local/bin/baseliner-ui-entrypoint"]
CMD ["nginx", "-g", "daemon off;"]
