import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import List, Optional
import requests
import logging
from colorlog import ColoredFormatter
import platform
import zipfile
import tarfile
import logging.handlers

user_path = os.path.expanduser("~")
print(user_path)
if platform.system() == "Windows":
    system_path = "C:\\Program Files"
    system_path_x86 = "C:\\Program Files (x86)"
else:
    system_path = "/Applications"
    system_path_x86 = None


@dataclass
class Package:
    """
    The Package dataclass represents a software package with all the necessary information
    required for installation and uninstallation.
    
    Attributes:
        name (str): The name of the software package.
        version (str): The version of the software package.
        strategy (str): The installation strategy to use (e.g., "vendor_install", "zip_install").
        location (str): The URL from where the package can be downloaded.
        checksum (Optional[str]): The SHA-256 checksum of the package file (if available).
        installer_type (str): The type of the installer (e.g., "exe", "cp").
        install_dependencies (Optional[List[str]]): A list of package names to install as dependencies.
        uninstall_dependencies (Optional[List[str]]): A list of package names to uninstall as dependencies.
        pre_install (Optional[str]): A script to run before the installation.
        install (str): The installation script.
        post_install (Optional[str]): A script to run after the installation.
        pre_uninstall (Optional[str]): A script to run before the uninstallation.
        uninstall (str): The uninstallation script.
        post_uninstall (Optional[str]): A script to run after the uninstallation.
    """

    name: str
    version: str
    strategy: str
    location: str
    checksum: Optional[str]
    installer_type: str
    install_dependencies: Optional[List[str]] = field(default_factory=list)
    uninstall_dependencies: Optional[List[str]] = field(default_factory=list)
    pre_install: Optional[str] = None
    install: str = None
    post_install: Optional[str] = None
    pre_uninstall: Optional[str] = None
    uninstall: str = None
    post_uninstall: Optional[str] = None

def configure_logger(package_name: str) -> logging.Logger:
    """
    Sets up and configures a logger for a given package. The logger will have a file handler to log messages
    to a file and a stream handler to log messages to stdout. The file handler will use a plain format
    while the stream handler will use a colored format.

    Arguments:
        package_name (str): The name of the package for which the logger is being configured.

    Returns:
        logging.Logger: The configured logger object.
    """

    log_format = "%(log_color)s%(levelname)-8s%(reset)s %(message)s"
    log_datefmt = "%Y-%m-%d %H:%M:%S"
    colored_formatter = ColoredFormatter(log_format, datefmt=log_datefmt,
                                  log_colors={"DEBUG": "cyan", "INFO": "green", "WARNING": "yellow",
                                              "ERROR": "red", "CRITICAL": "red,bg_white"})

    plain_formatter = logging.Formatter("%(levelname)-8s %(message)s", datefmt=log_datefmt)

    log_filename = f"{package_name}_{datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}.log"

    file_handler = logging.FileHandler(log_filename)
    file_handler.setFormatter(plain_formatter)

    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setFormatter(colored_formatter)

    logger = logging.getLogger(package_name)
    logger.setLevel(logging.INFO)
    logger.addHandler(file_handler)
    logger.addHandler(stream_handler)

    return logger


def parse_arguments() -> argparse.Namespace:
    """
    Parses command-line arguments for the package manager. It expects the package name and an action
    to be performed (install or uninstall).

    Returns:
        argparse.Namespace: An object containing the parsed arguments.
    """
    parser = argparse.ArgumentParser(description="Cross-platform software package manager")
    parser.add_argument("package_name", help="The name of the package")
    parser.add_argument("action", choices=["install", "uninstall"], help="Action to perform: install or uninstall")
    return parser.parse_args()


def fetch_and_parse_recipe(package_name: str) -> Package:
    """
    Fetches the JSON recipe file for the specified package name from the remote GitHub repository,
    parses the JSON data, and creates a Package object.

    Arguments:
        package_name (str): The name of the package for which the recipe file should be fetched.

    Returns:
        Package: An instance of the Package dataclass containing the parsed recipe data.
    """
    repo_owner = "MuhammadButt1995"
    repo_name = "recipes"
    branch = "master"  # or the branch you want to use
    file_path = f"{package_name}.json"

    url = f"https://raw.githubusercontent.com/{repo_owner}/{repo_name}/{branch}/{file_path}"
    response = requests.get(url)

    if response.status_code != 200:
        raise ValueError(f"Failed to fetch the recipe file for package '{package_name}'")

    recipe_json = response.text
    package_data = json.loads(recipe_json)
    package = Package(**package_data)

    return package

