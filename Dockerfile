FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app
COPY static ./static
ENV PORT=7860
EXPOSE 7860
CMD ["sh", "-c", "uvicorn app.server.app:app --host 0.0.0.0 --port ${PORT} --ws-ping-interval 20"]
