#!/usr/bin/env python3
"""
Text-mode Tetris for the Linux terminal.

Uses only the Python standard library (curses) - no graphics mode, no
external packages. Runs in any terminal of at least 54x24 characters,
including the plain Linux virtual console (Ctrl+Alt+F3, etc.).

Controls
  Left / Right  or  A / D  or  H / L   move
  Up  or  W  or  X  or  K              rotate clockwise
  Z                                    rotate counter-clockwise
  Down  or  S  or  J                   soft drop  (+1 per row)
  Space                                hard drop  (+2 per row)
  P                                    pause / resume
  R                                    restart (after game over)
  Q                                    quit
"""

import curses
import os
import random
import time

# --------------------------------------------------------------------------
# Configuration
# --------------------------------------------------------------------------
BOARD_W, BOARD_H = 10, 20          # playfield size in cells
ORIGIN_Y, ORIGIN_X = 1, 2          # top-left of the well on screen
MIN_ROWS, MIN_COLS = 24, 54        # smallest terminal we can draw in
TICK = 0.02                        # input poll interval (seconds)
HIGHSCORE_FILE = os.path.expanduser("~/.tetris_highscore")

# Piece shapes as square matrices ('#' = block). Colour index follows.
PIECES = {
    "I": (["....",
           "####",
           "....",
           "...."], 1),
    "O": (["##",
           "##"], 2),
    "T": ([".#.",
           "###",
           "..."], 3),
    "S": ([".##",
           "##.",
           "..."], 4),
    "Z": (["##.",
           ".##",
           "..."], 5),
    "J": (["#..",
           "###",
           "..."], 6),
    "L": (["..#",
           "###",
           "..."], 7),
}

LINE_SCORES = {1: 100, 2: 300, 3: 500, 4: 800}


# --------------------------------------------------------------------------
# Shape helpers
# --------------------------------------------------------------------------
def to_matrix(rows):
    return [[ch == "#" for ch in row] for row in rows]


def cells(shape):
    """Return (row, col) offsets of the filled cells in a shape matrix."""
    return [(r, c) for r, row in enumerate(shape) for c, v in enumerate(row) if v]


def rotate(shape, clockwise=True):
    if clockwise:
        return [list(row) for row in zip(*shape[::-1])]
    return [list(row) for row in zip(*shape)][::-1]


# --------------------------------------------------------------------------
# Game logic (independent of the display)
# --------------------------------------------------------------------------
class Game:
    def __init__(self, high_score=0):
        self.grid = [[0] * BOARD_W for _ in range(BOARD_H)]
        self.bag = []
        self.score = 0
        self.lines = 0
        self.level = 1
        self.high_score = high_score
        self.over = False
        self.paused = False
        self.next_kind = self._draw_from_bag()
        self.last_fall = time.monotonic()
        self._spawn()

    # --- piece generation: "7-bag" so every piece shows up regularly ---
    def _draw_from_bag(self):
        if not self.bag:
            self.bag = list(PIECES)
            random.shuffle(self.bag)
        return self.bag.pop()

    def _spawn(self):
        self.kind = self.next_kind
        self.next_kind = self._draw_from_bag()
        rows, self.color = PIECES[self.kind]
        self.shape = to_matrix(rows)
        self.x = (BOARD_W - len(self.shape[0])) // 2
        self.y = -min(r for r, _ in cells(self.shape))  # top block on row 0
        if self._collides(self.shape, self.x, self.y):
            self._game_over()

    def _game_over(self):
        self.over = True
        self.high_score = max(self.high_score, self.score)

    # --- collision & movement ---
    def _collides(self, shape, x, y):
        for r, c in cells(shape):
            bx, by = x + c, y + r
            if bx < 0 or bx >= BOARD_W or by >= BOARD_H:
                return True
            if by >= 0 and self.grid[by][bx]:
                return True
        return False

    def move(self, dx, dy):
        if self.over or self.paused:
            return False
        if self._collides(self.shape, self.x + dx, self.y + dy):
            return False
        self.x += dx
        self.y += dy
        return True

    def rotate(self, clockwise=True):
        if self.over or self.paused:
            return
        new_shape = rotate(self.shape, clockwise)
        # Simple wall kicks: try shifting sideways, then up.
        for dx, dy in ((0, 0), (-1, 0), (1, 0), (-2, 0), (2, 0), (0, -1)):
            if not self._collides(new_shape, self.x + dx, self.y + dy):
                self.shape = new_shape
                self.x += dx
                self.y += dy
                return

    def soft_drop(self):
        if self.over or self.paused:
            return
        if self.move(0, 1):
            self.score += 1
            self.last_fall = time.monotonic()
        else:
            self._lock()

    def hard_drop(self):
        if self.over or self.paused:
            return
        rows = 0
        while self.move(0, 1):
            rows += 1
        self.score += 2 * rows
        self._lock()

    def ghost_y(self):
        y = self.y
        while not self._collides(self.shape, self.x, y + 1):
            y += 1
        return y

    # --- locking & line clears ---
    def _lock(self):
        for r, c in cells(self.shape):
            by = self.y + r
            if by < 0:                     # stacked above the top: game over
                self._game_over()
                return
            self.grid[by][self.x + c] = self.color
        self._clear_lines()
        self._spawn()
        self.last_fall = time.monotonic()

    def _clear_lines(self):
        remaining = [row for row in self.grid if not all(row)]
        cleared = BOARD_H - len(remaining)
        if cleared:
            self.grid = [[0] * BOARD_W for _ in range(cleared)] + remaining
            self.score += LINE_SCORES[cleared] * self.level
            self.lines += cleared
            self.level = self.lines // 10 + 1

    # --- gravity ---
    def fall_interval(self):
        return max(0.05, 0.8 * (0.85 ** (self.level - 1)))

    def update(self, now):
        if self.over or self.paused:
            return
        if now - self.last_fall >= self.fall_interval():
            if not self.move(0, 1):
                self._lock()
            self.last_fall = now

    def toggle_pause(self):
        if not self.over:
            self.paused = not self.paused
            self.last_fall = time.monotonic()


