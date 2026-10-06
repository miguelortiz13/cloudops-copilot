# syntax=docker/dockerfile:1
FROM node:22-alpine AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY . .
# Las variables VITE_* se resuelven en tiempo de compilacion.
ARG VITE_API_URL=http://localhost:8000
ARG VITE_USER_DISPLAY_NAME=Operador
ENV VITE_API_URL=$VITE_API_URL VITE_USER_DISPLAY_NAME=$VITE_USER_DISPLAY_NAME
RUN npm run build

FROM nginx:1.27-alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
