FROM node:24-alpine AS build

WORKDIR /app

COPY package*.json ./
RUN npm ci

COPY . .
# Same-origin: o nginx deste container faz proxy de /api para o backend
ENV VITE_API_URL=/api/v1
RUN npm run build

# Tag COM versão. `nginx:alpine` flutuava em cima de qualquer major: hoje
# resolve para 1.31.3, e um nginx 2.x entraria em produção num rebuild sem
# nada no repositório registrando a troca. Com `1.31-alpine` os patches
# continuam vindo sozinhos e a subida de minor/major passa pelo Dependabot.
FROM nginx:1.31-alpine
COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
