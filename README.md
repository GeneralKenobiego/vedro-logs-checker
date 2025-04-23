# vedro-logs-checker

A plugin for the vedro.io testing framework that inspects Docker container logs during test execution and searches for messages based on specified substrings.

This plugin helps ensure that there are no errors or other message types in running containers during test execution.

## Installation:
```
pip install vedro-logs-checker
```

## Features:
- Monitors logs of Docker containers during test execution.
- Detects specific messages by substrings in logs.
- Skips specific test scenarios based on prefixes in the 'subject' attribute.
- Could filter the list of containers to check by a substring in their names.
- Marks tests as FAILED (optional) when errors are found in logs.

## Configuration (vedro.cfg.py)
The plugin reads its settings from vedro.cfg.py.

Example configuration:
```python
import vedro
from vedro_logs_checker import vedro_logs_checker

class Config(vedro.Config):
    class Plugins:
        class VedroLogsChecker(vedro_logs_checker.VedroLogsChecker):
            enabled = True
            search_for = ["ERROR", "CRITICAL"]  # Substrings to check in logs
            ignore_prefixes = ["try to", "experimental"]  # Scenarios with these prefixes will be ignored
            fail_when_found = True  # If True, test is marked as FAILED when substrings are found
            project_name = "my_project"  # Only check containers with this substring in the name. To check all running containers just don't specify the value
            container_names_to_check = ["grpc", "api", "e2e"] # Optional way to filter containers by name. To check all containers with "project_name" in name just don't specify the value

```
