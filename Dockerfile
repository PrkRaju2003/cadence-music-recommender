FROM python:3.13-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && useradd --create-home --uid 10001 cadence
COPY cadence ./cadence
COPY sql ./sql
RUN mkdir -p /app/data && chown -R cadence:cadence /app
USER cadence
ENV PORT=8000
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=45s \
    CMD python -c "import os,urllib.request; urllib.request.urlopen('http://127.0.0.1:'+os.getenv('PORT','8000')+'/api/health',timeout=3)"
CMD ["sh", "-c", "python -m cadence.seed && exec uvicorn cadence.api:app --host 0.0.0.0 --port ${PORT:-8000}"]
