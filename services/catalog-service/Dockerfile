FROM python:3.11-alpine
WORKDIR /app
COPY packages/python-sdk ./packages/python-sdk
COPY services/catalog-service ./services/catalog-service
WORKDIR /app/services/catalog-service
RUN pip install --no-cache-dir -r requirements.txt
EXPOSE 5002
CMD ["python", "app.py"]
