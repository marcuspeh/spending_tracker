import sys

from app.cli.healthcheck import healthcheck


def main():
    if len(sys.argv) < 2:
        print("Usage: python -m app.cli <command>")
        print("Commands: healthcheck")
        sys.exit(1)

    command = sys.argv[1]

    if command == "healthcheck":
        sys.exit(healthcheck())
    else:
        print(f"Unknown command: {command}")
        sys.exit(1)


if __name__ == "__main__":
    main()
