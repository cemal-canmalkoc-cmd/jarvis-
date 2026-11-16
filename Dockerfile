FROM python:3.13-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY jarvis ./jarvis
ENV JARVIS_HOME=/data PYTHONUNBUFFERED=1
VOLUME /data
EXPOSE 8000
CMD ["python", "-m", "jarvis", "serve"]
