#!/usr/bin/env python3
# =============================================================================
# simulate.py — Mac Simulator for Space Shooter SPI Project
# THD Case Study A06 — Group A06
#
# Simulates BOTH Pi A (master) and Pi B (slave) on a single Mac.
# Replaces all hardware (GPIO, SPI, I2C, LCD) with software mocks.
#
# Controls:
#   P1 (Pi A):  WASD = move,  SPACE = shoot
#   P2 (Pi B):  Arrow Keys  = move,  ENTER = shoot
#   ESC: Quit
#
# Run: python3 simulate.py  (or /opt/homebrew/bin/python3.11 simulate.py)
# =============================================================================

import sys
import time
import csv
import os
import threading
import queue
import pygame
from PIL import Image
import io

# =============================================================================
# PYGAME INIT
# =============================================================================
pygame.init()
pygame.font.init()

LCD_WIDTH   = 480
LCD_HEIGHT  = 320
SCALE       = 2             # 2x upscale so it's comfortable on a Mac display

screen = pygame.display.set_mode((LCD_WIDTH * SCALE, LCD_HEIGHT * SCALE))
pygame.display.set_caption("Space Shooter SPI — Simulator (Pi A + Pi B)")
clock  = pygame.time.Clock()

# Fonts
FONT_SM  = pygame.font.SysFont("Arial", 13)
FONT_MD  = pygame.font.SysFont("Arial", 20, bold=True)
FONT_LG  = pygame.font.SysFont("Arial", 36, bold=True)
FONT_XL  = pygame.font.SysFont("Arial", 64, bold=True)

# Colors (RGB)
C_BG      = (5,   10,  30)
C_STAR    = (200, 200, 255)
C_P1      = (0,   220, 120)
C_P2      = (255, 70,  70)
C_BULL_P1 = (0,   240, 240)
C_BULL_P2 = (255, 220, 0)
C_HUD     = (180, 180, 255)
C_WHITE   = (255, 255, 255)
C_MENU_BG = (10,  15,  50)
C_ACCENT  = (80,  140, 255)
C_GOLD    = (255, 200, 50)

# =============================================================================
# HARDWARE CONSTANTS (mirror from master.py)
# =============================================================================
FRAME_TIME        = 0.0333
SHIP_W            = 22
SHIP_H            = 22
BULLET_W          = 6
BULLET_H          = 4
BULLET_SPEED      = 8
SHIP_SPEED        = 4
MAX_LIVES         = 3
LOG_BUFFER_MAX    = 60
DEAD_RECK_LIMIT   = 2
AXIS_CENTER       = 32767

# =============================================================================
# SIMULATED SPI QUEUE (replaces physical SPI wire)
# Pi B puts packets here → Pi A reads from here (and vice versa)
# =============================================================================
spi_pb_to_pa = queue.Queue(maxsize=2)   # Pi B → Pi A
spi_pa_to_pb = queue.Queue(maxsize=2)   # Pi A → Pi B

# =============================================================================
# GAME STATE (shared between both simulated nodes)
# =============================================================================
p1_lives  = MAX_LIVES
p2_lives  = MAX_LIVES
p1_score  = 0
p2_score  = 0
game_state = "playing"        # start directly in playing mode
winner     = None

p1_x = LCD_WIDTH  // 4
p1_y = LCD_HEIGHT // 2
p2_x = (LCD_WIDTH * 3) // 4
p2_y = LCD_HEIGHT // 2

bullets = []               # [x, y, owner, direction]

p1_name = "Player 1"
p2_name = "Player 2"

# =============================================================================
# KEYBOARD STATE (mock for joystick + buttons)
# =============================================================================
keys_held   = set()
key_events  = []           # (key, type)  — filled by pygame event loop

# P1 shoot / P2 shoot (one-shot per press)
p1_shot_this_frame = False
p2_shot_this_frame = False

demo_frames = []
demo_game_over_frames = 0

# =============================================================================
# DATA LOGGER (Module 6 — from master.py)
# =============================================================================
log_buffer = []
LOG_PATH   = os.path.join(os.path.dirname(__file__), "logs", "game_log.csv")
log_file   = None

