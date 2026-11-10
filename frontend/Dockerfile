# Development image: runs the Vite dev server. A production (static + Nginx) image comes in M8.
FROM node:24-slim

WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci

COPY . .
EXPOSE 5173
CMD ["npm", "run", "dev"]
