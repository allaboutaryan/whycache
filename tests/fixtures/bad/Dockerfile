FROM python:3.12-slim
WORKDIR /app

# The anti-pattern: whole context copied BEFORE the expensive step, so any
# file change invalidates the install below.
COPY . .
RUN pip install --no-cache-dir -r requirements.txt

CMD ["python", "src/app.py"]
