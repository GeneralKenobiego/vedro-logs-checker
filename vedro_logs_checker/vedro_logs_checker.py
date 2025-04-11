import datetime
import logging

import docker
from vedro.core import Dispatcher, Plugin, PluginConfig, VirtualScenario, VirtualStep
from vedro.events import ScenarioRunEvent, StartupEvent

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
        self._project_name = config.project_name

        logging.basicConfig(level=logging.WARNING)

    def subscribe(self, dispatcher: Dispatcher) -> None:
        dispatcher.listen(StartupEvent, self.on_startup)
        dispatcher.listen(ScenarioRunEvent, self.on_scenario_run)

    def on_startup(self, event: StartupEvent) -> None:
        # Добавляем в каждый найденный сценарий кастомный шаг с проверкой логов в конец
        for scenario in event.scenarios:
            step_func = lambda slf: self._new_step()
            step_func.__name__ = 'checking_logs'
            step = VirtualStep(step_func)
            scenario._steps.append(step)
        # Получаем список контейнеров проекта
        self._get_containers()

    def on_scenario_run(self, event: ScenarioRunEvent) -> None:
        self._current_scenario = event.scenario_result.scenario
        self._start_time = datetime.datetime.utcnow()
        logging.info(f"Тест {self._current_scenario.subject} запустился, сохраняем время {self._start_time}")

    def _new_step(self):
        if self._fail_when_found:
            is_found, found_messages = self._check_logs(self._current_scenario)
            if is_found:
                raise AssertionError(found_messages)

    def _check_logs(self, _current_scenario: VirtualScenario) -> bool:
        is_found = False
        found_messages = {}
        if not self._project_containers:
            logging.error('Не найдено запущенных контейнеров')
            return is_found, found_messages
        if not self._start_time:
            logging.error('Не удалось сохранить время начала запуска теста')
            return is_found, found_messages
        # Пропускаем тесты с игнорируемыми префиксами в subject и названии файла
        if _current_scenario.subject.startswith(tuple(self._ignore_prefixes)):
            logging.info(f"Тест {_current_scenario.subject} имеет префикс для игнорирования. Логи не проверяем")
            return is_found, found_messages
        found_messages = self._search_messages_in_logs()
        if found_messages:
            error_msg = "\n❌ Обнаружено в логах контейнеров:\n"
            for container_name, logs in found_messages.items():
                error_msg += f"\n🔴 {container_name}:\n" + "\n".join(logs) + "\n"
            is_found = True
            found_messages = error_msg
        return is_found, found_messages

    def _get_containers(self):
        try:
            if not self._project_name:
                logging.warning("PROJECT_NAME не указан в конфиге, будут проверяться все запущенные контейнеры")
            self._project_containers = self._client.containers.list(filters={"name": self._project_name})
            containers_names = []
            for container in self._project_containers:
                containers_names.append(container.name)
            logging.info(f"Найдены контейнеры: {containers_names}")
        except Exception as e:
            logging.error(f"Ошибка при получении списка контейнеров: {e}")
            return

    def _search_messages_in_logs(self) -> dict:
        found_messages = {}
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
                    found_messages[container.name] = error_logs
            except Exception as e:
                logging.error(f"Ошибка получения логов контейнера {container.name}: {e}")
        return found_messages

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


# Экспорт плагина
class VedroLogsChecker(PluginConfig):
    plugin = VedroLogsCheckerPlugin
    search_for: list[str] = ["ERROR", "CRITICAL"]  # Искомые подстроки по умолчанию
    ignore_prefixes: list[str] = ["try to"]  # Префиксы screnario, которые игнорируются
    fail_when_found: bool = True  # Должен ли тест падать при нахождении подстрок в логах
    project_name: str = ''  # Название проекта для фильтрации докер контейнеров