def data_logger_init():
    global log_file
    os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
    log_file = open(LOG_PATH, "a", newline="")
    writer = csv.writer(log_file)
    writer.writerow(["timestamp", "fps", "cpu_temp", "spi_latency_ms",
                     "p1_lives", "p2_lives", "error"])
    log_file.flush()

def data_logger(fps, spi_latency_ms, error="None"):
    global log_buffer
    ts  = time.strftime("%H:%M:%S") + f":{int((time.time() % 1)*1000):03d}"
    row = [ts, f"{fps:.1f}", "N/A", f"{spi_latency_ms:.2f}",
           p1_lives, p2_lives, error]
    log_buffer.append(row)
    if len(log_buffer) >= LOG_BUFFER_MAX:
        _flush_log()

def _flush_log():
    global log_buffer
    if log_file and log_buffer:
        csv.writer(log_file).writerows(log_buffer)
        log_file.flush()
        log_buffer = []

def data_logger_close():
    _flush_log()
    if log_file:
        log_file.close()

# =============================================================================
# STAR FIELD (background decoration)
# =============================================================================
import random
random.seed(42)
STARS = [(random.randint(0, LCD_WIDTH-1), random.randint(0, LCD_HEIGHT-1),
          random.choice([1, 1, 1, 2])) for _ in range(80)]

star_scroll = 0

# =============================================================================
# SPI SIMULATION (Module 4 + 5)
# =============================================================================

def spi_master_sim():
    """
    Module 4 (simulated): Get P2 input from the SPI queue.
    Returns (x, y, btn, ok).
    """
    t0 = time.time()
    try:
        packet = spi_pb_to_pa.get_nowait()
        spi_latency = (time.time() - t0) * 1000

        # Validate header
        if packet[0] != 0xFF:
            return AXIS_CENTER, AXIS_CENTER, 0, False, spi_latency

        x_h, x_l, y_h, y_l, btn = packet[1], packet[2], packet[3], packet[4], packet[5]
        cs_calc = x_h ^ x_l ^ y_h ^ y_l ^ btn
        if cs_calc != packet[8]:
            return AXIS_CENTER, AXIS_CENTER, 0, False, spi_latency

        x = (x_h << 8) | x_l
        y = (y_h << 8) | y_l

        # Send game state back to Pi B
        _send_game_state_sim()

        return x, y, btn, True, spi_latency

    except queue.Empty:
        return AXIS_CENTER, AXIS_CENTER, 0, False, 0.0


def _send_game_state_sim():
    winner_byte = 0x01 if winner == p1_name else (0x02 if winner == p2_name else 0x00)
    state_byte  = 0xEE if game_state == "game_over" else 0x01
    data = [state_byte, p1_lives, p2_lives,
            (p1_score >> 8) & 0xFF, p1_score & 0xFF,
            (p2_score >> 8) & 0xFF, p2_score & 0xFF,
            winner_byte, 0x00]
    cs = 0
    for b in data[:-1]:
        cs ^= b
    data[8] = cs
    try:
        spi_pa_to_pb.put_nowait(data)
    except queue.Full:
        pass


def spi_slave_push(jx, jy, btn):
    """
    Module 5 (simulated): Pi B builds a packet and puts it in the SPI queue.
    """
    x_h = (jx >> 8) & 0xFF
    x_l =  jx       & 0xFF
    y_h = (jy >> 8) & 0xFF
    y_l =  jy       & 0xFF
    cs  = x_h ^ x_l ^ y_h ^ y_l ^ btn
    packet = [0xFF, x_h, x_l, y_h, y_l, btn, 0x00, 0x00, cs]
    try:
        spi_pb_to_pa.put_nowait(packet)
    except queue.Full:
        pass

# =============================================================================
# HELPERS
# =============================================================================

def _normalize_key_axis(neg_key, pos_key):
    """Map two keys to -1, 0, +1."""
    val = 0
    if neg_key in keys_held:
        val -= 1
    if pos_key in keys_held:
        val += 1
    return val

def _clamp(val, lo, hi):
    return max(lo, min(hi, val))

