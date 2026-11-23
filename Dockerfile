FROM python:3.12-slim
WORKDIR /app
COPY . .
ENV PORT=3000 DATA_FILE=/app/data/state.json PYTHONUNBUFFERED=1
VOLUME ["/app/data"]
EXPOSE 3000
CMD ["python", "server.py"]
