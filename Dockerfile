# Sahayak — full stack (backend + Paytm-clone app + dashboard + visualizer)
FROM python:3.10-slim
WORKDIR /app
RUN pip install --no-cache-dir fastapi 'uvicorn[standard]' qrcode google-genai
COPY backend ./backend
COPY ui ./ui
COPY sandbox ./sandbox

# Cloud-scale dataset baked at build (seeded, deterministic).
# Local dev uses the full 500K DB; the container generates a representative
# slice to keep image size and build time sane.
RUN mkdir -p /app/data
ENV SAHAYAK_DB=/app/data/sahayak.db \
    SAHAYAK_GEMINI_MODEL=gemini-2.5-flash
RUN python3 sandbox/seed500k.py $SAHAYAK_DB --users 120000 --per-user 8 \
 && python3 backend/profiles.py

EXPOSE 8080
CMD ["python3", "-m", "uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8080", "--app-dir", "backend"]
