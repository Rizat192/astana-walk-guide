FROM python:3.12-slim
WORKDIR /app
COPY mcp_server/requirements.txt mcp_server/requirements.txt
RUN pip install --no-cache-dir -r mcp_server/requirements.txt
COPY mcp_server mcp_server
COPY data data
ENV HOST=0.0.0.0 PORT=8080
CMD ["python", "mcp_server/server.py"]
