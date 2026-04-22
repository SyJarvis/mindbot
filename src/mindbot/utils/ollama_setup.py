"""Ollama auto-installation and setup utility."""

from __future__ import annotations

import platform
import subprocess
import time
from typing import Callable


class OllamaSetup:
    """Handles Ollama installation, model downloading and service management."""

    DEFAULT_MODEL = "qwen3:2b"
    OLLAMA_API_URL = "http://localhost:11434"

    # Recommended models with approximate sizes
    RECOMMENDED_MODELS = [
        {"name": "qwen3:2b", "size": "~1.2GB", "description": "轻量快速，推荐新用户"},
        {"name": "qwen3:8b", "size": "~4.7GB", "description": "更强推理能力"},
        {"name": "llama3:8b", "size": "~4.7GB", "description": "Meta经典模型"},
        {"name": "gemma3:4b", "size": "~2.5GB", "description": "Google轻量模型"},
    ]

    def __init__(self, progress_callback: Callable[[str], None] | None = None):
        """Initialize OllamaSetup.

        Args:
            progress_callback: Optional callback to report progress messages.
        """
        self.progress = progress_callback or print

    def is_installed(self) -> bool:
        """Check if Ollama command is available."""
        try:
            subprocess.run(
                ["ollama", "--version"],
                capture_output=True,
                check=True,
            )
            return True
        except (subprocess.CalledProcessError, FileNotFoundError):
            return False

    def is_running(self) -> bool:
        """Check if Ollama service is running."""
        try:
            import httpx
            response = httpx.get(f"{self.OLLAMA_API_URL}/api/tags", timeout=5.0)
            return response.status_code == 200
        except Exception:
            return False

    def install(self) -> bool:
        """Install Ollama based on the current platform.

        Returns:
            True if installation succeeded or was cancelled by user.
        """
        system = platform.system()

        if system == "Darwin":
            return self._install_macos()
        elif system == "Linux":
            return self._install_linux()
        elif system == "Windows":
            return self._install_windows()
        else:
            self.progress(f"Unsupported platform: {system}")
            return False

    def _install_macos(self) -> bool:
        """Install Ollama on macOS using Homebrew or official installer."""
        self.progress("Installing Ollama on macOS...")

        # Try Homebrew first
        try:
            subprocess.run(["brew", "--version"], capture_output=True, check=True)
            self.progress("Using Homebrew to install Ollama...")
            result = subprocess.run(
                ["brew", "install", "ollama"],
                capture_output=False,
            )
            if result.returncode == 0:
                self.progress("Ollama installed successfully via Homebrew")
                return True
        except (subprocess.CalledProcessError, FileNotFoundError):
            pass

        # Fall back to official installer
        self.progress("Downloading Ollama from official site...")
        self.progress("Please download and install Ollama from: https://ollama.com/download")
        return False

    def _install_linux(self) -> bool:
        """Install Ollama on Linux using the official install script."""
        self.progress("Installing Ollama on Linux...")

        try:
            # Use official install script
            result = subprocess.run(
                ["curl", "-fsSL", "https://ollama.com/install.sh"],
                capture_output=True,
                text=True,
            )
            if result.returncode != 0:
                self.progress("Failed to download Ollama installer")
                return False

            # Run the installer script
            install_result = subprocess.run(
                ["sh"],
                input=result.stdout,
                capture_output=False,
            )
            if install_result.returncode == 0:
                self.progress("Ollama installed successfully")
                return True
            else:
                self.progress("Ollama installation failed")
                return False
        except Exception as e:
            self.progress(f"Installation error: {e}")
            return False

    def _install_windows(self) -> bool:
        """Install Ollama on Windows."""
        self.progress("Installing Ollama on Windows...")
        self.progress("Please download and install Ollama from: https://ollama.com/download")
        return False

    def start_service(self) -> bool:
        """Start Ollama service."""
        self.progress("Starting Ollama service...")

        try:
            # Start ollama in background
            subprocess.Popen(
                ["ollama", "serve"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )

            # Wait for service to be ready
            for _ in range(30):  # Wait up to 30 seconds
                if self.is_running():
                    self.progress("Ollama service is running")
                    return True
                time.sleep(1)

            self.progress("Timeout waiting for Ollama service")
            return False
        except Exception as e:
            self.progress(f"Failed to start Ollama service: {e}")
            return False

    def list_local_models(self) -> list[dict]:
        """Get list of locally available ollama models with details.

        Returns:
            List of dicts with model name, size, and modified time.
        """
        try:
            result = subprocess.run(
                ["ollama", "list"],
                capture_output=True,
                text=True,
                check=True,
            )
            lines = result.stdout.strip().split("\n")
            if len(lines) <= 1:
                return []

            # Parse header and data rows
            # Format: NAME    ID    SIZE    MODIFIED
            models = []
            for line in lines[1:]:
                if not line.strip():
                    continue
                parts = line.split()
                if len(parts) >= 3:
                    models.append({
                        "name": parts[0],
                        "size": parts[2] if len(parts) >= 3 else "unknown",
                        "modified": parts[3] if len(parts) >= 4 else "",
                    })
            return models
        except subprocess.CalledProcessError:
            return []

    def is_model_downloaded(self, model: str) -> bool:
        """Check if a model is already downloaded."""
        try:
            result = subprocess.run(
                ["ollama", "list"],
                capture_output=True,
                text=True,
                check=True,
            )
            return model in result.stdout
        except subprocess.CalledProcessError:
            return False

    def pull_model(self, model: str) -> bool:
        """Download a model using ollama pull."""
        self.progress(f"Downloading model {model}...")

        try:
            result = subprocess.run(
                ["ollama", "pull", model],
                capture_output=False,
            )
            if result.returncode == 0:
                self.progress(f"Model {model} downloaded successfully")
                return True
            else:
                self.progress(f"Failed to download model {model}")
                return False
        except Exception as e:
            self.progress(f"Error downloading model: {e}")
            return False

    def setup(self) -> bool:
        """Complete setup: install Ollama, start service, and download default model.

        Returns:
            True if setup completed successfully.
        """
        # Check if already installed and running with model
        if self.is_installed():
            self.progress("Ollama is already installed")

            if not self.is_running():
                self.progress("Ollama service is not running, starting it...")
                if not self.start_service():
                    return False
            else:
                self.progress("Ollama service is already running")

            if self.is_model_downloaded(self.DEFAULT_MODEL):
                self.progress(f"Model {self.DEFAULT_MODEL} is already downloaded")
            else:
                if not self.pull_model(self.DEFAULT_MODEL):
                    return False

            return True

        # Need to install
        self.progress("Ollama not found, installing...")
        if not self.install():
            return False

        # Start service
        if not self.start_service():
            return False

        # Download default model
        if not self.pull_model(self.DEFAULT_MODEL):
            return False

        return True


def setup_ollama(progress_callback: Callable[[str], None] | None = None) -> bool:
    """Convenience function to set up Ollama.

    Args:
        progress_callback: Optional callback to receive progress messages.

    Returns:
        True if setup was successful.
    """
    setup = OllamaSetup(progress_callback=progress_callback)
    return setup.setup()
