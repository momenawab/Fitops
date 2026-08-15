FROM node:24-slim

WORKDIR /app

COPY --chown=node:node frontend/package.json frontend/package-lock.json ./
RUN npm ci

COPY --chown=node:node frontend/ /app/

USER node

EXPOSE 3000

CMD ["npm", "run", "dev", "--", "--hostname", "0.0.0.0"]
