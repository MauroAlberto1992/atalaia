# Mini-COP frontend: built with Node, served by nginx (no Node at runtime).

# --- build stage ---
FROM node:22-alpine AS build
WORKDIR /app
# Lockfile first: `npm ci` is cached until dependencies change.
COPY package.json package-lock.json .npmrc ./
RUN npm ci
COPY . .
RUN npm run build

# --- runtime stage ---
FROM nginx:1.28-alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
