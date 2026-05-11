FROM python:3.13-slim-bookworm

WORKDIR /app

RUN apt-get update && \
    apt-get upgrade -y && \
    apt-get install -y --no-install-recommends libmagic1 && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

RUN groupadd -g 1000 sharedgroup \
    && useradd -u 1000 -g sharedgroup -m appuser

RUN chown -R appuser:sharedgroup /app

ENV PATH="/home/appuser/.local/bin:${PATH}"

USER appuser

ARG is_development=false
COPY requirements*.txt .

RUN pip install --no-cache-dir -r requirements.txt
RUN if [ "$is_development" = "true" ] ; then pip install --no-cache-dir -r requirements.dev.txt ; fi

COPY . .

# Fix line endings and make entrypoint executable
RUN sed -i 's/\r$//' entrypoint.sh && chmod +x entrypoint.sh

EXPOSE 8000

ENTRYPOINT ["./entrypoint.sh"]
CMD ["gunicorn", "main:app", "-k", "uvicorn.workers.UvicornWorker", "--bind", "0.0.0.0:8000", "--workers", "2", "--max-requests", "100", "--max-requests-jitter", "10"]
