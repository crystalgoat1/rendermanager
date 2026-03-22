# -- Build stage --
FROM node:20-alpine AS build

WORKDIR /app

# Install dependencies first (cache layer)
COPY package.json package-lock.json ./
RUN npm ci

# Copy source and config
COPY index.html tsconfig.json vite.config.ts tailwind.config.cjs postcss.config.cjs ./
COPY src/ ./src/
COPY public/ ./public/

# Vite inlines these at build time
ARG VITE_SUPABASE_URL
ARG VITE_SUPABASE_ANON_KEY

RUN npm run build

# -- Serve stage --
FROM nginx:alpine

COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY nginx.ssl.conf /etc/nginx/nginx.ssl.conf

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]
