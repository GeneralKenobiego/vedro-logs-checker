import datetime
import logging

import docker
from vedro.core import Dispatcher, Plugin, PluginConfig
from vedro.events import ScenarioRunEvent

from config import Config

__all__ = ("VedroLogsChecker")


class VedroLogsCheckerPlugin(Plugin):
    def __init__(self, config: PluginConfig) -> None:
        super().__init__(config)
        self._start_time = None
        self._project_containers = []
        self._search_for = config.search_for
        self._ignore_prefixes = config.ignore_prefixes
        self._fail_when_found = config.fail_when_found
        self._client = docker.from_env()
        try:
            self._project_name = Config.Docker.PROJECT_NAME
        except AttributeError:
            logging.error("PROJECT_NAME не найден в Config.Docker")
            self._project_name = None

        logging.basicConfig(level=logging.WARNING)

    def subscribe(self, dispatcher: Dispatcher) -> None:
        dispatcher.listen(ScenarioRunEvent, self._on_scenario_run)

    def _get_containers(self):
        try:
            self._project_containers = self._client.containers.list(filters={"name": self._project_name})
            containers_names = []
            for container in self._project_containers:
                containers_names.append(container.name)
            logging.warning(f"Найдены контейнеры: {containers_names}")
        except Exception as e:
            logging.error(f"Ошибка при получении списка контейнеров: {e}")
            return

    def _convert_log_str(self, line: str) -> tuple[str, str]:
        # Разделяем временную метку и сообщение лога
        parts = line.split(" ", 1)
        # Если строка не содержит метки времени — пропускаем
        if len(parts) < 2:
            return

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

        return log_time, log_message

    def _search_error_logs(self) -> dict:
        found_errors = {}
        # Переводим _start_time в UNIX-время
        start_time_unix = int(self._start_time.timestamp())

        for container in self._project_containers:
            try:
                logs = container.logs(since=start_time_unix, timestamps=True).decode("utf-8", errors="ignore")
                error_logs = []

                for line in logs.splitlines():
                    log_time, log_message = self._convert_log_str(line)
                    log_message_lower = log_message.lower()
                    search_for_lower = [level.lower() for level in self._search_for]
                    if log_time >= self._start_time and any(level in log_message_lower for level in search_for_lower):
                        error_logs.append(log_message)

                if error_logs:
                    found_errors[container.name] = error_logs

            except Exception as e:
                logging.error(f"Ошибка получения логов контейнера {container.name}: {e}")
        return found_errors

    def _return_errors(self, found_errors: dict, event: ScenarioRunEvent):
        if found_errors:
            error_msg = "\n❌ Обнаружено в логах контейнеров:\n"
            for container_name, logs in found_errors.items():
                error_msg += f"\n🔴 {container_name}:\n" + "\n".join(logs) + "\n"
            if self._fail_when_found:
                logging.error(error_msg)
                event.scenario_result.mark_failed()
            else:
                logging.error(error_msg)
        else:
            logging.warning("Ошибок не найдено в контейнерах проекта.")

    def _check_logs(self, event: ScenarioRunEvent) -> None:
        if not self._start_time or not self._project_containers:
            return

        logging.warning(f"Проверяем логи контейнеров с {self._start_time}")
        found_errors = self._search_error_logs()
        self._return_errors(found_errors=found_errors, event=event)

    async def _on_scenario_run(self, event: ScenarioRunEvent) -> None:
        scenario_name = event.scenario_result.scenario.subject
        # Пропускаем тесты с игнорируемыми префиксами в subject и названии файла
        if scenario_name.startswith(tuple(self._ignore_prefixes)):
            logging.warning(f"Тест {scenario_name} имеет префикс для игнорирования. Логи не проверяем")
            return

        self._start_time = datetime.datetime.utcnow()
        logging.warning(f"Тест {scenario_name} запустился, сохраняем время {self._start_time}")

        # Получаем список контейнеров проекта
        self._get_containers()
        # Проверяем логи после выполнения теста
        self._check_logs(event)


# Экспорт плагина
class VedroLogsChecker(PluginConfig):
    plugin = VedroLogsCheckerPlugin
    search_for: list[str] = ["ERROR"]  # Искомые подстроки по умолчанию
    ignore_prefixes: list[str] = ["try to"]  # Префиксы screnario, которые игнорируются
    fail_when_found: bool = True  # Должен ли тест падать при нахождении подстрок в логах
