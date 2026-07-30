from config_layers import resolve_config


defaults = {"model": "base", "timeout": 30, "verbose": False}
file_values = {"model": "file", "timeout": 60}
environment_values = {"model": "env", "timeout": None}
cli_values = {"model": None, "verbose": True}
snapshots = [dict(layer) for layer in (defaults, file_values, environment_values, cli_values)]

assert resolve_config(defaults, file_values, environment_values, cli_values) == {
    "model": "env",
    "timeout": 60,
    "verbose": True,
}
assert snapshots == [defaults, file_values, environment_values, cli_values]
