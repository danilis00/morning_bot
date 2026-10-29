"""Картинки для бота: чёрный фон и оранжевый KTM. Только Pillow — без браузера, работает на Railway."""
from __future__ import annotations

import datetime as dt
import io
import math
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from . import core

FONTS = Path(__file__).with_name("fonts")

# Палитра: тёмная ночь + оранжевый KTM (#FF6600)
BG = (10, 10, 11)
PANEL = (21, 22, 25)
CELL = (30, 32, 36)
CELL_HI = (40, 42, 48)
LINE = (52, 55, 62)
Y = (255, 102, 0)        # акцент: оранжевый KTM
Y_DIM = (140, 58, 6)     # приглушённый акцент: рамки пустых шагов
Y_DARK = (46, 22, 8)     # фон выполненных ячеек
TEXT = (234, 234, 236)
MUTED = (140, 145, 154)
INK = (12, 12, 12)

MON = ["янв", "фев", "мар", "апр", "мая", "июн", "июл", "авг", "сен", "окт", "ноя", "дек"]
WD = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]


@lru_cache(maxsize=64)
def font(weight: str, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(FONTS / f"Inter-{weight}.otf"), size)


def _png(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.save(buf, "PNG", optimize=True)
    return buf.getvalue()


NBSP = "\u00a0"


def _prep(text: str) -> str:
    """Не рвём «10 000» и «€ 500» между строками."""
    import re
    text = re.sub(r"(\d) (?=\d{3}\b)", "\\1" + NBSP, text)
    return text.replace("€ ", "€" + NBSP)


def _tokens(text: str) -> list[str]:
    """Слова по пробелам; дефисные слова можно переносить после дефиса."""
    out = []
    for w in text.split(" "):
        if not w:
            continue
        parts = w.split("-")
        for i, p in enumerate(parts):
            out.append(p + ("-" if i < len(parts) - 1 else ""))
            if i < len(parts) - 1:
                out.append("\x00")  # мягкая точка переноса без пробела
    return out


def wrap(draw: ImageDraw.ImageDraw, text: str, f, maxw: int) -> list[str]:
    lines, cur, glue = [], "", ""
    for tok in _tokens(_prep(text)):
        if tok == "\x00":
            glue = ""
            continue
        trial = (cur + glue + tok) if cur else tok
        if draw.textlength(trial, font=f) <= maxw or not cur:
            cur = trial
        else:
            lines.append(cur)
            cur = tok
        glue = " "
    if cur:
        lines.append(cur)
    return lines


def _fits(draw, text, f, maxw) -> bool:
    return all(draw.textlength(t, font=f) <= maxw for t in _tokens(_prep(text)) if t != "\x00")


def fit_text(draw, text, weight, size, maxw, maxh, min_size=11, lh=1.2):
    """Подбирает размер, чтобы текст влез: ни одно слово не режется, строки помещаются по высоте."""
    for s in range(size, min_size - 1, -1):
        f = font(weight, s)
        if not _fits(draw, text, f, maxw):
            continue
        lines = wrap(draw, text, f, maxw)
        step = int(s * lh)
        if len(lines) * step <= maxh:
            return f, lines, step
    f = font(weight, min_size)
    step = int(min_size * lh)
    lines = wrap(draw, text, f, maxw)[: max(1, maxh // step)]
    return f, lines, step


def draw_lines(draw, xy, lines, f, step, fill, strike=False, center_w=None):
    x, y = xy
    for ln in lines:
        lx = x + (center_w - draw.textlength(ln, font=f)) / 2 if center_w else x
        draw.text((lx, y), ln, font=f, fill=fill)
        if strike:
            w = draw.textlength(ln, font=f)
            my = y + f.size * 0.62
            draw.line((lx, my, lx + w, my), fill=fill, width=2)
        y += step
    return y


def star(draw, cx, cy, r, fill):
    pts = []
    for i in range(10):
        a = -math.pi / 2 + i * math.pi / 5
        rr = r if i % 2 == 0 else r * 0.45
        pts.append((cx + rr * math.cos(a), cy + rr * math.sin(a)))
    draw.polygon(pts, fill=fill)


def check(draw, x, y, s, fill, width=3):
    draw.line([(x + s * 0.18, y + s * 0.52), (x + s * 0.42, y + s * 0.76), (x + s * 0.84, y + s * 0.26)], fill=fill, width=width, joint="curve")


def bar(draw, x, y, w, h, frac, fg=Y, bg=LINE, r=None):
    r = h // 2 if r is None else r
    draw.rounded_rectangle((x, y, x + w, y + h), r, fill=bg)
    if frac > 0:
        draw.rounded_rectangle((x, y, x + max(h, int(w * min(1, frac))), y + h), r, fill=fg)


def in_days(n: int) -> str:
    return "сегодня" if n == 0 else ("завтра" if n == 1 else f"через {n} дн")


def date_ru(day: dt.date, year=False) -> str:
    return f"{day.day} {MON[day.month - 1]}" + (f" {day.year}" if year else "")


def _header(draw, W, title, right, sub=None, y=34):
    draw.text((40, y), title, font=font("Black", 44), fill=Y)
    rw = draw.textlength(right, font=font("SemiBold", 22))
    draw.text((W - 40 - rw, y + 16), right, font=font("SemiBold", 22), fill=MUTED)
    y += 62
    if sub:
        draw.text((40, y), sub, font=font("Medium", 22), fill=TEXT)
        y += 36
    draw.rectangle((40, y + 6, W - 40, y + 9), fill=Y)
    return y + 30


# ======================================================================
# 1. Сетка 9×9
# ======================================================================
POS = [(0, 0), (0, 1), (0, 2), (1, 2), (2, 2), (2, 1), (2, 0), (1, 0)]


def render_grid(grid: dict, prog: core.Progress, today: dt.date) -> bytes:
    W, M, BG_GAP, IN_GAP, CH = 1600, 40, 14, 5, 168
    CW = (W - 2 * M - 2 * BG_GAP - 6 * IN_GAP) // 9
    grid_w = CW * 9 + 6 * IN_GAP + 2 * BG_GAP
    M = (W - grid_w) // 2
    head_h = 230
    H = head_h + CH * 9 + 6 * IN_GAP + 2 * BG_GAP + 16 * 3 + 90
    img = Image.new("RGB", (W, H), BG)
    dr = ImageDraw.Draw(img)

    closed, total = core.tasks_closed(grid, prog)
    hd = core.habits_for_day(grid, today)
    done_today = sum(1 for h in hd if h["code"] in prog.habits_on(today))
    nxt = core.next_checkpoint(grid, today)
    y = _header(dr, W, "КАРТА ЦЕЛИ 9×9", f"{WD[today.weekday()]} · {date_ru(today, True)}",
                f"{grid['goal']['title']} · до {core.d(grid['goal']['deadline']).strftime('%d.%m.%Y')}")
    # три метрики в линию
    cols = [("ЗАДАЧИ", f"{closed} / {total}", closed / total if total else 0),
            ("ПРИВЫЧКИ СЕГОДНЯ", f"{done_today} / {len(hd)}", done_today / len(hd) if hd else 0)]
    if nxt:
        i, c = nxt
        start = core.period_start(grid, i)
        span = max(1, (c - start).days)
        cols.append((f"ЧЕК-ПОИНТ {i} · {c.strftime('%d.%m')}", in_days((c - today).days), min(1, (today - start).days / span)))
    cw = (W - 2 * 40 - 2 * 40) // 3
    for k, (lab, val, frac) in enumerate(cols):
        x = 40 + k * (cw + 40)
        dr.text((x, y), lab, font=font("Bold", 15), fill=MUTED)
        vw = dr.textlength(val, font=font("Bold", 22))
        dr.text((x + cw - vw, y - 5), val, font=font("Bold", 22), fill=TEXT)
        bar(dr, x, y + 30, cw, 10, frac)
    top = head_h - 10

    for bi in range(9):
        br, bc = divmod(bi, 3)
        bx = M + bc * (3 * CW + 2 * IN_GAP + BG_GAP)
        by = top + br * (3 * CH + 2 * IN_GAP + BG_GAP + 16)
        center = (br, bc) == (1, 1)
        dr.rounded_rectangle((bx - 6, by - 6, bx + 3 * CW + 2 * IN_GAP + 6, by + 3 * CH + 2 * IN_GAP + 6), 14,
                             fill=Y_DIM if center else PANEL)
        for r in range(3):
            for c in range(3):
                x = bx + c * (CW + IN_GAP)
                yy = by + r * (CH + IN_GAP)
                box = (x, yy, x + CW, yy + CH)
                if center:
                    if (r, c) == (1, 1):
                        _goal_cell(dr, box, grid, prog)
                    else:
                        _pillar_cell(dr, box, grid, prog, POS.index((r, c)), mirror=True)
                else:
                    pi = POS.index((br, bc))
                    if (r, c) == (1, 1):
                        _pillar_cell(dr, box, grid, prog, pi, mirror=False)
                    else:
                        _slot_cell(dr, box, grid["pillars"][pi]["slots"][POS.index((r, c))], prog, today)

    fy = H - 60
    dr.text((40, fy), "★ старт   ↻ привычка   ■ шаг сделан   ✓ закрыто", font=font("Medium", 19), fill=MUTED)
    cmd = "/today · /habits · /progress"
    dr.text((W - 40 - dr.textlength(cmd, font=font("SemiBold", 19)), fy), cmd, font=font("SemiBold", 19), fill=Y)
    return _png(img)


def _goal_cell(dr, box, grid, prog):
    x0, y0, x1, y1 = box
    dr.rounded_rectangle(box, 10, fill=BG, outline=Y, width=3)
    w = x1 - x0 - 20
    f, lines, step = fit_text(dr, grid["goal"]["title"].upper(), "Black", 19, w, 78, lh=1.12)
    yy = draw_lines(dr, (x0 + 10, y0 + 18), lines, f, step, Y, center_w=w)
    closed, total = core.tasks_closed(grid, prog)
    frac = sum(core.pillar_progress(grid, prog, p["id"]) for p in grid["pillars"]) / 8
    t = f"{core.pct(frac)} пути"
    dr.text((x0 + 10 + (w - dr.textlength(t, font=font("Bold", 16))) / 2, y1 - 52), t, font=font("Bold", 16), fill=TEXT)
    bar(dr, x0 + 14, y1 - 24, x1 - x0 - 28, 8, frac)


def _pillar_cell(dr, box, grid, prog, pi, mirror):
    x0, y0, x1, y1 = box
    p = grid["pillars"][pi]
    frac = core.pillar_progress(grid, prog, p["id"])
    w = x1 - x0 - 20
    if mirror:
        dr.rounded_rectangle(box, 10, fill=CELL_HI)
        dr.text((x0 + 12, y0 + 12), f"0{p['id']}", font=font("Bold", 14), fill=Y_DIM)
        f, lines, step = fit_text(dr, p["name"], "Black", 19, w, 50, lh=1.1)
        draw_lines(dr, (x0 + 10, y0 + 40), lines, f, step, Y, center_w=w)
        t = core.pct(frac)
        dr.text((x0 + 10 + (w - dr.textlength(t, font=font("Bold", 18))) / 2, y1 - 54), t, font=font("Bold", 18), fill=TEXT)
        bar(dr, x0 + 14, y1 - 24, x1 - x0 - 28, 8, frac)
        return
    dr.rounded_rectangle(box, 10, fill=Y)
    dr.text((x0 + 12, y0 + 10), f"0{p['id']}", font=font("Bold", 14), fill=(110, 40, 0))
    f, lines, step = fit_text(dr, p["name"], "Black", 20, w, 50, lh=1.08)
    yy = draw_lines(dr, (x0 + 10, y0 + 34), lines, f, step, INK, center_w=w)
    if p.get("kpi"):
        f2, l2, s2 = fit_text(dr, p["kpi"], "SemiBold", 14, w, 36, lh=1.15)
        draw_lines(dr, (x0 + 10, yy + 4), l2, f2, s2, (70, 26, 0), center_w=w)
    bar(dr, x0 + 14, y1 - 22, x1 - x0 - 28, 8, frac, fg=INK, bg=(196, 78, 0))


def _slot_cell(dr, box, s, prog, today):
    x0, y0, x1, y1 = box
    pad = 11
    w = x1 - x0 - 2 * pad
    if s["type"] == "habit":
        on = s["code"] in prog.habits_on(today)
        dr.rounded_rectangle(box, 10, fill=Y_DARK if on else CELL, outline=Y if on else None, width=2)
        tag = f"↻ {s['code']} · {s['freq']}"
        dr.text((x0 + pad, y0 + 9), tag, font=font("Bold", 13), fill=Y)
        f, lines, step = fit_text(dr, s["text"], "Medium", 17, w, CH_TEXT, lh=1.2)
        draw_lines(dr, (x0 + pad, y0 + 34), lines, f, step, TEXT)
        lab = "сегодня ✓" if on else "сегодня —"
        dr.text((x0 + pad, y1 - 28), lab, font=font("SemiBold", 14), fill=Y if on else MUTED)
        return
    done = core.task_steps_done(prog, s)
    closed = done >= s["steps"]
    dr.rounded_rectangle(box, 10, fill=Y_DARK if closed else CELL, outline=Y if closed else None, width=2)
    ty = y0 + 12
    if s.get("star"):
        star(dr, x0 + pad + 7, y0 + 17, 8, Y)
        dr.text((x0 + pad + 19, y0 + 9), "СТАРТ", font=font("Bold", 12), fill=Y)
    if closed:
        check(dr, x1 - 34, y0 + 6, 26, Y, width=4)
    ty = y0 + 34
    # шаги
    n = s["steps"]
    sq, gap = (12, 4) if n <= 16 else (9, 3)
    per_row = max(1, (w + gap) // (sq + gap))
    rows = math.ceil(n / per_row)
    steps_h = rows * (sq + gap)
    f, lines, step = fit_text(dr, s["text"], "Medium", 17, w, y1 - 14 - steps_h - ty - 4, lh=1.2)
    draw_lines(dr, (x0 + pad, ty), lines, f, step, MUTED if closed else TEXT, strike=closed)
    sy = y1 - 12 - steps_h
    for i in range(n):
        rx = x0 + pad + (i % per_row) * (sq + gap)
        ry = sy + (i // per_row) * (sq + gap)
        if i < done:
            dr.rounded_rectangle((rx, ry, rx + sq, ry + sq), 2, fill=Y)
        else:
            dr.rounded_rectangle((rx, ry, rx + sq, ry + sq), 2, outline=Y_DIM, width=2)


CH_TEXT = 90


# ======================================================================
# 2. Утро: фокус дня + привычки
# ======================================================================
def render_today(grid: dict, prog: core.Progress, today: dt.date, focus: list[dict], focus_done: set[str] | None = None) -> bytes:
    focus_done = focus_done or set()
    W = 1080
    hs = core.habits_for_day(grid, today)
    H = 250 + len(focus) * 128 + 90 + math.ceil(len(hs) / 2) * 62 + 150
    img = Image.new("RGB", (W, H), BG)
    dr = ImageDraw.Draw(img)
    y = _header(dr, W, f"{WD[today.weekday()].upper()} · {date_ru(today).upper()}", "утренний ритуал", grid["goal"]["title"])
    dr.text((40, y), "ФОКУС ДНЯ", font=font("Black", 26), fill=Y)
    y += 48
    names = {p["id"]: p["name"] for p in grid["pillars"]}
    for i, t in enumerate(focus):
        done_now = t["id"] in focus_done
        box = (40, y, W - 40, y + 112)
        dr.rounded_rectangle(box, 14, fill=Y_DARK if done_now else CELL, outline=Y if done_now else LINE, width=2)
        dr.ellipse((60, y + 30, 112, y + 82), fill=Y if done_now else BG, outline=Y, width=3)
        if done_now:
            check(dr, 70, y + 40, 32, INK, width=5)
        else:
            nt = str(i + 1)
            dr.text((86 - dr.textlength(nt, font=font("Black", 26)) / 2, y + 40), nt, font=font("Black", 26), fill=Y)
        meta = f"0{t['pillar']} {names[t['pillar']]}" + ("  ★" if t.get("star") else "")
        dr.text((136, y + 18), meta, font=font("Bold", 16), fill=Y if t.get("star") else MUTED)
        f, lines, step = fit_text(dr, t["text"], "SemiBold", 26, W - 40 - 136 - 170, 60, lh=1.15)
        draw_lines(dr, (136, y + 44), lines, f, step, MUTED if done_now else TEXT, strike=done_now)
        sd = core.task_steps_done(prog, t)
        lab = f"шаг {min(sd + 1, t['steps'])} из {t['steps']}" if t["steps"] > 1 else "1 шаг"
        lw = dr.textlength(lab, font=font("SemiBold", 18))
        dr.text((W - 64 - lw, y + 20), lab, font=font("SemiBold", 18), fill=MUTED)
        bar(dr, W - 64 - 130, y + 62, 130, 10, sd / t["steps"])
        y += 128
    y += 14
    dr.text((40, y), "ПРИВЫЧКИ СЕГОДНЯ", font=font("Black", 26), fill=Y)
    y += 50
    colw = (W - 80 - 20) // 2
    for k, h in enumerate(hs):
        cx = 40 + (k % 2) * (colw + 20)
        cy = y + (k // 2) * 62
        on = h["code"] in prog.habits_on(today)
        dr.rounded_rectangle((cx, cy, cx + colw, cy + 50), 12, fill=Y_DARK if on else CELL, outline=Y if on else None, width=2)
        dr.rounded_rectangle((cx + 12, cy + 12, cx + 38, cy + 38), 6, fill=Y if on else None, outline=Y, width=2)
        if on:
            check(dr, cx + 13, cy + 13, 24, INK, width=4)
        dr.text((cx + 52, cy + 13), h["code"], font=font("Black", 19), fill=Y)
        f, lines, _ = fit_text(dr, h["text"], "Medium", 19, colw - 110, 26, lh=1.1)
        dr.text((cx + 52 + dr.textlength(h["code"] + " ", font=font("Black", 19)), cy + 13), lines[0], font=f, fill=TEXT)
    y += math.ceil(len(hs) / 2) * 62 + 20
    nxt = core.next_checkpoint(grid, today)
    goal_days = (core.d(grid["goal"]["deadline"]) - today).days
    foot = (f"Чек-поинт {nxt[0]} {in_days((nxt[1] - today).days)}" if nxt else "Все чек-поинты пройдены") + f"  ·  до цели {goal_days} дн"
    dr.rounded_rectangle((40, y, W - 40, y + 64), 14, fill=Y)
    dr.text((64, y + 17), foot, font=font("Bold", 24), fill=INK)
    return _png(img.crop((0, 0, W, y + 100)))


# ======================================================================
# 3. Трекер привычек (тепловая карта)
# ======================================================================
def render_habits(grid: dict, prog: core.Progress, start: dt.date, end: dt.date, today: dt.date) -> bytes:
    hs = core.habits(grid)
    days = [start + dt.timedelta(i) for i in range((end - start).days + 1)]
    W = 1600
    LAB, RATE = 400, 90
    cw = (W - 80 - LAB - RATE) / len(days)
    sq = min(30, int(cw) - 6)
    RH = 52
    H = 210 + 70 + len(hs) * RH + 120
    img = Image.new("RGB", (W, H), BG)
    dr = ImageDraw.Draw(img)
    y = _header(dr, W, "ТРЕКЕР ПРИВЫЧЕК", f"{date_ru(start)} – {date_ru(end, True)}")
    gx = 40 + LAB
    for i, day in enumerate(days):
        x = gx + i * cw
        if day.weekday() >= 5:
            dr.rectangle((x, y, x + cw, y + 60 + len(hs) * RH), fill=PANEL)
        if day == today:
            dr.rectangle((x, y, x + cw, y + 60 + len(hs) * RH), outline=Y, width=2)
        t = str(day.day)
        dr.text((x + (cw - dr.textlength(t, font=font("Bold", 17))) / 2, y + 8), t, font=font("Bold", 17), fill=Y if day == today else TEXT)
        t = WD[day.weekday()]
        dr.text((x + (cw - dr.textlength(t, font=font("Medium", 12))) / 2, y + 32), t, font=font("Medium", 12), fill=MUTED)
    dr.text((W - 40 - RATE + 14, y + 20), "итог", font=font("Bold", 15), fill=MUTED)
    y += 60
    for h in hs:
        dr.line((40, y, W - 40, y), fill=LINE, width=1)
        dr.text((40, y + 14), h["code"], font=font("Black", 19), fill=Y)
        f, lines, _ = fit_text(dr, h["text"], "Medium", 19, LAB - 70 - 10, 24, lh=1.1)
        dr.text((40 + 56, y + 14), lines[0], font=f, fill=TEXT)
        fr = h["freq"]
        dr.text((40 + LAB - 10 - dr.textlength(fr, font=font("Medium", 13)), y + 34), fr, font=font("Medium", 13), fill=MUTED)
        for i, day in enumerate(days):
            x = gx + i * cw + (cw - sq) / 2
            yy = y + (RH - sq) / 2
            on = h["code"] in prog.habits_on(day)
            sched = core.habit_scheduled(h, day)
            if on:
                dr.rounded_rectangle((x, yy, x + sq, yy + sq), 5, fill=Y)
            elif not sched:
                dr.rounded_rectangle((x, yy, x + sq, yy + sq), 5, fill=(24, 25, 28))
            elif day > today:
                dr.rounded_rectangle((x, yy, x + sq, yy + sq), 5, outline=(46, 48, 54), width=2)
            else:
                dr.rounded_rectangle((x, yy, x + sq, yy + sq), 5, outline=Y_DIM, width=2)
        r = core.habit_rate(grid, prog, h["code"], start, min(end, today))
        t = core.pct(r)
        dr.text((W - 40 - dr.textlength(t, font=font("Bold", 20)), y + 14), t, font=font("Bold", 20), fill=Y if (r or 0) >= .8 else TEXT)
        y += RH
    dr.line((40, y, W - 40, y), fill=LINE, width=1)
    avg = core.habits_rate(grid, prog, start, min(end, today))
    y += 26
    dr.text((40, y), f"Средний % за период: {core.pct(avg)}", font=font("Bold", 24), fill=TEXT)
    legend = "■ сделано   □ пропущено   ▪ выходной для привычки"
    dr.text((W - 40 - dr.textlength(legend, font=font("Medium", 18)), y + 4), legend, font=font("Medium", 18), fill=MUTED)
    return _png(img.crop((0, 0, W, y + 70)))


# ======================================================================
# 4. Прогресс и чек-поинты
# ======================================================================
def render_progress(grid: dict, prog: core.Progress, today: dt.date, title: str = "ПРОГРЕСС", extra: dict | None = None) -> bytes:
    W, H = 1080, 1240
    img = Image.new("RGB", (W, H), BG)
    dr = ImageDraw.Draw(img)
    y = _header(dr, W, title, date_ru(today, True), grid["goal"]["title"])
    closed, total = core.tasks_closed(grid, prog)
    path = sum(core.pillar_progress(grid, prog, p["id"]) for p in grid["pillars"]) / 8
    h30 = core.habits_rate(grid, prog, max(core.d(grid["goal"]["start"]), today - dt.timedelta(29)), today)
    tiles = [("ПУТЬ К ЦЕЛИ", core.pct(path)), ("ЗАДАЧ ЗАКРЫТО", f"{closed}/{total}"), ("ПРИВЫЧКИ · 30 ДН", core.pct(h30))]
    if extra:
        tiles = list(extra.items())[:3] if len(extra) >= 3 else tiles[: 3 - len(extra)] + list(extra.items())
    tw = (W - 80 - 2 * 20) // 3
    for k, (lab, val) in enumerate(tiles):
        x = 40 + k * (tw + 20)
        hi = k == 0
        dr.rounded_rectangle((x, y, x + tw, y + 150), 16, fill=Y if hi else CELL)
        dr.text((x + 22, y + 20), lab, font=font("Bold", 16), fill=INK if hi else MUTED)
        dr.text((x + 22, y + 52), str(val), font=font("Black", 58), fill=INK if hi else TEXT)
    y += 190
    dr.text((40, y), "БЛОКИ", font=font("Black", 26), fill=Y)
    y += 48
    for p in grid["pillars"]:
        fr = core.pillar_progress(grid, prog, p["id"])
        dr.text((40, y + 2), f"0{p['id']}", font=font("Bold", 18), fill=Y_DIM)
        dr.text((84, y), p["name"], font=font("Bold", 22), fill=TEXT)
        bar(dr, 380, y + 8, W - 40 - 380 - 90, 16, fr)
        t = core.pct(fr)
        dr.text((W - 40 - dr.textlength(t, font=font("Bold", 22)), y), t, font=font("Bold", 22), fill=Y if fr >= 1 else TEXT)
        y += 50
    y += 26
    dr.text((40, y), "ЧЕК-ПОИНТЫ", font=font("Black", 26), fill=Y)
    y += 70
    start, end = core.d(grid["goal"]["start"]), core.d(grid["goal"]["deadline"])
    x0, x1 = 70, W - 70
    span = (end - start).days

    def px(day):
        return x0 + (x1 - x0) * max(0, min(1, (day - start).days / span))

    dr.line((x0, y, x1, y), fill=LINE, width=6)
    dr.line((x0, y, px(today), y), fill=Y, width=6)
    cps = core.checkpoints(grid)
    for i, c in enumerate(cps):
        cx = px(c)
        passed = c < today
        dr.ellipse((cx - 14, y - 14, cx + 14, y + 14), fill=Y if passed else BG, outline=Y, width=4)
        lab = "ФИНАЛ" if i == len(cps) - 1 else f"ЧП {i + 1}"
        dr.text((cx - dr.textlength(lab, font=font("Bold", 16)) / 2, y - 46), lab, font=font("Bold", 16), fill=Y)
        t = c.strftime("%d.%m.%y")
        dr.text((cx - dr.textlength(t, font=font("Medium", 15)) / 2, y + 24), t, font=font("Medium", 15), fill=MUTED)
    tx = px(today)
    dr.polygon([(tx - 9, y + 64), (tx + 9, y + 64), (tx, y + 50)], fill=TEXT)
    t = "сегодня"
    dr.text((tx - dr.textlength(t, font=font("SemiBold", 15)) / 2, y + 68), t, font=font("SemiBold", 15), fill=TEXT)
    y += 122
    nxt = core.next_checkpoint(grid, today)
    foot = f"Следующий: чек-поинт {nxt[0]} · {nxt[1].strftime('%d.%m.%Y')} · {in_days((nxt[1] - today).days)}" if nxt else "Финал пройден"
    dr.rounded_rectangle((40, y, W - 40, y + 66), 14, fill=Y)
    dr.text((64, y + 18), foot, font=font("Bold", 24), fill=INK)
    return _png(img.crop((0, 0, W, y + 100)))
