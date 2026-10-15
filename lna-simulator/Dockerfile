# Būvē no repozitorija saknes:  docker build -f lna-simulator/Dockerfile -t pac/lna-simulator .
FROM python:3.12-slim
RUN pip install --no-cache-dir fastapi==0.115.6 "uvicorn[standard]==0.34.0" lxml==5.3.0 PyYAML==6.0.2 boto3==1.35.90 python-multipart==0.0.20
WORKDIR /app
COPY lna-simulator/lna_simulator.py .
COPY src/opendms/archive/schemas/arhivesana-v1.xsd .
COPY src/opendms/archive/lna/validator.py lna/validator.py
COPY src/opendms/archive/lna/shemas lna/shemas
COPY src/opendms/archive/lna/profili lna/profili
ENV LNA_DATA=/data LNA_REVIEW=auto LNA_S3_BUCKET=lna-ievade
EXPOSE 8710
CMD ["uvicorn", "lna_simulator:app", "--host", "0.0.0.0", "--port", "8710"]
