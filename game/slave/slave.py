#!/usr/bin/env python3
# =============================================================================
# slave.py — Pi B (Slave Node)
# Space Shooter via SPI — THD Case Study A06
# Runs on: Raspberry Pi 1, BCM2835, ARMv6, 700MHz
# Role: P2 joystick reading + SPI Slave → forward data to Pi A only
# NO display — NO game logic
# =============================================================================

import RPi.GPIO as GPIO
import spidev
import smbus
import time
import threading

# =============================================================================
# HARDWARE CONSTANTS
# =============================================================================

# SPI
SPI_BUS       = 0
SPI_DEVICE    = 0          # CE0 → Pi A (master)
SPI_SPEED_HZ  = 1_000_000

# I2C (Joystick ADC)
I2C_BUS       = 1
ADC_ADDR      = 0x48       # ADS1x15 default address
ADC_X_CH      = 0          # X axis channel
ADC_Y_CH      = 1          # Y axis channel

# GPIO
GPIO_CE0_IN   = 8          # BCM pin 8 — CE0 input (monitor from Pi A)
GPIO_SHOOT_P2 = 17         # P2 shoot button
GPIO_MENU_P2  = 27         # P2 menu / extra button

# SPI Packet
PKT_SIZE      = 9
PKT_HEADER    = 0xFF

# Joystick
AXIS_CENTER   = 32767      # 16-bit midpoint
AXIS_MIN      = 0
AXIS_MAX      = 65535

# =============================================================================
# GLOBAL STATE
# =============================================================================

spi = None
bus = None

# Current joystick readings (updated by read loop, consumed by SPI handler)
_jx   = AXIS_CENTER
_jy   = AXIS_CENTER
_btn  = 0

# Received game state from Pi A
_p1_lives   = 3
_p2_lives   = 3
_p1_score   = 0
_p2_score   = 0
_game_state = 0x01         # 0x01=playing, 0xEE=game_over
_winner     = 0x00

_stop_event = threading.Event()

# =============================================================================
# MODULE 2 — Pi B STARTUP & JOIN
# =============================================================================

def startup():
    """
    Module 2: Initialize Pi B hardware, wait on SPI for JOIN_REQUEST,
    send JOIN_ACK, then enter spi_slave() loop.
    Flowchart steps 1-7.
    """
    global spi, bus

    # --- Step 1: Initialize Pi B ---
    GPIO.setmode(GPIO.BCM)
    GPIO.setwarnings(False)
    GPIO.setup(GPIO_CE0_IN,   GPIO.IN)
    GPIO.setup(GPIO_SHOOT_P2, GPIO.IN, pull_up_down=GPIO.PUD_UP)
    GPIO.setup(GPIO_MENU_P2,  GPIO.IN, pull_up_down=GPIO.PUD_UP)

    spi = spidev.SpiDev()
    spi.open(SPI_BUS, SPI_DEVICE)
    spi.max_speed_hz = SPI_SPEED_HZ
    spi.mode = 0

    try:
        bus = smbus.SMBus(I2C_BUS)
    except Exception:
        bus = None

    print("[Pi B] Initialized. Waiting on SPI line...")

    # --- Step 2: Wait silently on SPI line ---
    # --- Step 3: Wait for JOIN_REQUEST (0xA1) from Pi A ---
    while True:
        try:
            resp = spi.xfer2([0x00], SPI_SPEED_HZ, 0)
            if resp[0] == 0xA1:        # JOIN_REQUEST received
                break
        except Exception:
            pass
        time.sleep(0.05)

    # --- Step 4: Send JOIN_ACK (0xA2) to Pi A ---
    try:
        spi.xfer2([0xA2], SPI_SPEED_HZ, 0)
    except Exception:
        pass
    print("[Pi B] JOIN_ACK sent. Waiting for game start...")

    # --- Steps 5-6: Wait for first game data from Pi A ---
    while True:
        try:
            resp = spi.xfer2([0x00], SPI_SPEED_HZ, 0)
            if resp[0] != 0x00:        # any non-zero → game started
                break
        except Exception:
            pass
        time.sleep(0.05)

    print("[Pi B] Game started. Entering SPI slave loop.")

    # --- Step 7: Enter SPI slave ---
    spi_slave()


# =============================================================================
# MODULE 5 — SPI SLAVE (Pi B Background Thread)
# =============================================================================

