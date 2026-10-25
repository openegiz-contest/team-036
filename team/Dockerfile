# One image for the three services of the digital pit: setup (twins), simulator, console (stand).
FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY pit ./pit
COPY console ./console
COPY simulator.py setup_twins.py ./
USER nobody
CMD ["python", "simulator.py"]
