import sys
import os
from colorama import init, Fore, Back, Style

if os.name == 'posix':
    os.environ['TERM'] = 'xterm-256color'
init()


class ColorPrinter:
    def __init__(self):
        self._fore_color = ''
        self._back_color = ''
        self._style = ''
        self._text = ''

    def _reset(self):
        self._fore_color = ''
        self._back_color = ''
        self._style = ''
        return self

    def red(self):
        self._fore_color = Fore.RED
        return self

    def green(self):
        self._fore_color = Fore.GREEN
        return self

    def yellow(self):
        self._fore_color = Fore.YELLOW
        return self

    def blue(self):
        self._fore_color = Fore.BLUE
        return self

    def cyan(self):
        self._fore_color = Fore.CYAN
        return self

    def bold(self):
        self._style = Style.BRIGHT
        return self

    def print(self, text, end='\n', file=sys.stdout):
        formatted = f"{self._style}{self._back_color}{self._fore_color}{text}{Style.RESET_ALL}"
        print(formatted, end=end, file=file)
        self._reset()
        return self


_printer = ColorPrinter()


def print_success(text):
    _printer.green().print(f"[OK] {text}")


def print_error(text):
    _printer.red().print(f"[ERR] {text}")


def print_warning(text):
    _printer.yellow().print(f"[WARN] {text}")


def print_info(text):
    _printer.cyan().print(f"[INFO] {text}")
