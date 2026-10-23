FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt webui/requirements.txt ./webui-requirements.txt
RUN pip install --no-cache-dir -r requirements.txt -r webui-requirements.txt gunicorn==22.0.0

COPY model ./model
COPY webui ./webui

ENV PORT=7070 HF_HOME=/app/.cache/huggingface
EXPOSE 7070
WORKDIR /app/webui

# Single worker: the loaded Kronos model is kept in process memory.
CMD ["sh", "-c", "gunicorn app:app --bind 0.0.0.0:${PORT} --workers 1 --threads 4 --timeout 600"]