def install_package(package: Package, logger: logging.Logger):
    """
    Installs the specified package by following the installation strategy defined in the Package object.
    Handles installation of package dependencies as well.

    Arguments:
        package (Package): An instance of the Package dataclass containing the parsed recipe data.
        logger (logging.Logger): A logger instance for logging messages during the installation process.

    Raises:
        ValueError: If the installation strategy is not supported.
        Exception: If there is an error during the installation process.
    """
    try:
        # Install dependencies first
        for dependency_name in package.install_dependencies:
            logger.info(f"Installing dependency '{dependency_name}'")
            dependency_package = fetch_and_parse_recipe(dependency_name)
            install_package(dependency_package, logger)

        logger.info(f"Installing package '{package.name}'")
        if package.strategy == "vendor_install":
            vendor_install(package, logger)
        elif package.strategy == "zip_install":
            zip_install(package, logger)
        else:
            raise ValueError(f"Unsupported installation strategy '{package.strategy}'")
        
        logger.info(f"Installation of '{package.name}' completed successfully")

    except Exception as e:
        logger.error(f"Installation of '{package.name}' failed: {str(e)}")
        raise


def download_and_verify_package(package, logger) -> str:
    """
    Downloads the package from the specified location, verifies the checksum (if provided),
    and extracts the package if it's a zip or tar.gz file.

    Arguments:
        package (Package): An instance of the Package dataclass containing the parsed recipe data.
        logger (logging.Logger): A logger instance for logging messages during the download and verification process.

    Returns:
        str: The path to the downloaded package file or the extracted directory.

    Raises:
        ValueError: If the checksum provided doesn't match the calculated checksum of the downloaded file.
    """
    with tempfile.NamedTemporaryFile(delete=False) as temp_file:
        # Download the package
        logger.info(f"Downloading package '{package.name}'")
        response = requests.get(package.location, stream=True)
        response.raise_for_status()

        # Save the package to a temporary file
        for chunk in response.iter_content(chunk_size=8192):
            temp_file.write(chunk)

        # Close the temporary file
        temp_file.close()

        # Verify the checksum if provided
        if package.checksum:
            logger.info(f"Verifying checksum for package '{package.name}'")
            with open(temp_file.name, 'rb') as file:
                file_hash = hashlib.sha256(file.read()).hexdigest()

            if file_hash != package.checksum.lower():
                os.remove(temp_file.name)
                raise ValueError(f"Checksum mismatch for package '{package.name}'")

        # Extract the package if it's a zip or tar.gz file
        extracted_dir = None
        if temp_file.name.endswith('.zip'):
            extracted_dir = os.path.splitext(temp_file.name)[0]
            with zipfile.ZipFile(temp_file.name, 'r') as zip_ref:
                zip_ref.extractall(extracted_dir)
            os.remove(temp_file.name)
        elif temp_file.name.endswith('.tar.gz'):
            extracted_dir = os.path.splitext(os.path.splitext(temp_file.name)[0])[0]
            with tarfile.open(temp_file.name, 'r:gz') as tar_ref:
                tar_ref.extractall(extracted_dir)
            os.remove(temp_file.name)

        if extracted_dir:
            return extracted_dir
        else:
            return temp_file.name


def run_script(script: str, logger: logging.Logger, **format_args)  -> None:
    """
    Runs a given script as a temporary shell script or PowerShell script, depending on the platform.

    Arguments:
        script (str): The script to be executed, either as a shell script or PowerShell script.
        logger (logging.Logger): A logger instance for logging messages during the execution process.
        **format_args: Keyword arguments to be passed to the script.format() method, for replacing placeholders in the script.

    Raises:
        subprocess.CalledProcessError: If the script execution fails.
    """
    is_windows = platform.system() == "Windows"
    script_name = "script.ps1" if is_windows else "script.sh"

    with tempfile.NamedTemporaryFile(mode="w", prefix="pkg_manager_", suffix=script_name, delete=False) as script_file:
        script_file.write(script.format(**format_args))
        script_file.flush()
        script_file.seek(0)

    try:
        if is_windows:
            result = subprocess.run(["powershell", "-ExecutionPolicy", "Unrestricted", "-File", script_file.name], check=True)
            logger.debug(result.stdout)
        else:
            result = subprocess.run(["bash", script_file.name], check=True)
            logger.debug(result.stdout)
    
    except subprocess.CalledProcessError as e:
        logger.error(e.stderr)
        raise

    os.remove(script_file.name)