def _rect_overlap(ax, ay, aw, ah, bx, by, bw, bh):
    return (ax < bx + bw and ax + aw > bx and
            ay < by + bh and ay + ah > by)

def _axis_from_key(neg, pos):
    """Return 16-bit axis value from key state."""
    d = 0
    if neg in keys_held:  d -= 1
    if pos in keys_held:  d += 1
    return AXIS_CENTER + d * 30000

# =============================================================================
# DRAWING HELPERS
# =============================================================================

def _surf():
    """Return the logical (pre-scale) surface."""
    return pygame.Surface((LCD_WIDTH, LCD_HEIGHT))

def blit_scaled(surf):
    scaled = pygame.transform.scale(surf, (LCD_WIDTH * SCALE, LCD_HEIGHT * SCALE))
    screen.blit(scaled, (0, 0))
    pygame.display.flip()

def draw_bg(surf):
    surf.fill(C_BG)
    global star_scroll
    star_scroll = (star_scroll + 1) % LCD_WIDTH
    for sx, sy, size in STARS:
        x = (sx - star_scroll) % LCD_WIDTH
        pygame.draw.circle(surf, C_STAR, (x, sy), size)

def draw_ship(surf, x, y, color, facing_right=True):
    """Draw a simple spaceship triangle."""
    if facing_right:
        pts = [(x, y + SHIP_H//2), (x + SHIP_W, y), (x + SHIP_W, y + SHIP_H)]
    else:
        pts = [(x + SHIP_W, y + SHIP_H//2), (x, y), (x, y + SHIP_H)]
    pygame.draw.polygon(surf, color, pts)
    # Cockpit
    cx = x + SHIP_W//2
    cy = y + SHIP_H//2
    pygame.draw.circle(surf, C_WHITE, (cx, cy), 3)

def draw_heart(surf, x, y, color):
    pygame.draw.circle(surf, color, (x + 4, y + 4), 4)
    pygame.draw.circle(surf, color, (x + 10, y + 4), 4)
    pts = [(x, y + 5), (x + 7, y + 14), (x + 14, y + 5)]
    pygame.draw.polygon(surf, color, pts)

def draw_hud(surf):
    # Top bar
    pygame.draw.rect(surf, (15, 20, 60), (0, 0, LCD_WIDTH, 20))

    # P1 lives
    lbl = FONT_SM.render(f"{p1_name}", True, C_P1)
    surf.blit(lbl, (4, 3))
    for i in range(p1_lives):
        draw_heart(surf, 70 + i * 16, 3, C_P2)

    # P1 score
    s1 = FONT_SM.render(f"{p1_score}pts", True, C_HUD)
    surf.blit(s1, (130, 3))

    # Divider
    pygame.draw.line(surf, C_ACCENT, (LCD_WIDTH//2, 0), (LCD_WIDTH//2, 20), 1)

    # P2 lives
    lbl2 = FONT_SM.render(f"{p2_name}", True, C_P2)
    surf.blit(lbl2, (LCD_WIDTH//2 + 4, 3))
    for i in range(p2_lives):
        draw_heart(surf, LCD_WIDTH//2 + 70 + i * 16, 3, C_P2)

    # P2 score
    s2 = FONT_SM.render(f"{p2_score}pts", True, C_HUD)
    surf.blit(s2, (LCD_WIDTH//2 + 130, 3))

def draw_divider(surf):
    # Center dashed line
    for y in range(24, LCD_HEIGHT, 12):
        pygame.draw.line(surf, (40, 50, 100), (LCD_WIDTH//2, y), (LCD_WIDTH//2, y+6), 1)

def draw_controls_hint(surf):
    hints = [
        "P1: WASD + SPACE",
        "P2: Arrows + ENTER",
        "ESC: Quit"
    ]
    for i, h in enumerate(hints):
        t = FONT_SM.render(h, True, (80, 90, 130))
        surf.blit(t, (4, LCD_HEIGHT - 14 * (len(hints) - i)))

# =============================================================================
# SCREEN: MAIN MENU
# =============================================================================

def screen_main_menu(surf):
    surf.fill(C_MENU_BG)

    # Title
    title = FONT_XL.render("SPACE", True, C_ACCENT)
    sub   = FONT_XL.render("SHOOTER", True, C_GOLD)
    surf.blit(title,  (LCD_WIDTH//2 - title.get_width()//2,  30))
    surf.blit(sub,    (LCD_WIDTH//2 - sub.get_width()//2,    95))

    # Subtitle
    tag = FONT_SM.render("SPI Edition — THD Case Study A06", True, (100, 110, 160))
    surf.blit(tag, (LCD_WIDTH//2 - tag.get_width()//2, 158))

    # Button
    btn_rect = pygame.Rect(LCD_WIDTH//2 - 110, 190, 220, 38)
    pygame.draw.rect(surf, C_ACCENT, btn_rect, border_radius=8)
    btn_t = FONT_MD.render("HOST MULTIPLAYER [M]", True, C_WHITE)
    surf.blit(btn_t, (btn_rect.x + btn_rect.w//2 - btn_t.get_width()//2,
                      btn_rect.y + 8))

    draw_controls_hint(surf)


# =============================================================================
# SCREEN: WAITING / COUNTDOWN
# =============================================================================

def screen_waiting(surf, text, sub=""):
    surf.fill(C_MENU_BG)
    t = FONT_LG.render(text, True, C_WHITE)
    surf.blit(t, (LCD_WIDTH//2 - t.get_width()//2, LCD_HEIGHT//2 - 30))
    if sub:
        s = FONT_SM.render(sub, True, C_HUD)
        surf.blit(s, (LCD_WIDTH//2 - s.get_width()//2, LCD_HEIGHT//2 + 20))


# =============================================================================
# SCREEN: GAME OVER
# =============================================================================

def screen_game_over(surf):
    surf.fill((5, 5, 20))
    go = FONT_LG.render("GAME OVER", True, C_GOLD)
    surf.blit(go, (LCD_WIDTH//2 - go.get_width()//2, 60))

    wt = FONT_MD.render(f"Winner: {winner}", True, C_WHITE)
    surf.blit(wt, (LCD_WIDTH//2 - wt.get_width()//2, 120))

    s1 = FONT_MD.render(f"{p1_name}: {p1_score} pts", True, C_P1)
    s2 = FONT_MD.render(f"{p2_name}: {p2_score} pts", True, C_P2)
    surf.blit(s1, (LCD_WIDTH//2 - s1.get_width()//2, 160))
    surf.blit(s2, (LCD_WIDTH//2 - s2.get_width()//2, 192))

    restart = FONT_SM.render("Press R to restart  |  ESC to quit", True, (100, 110, 160))
    surf.blit(restart, (LCD_WIDTH//2 - restart.get_width()//2, 260))

    log_t = FONT_SM.render(f"Log saved: {LOG_PATH}", True, (60, 70, 100))
    surf.blit(log_t, (LCD_WIDTH//2 - log_t.get_width()//2, 290))


# =============================================================================
# GAME RESET
# =============================================================================

def reset_game():
    global p1_lives, p2_lives, p1_score, p2_score, game_state, winner
    global p1_x, p1_y, p2_x, p2_y, bullets
    p1_lives  = MAX_LIVES
    p2_lives  = MAX_LIVES
    p1_score  = 0
    p2_score  = 0
    game_state = "menu"
    winner     = None
    p1_x = LCD_WIDTH  // 4
    p1_y = LCD_HEIGHT // 2
    p2_x = (LCD_WIDTH * 3) // 4
    p2_y = LCD_HEIGHT // 2
    bullets = []


# =============================================================================
# MAIN LOOP
# =============================================================================

def main():
    global game_state, winner
    global p1_lives, p2_lives, p1_score, p2_score
    global p1_x, p1_y, p2_x, p2_y, bullets
    global p1_shot_this_frame, p2_shot_this_frame
    global keys_held

    data_logger_init()

    countdown_start  = None
    countdown_val    = 3
    connect_done     = False
    p2_last_valid    = (AXIS_CENTER, AXIS_CENTER, 0)
    miss_frames      = 0
    frame_no         = 0
    global demo_game_over_frames

    running = True
    while running:
        frame_start = time.time()
        p1_shot_this_frame = False
        p2_shot_this_frame = False

        # ----------------------------------------------------------------
        # EVENT HANDLING
        # ----------------------------------------------------------------
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False

            elif event.type == pygame.KEYDOWN:
                keys_held.add(event.key)

                if event.key == pygame.K_ESCAPE:
                    running = False

                # Menu: M = host game
                if game_state == "menu" and event.key == pygame.K_m:
                    game_state = "waiting"
                    connect_done = False

                # Game over: R = restart
                if game_state == "game_over" and event.key == pygame.K_r:
                    reset_game()

                # Shoot (one-shot per keydown)
                if game_state == "playing":
                    if event.key == pygame.K_SPACE:
                        p1_shot_this_frame = True
                    if event.key == pygame.K_RETURN:
                        p2_shot_this_frame = True

            elif event.type == pygame.KEYUP:
                keys_held.discard(event.key)

        # ----------------------------------------------------------------
        # STATE MACHINE
        # ----------------------------------------------------------------
        surf = _surf()

        # ── MENU ──────────────────────────────────────────────────────
        if game_state == "menu":
            screen_main_menu(surf)

        # ── WAITING (simulate Pi B JOIN_ACK after 1 sec) ──────────────
        elif game_state == "waiting":
            if not connect_done:
                screen_waiting(surf, "Waiting for P2...", "Simulating Pi B SPI join")
                blit_scaled(surf)
                pygame.display.flip()
                time.sleep(1.0)           # simulate Pi B responding
                connect_done = True
                game_state = "countdown"
                countdown_start = time.time()
                countdown_val   = 3
                continue
            screen_waiting(surf, "Player 2 Connected!")

        # ── COUNTDOWN ─────────────────────────────────────────────────
        elif game_state == "countdown":
            elapsed = time.time() - countdown_start
            val = 3 - int(elapsed)
            if val <= 0:
                game_state = "playing"
            else:
                screen_waiting(surf, str(val), "Get ready!")

        # ── PLAYING ───────────────────────────────────────────────────
        elif game_state == "playing":
            frame_no += 1

            # -- AI for P2 (simulated Pi B) --
            p2_jx, p2_jy = AXIS_CENTER, AXIS_CENTER
            if p2_y + SHIP_H//2 < p1_y:
                p2_jy = AXIS_CENTER + 30000
            elif p2_y + SHIP_H//2 > p1_y + SHIP_H:
                p2_jy = AXIS_CENTER - 30000
            p2_btn = 1 if random.random() < 0.05 else 0
            spi_slave_push(p2_jx, p2_jy, p2_btn)

            # -- Module 4 (simulated Pi A): pull P2 data from SPI queue --
            spi_t0 = time.time()
            p2_jx_r, p2_jy_r, p2_btn_r, spi_ok, spi_lat = spi_master_sim()
            frame_error = "None" if spi_ok else "SPI_ERR"

            if spi_ok:
                p2_last_valid = (p2_jx_r, p2_jy_r, p2_btn_r)
                miss_frames   = 0
            else:
                miss_frames += 1
                if miss_frames > DEAD_RECK_LIMIT:
                    p2_jx_r, p2_jy_r, p2_btn_r = AXIS_CENTER, AXIS_CENTER, 0
                else:
                    p2_jx_r, p2_jy_r, p2_btn_r = p2_last_valid

            # -- AI for P1 (simulated Pi A) --
            p1_dx, p1_dy = 0, 0
            if p1_y + SHIP_H//2 < p2_y:
                p1_dy = 1
            elif p1_y + SHIP_H//2 > p2_y + SHIP_H:
                p1_dy = -1
            if random.random() < 0.05:
                p1_shot_this_frame = True

            # -- Update ship positions --
            p1_x = _clamp(int(p1_x + p1_dx * SHIP_SPEED), SHIP_W, LCD_WIDTH//2 - SHIP_W*2)
            p1_y = _clamp(int(p1_y + p1_dy * SHIP_SPEED), 22 + SHIP_H, LCD_HEIGHT - SHIP_H*2)

            def _norm16(v):
                d = v - AXIS_CENTER
                dz = 2000
                if abs(d) < dz: return 0.0
                return (d - dz * (1 if d > 0 else -1)) / (AXIS_CENTER - dz)

            p2_x = _clamp(int(p2_x + _norm16(p2_jx_r) * SHIP_SPEED),
                          LCD_WIDTH//2 + SHIP_W*2, LCD_WIDTH - SHIP_W*2)
            p2_y = _clamp(int(p2_y + _norm16(p2_jy_r) * SHIP_SPEED),
                          22 + SHIP_H, LCD_HEIGHT - SHIP_H*2)

            # -- Bullets --
            if p1_shot_this_frame:
                bullets.append([p1_x + SHIP_W, p1_y + SHIP_H//2, 1,  1])
            if p2_btn_r & 0x01:
                bullets.append([p2_x,          p2_y + SHIP_H//2, 2, -1])

            # Move + remove off-screen
            bullets = [[b[0] + b[3]*BULLET_SPEED, b[1], b[2], b[3]]
                       for b in bullets if 0 <= b[0] + b[3]*BULLET_SPEED <= LCD_WIDTH]

            # -- Collision --
            surviving = []
            for b in bullets:
                hit = False
                if b[2] == 1:
                    if _rect_overlap(b[0], b[1], BULLET_W, BULLET_H,
                                     p2_x, p2_y, SHIP_W, SHIP_H):
                        p2_lives -= 1
                        p1_score += 10
                        hit = True
                else:
                    if _rect_overlap(b[0], b[1], BULLET_W, BULLET_H,
                                     p1_x, p1_y, SHIP_W, SHIP_H):
                        p1_lives -= 1
                        p2_score += 10
                        hit = True
                if not hit:
                    surviving.append(b)
            bullets = surviving

            # -- Win condition --
            if p1_lives <= 0:
                winner, game_state = p2_name, "game_over"
            elif p2_lives <= 0:
                winner, game_state = p1_name, "game_over"

            # -- Render frame --
            draw_bg(surf)
            draw_divider(surf)
            draw_hud(surf)

            draw_ship(surf, p1_x, p1_y, C_P1, facing_right=True)
            draw_ship(surf, p2_x, p2_y, C_P2, facing_right=False)

            for b in bullets:
                col = C_BULL_P1 if b[2] == 1 else C_BULL_P2
                pygame.draw.rect(surf, col, (b[0], b[1], BULLET_W, BULLET_H))

            draw_controls_hint(surf)

            # -- SPI indicator --
            spi_col = (0, 200, 80) if spi_ok else (200, 50, 50)
            pygame.draw.circle(surf, spi_col, (LCD_WIDTH - 10, 10), 5)
            si = FONT_SM.render(f"SPI {spi_lat:.1f}ms", True, spi_col)
            surf.blit(si, (LCD_WIDTH - 80, 4))

            # -- Data logger --
            fps = clock.get_fps()
            data_logger(fps, spi_lat, frame_error)

        # ── GAME OVER ─────────────────────────────────────────────────
        elif game_state == "game_over":
            screen_game_over(surf)
            demo_game_over_frames += 1
            if demo_game_over_frames > 60: # 2 seconds of game over screen
                running = False

        # ----------------------------------------------------------------
        blit_scaled(surf)
        
        # Save frame to list
        frame_str = pygame.image.tostring(surf, 'RGB')
        demo_frames.append(frame_str)
        
        clock.tick(30)   # cap at 30 FPS

    # ----------------------------------------------------------------
    # CLEANUP
    # ----------------------------------------------------------------
    print(f"Generating demo.gif with {len(demo_frames)} frames...")
    images = [Image.frombytes("RGB", (LCD_WIDTH, LCD_HEIGHT), f) for f in demo_frames]
    if images:
        images[0].save('demo.gif', save_all=True, append_images=images[1:], duration=33, loop=0)
        print("Successfully generated demo.gif")
    data_logger_close()
    pygame.quit()
    sys.exit(0)


# =============================================================================
if __name__ == "__main__":
    main()
