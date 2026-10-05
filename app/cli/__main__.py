import sys

from app.cli.healthcheck import healthcheck
from app.logging_setup import shutdown_logging


def main():
    if len(sys.argv) < 2:
        print("Usage: python -m app.cli <command>")
        print("Commands: healthcheck")
        sys.exit(1)

    command = sys.argv[1]

    try:
        if command == "healthcheck":
            sys.exit(healthcheck())
        else:
            print(f"Unknown command: {command}")
            sys.exit(1)
    finally:
        # Flush the SDK's async queue before the process exits, otherwise
        # the healthcheck event may never reach Kafka.
        shutdown_logging()


if __name__ == "__main__":
    main()
