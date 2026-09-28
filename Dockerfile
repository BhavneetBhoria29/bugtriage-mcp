FROM python:3.11-slim
WORKDIR /app
ENV BUGTRIAGE_DATA=/app/data PORT=8000
COPY pyproject.toml ./
COPY src ./src
RUN pip install --no-cache-dir . && python -m bugtriage_mcp.data
EXPOSE 8000
# streamable HTTP transport; MCP endpoint at http://localhost:8000/mcp
CMD ["python", "-m", "bugtriage_mcp.server", "--http"]
