# Use a imagem oficial do Python com Playwright
FROM mcr.microsoft.com/playwright/python:v1.43.0-jammy

# Definir diretório de trabalho
WORKDIR /app

# Copiar requirements e instalar dependências
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copiar código
COPY . .

# Instalar Chromium
RUN playwright install chromium

# Expor porta
EXPOSE 5000

# Variáveis de otimização
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

# Comando para iniciar com Gunicorn otimizado
CMD ["gunicorn", "-w", "8", "-b", "0.0.0.0:5000", "--worker-class=sync", "--worker-connections=1000", "--max-requests=1000", "--max-requests-jitter=50", "--timeout=30", "--access-logfile=-", "--error-logfile=-", "--log-level=warning", "app:app"]
