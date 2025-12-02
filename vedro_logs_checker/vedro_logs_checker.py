import datetime
import logging
import re
from typing import Type, TypeVar

import docker
import vedro
from vedro import Scenario
from vedro.core import Dispatcher, Plugin, PluginConfig, VirtualScenario, VirtualStep
from vedro.events import ScenarioRunEvent, StartupEvent

__all__ = ("VedroLogsChecker")

logger = logging.getLogger("vedro_logs_checker")
logger.setLevel(logging.INFO)

T = TypeVar("T", bound=Type[Scenario])


def skip_logs_check(scenario: T) -> T:
    # Декоратор для пропуска проверки теста
    setattr(scenario, "__vedro__skip_logs_check__", True)
    return scenario


class VedroLogsCheckerPlugin(Plugin):
    def __init__(self, config: PluginConfig) -> None:
        super().__init__(config)
        self._silent = config.silent
        self._start_time = None
        self._project_containers = []
        self._search_for = config.search_for
        self._ignore_prefixes = config.ignore_prefixes
        self._fail_when_found = config.fail_when_found
        self._client = docker.from_env()
        self._project_name = config.project_name
        self._container_name_patterns = [
            # Компилируем регулярные выражения для повышения скорости фильтрации контейнеров
            re.compile(pattern) for pattern in config.regex_container_names_to_check
        ]
        self._container_name_exclude_patterns = [
            re.compile(pattern) for pattern in config.regex_container_names_to_ignore
        ]

    def _has_skip_logs_check(self, scenario: VirtualScenario) -> bool:
        # Проверяет наличие атрибута __vedro__skip_logs_check__
        template = getattr(scenario._orig_scenario, "__vedro__template__", None)
        has_attr = getattr(template, "__vedro__skip_logs_check__", False)
        has_attr += getattr(scenario._orig_scenario, "__vedro__skip_logs_check__", False)
        return has_attr

    def subscribe(self, dispatcher: Dispatcher) -> None:
        dispatcher.listen(StartupEvent, self.on_startup)
        dispatcher.listen(ScenarioRunEvent, self.on_scenario_run)

    def on_startup(self, event: StartupEvent) -> None:
        if not self._silent:
            logger.warning("VedroLogsChecker подключен. Конфигурация:")
            logger.warning(f"  Искомые подстроки в логах: {self._search_for}")
            logger.warning(f"  Название проекта: {self._project_name or '(не указано)'}")
            logger.warning(f"  Regex для поиска контейнеров: "
                           f"{[r.pattern for r in self._container_name_patterns] or '(не указаны)'}")
            logger.warning(f"  Regex для игнорирования контейнеров: "
                           f"{[r.pattern for r in self._container_name_exclude_patterns] or '(не указаны)'}")
            logger.warning(f"  Отмечать тест упавшим при нахождении подстрок: {self._fail_when_found}")
        # Добавляем в каждый найденный сценарий кастомный шаг с проверкой логов в конец
        for scenario in event.scenarios:
            skip = self._has_skip_logs_check(scenario)
            # Пропускаем тесты с декоратором в subject и названии файла
            if skip:
                if not self._silent:
                    logger.warning(f"Тест {scenario.subject} отмечен декоратором для игнорирования. Логи не проверяем")
            # Пропускаем тесты с игнорируемыми префиксами в subject и названии файла
            elif scenario.subject.startswith(tuple(self._ignore_prefixes)):
                if not self._silent:
                    logger.warning(f"Тест {scenario.subject} имеет префикс для игнорирования. Логи не проверяем")
            else:
                step_func = lambda scn: self._new_step(scn)
                step_func.__name__ = 'checking_logs'
                step = VirtualStep(step_func)
                scenario._steps.append(step)
        # Получаем список контейнеров проекта
        self._project_containers = self._get_containers()

    def on_scenario_run(self, event: ScenarioRunEvent) -> None:
        self._start_time = datetime.datetime.utcnow()
        logger.info(f"Тест {event.scenario_result.scenario} запустился, сохраняем время {self._start_time}")

    def _new_step(self, scn: vedro.Scenario) -> None:
        if self._fail_when_found:
            is_found = self._check_logs(scn)
            if is_found:
                raise AssertionError(f"В логах обнаружены подстроки из списка {self._search_for}")

    def _check_logs(self, scn: vedro.Scenario) -> bool:
        is_found = False
        found_messages = {}
        if not self._project_containers:
            logger.error('Не найдено запущенных контейнеров')
            return is_found, found_messages
        if not self._start_time:
            logger.error('Не удалось сохранить время начала запуска теста')
            return is_found, found_messages
        found_messages = self._search_messages_in_logs()
        if found_messages:
            error_msg = []
            error_msg.append("❌ Обнаружено в логах контейнеров:")
            for container_name, logs in found_messages.items():
                error_msg.append(f"🔴 {container_name}:")
                error_msg.append(logs)
            is_found = True
            found_messages = error_msg
            scn.found_messages = error_msg
        return is_found

    def _get_containers(self) -> list:
        try:
            if not self._project_name:
                logger.warning("PROJECT_NAME не указан в конфиге, будут проверяться все запущенные контейнеры")
            project_containers = self._client.containers.list(filters={"name": self._project_name})
            if not self._container_name_patterns:
                logger.warning("regex_container_names_to_check не указан в конфиге, ")
            else:
                project_containers = [
                    item for item in project_containers
                    if any(pattern.search(item.name) for pattern in self._container_name_patterns)
                ]
            if not self._container_name_exclude_patterns:
                logger.warning("regex_container_names_to_ignore не указан в конфиге, ")
            else:
                project_containers = [
                    item for item in project_containers
                    if not any(pattern.search(item.name) for pattern in self._container_name_exclude_patterns)
                ]
            containers_names = [container.name for container in project_containers]
            logger.warning(f"Будут проверены логи контейнеров: {containers_names}")
            return project_containers
        except Exception as e:
            logger.error(f"Ошибка при получении списка контейнеров: {e}")
            return []

    def _search_messages_in_logs(self) -> dict:
        found_messages = {}
        # Переводим _start_time в UNIX-время
        start_time_unix = self._start_time
        for container in self._project_containers:
            try:
                logs = container.logs(since=start_time_unix, timestamps=True).decode("utf-8", errors="ignore")
                error_logs = []
                for line in logs.splitlines():
                    log_time, log_message = self._convert_log_str(line)
                    log_message_lower = log_message.lower()
                    search_for_lower = [substr.lower() for substr in self._search_for]
                    if log_time >= self._start_time and any(substr in log_message_lower for substr in search_for_lower):
                        logger.info(f"Имя контейнера с ошибкой в логах: {container.name}")
                        logger.info(f"Время старта сценария: {self._start_time}")
                        logger.info(f"Время ошибки: {log_time}")
                        error_logs.append(log_message)
                if error_logs:
                    found_messages[container.name] = error_logs
            except Exception as e:
                logger.error(f"Ошибка получения логов контейнера {container.name}: {e}")
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
        except ValueError as e:
            logger.error(f"Ошибка конвертации строки {timestamp_str} в timestamp: {e}")
        return log_time, log_message


# Экспорт плагина
class VedroLogsChecker(PluginConfig):
    plugin = VedroLogsCheckerPlugin
    search_for: list[str] = ["ERROR", "CRITICAL"]  # Искомые подстроки по умолчанию
    ignore_prefixes: list[str] = ["try to"]  # Префиксы screnario, которые игнорируются
    fail_when_found: bool = True  # Должен ли тест падать при нахождении подстрок в логах
    project_name: str = ''  # Название проекта для фильтрации докер контейнеров
    regex_container_names_to_check: list[str] = []  # Названия контейнеров для проверки (доп фильтрация по regex)
    regex_container_names_to_ignore: list[str] = []  # Названия контейнеров для игнорирования (доп фильтрация по regex)
    silent: bool = False  # Отключить вывод конфига при старте плагина
