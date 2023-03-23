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
import urllib.request
import zipfile
import tarfile
import logging.handlers

user_path = os.path.expanduser("~")
if platform.system() == "Windows":
    system_path = "C:\\Program Files"
    system_path_x86 = "C:\\Program Files (x86)"
else:
    system_path = "/Applications"
    system_path_x86 = None


@dataclass
class Package:
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

def configure_logger(package_name: str):
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


def parse_arguments():
    parser = argparse.ArgumentParser(description="Cross-platform software package manager")
    parser.add_argument("package_name", help="The name of the package")
    parser.add_argument("action", choices=["install", "uninstall"], help="Action to perform: install or uninstall")
    return parser.parse_args()


def fetch_and_parse_recipe(package_name: str) -> Package:
    repo_owner = "MuhammadButt1995"
    repo_name = "recipes"
    branch = "master"  # or the branch you want to use
    file_path = f"{package_name}.json"
    print(file_path)

    url = f"https://raw.githubusercontent.com/{repo_owner}/{repo_name}/{branch}/{file_path}"
    response = requests.get(url)

    if response.status_code != 200:
        raise ValueError(f"Failed to fetch the recipe file for package '{package_name}'")

    recipe_json = response.text
    package_data = json.loads(recipe_json)
    package = Package(**package_data)

    return package

def install_package(package: Package, logger: logging.Logger):
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

def is_zipfile(file_path: str) -> bool:
    return zipfile.is_zipfile(file_path)

def is_tarfile(file_path: str) -> bool:
    return tarfile.is_tarfile(file_path)


def download_and_verify_package(package: Package, logger: logging.Logger) -> str:
    logger.info(f"Downloading package '{package.name}'")
    with tempfile.NamedTemporaryFile(delete=False) as temp_file:
        with urllib.request.urlopen(package.location) as response:
            shutil.copyfileobj(response, temp_file)

        temp_file.flush()
        temp_file.close()

        if package.checksum:
            logger.info("Verifying package checksum")
            with open(temp_file.name, "rb") as f:
                checksum = hashlib.sha256(f.read()).hexdigest()
            if checksum != package.checksum:
                os.remove(temp_file.name)
                raise ValueError("Checksum mismatch for the downloaded package")

        file_ext = os.path.splitext(temp_file.name)[1]
        if file_ext in [".zip", ".tar.gz"]:
            extracted_dir = tempfile.mkdtemp(prefix="pkg_manager_")
            if file_ext == ".zip":
                with zipfile.ZipFile(temp_file.name, "r") as zip_ref:
                    zip_ref.extractall(extracted_dir)
            elif file_ext == ".tar.gz":
                with tarfile.open(temp_file.name, "r:gz") as tar_ref:
                    tar_ref.extractall(extracted_dir)

            os.remove(temp_file.name)
            return extracted_dir

    return temp_file.name

def run_script(script: str, logger: logging.Logger, **format_args):
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

def extract_package(package_file: str, extract_dir: str):
    shutil.unpack_archive(package_file, extract_dir)


def vendor_install(package: Package, logger: logging.Logger):
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

       
        
        

def zip_install(package: Package, logger: logging.Logger):
    package_file = download_and_verify_package(package, logger)
    extract_dir = os.path.join(os.path.dirname(package_file), package.name)
    logger.info(f"Extracting package '{package.name}' to '{extract_dir}'")
    with zipfile.ZipFile(package_file, "r") as zip_ref:
        zip_ref.extractall(extract_dir)

    if package.pre_install:
        logger.info("Running pre-install script")
        run_script(package.pre_install, logger)
    if package.install:
        logger.info("Running install script")
        run_script(package.install.format(package_file=package_file, extract_dir=extract_dir), logger)
    if package.post_install:
        logger.info("Running post-install script")
        run_script(package.post_install, logger)
    shutil.rmtree(package_file)
    
def main():
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