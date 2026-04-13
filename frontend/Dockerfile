FROM node:20-alpine AS builder

WORKDIR /app

COPY package*.json ./
RUN npm install

COPY . .

RUN npm run build

FROM busybox:stable-musl

COPY --from=builder /app/dist /app/dist

CMD ["sh", "-c", "cp -r /app/dist/. /dist/ && sleep infinity"]
