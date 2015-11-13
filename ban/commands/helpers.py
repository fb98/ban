from concurrent.futures import ThreadPoolExecutor
import csv
import pkgutil
import sys
from importlib import import_module
from pathlib import Path

from progressbar import ProgressBar

from ban.auth.models import Session, User
from ban.core import context


def load_commands():
    from ban import commands
    prefix = commands.__name__ + "."
    for importer, modname, ispkg in pkgutil.iter_modules(commands.__path__,
                                                         prefix):
        if ispkg or modname == __name__:
            continue
        import_module(modname, package=commands.__name__)


def load_csv(path, encoding='utf-8'):
    path = Path(path)
    if not path.exists():
        abort('Path does not exist: {}'.format(path))
    with path.open(encoding=encoding) as f:
        extract = f.read(4096)
        try:
            dialect = csv.Sniffer().sniff(extract)
        except csv.Error:
            dialect = csv.unix_dialect()
        f.seek(0)
        content = f.read()
        return csv.DictReader(content.splitlines(), dialect=dialect)


def iter_file(path, formatter=lambda x: x):
    path = Path(path)
    if not path.exists():
        abort('Path does not exist: {}'.format(path))
    with path.open() as f:
        for l in f:
            yield formatter(l)


def abort(msg):
    sys.stderr.write("\n" + msg)
    sys.exit(1)


def bar(iterable, *args, **kwargs):
    return ProgressBar(*args, **kwargs)(iterable)


def batch(func, iterable, chunksize=1000, max_value=None):
    pbar = ProgressBar(max_value=max_value).start()
    with ThreadPoolExecutor(max_workers=4) as executor:
        for i, res in enumerate(executor.map(func, iterable)):
            pbar.update(i)
        pbar.finish()


def prompt(text, default=None, confirmation=False, coerce=None):
    """Prompts a user for input.  This is a convenience function that can
    be used to prompt a user for input later.

    :param text: the text to show for the prompt.
    :param default: the default value to use if no input happens.  If this
                    is not given it will prompt until it's aborted.
    :param confirmation_prompt: asks for confirmation for the value.
    :param type: the type to use to check the value against.
    """
    result = None

    while 1:
        while 1:
            try:
                result = input('{}: '.format(text))
            except (KeyboardInterrupt, EOFError):
                abort('Bye.')
            if result:
                break
            elif default is not None:
                return default
        if coerce:
            try:
                result = coerce(result)
            except ValueError:
                sys.stderr.write('Wrong value for type {}'.format(type))
                continue
        if not confirmation:
            return result
        while 1:
            try:
                confirm = input('{} (again): '.format(text))
            except (KeyboardInterrupt, EOFError):
                abort('Bye.')
            if confirm:
                break
        if result == confirm:
            return result
        sys.stderr.write('Error: the two entered values do not match')


def session(func):
    def decorated(*args, **kwargs):
        # TODO make configurable from command line
        user = User.select(User.is_admin == True).first()
        if not user:
            abort('No admin user')
        session = Session.create(user=user)
        context.set('session', session)
        return func(*args, **kwargs)
    return decorated