import dotenv
import os
from pathlib import Path

current_dir = Path(__file__).parent.absolute()


# env_file = os.getenv("SCWEET_ENV_FILE", current_dir.parent.joinpath(".env"))
# dotenv.load_dotenv(env_file, verbose=True)


def load_env_variable(key, default_value=None, none_allowed=False):
    v = os.getenv(key, default=default_value)
    if v is None and not none_allowed:
        raise RuntimeError(f"{key} returned {v} but this is not allowed!")
    return v


def get_email(env):
    dotenv.load_dotenv(env, verbose=True)
    return load_env_variable("SCWEET_EMAIL", none_allowed=True)


def get_password(env):
    dotenv.load_dotenv(env, verbose=True)
    return load_env_variable("SCWEET_PASSWORD", none_allowed=True)


def get_username(env):
    dotenv.load_dotenv(env, verbose=True)
    return load_env_variable("SCWEET_USERNAME", none_allowed=True)
