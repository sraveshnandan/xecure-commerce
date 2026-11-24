FROM node:22-alpine
WORKDIR /app
COPY packages/node-sdk ./packages/node-sdk
COPY services/checkout-service ./services/checkout-service
WORKDIR /app/services/checkout-service
EXPOSE 5001
CMD ["node", "src/server.mjs"]
