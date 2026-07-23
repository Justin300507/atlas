# --- build stage ---
FROM node:20-alpine AS build
WORKDIR /app

COPY package.json package-lock.json* ./
RUN npm ci

COPY . .

# VITE_API_BASE is a Vite *build-time* env var -- it gets baked into the
# static JS bundle at `npm run build`, not read at container runtime. It
# must be passed as a Docker build ARG (see docker-compose.yml), not a
# plain `docker run -e` environment variable, or it'll silently keep
# whatever value was set at image-build time.
ARG VITE_API_BASE
ENV VITE_API_BASE=$VITE_API_BASE
RUN npm run build

# --- serve stage ---
FROM nginx:alpine
COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80
