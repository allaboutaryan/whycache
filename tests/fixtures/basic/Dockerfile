FROM python:3.12-slim

WORKDIR /app

# Slow step. Everything below a cache miss here re-runs.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# The trap: copies the whole context, including .git if not ignored.
COPY . .

CMD ["python", "src/app.py"]