def vendor_install(package: Package, logger: logging.Logger) -> None:
    """
    Installs a software package using the vendor_install strategy, which downloads and runs the installer provided by the vendor.

    Arguments:
        package (Package): A Package instance containing the package information and installation instructions.
        logger (logging.Logger): A logger instance for logging messages during the installation process.

    Raises:
        ValueError: If the checksum of the downloaded package does not match the expected checksum.
        subprocess.CalledProcessError: If the script execution fails during the installation process.
    """
    package_file = download_and_verify_package(package, logger)
    format_args = {
        'package_file': package_file,
        'user_path': user_path,
        'system_path': system_path,
        'system_path_x86': system_path_x86
    }
    if package.pre_install:
        logger.info("Running pre-install script")
        run_script(package.pre_install.format(**format_args), logger, **format_args)
    if package.install:
        logger.info("Running install script")
        run_script(package.install.format(**format_args), logger, **format_args)
    if package.post_install:
        logger.info("Running post-install script")
        run_script(package.post_install.format(**format_args), logger, **format_args)
    if os.path.isdir(package_file):
        shutil.rmtree(package_file)
    else:
        os.remove(package_file)

def find_binary_file(root_dir) -> Optional[str]:
    """
    Recursively searches for a binary file with one of the specified extensions (.exe, .msi, .dmg, .pkg)
    starting from the root directory.

    Arguments:
        root_dir (str): The root directory to start the search from.

    Returns:
        Optional[str]: The path to the binary file if found, otherwise None.
    """
    extensions = ['.exe', '.msi', '.dmg', '.pkg']
    for root, dirs, files in os.walk(root_dir):
        for file in files:
            if os.path.splitext(file)[-1].lower() in extensions:
                return os.path.join(root, file)
    return None

def extract_package(package_file: str, extract_dir: str) -> None:
    """
    Extracts the given package archive file into the specified directory.
    Supports .zip, .tar, .tar.gz, .tar.bz2, and .tar.xz archive formats.

    Arguments:
        package_file (str): The path to the package archive file.
        extract_dir (str): The directory to extract the contents of the package file into.
    """
    shutil.unpack_archive(package_file, extract_dir)
        

def zip_install(package: Package, logger: logging.Logger) -> None:
    """
    Installs a software package using the zip_install strategy.
    The package is expected to be in a .zip archive. The function extracts the archive,
    finds the binary installer file, and runs the pre-install, install, and post-install scripts.

    Arguments:
        package (Package): The Package object containing the package information.
        logger (logging.Logger): The logger object for logging events during the installation process.
    """
    # Extract the package zip file to a temporary directory
    with tempfile.TemporaryDirectory() as temp_dir:
        extract_package(package.location, temp_dir)

        # Find the binary installer file
        package_file = find_binary_file(temp_dir)

        if not package_file:
            raise ValueError(f"Installer file not found in '{package.location}'")

        # Run pre-install, install, and post-install scripts
        format_args = {
            'package_file': package_file,
            'user_path': user_path,
            'system_path': system_path,
            'system_path_x86': system_path_x86
        }

        if package.pre_install:
            logger.info("Running pre-install script")
            run_script(package.pre_install.format(**format_args), logger, **format_args)
        if package.install:
            logger.info("Running install script")
            run_script(package.install.format(**format_args), logger, **format_args)
        if package.post_install:
            logger.info("Running post-install script")
            run_script(package.post_install.format(**format_args), logger, **format_args)
    
def main() -> None:
    """
    The entry point of the script. This function parses the command-line arguments, fetches the
    recipe for the specified package, configures the logger, and performs the install or uninstall
    action as requested.
    """
    args = parse_arguments()
    package_name, action = args.package_name, args.action
    package = fetch_and_parse_recipe(package_name)

    logger = configure_logger(package_name)

    if action == "install":
        install_package(package, logger)
    elif action == "uninstall":
        # Add logic to handle uninstallation here
        pass
    else:
        raise ValueError("Unsupported action")

if __name__ == "__main__":
    main()