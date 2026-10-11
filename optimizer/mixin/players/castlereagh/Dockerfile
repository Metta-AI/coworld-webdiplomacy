# The starter policy (package `castlereagh`). Build with tools/build.sh (it builds the base first).
# The base is coworld-webdiplomacy's player image: Python 3.12 in /opt/.venv, uv, and the
# launcher as ENTRYPOINT. CMD below is the launcher's child command.
ARG BASE_IMAGE=coworld-webdiplomacy-player:latest
FROM ${BASE_IMAGE}
# The press layer's agent harness (talks only to the Coworld LLM sidecar). Pinned so the image
# is reproducible and matches the test command. The search path needs only the stdlib.
RUN uv pip install --python /opt/.venv/bin/python --no-cache "pydantic-ai-slim[openai]==2.54.0"
COPY castlereagh /opt/castlereagh
WORKDIR /opt
# Fail the build if either mode cannot import in the actual runtime.
RUN /opt/.venv/bin/python -c "import castlereagh.bot, castlereagh.press.player, pydantic_ai, httpx2"
ARG POLICY=press
# Config overrides for one-knob experiments (tools/build.sh --overrides); empty = defaults.
ARG OVERRIDES=""
ENV CASTLEREAGH_POLICY=${POLICY} \
    CASTLEREAGH_OVERRIDES=${OVERRIDES} \
    PYDANTIC_AI_NO_BANNER=1 \
    PYTHONDONTWRITEBYTECODE=1
CMD ["/opt/.venv/bin/python", "-m", "castlereagh"]
