"""Progress display: what is being done, a bar, count, elapsed time and time left.

On a console the bar updates in place on one line; when output is redirected to a file
each step is printed on its own line instead.
"""
import shutil
import sys
import time


def _fmt(sec):
    sec = int(max(0, sec))
    h, r = divmod(sec, 3600)
    m, s = divmod(r, 60)
    return '%d:%02d:%02d' % (h, m, s) if h else '%d:%02d' % (m, s)


CURRENT = [None]   # the active Progress, so deep code (upscaler tiles) can report into it


def sub(frac, note=''):
    if CURRENT[0] is not None:
        CURRENT[0].sub_progress(frac, note)


def label(text):
    """name the sub-task inside the current item, e.g. 'upscaling bodybag.dds'"""
    if CURRENT[0] is not None:
        CURRENT[0].sublabel = text
        CURRENT[0].sub_progress(0.0)


def log(msg):
    if CURRENT[0] is not None:
        CURRENT[0].log(msg)
    else:
        print(msg)


class Progress:
    tty = sys.stdout.isatty()

    def __init__(self, total, title, total_weight=None):
        self.total = max(0, int(total))
        self.total_w = float(total_weight) if total_weight else float(self.total)
        self.done_w = 0.0
        self.cur_w = 1.0
        self.title = title
        self.i = 0
        self.t0 = time.time()
        self.item = ''
        self.sub = None
        self.sublabel = ''
        self._last_print = 0.0
        self._last_draw = 0.0
        self._shown = False
        self._prev = CURRENT[0]
        CURRENT[0] = self
        print('%s (%d item%s)' % (title, self.total, '' if self.total == 1 else 's'))
        sys.stdout.flush()

    # -- main steps
    def step(self, item, weight=1.0):
        """call BEFORE working on the next item (or when an item finishes, in parallel runs)"""
        self.done_w += self.cur_w if self.i else 0.0
        self.cur_w = weight
        self.i += 1
        self.item = item
        self.sub = None
        self.sublabel = ''
        self._draw(force=True)

    def sub_progress(self, frac, note=''):
        """progress inside the current item (0..1), e.g. tiles of a big texture"""
        self.sub = (frac, note)
        self._draw()

    def log(self, msg):
        """print a normal line without breaking the bar"""
        self._clear()
        print(msg)
        self._shown = False
        self._draw(force=True)

    def done(self, summary=None):
        self._clear()
        CURRENT[0] = self._prev
        el = time.time() - self.t0
        print('%s: done, %d item%s in %s%s' % (self.title, self.i, '' if self.i == 1 else 's', _fmt(el),
                                              ('. ' + summary) if summary else ''))
        sys.stdout.flush()

    # -- drawing
    def _line(self):
        el = time.time() - self.t0
        done_frac = (self.done_w + (self.sub[0] if self.sub else 0.0) * self.cur_w) / self.total_w if self.total_w else 1.0
        done_frac = min(1.0, max(0.0, done_frac))
        left = (el / done_frac - el) if done_frac > 0.01 and el > 2 else None
        width = shutil.get_terminal_size((100, 20)).columns - 3   # never fill the last column: Windows consoles wrap
        bar_w = 20
        fill = int(round(done_frac * bar_w))
        bar = '[' + '#' * fill + '-' * (bar_w - fill) + ']'
        eta = ('~%s left' % _fmt(left)) if left is not None else 'estimating...'
        sub = ''
        if self.sub:
            parts = [p for p in (self.sublabel, self.sub[1]) if p]
            sub = ' > ' + ': '.join(parts) + ' (%d%%)' % int(self.sub[0] * 100)
        head = '%s %d/%d %3d%% | %s elapsed, %s | ' % (bar, self.i, self.total, int(done_frac * 100), _fmt(el), eta)
        room = max(10, width - len(head))
        item = self.item
        if len(item) + len(sub) > room:                  # shorten the path first, keep the sub-task visible
            item = item.replace('\\', '/').split('/')[-1]
        text = item + sub
        if len(text) > room:
            text = text[:room - 3] + '...'
        return head + text

    def _draw(self, force=False):
        now = time.time()
        if not force and now - self._last_draw < 0.2:
            return
        self._last_draw = now
        if self.tty:
            line = self._line()
            sys.stdout.write('\r' + line + ' ' * max(0, shutil.get_terminal_size((100, 20)).columns - 3 - len(line)))
            sys.stdout.flush()
            self._shown = True
        elif force or now - self._last_print > 10:     # log file: every step, plus every 10 s while busy
            self._last_print = now
            print(self._line())
            sys.stdout.flush()

    def _clear(self):
        if self.tty and self._shown:
            sys.stdout.write('\r' + ' ' * (shutil.get_terminal_size((100, 20)).columns - 3) + '\r')
            sys.stdout.flush()
            self._shown = False


class Spinner:
    """for a single long step with no count (e.g. scanning a big folder)"""
    def __init__(self, msg):
        self.msg = msg; self.t0 = time.time()
        print(msg + ' ...', end='' if Progress.tty else '\n'); sys.stdout.flush()

    def done(self, extra=''):
        el = time.time() - self.t0
        if Progress.tty:
            print(' %s(%s)' % ((extra + ' ') if extra else '', _fmt(el)))
        else:
            print('%s: %s(%s)' % (self.msg, (extra + ' ') if extra else '', _fmt(el)))
        sys.stdout.flush()
