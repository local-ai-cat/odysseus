"""
chroma_client.py

Singleton ChromaDB client with dual transport.

When CHROMADB_HOST is set, connects over HTTP to a standalone ChromaDB
service (e.g. `docker compose up chromadb`). Otherwise it falls back to an
embedded, in-process PersistentClient that writes the vector store to disk —
no server, no Docker, fully self-contained.
"""

import os
import socket
import logging

logger = logging.getLogger(__name__)

_client = None

# A short connect probe so an unreachable ChromaDB fails fast instead of
# blocking on the OS connection timeout (~30-60s, WinError 10060 on Windows),
# which otherwise stalls app startup. Tunable via CHROMADB_CONNECT_TIMEOUT.
_CONNECT_TIMEOUT = float(os.getenv("CHROMADB_CONNECT_TIMEOUT", "2.0"))


def _port_open(host: str, port: int, timeout: float = None) -> bool:
    """Return True if a TCP connection to host:port succeeds within timeout."""
    try:
        with socket.create_connection((host, port), timeout=timeout or _CONNECT_TIMEOUT):
            return True
    except OSError:
        return False


def get_chroma_client():
    """Get or create the singleton ChromaDB HTTP client.

    Raises RuntimeError with a clear install hint if the `chromadb` package
    is not installed — it's an optional dependency (RAG + memory vectors).
    """
    global _client
    if _client is not None:
        return _client
    try:
        import chromadb
    except ImportError as e:
        raise RuntimeError(
            "ChromaDB integration is not installed. Install it with: pip install chromadb"
        ) from e

    host = os.getenv("CHROMADB_HOST")
    if host:
        port = int(os.getenv("CHROMADB_PORT", "8100"))
        if not _port_open(host, port):
            raise RuntimeError(
                f"ChromaDB is not reachable at {host}:{port}. Start the service "
                f"(e.g. `docker compose up chromadb`) or unset CHROMADB_HOST to use "
                f"the built-in in-process store."
            )
        client = chromadb.HttpClient(host=host, port=port)
        client.heartbeat()
        _client = client
        logger.info(f"ChromaDB connected (server): {host}:{port}")
        return _client

    # Embedded, in-process, self-contained — persisted to disk, no server.
    path = os.getenv("CHROMADB_PATH") or os.path.join("data", "chroma")
    os.makedirs(path, exist_ok=True)
    client = chromadb.PersistentClient(path=path)
    _client = client
    logger.info(f"ChromaDB connected (embedded): {path}")
    return _client


def reset_client():
    """Reset the singleton (e.g. after config change)."""
    global _client
    _client = None
