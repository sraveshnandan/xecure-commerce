FROM eclipse-temurin:17-jre-alpine
WORKDIR /app
COPY packages/java-sdk ./packages/java-sdk
COPY services/inventory-service/bin ./services/inventory-service/bin
EXPOSE 5003
CMD ["java", "-cp", "packages/java-sdk/reliability-sdk-0.2.0.jar:services/inventory-service/bin", "com.commerce.inventory.InventoryApplication"]