# --------------------------------------------------------------------------
# High score persistence
# --------------------------------------------------------------------------
def load_high_score():
    try:
        with open(HIGHSCORE_FILE) as f:
            return int(f.read().strip() or 0)
    except (OSError, ValueError):
        return 0


def save_high_score(score):
    try:
        with open(HIGHSCORE_FILE, "w") as f:
            f.write(str(score))
    except OSError:
        pass


# --------------------------------------------------------------------------
# Rendering (text mode via curses)
# --------------------------------------------------------------------------
def init_colors():
    if not curses.has_colors():
        return
    curses.start_color()
    try:
        curses.use_default_colors()
        bg = -1
    except curses.error:
        bg = curses.COLOR_BLACK
    palette = [curses.COLOR_CYAN, curses.COLOR_YELLOW, curses.COLOR_MAGENTA,
               curses.COLOR_GREEN, curses.COLOR_RED, curses.COLOR_BLUE,
               curses.COLOR_WHITE]
    for i, fg in enumerate(palette, start=1):
        curses.init_pair(i, fg, bg)


def color_attr(color):
    return curses.color_pair(color) if curses.has_colors() else 0


def put(win, y, x, text, attr=0):
    """addstr that ignores writes falling off the edge of the window."""
    try:
        win.addstr(y, x, text, attr)
    except curses.error:
        pass


def draw_cell(win, row, col, color, ghost=False):
    y, x = ORIGIN_Y + row, ORIGIN_X + 2 + col * 2
    if ghost:
        put(win, y, x, "::", color_attr(color))
    else:
        put(win, y, x, "[]", color_attr(color) | curses.A_REVERSE | curses.A_BOLD)


