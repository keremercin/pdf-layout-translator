from pdf_translator.db import init_db


def main() -> None:
    init_db()
    print("Database initialized")


if __name__ == "__main__":
    main()
