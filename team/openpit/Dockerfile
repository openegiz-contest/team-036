FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY twins.json setup_twins.py simulator.py scene.py ./
CMD ["python", "simulator.py"]
