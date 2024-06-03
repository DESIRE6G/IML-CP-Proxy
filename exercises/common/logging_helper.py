import logging


def configure_logger_with_common_settings(log_filename: str) -> None:
    logging.basicConfig(
        level=logging.DEBUG,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[
            logging.FileHandler(f"logs/{log_filename}"), logging.StreamHandler()
        ]
    )
