FROM python:3.12-slim
RUN pip install --no-cache-dir paho-mqtt
WORKDIR /app
COPY deploy/ess_mqtt_bridge.py .
CMD ["python3", "-u", "ess_mqtt_bridge.py"]
