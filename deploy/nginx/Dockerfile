FROM nginx:1.27-alpine

# envsubst for templating nginx site config
RUN apk add --no-cache gettext

# We rely on the official nginx entrypoint which runs /docker-entrypoint.d scripts,
# then starts nginx in the foreground.
