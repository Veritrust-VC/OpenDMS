FROM python:3.12-slim
RUN pip install --no-cache-dir fastapi==0.115.6 "uvicorn[standard]==0.34.0" lxml==5.3.0 PyYAML==6.0.2
WORKDIR /app
COPY div_emulator.py .
ENV DIV_DATA=/data DIV_ADDRESSES=/etc/div/addresses.yaml
EXPOSE 8700
CMD ["uvicorn", "div_emulator:app", "--host", "0.0.0.0", "--port", "8700"]
