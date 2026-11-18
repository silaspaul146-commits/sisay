"""Worker process entrypoint: `python -m app.worker`. Same codebase as the API, separate process."""
from app.core.logging import configure_logging
from app.infrastructure.workers.runner import Worker

if __name__ == "__main__":
    configure_logging()
    Worker().run_forever()