def draw(win, game):
    win.erase()
    rows, cols = win.getmaxyx()
    if rows < MIN_ROWS or cols < MIN_COLS:
        put(win, 0, 0, f"Terminal too small: need {MIN_COLS}x{MIN_ROWS},")
        put(win, 1, 0, f"have {cols}x{rows}. Resize or press Q.")
        win.refresh()
        return

    # Well borders
    right = ORIGIN_X + 2 + BOARD_W * 2
    for r in range(BOARD_H):
        put(win, ORIGIN_Y + r, ORIGIN_X, "<!")
        put(win, ORIGIN_Y + r, right, "!>")
    put(win, ORIGIN_Y + BOARD_H, ORIGIN_X, "<!" + "=" * (BOARD_W * 2) + "!>")
    put(win, ORIGIN_Y + BOARD_H + 1, ORIGIN_X + 2, "\\/" * BOARD_W)

    # Locked blocks and empty cells
    for r in range(BOARD_H):
        for c in range(BOARD_W):
            if game.grid[r][c]:
                draw_cell(win, r, c, game.grid[r][c])
            else:
                put(win, ORIGIN_Y + r, ORIGIN_X + 2 + c * 2, " .", curses.A_DIM)

    # Ghost piece, then the falling piece on top of it
    if not game.over:
        gy = game.ghost_y()
        for r, c in cells(game.shape):
            if gy + r >= 0:
                draw_cell(win, gy + r, game.x + c, game.color, ghost=True)
        for r, c in cells(game.shape):
            if game.y + r >= 0:
                draw_cell(win, game.y + r, game.x + c, game.color)

    # Side panel
    px = right + 5
    put(win, ORIGIN_Y, px, "T E T R I S", curses.A_BOLD)

    put(win, ORIGIN_Y + 2, px, "NEXT:")
    nrows, ncolor = PIECES[game.next_kind]
    for r, c in cells(to_matrix(nrows)):
        put(win, ORIGIN_Y + 3 + r, px + 2 + c * 2, "[]",
            color_attr(ncolor) | curses.A_REVERSE | curses.A_BOLD)

    put(win, ORIGIN_Y + 8, px, f"SCORE  {game.score}")
    put(win, ORIGIN_Y + 9, px, f"HIGH   {max(game.high_score, game.score)}")
    put(win, ORIGIN_Y + 10, px, f"LEVEL  {game.level}")
    put(win, ORIGIN_Y + 11, px, f"LINES  {game.lines}")

    help_lines = ["<- ->  move", "Up/X   rotate", "Z      rotate back",
                  "Down   soft drop", "Space  hard drop", "P pause   Q quit"]
    for i, line in enumerate(help_lines):
        put(win, ORIGIN_Y + 13 + i, px, line, curses.A_DIM)

    # Overlays
    mid_y = ORIGIN_Y + BOARD_H // 2 - 1
    center_x = ORIGIN_X + 2 + BOARD_W

    def banner(y, text, attr=curses.A_BOLD | curses.A_REVERSE):
        put(win, y, center_x - len(text) // 2, text, attr)

    if game.paused:
        banner(mid_y, "  PAUSED  ")
        banner(mid_y + 1, " P resume ", curses.A_REVERSE)
    elif game.over:
        banner(mid_y, "  GAME  OVER  ")
        banner(mid_y + 1, " R retry Q quit ", curses.A_REVERSE)

    win.refresh()


# --------------------------------------------------------------------------
# Main loop
# --------------------------------------------------------------------------
KEYS_LEFT = {curses.KEY_LEFT, ord("a"), ord("A"), ord("h")}
KEYS_RIGHT = {curses.KEY_RIGHT, ord("d"), ord("D"), ord("l")}
KEYS_ROT_CW = {curses.KEY_UP, ord("w"), ord("W"), ord("x"), ord("X"), ord("k")}
KEYS_ROT_CCW = {ord("z"), ord("Z")}
KEYS_SOFT = {curses.KEY_DOWN, ord("s"), ord("S"), ord("j")}
KEYS_HARD = {ord(" ")}
KEYS_PAUSE = {ord("p"), ord("P")}
KEYS_QUIT = {ord("q"), ord("Q")}
KEYS_RESTART = {ord("r"), ord("R")}


def run(stdscr):
    try:
        curses.curs_set(0)
    except curses.error:
        pass
    stdscr.keypad(True)
    stdscr.timeout(int(TICK * 1000))
    init_colors()

    game = Game(load_high_score())
    while True:
        key = stdscr.getch()
        while key != -1:                  # drain all pending keys this tick
            if key in KEYS_QUIT:
                save_high_score(max(game.high_score, game.score))
                return
            if key == curses.KEY_RESIZE:
                stdscr.clear()
            elif game.over:
                if key in KEYS_RESTART:
                    save_high_score(game.high_score)
                    game = Game(game.high_score)
            elif key in KEYS_PAUSE:
                game.toggle_pause()
            elif key in KEYS_LEFT:
                game.move(-1, 0)
            elif key in KEYS_RIGHT:
                game.move(1, 0)
            elif key in KEYS_ROT_CW:
                game.rotate(clockwise=True)
            elif key in KEYS_ROT_CCW:
                game.rotate(clockwise=False)
            elif key in KEYS_SOFT:
                game.soft_drop()
            elif key in KEYS_HARD:
                game.hard_drop()
            stdscr.nodelay(True)
            key = stdscr.getch()
        stdscr.timeout(int(TICK * 1000))

        was_over = game.over
        game.update(time.monotonic())
        if game.over and not was_over:
            save_high_score(game.high_score)
        draw(stdscr, game)


def main():
    os.environ.setdefault("ESCDELAY", "25")
    try:
        curses.wrapper(run)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
