# Apify Actor image (publish-time). The MCP server needs no container.
FROM apify/actor-python:3.11
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY . ./
# stdlib-only service layer; apify SDK + tzdata installed above.
CMD ["python3", "actor_main.py"]
