FROM node:20-alpine

WORKDIR /app

COPY frontend/package*.json /app/
RUN if [ -f package.json ]; then npm install; fi

COPY frontend/ /app/

EXPOSE 3000

CMD ["npm", "run", "dev"]
