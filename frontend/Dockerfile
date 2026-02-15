# dev
FROM node:18-alpine

WORKDIR /app

# Копируем package.json и package-lock.json
COPY package*.json ./

# Устанавливаем зависимости
RUN npm install

# Копируем весь код
COPY . .

# Запускаем Vite dev сервер
CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0"]