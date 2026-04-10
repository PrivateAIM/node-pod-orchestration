import logging


def get_logger() -> logging.Logger:
    _set_custom_log_level(11, 'ACTION')
    _set_custom_log_level(12, 'STATUS LOOP')

    logging.basicConfig(format='[PO %(levelname)s] - %(message)s', level=logging.INFO)
    logger = logging.getLogger(__name__)
    return logger


def _set_custom_log_level(level, level_name):
    def logForLevel(self, message, *args, **kws):
        if self.isEnabledFor(level):
            self._log(level, message, args, **kws)

    def logToRoot(message, *args, **kwargs):
        logging.log(level, message, *args, **kwargs)

    logging.addLevelName(level, level_name.upper())
    setattr(logging, level_name.upper(), level)
    setattr(logging.getLoggerClass(), level_name.lower(), logForLevel)
    setattr(logging, level_name.lower(), logToRoot)