def spi_slave():
    """
    Module 5: Main slave loop.
    Waits for CE0 LOW from Pi A, responds with joystick packet,
    then receives game state. Stops on game-over signal.
    """
    _stop_event.clear()

    # Start joystick polling in a background thread
    joystick_thread = threading.Thread(target=_joystick_poll_loop, daemon=True)
    joystick_thread.start()

    print("[Pi B] SPI slave loop running.")

    while not _stop_event.is_set():

        # --- Step 1: Wait for CE0 LOW (Pi A starts transaction) ---
        # On Pi 1 as SPI slave, we rely on hardware CE0 line.
        # We detect this by trying to read; Pi A drives CE0 via spidev.
        # In practice: use GPIO interrupt on CE0 for precision timing.
        _wait_for_ce0_low()

        # --- Step 2: Request received from Pi A → YES (CE0 went low) ---

        # --- Step 3-4: Read joystick (latest values from poll thread) ---
        jx  = _jx
        jy  = _jy
        btn = _btn

        # --- Step 5: Build SPI packet (9 bytes) ---
        x_h = (jx >> 8) & 0xFF
        x_l =  jx       & 0xFF
        y_h = (jy >> 8) & 0xFF
        y_l =  jy       & 0xFF
        cs  = x_h ^ x_l ^ y_h ^ y_l ^ btn

        packet = [PKT_HEADER, x_h, x_l, y_h, y_l, btn, 0x00, 0x00, cs]

        # --- Step 6: Send packet to Pi A via MISO ---
        try:
            raw = spi.xfer2(packet, SPI_SPEED_HZ, 0)
        except Exception:
            continue

        # --- Steps 7-8: Receive game state from Pi A ---
        # Pi A sends game state in the same xfer2 (full-duplex)
        # raw[] contains Pi A's simultaneous transmission
        _parse_game_state(raw)

        # --- Step 9: Game over? ---
        if _game_state == 0xEE:
            print("[Pi B] Game over signal received. Stopping.")
            _stop_event.set()
            break

    print("[Pi B] SPI slave stopped.")
    _cleanup()


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def _wait_for_ce0_low():
    """
    Wait until CE0 (GPIO8) goes LOW — Pi A is starting a transaction.
    Uses busy-wait for minimal latency on Pi 1 (no threading overhead).
    """
    timeout = time.time() + 0.1   # 100 ms max wait per frame
    while GPIO.input(GPIO_CE0_IN) == GPIO.HIGH:
        if time.time() > timeout:
            return   # timeout — Pi A may not be ready yet
    # CE0 is now LOW


def _joystick_poll_loop():
    """
    Background thread: read P2 joystick + button at ≥100 Hz.
    Updates globals _jx, _jy, _btn.
    """
    global _jx, _jy, _btn
    poll_interval = 0.008   # 8 ms → ~125 Hz

    while not _stop_event.is_set():
        _jx, _jy = _read_adc_axes()
        _btn = _read_buttons()
        time.sleep(poll_interval)


def _read_adc_axes():
    """Read X and Y axis from I2C ADC (ADS1x15, 16-bit)."""
    x, y = AXIS_CENTER, AXIS_CENTER
    if not bus:
        return x, y
    try:
        # CH0 → X axis
        bus.write_byte_data(ADC_ADDR, 0x01, 0xC3)
        time.sleep(0.001)
        raw = bus.read_i2c_block_data(ADC_ADDR, 0x00, 2)
        x = ((raw[0] << 8) | raw[1]) & 0xFFFF

        # CH1 → Y axis
        bus.write_byte_data(ADC_ADDR, 0x01, 0xD3)
        time.sleep(0.001)
        raw = bus.read_i2c_block_data(ADC_ADDR, 0x00, 2)
        y = ((raw[0] << 8) | raw[1]) & 0xFFFF
    except Exception:
        pass
    return x, y


def _read_buttons():
    """Read P2 shoot button state. Returns bitmask: bit0 = shoot."""
    btn = 0
    if not GPIO.input(GPIO_SHOOT_P2):   # active low
        btn |= 0x01
    return btn


def _parse_game_state(raw):
    """
    Parse game state packet received from Pi A (9 bytes, full-duplex).
    Packet: [state_byte, p1_lives, p2_lives, p1s_H, p1s_L,
             p2s_H, p2s_L, winner_byte, checksum]
    """
    global _game_state, _p1_lives, _p2_lives, _p1_score, _p2_score, _winner

    if len(raw) < PKT_SIZE:
        return

    state_byte  = raw[0]
    p1l         = raw[1]
    p2l         = raw[2]
    p1s         = (raw[3] << 8) | raw[4]
    p2s         = (raw[5] << 8) | raw[6]
    winner_byte = raw[7]
    cs_recv     = raw[8]

    # Validate checksum
    cs_calc = state_byte ^ p1l ^ p2l ^ raw[3] ^ raw[4] ^ raw[5] ^ raw[6] ^ winner_byte
    if cs_calc != cs_recv:
        return   # Discard corrupted packet — keep last valid state

    _game_state = state_byte
    _p1_lives   = p1l
    _p2_lives   = p2l
    _p1_score   = p1s
    _p2_score   = p2s
    _winner     = winner_byte


def _cleanup():
    """Release SPI and GPIO resources."""
    global spi
    try:
        if spi:
            spi.close()
    except Exception:
        pass
    try:
        GPIO.cleanup()
    except Exception:
        pass
    print("[Pi B] Cleanup complete.")


# =============================================================================
# ENTRY POINT
# =============================================================================

if __name__ == "__main__":
    try:
        startup()
    except KeyboardInterrupt:
        print("\n[Pi B] Interrupted by user.")
        _stop_event.set()
    finally:
        _cleanup()
