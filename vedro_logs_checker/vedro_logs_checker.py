import datetime
import logging
import os

import docker
from vedro.core import Dispatcher, Plugin, PluginConfig
from vedro.events import ScenarioRunEvent

__all__ = ("VedroLogsChecker")


class VedroLogsCheckerPlugin(Plugin):
    def __init__(self, config: PluginConfig) -> None:
        super().__init__(config)
        self._start_time = None
        self._project_containers = []
        self._log_levels = config.log_levels
        self._ignore_prefixes = config.ignore_prefixes
        self._fail_on_errors = config.fail_on_errors
        self._client = docker.from_env()

        logging.basicConfig(level=logging.WARNING)

    def subscribe(self, dispatcher: Dispatcher) -> None:
        dispatcher.listen(ScenarioRunEvent, self._on_scenario_run)

    async def _on_scenario_run(self, event: ScenarioRunEvent) -> None:
        scenario = event.scenario_result.scenario
        scenario_file = os.path.basename(scenario.path)

        # Пропускаем тесты с игнорируемыми префиксами
        if scenario_file.startswith(tuple(self._ignore_prefixes)):
            return

        self._start_time = datetime.datetime.utcnow()
        logging.warning(f"Тест {scenario_file} запустился, сохраняем время {self._start_time}")

        # Получаем список контейнеров проекта
        try:
            self._project_containers = self._client.containers.list()
            containers_names = []
            for container in self._project_containers:
                containers_names.append(container.name)
            logging.warning(f"Найдены контейнеры: {containers_names}")
        except Exception as e:
            logging.error(f"Ошибка при получении списка контейнеров: {e}")
            return

        # Проверяем логи после выполнения теста
        self.check_logs()

    def check_logs(self) -> None:
        if not self._start_time or not self._project_containers:
            return
        found_errors = {}
        # Переводим _start_time в UNIX-время
        start_time_unix = int(self._start_time.timestamp())

        logging.warning(f"Проверяем логи контейнеров с {self._start_time}")
        for container in self._project_containers:
            try:
                logs = container.logs(since=start_time_unix, timestamps=True).decode("utf-8", errors="ignore")
                error_logs = []

                for line in logs.splitlines():
                    # Разделяем временную метку и сообщение лога
                    parts = line.split(" ", 1)
                    # Если строка не содержит метки времени — пропускаем
                    if len(parts) < 2:
                        continue

                    timestamp_str, log_message = parts
                    # Конвертируем специфичный timestamp докера в нормальный
                    try:
                        # Подрезаем милисекунды до 6 знаков
                        if "." in timestamp_str:
                            timestamp_str = timestamp_str.split(".")[0] + "." + timestamp_str.split(".")[1][:6]
                        # Убираем Z в конце
                        timestamp_str = timestamp_str.replace("Z", "+00:00")
                        log_time = datetime.datetime.fromisoformat(timestamp_str)

                    except ValueError:
                        # Если не получилось конвертировать в норм timestamp то считаем, что лог новый
                        log_time = self._start_time
                        log_message = line

                    if log_time >= self._start_time and any(level in log_message for level in self._log_levels):
                        error_logs.append(log_message)

                if error_logs:
                    found_errors[container.name] = error_logs

            except Exception as e:
                logging.error(f"Ошибка получения логов контейнера {container.name}: {e}")

        if found_errors:
            error_msg = "\n❌ Найдены ошибки в контейнерах:\n"
            for container_name, logs in found_errors.items():
                error_msg += f"\n🔴 {container_name}:\n" + "\n".join(logs) + "\n"
            if self._fail_on_errors:
                raise AssertionError(error_msg)
            else:
                logging.error(error_msg)
        else:
            logging.warning("Ошибок не найдено в контейнерах проекта.")


# Экспорт плагина
class VedroLogsChecker(PluginConfig):
    plugin = VedroLogsCheckerPlugin
    log_levels: list[str] = ["ERROR"]  # Уровни логов для поиска по умолчанию
    ignore_prefixes: list[str] = ["try_to_"]  # Префиксы файлов, которые игнорируются
    fail_on_errors: bool = True  # Должен ли тест падать при нахождении ошибок в логах
