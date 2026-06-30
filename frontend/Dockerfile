FROM node:18-alpine

WORKDIR /app

COPY package*.json ./

RUN npm install

COPY . .

EXPOSE 5173

# Vite runs on 5173, --host exposes it outside the container
CMD ["npm", "run", "dev", "--", "--host"]
