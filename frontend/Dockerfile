# Development image: runs the Vite dev server. Production: Dockerfile.prod (built, served by Caddy).
FROM node:24-slim

WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci

COPY . .
EXPOSE 5173
CMD ["npm", "run", "dev"]
