import os
import sys
import psutil
import win32api
import boto3
import logging
from time import sleep

from config import config

"""
Due to Session 0 isolation, program is unable to be run automatically using
Task Scheduler and still get user input information using
win32api.GetLastInputInfo.  There are no issues when running manually.
"""


class Idle_Usage_Checker:
    def __init__(self, **kwargs) -> None:
        """Set instance constants and logger object."""

        def logger_setup() -> logging.Logger:
            """Create and configure logger object."""

            logger = logging.getLogger(__name__)

            if self.debug:
                level = logging.DEBUG
            else:
                level = logging.INFO

            logger.setLevel(level)

            formatter = logging.Formatter(
                "%(asctime)s:%(levelname)s:%(name)s:%(message)s"
            )
            file_handler = logging.FileHandler("idle_usage_checker_logs.log")
            file_handler.setFormatter(formatter)

            logger.addHandler(file_handler)

            if self.debug:
                stream_handler = logging.StreamHandler()
                stream_handler.setFormatter(formatter)
                logger.addHandler(stream_handler)

            return logger

        self.debug = kwargs.get("debug")
        self.logger = logger_setup()
        self.last_action = win32api.GetLastInputInfo()

        if self.debug:
            # Set some constant values for debugging purposes

            config["RUNNING_DURATION"] = 30
            config["SLEEP_MODE_LENGTH"] = 5
            config["CPU_THRESHOLD"] = 10
            config["RESOURCE_CHECK_INTERVAL"] = 1
            config["PRESENCE_WAIT_TIME"] = 1
            config["PRESENCE_CHECK_COUNT"] = 3

        self.logger.info("**********")
        self.logger.info("Initial setup complete.")

    def begin(self) -> None:
        """Main loop for usage checking."""

        def sleep_mode() -> None:
            """Start idle state after activity detection / resource check."""

            self.logger.info(
                f"Entering sleep mode... "
                f"({config['SLEEP_MODE_LENGTH']/60} minutes)"
            )
            config["ELAPSED_TIME"] += config["SLEEP_MODE_LENGTH"]
            sleep(config["SLEEP_MODE_LENGTH"])

        if self.debug:
            self.logger.info("***** Debugging Mode *****")

        self.logger.info("Beginning main loop.")
        total_passed_resource_checks = 0

        while config["ELAPSED_TIME"] <= config["RUNNING_DURATION"]:
            self.logger.info("Checking for user presence...")

            if not self.presence():
                # Checks if user is present
                if self.resource_utilization():
                    # Checks resource utilization
                    self.send_notification()
                    # If resources are being utilized and user is not present,
                    # AWS SNS sends a notification email and ends the loop
                else:
                    total_passed_resource_checks += 1

                    if (
                        total_passed_resource_checks
                        >= config["MAX_PASSED_CHECKS"]
                    ):
                        self.close_program(
                            message=(
                                "Total passed resource checks have "
                                "reached allowed maximum."
                            )
                        )
                    sleep_mode()
            else:
                total_passed_resource_checks = 0
                # Resets num of passed resorce checks if presence is detected
                sleep_mode()

        self.close_program(message="Maximum running duration reached.")

    def close_program(self, message: str = "") -> None:
        """Log closing messages and exit program."""

        if message:
            self.logger.info(message)
        self.logger.info("Closing program...")
        sys.exit()

    def update_resources(self) -> None:
        """Get most recent resource levels."""

        self.cpu, self.memory = (
            psutil.cpu_percent(interval=0.6),
            psutil.virtual_memory().percent,
        )
        self.logger.debug(
            f"CPU usage is at {self.cpu}% and "
            f"memory usage is at {self.memory}%."
        )

    def resource_utilization(self) -> bool:
        """Check for resource utilization."""

        resource_counter = 0
        total_checks = 0
        self.logger.info("Starting resource checks...")

        while (
            resource_counter < config["RESOURCE_CHECKS"]
            and resource_counter > -config["RESOURCE_CHECKS"]
            and total_checks < config["MAX_RESOURCE_CHECKS"]
        ):

            sleep(config["RESOURCE_CHECK_INTERVAL"])
            self.update_resources()

            if (
                self.cpu >= config["CPU_THRESHOLD"]
                or self.memory >= config["MEMORY_THRESHOLD"]
            ):
                verb = "are"
                resource_counter += 1
                total_checks += 1

            else:
                verb = "are not"
                resource_counter -= 1
                total_checks += 1

            self.logger.debug(
                f"Resources {verb} being heavily utilized. "
                "(Allowed CPU usage: "
                f"{config['CPU_THRESHOLD']}%, "
                "Allowed RAM usage: "
                f"{config['MEMORY_THRESHOLD']}"
                "%)"
            )

        total_checks_msg = f"(Total number of checks: {total_checks})"

        if resource_counter >= config["RESOURCE_CHECKS"]:
            # Case of heavy resource usage

            self.logger.warning(
                "Computer has failed resource checks. " f"{total_checks_msg}"
            )
            return True

        elif resource_counter <= -config["RESOURCE_CHECKS"]:
            # Case of light resource usage

            self.logger.info(
                "Computer has passed resource checks. " f"{total_checks_msg}"
            )
            return False

        elif total_checks >= config["MAX_RESOURCE_CHECKS"]:
            # Total number of checks exceeded

            self.logger.warning(
                "Computer has reached maximum number of allowed checks. "
                f"{total_checks_msg}"
            )
            return False

        else:
            # Other error catcher

            self.logger.error(
                "An unknown error has occured in resource checks. "
                f"{total_checks_msg}"
            )
            return False

    def presence(self) -> bool:
        """Check for user presence."""

        for _ in range(config["PRESENCE_CHECK_COUNT"]):

            new_action = win32api.GetLastInputInfo()
            if new_action != self.last_action:
                self.logger.info("Activity detected.")
                self.last_action = new_action
                return True
            sleep(config["PRESENCE_WAIT_TIME"])

        self.logger.info("User does not seem to be present.")
        return False

    def send_notification(self) -> None:
        """Send computer usage notification via AWS SNS."""

        self.logger.info("Sending notification via AWS SNS...")

        if not self.debug:
            client = boto3.client(
                "sns",
                aws_access_key_id=os.environ.get("AWS-Python-Access-Key-ID"),
                aws_secret_access_key=os.environ.get(
                    "AWS-Python-Secret-Access-Key"
                ),
                region_name=os.environ.get("AWS-Region"),
            )

            client.publish(
                TopicArn=os.environ.get("AWS-Python-Idle-Checker-TopicArn"),
                Message=(
                    f"Your CPU usage was recorded at {self.cpu}% "
                    f"and your RAM usage was recorded at {self.memory}%. "
                    "Allowed maximums: "
                    f"CPU: {config['CPU_THRESHOLD']}% RAM: {config['MEMORY_THRESHOLD']}%"
                    " Did you leave a task running?"
                ),
                Subject="Idle Checker Notification",
            )

        self.close_program(message="Notification has been sent.")


def main() -> None:
    """Start application."""

    def cmd_line_arg_handler() -> dict:
        """Handle command line arguments."""

        opts = [opt for opt in sys.argv[1:] if opt.startswith("-")]

        cmd_line_args = {"debug": False}

        if opts:

            if "-h" in opts or "--help" in opts:
                print(
                    "'Idle Usage Checker' by Jason Tarka\n"
                    "Accepted command line arguments:\n"
                    '"-d" - Enter debugging mode\n'
                    '"-v" - Display version information'
                )
                sys.exit()

            if "-v" in opts or "--version" in opts:
                print(
                    "Application version: 1.0.0\n"
                    f"Python version: {sys.version}"
                )
                sys.exit()

            if "-d" in opts or "--debug" in opts:
                cmd_line_args["debug"] = True

        return cmd_line_args

    debug = cmd_line_arg_handler().get("debug")

    checker = Idle_Usage_Checker(debug=debug)
    checker.begin()


if __name__ == "__main__":
    main()
