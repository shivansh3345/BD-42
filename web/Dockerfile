# BD-42 web UI — Vite dev server
FROM node:22-alpine

WORKDIR /app

# Install deps first for layer caching
COPY package.json package-lock.json* ./
RUN npm install

# Application code (see .dockerignore for what's excluded)
COPY . .

EXPOSE 5174

# --host makes Vite bind 0.0.0.0 so it's reachable from outside the container
CMD ["npm", "run", "dev", "--", "--host"]
