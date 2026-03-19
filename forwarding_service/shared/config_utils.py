"""Environment parsing helpers for forwarding service components."""

from __future__ import annotations

import os

PLACEHOLDER_SECRET_VALUE_SET = {
    "change-me",
    "replace-me",
    "replace-with-a-long-random-secret",
    "replace-with-the-same-long-random-secret",
}


def load_bool_env(env_var_name: str, default_value: bool) -> bool:
    """Load a boolean environment variable.

    Args:
        env_var_name (str): Environment variable name.
        default_value (bool): Value used when the variable is absent.

    Returns:
        bool: Parsed boolean value.
    """
    raw_env_value = os.getenv(env_var_name)
    if raw_env_value is None:
        return default_value
    return raw_env_value.strip().lower() in {"1", "true", "yes", "on"}


def load_float_env(env_var_name: str, default_value: float) -> float:
    """Load a float environment variable.

    Args:
        env_var_name (str): Environment variable name.
        default_value (float): Value used when the variable is absent.

    Returns:
        float: Parsed float value.
    """
    raw_env_value = os.getenv(env_var_name)
    if raw_env_value is None or raw_env_value.strip() == "":
        return default_value
    return float(raw_env_value)


def load_int_env(env_var_name: str, default_value: int) -> int:
    """Load an integer environment variable.

    Args:
        env_var_name (str): Environment variable name.
        default_value (int): Value used when the variable is absent.

    Returns:
        int: Parsed integer value.
    """
    raw_env_value = os.getenv(env_var_name)
    if raw_env_value is None or raw_env_value.strip() == "":
        return default_value
    return int(raw_env_value)


def load_required_env(env_var_name: str) -> str:
    """Load a required environment variable.

    Args:
        env_var_name (str): Environment variable name.

    Returns:
        str: Parsed environment variable value.

    Raises:
        ValueError: Raised when the variable is missing or blank.
    """
    raw_env_value = os.getenv(env_var_name)
    if raw_env_value is None or raw_env_value.strip() == "":
        raise ValueError(f"Missing required environment variable: {env_var_name}")
    return raw_env_value


def load_required_secret_env(env_var_name: str) -> str:
    """Load a required secret environment variable.

    Args:
        env_var_name (str): Environment variable name.

    Returns:
        str: Parsed secret value.

    Raises:
        ValueError: Raised when the variable is missing, blank, or still a
            placeholder example value.
    """
    raw_secret_value = load_required_env(env_var_name).strip()
    if raw_secret_value.lower() in PLACEHOLDER_SECRET_VALUE_SET:
        raise ValueError(
            f"{env_var_name} must be set to a non-placeholder secret value"
        )
    return raw_secret_value
