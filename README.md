# vedro-logs-checker

A Vedro plugin that checks logs of Docker containers during test execution and detects messages based on given filters.

This plugin helps ensure that your tests do not introduce errors or other message types in running containers during execution.

## Features:
- Monitors logs of filtered Docker containers during test execution.
- Detects specific messages (by <substring>) appearing in logs after the test starts.
- Ignores certain test scenarios based on prefixes (<prefix>).
- Uses PROJECT_NAME from cabina.Config to filter the list of containers.
- Marks tests as FAILED (optional) when errors are found in logs (controlled via <flag> in config).

## Configuration (vedro.cfg.py)
The plugin reads its settings from vedro.cfg.py.

Example configuration:
```
import vedro
from vedro_logs_checker import VedroLogsChecker

class Config(vedro.Config):
    class Plugins:
        VedroLogsChecker:
            log_levels = ["ERROR", "CRITICAL"]  # Substrings to check in logs
            ignore_prefixes = ["skip_", "experimental_"]  # Scenarios with these prefixes will be ignored
            fail_on_errors = True  # If True, test is marked as FAILED when substrings are found
            project_name = "my_project"  # Only check containers with this name. To check all running containers just don't specify the value

```