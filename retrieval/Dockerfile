FROM python:3.12-slim@sha256:a0f57064cbdcd6285fa45f51237ab0b35ea8ebaed06a1f5973e89e19dfb86704
ENV PYTHONUNBUFFERED=1 PIP_DISABLE_PIP_VERSION_CHECK=1 OMP_NUM_THREADS=2
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY download_model.py .
RUN python download_model.py
COPY service.py .
RUN useradd --create-home appuser
ENV HF_HUB_OFFLINE=1 HF_HUB_DISABLE_TELEMETRY=1
USER appuser
EXPOSE 8100
CMD ["uvicorn", "service:app", "--host", "0.0.0.0", "--port", "8100"]
