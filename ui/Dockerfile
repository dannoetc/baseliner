# Baseliner UI (static SPA served by nginx)

FROM node:20-alpine AS build
WORKDIR /app

COPY ui/package.json ui/package-lock.json* ./
RUN npm install

COPY ui/ ./
RUN npm run build

FROM nginx:1.27-alpine

COPY ui/nginx/default.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html

# Runtime config injection + start nginx
COPY ui/docker-entrypoint.sh /usr/local/bin/baseliner-ui-entrypoint
EXPOSE 8080
ENTRYPOINT ["/usr/local/bin/baseliner-ui-entrypoint"]
