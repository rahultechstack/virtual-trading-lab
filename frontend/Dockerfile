# ---------------------------------------------------------------------------
# React + TypeScript frontend.
#   deps  -> node_modules only
#   dev   -> Vite dev server, source bind-mounted by docker-compose
#   build -> static production bundle
#   prod  -> nginx serving the bundle
# ---------------------------------------------------------------------------
FROM node:20-alpine AS deps

WORKDIR /app
COPY package.json ./
RUN npm install


FROM deps AS dev
ENV CHOKIDAR_USEPOLLING=true
EXPOSE 5173
CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0"]


FROM deps AS build
COPY . .
RUN npm run build


FROM nginx:1.27-alpine AS prod
COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
