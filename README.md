# vedro-logs-checker

A Vedro plugin that checks logs of Docker containers during test execution and detects messages based on given filters.

This plugin helps ensure that your tests do not introduce errors or other message types in running containers during execution.

## Features:
- Monitors logs of filtered Docker containers during test execution.
- Detects specific messages (by <substring>) appearing in logs after the test starts.
- Ignores certain test scenarios based on prefixes (<prefix>).
- Uses PROJECT_NAME from cabina.Config to filter the list of containers.
- Marks tests as FAILED (optional) when errors are found in logs (controlled via <flag> in config).