#!/usr/bin/env python3
"""Hito 1: UID como identificador, nunca como credencial de acceso.

SPI0 CE0: BCM8/11/10/9; RST: BCM25; alimentación: 3,3 V.
No escribe sectores de la tarjeta ni usa RPi.GPIO. Presentar una tarjeta por vez.
"""
import argparse
import signal
import sys
import time
from contextlib import ExitStack

REGISTRO_COMANDO = 0x01
REGISTRO_IRQ = 0x04
REGISTRO_ERROR = 0x06
REGISTRO_FIFO = 0x09
REGISTRO_NIVEL_FIFO = 0x0A
REGISTRO_CONTROL = 0x0C
REGISTRO_FRAMING = 0x0D
REGISTRO_CONTROL_TX = 0x14
REGISTRO_VERSION = 0x37
GPIO_RST = 25


class ErrorLectura(RuntimeError):
    """Respuesta inválida, colisión o fallo del lector; no ausencia normal."""


def calcular_crc_a(datos):
    """CRC ISO/IEC 14443 A: valor inicial 0x6363, byte bajo primero."""
    crc = 0x6363
    for valor in datos:
        crc ^= valor
        for _ in range(8):
            crc = (crc >> 1) ^ (0x8408 if crc & 1 else 0)
    return [crc & 0xFF, crc >> 8]


def uid_como_texto_hex(bytes_uid):
    return "-".join(f"{valor:02X}" for valor in bytes_uid)


class LectorMFRC522:
    def __init__(self, numero_gpiochip=0):
        # Importación diferida: --help y las pruebas no necesitan hardware.
        import lgpio
        import spidev

        self.gpio = lgpio
        self.recursos = ExitStack()
        try:
            self.gestor_gpio = lgpio.gpiochip_open(numero_gpiochip)
            self.recursos.callback(lgpio.gpiochip_close, self.gestor_gpio)
            lgpio.gpio_claim_output(self.gestor_gpio, GPIO_RST, 1)
            self.bus_spi = spidev.SpiDev()
            self.recursos.callback(self.bus_spi.close)
            self.bus_spi.open(0, 0)
            self.bus_spi.max_speed_hz = 1_000_000
            self.bus_spi.mode = 0
            lgpio.gpio_write(self.gestor_gpio, GPIO_RST, 0)
            time.sleep(0.05)
            lgpio.gpio_write(self.gestor_gpio, GPIO_RST, 1)
            time.sleep(0.05)
            self.version = self._leer_registro(REGISTRO_VERSION)
            if self.version in (0x00, 0xFF):
                raise ErrorLectura(
                    f"VersionReg=0x{self.version:02X}: revisar SPI, alimentación y cableado."
                )
            self._escribir_registro(REGISTRO_COMANDO, 0x0F)
            time.sleep(0.05)
            if self._leer_registro(REGISTRO_COMANDO) & 0x10:
                raise ErrorLectura("El MFRC522 no salió del reset.")
            # Timer automático: 13,56 MHz / (2*169 + 1), recarga 1000: 25 ms.
            for direccion, valor in (
                (0x2A, 0x80), (0x2B, 0xA9), (0x2C, 0x03), (0x2D, 0xE8),
                (0x12, 0x00), (0x13, 0x00),  # 106 kBd, CRC manual
                (0x15, 0x40), (0x11, 0x3D),
            ):
                self._escribir_registro(direccion, valor)
            self._escribir_registro(REGISTRO_CONTROL_TX,
                                    self._leer_registro(REGISTRO_CONTROL_TX) | 0x03)
            self.recursos.callback(self._apagar_antena)
            time.sleep(0.01)
        except BaseException:
            self.recursos.close()
            raise

    def _apagar_antena(self):
        self._escribir_registro(REGISTRO_CONTROL_TX,
                                self._leer_registro(REGISTRO_CONTROL_TX) & 0xFC)

    def cerrar(self):
        """Cierre idempotente, incluso si falla la inicialización."""
        self.recursos.close()

    def restablecer_campo(self):
        """Devuelve la tarjeta a IDLE tras una selección interrumpida."""
        self._apagar_antena()
        time.sleep(0.01)
        self._escribir_registro(REGISTRO_CONTROL_TX,
                                self._leer_registro(REGISTRO_CONTROL_TX) | 0x03)
        time.sleep(0.01)

    def __enter__(self):
        return self

    def __exit__(self, *argumentos):
        self.cerrar()

    def _escribir_registro(self, direccion, valor):
        self.bus_spi.xfer2([(direccion << 1) & 0x7E, valor & 0xFF])

    def _leer_registro(self, direccion):
        return self.bus_spi.xfer2([((direccion << 1) & 0x7E) | 0x80, 0])[1]

    def _transceive(self, datos, bits_ultimo_byte=0):
        """Devuelve (bytes, bits) o None al vencer el timer del chip."""
        self._escribir_registro(REGISTRO_COMANDO, 0x00)
        # IRQ usa write-one-to-clear con Set1=0; no es un registro común.
        self._escribir_registro(REGISTRO_IRQ, 0x7F)
        self._escribir_registro(REGISTRO_NIVEL_FIFO, 0x80)
        for valor in datos:
            self._escribir_registro(REGISTRO_FIFO, valor)
        self._escribir_registro(REGISTRO_FRAMING, bits_ultimo_byte)
        self._escribir_registro(REGISTRO_COMANDO, 0x0C)
        self._escribir_registro(REGISTRO_FRAMING, 0x80 | bits_ultimo_byte)
        limite = time.monotonic() + 0.15
        try:
            while time.monotonic() < limite:
                interrupciones = self._leer_registro(REGISTRO_IRQ)
                errores = self._leer_registro(REGISTRO_ERROR) & 0xDF
                if errores:
                    raise ErrorLectura(f"ErrorReg=0x{errores:02X}; presentar una sola tarjeta.")
                if interrupciones & 0x20:  # RxIRq: trama recibida
                    cantidad = self._leer_registro(REGISTRO_NIVEL_FIFO) & 0x7F
                    bits_finales = self._leer_registro(REGISTRO_CONTROL) & 7
                    if not 1 <= cantidad <= 64:
                        raise ErrorLectura(f"Longitud FIFO inválida: {cantidad}.")
                    respuesta = [self._leer_registro(REGISTRO_FIFO) for _ in range(cantidad)]
                    bits = (cantidad - 1) * 8 + (bits_finales or 8)
                    return respuesta, bits
                if interrupciones & 0x01:
                    return None
                time.sleep(0.001)
            raise ErrorLectura("Timeout del lector: no llegaron RxIRq ni TimerIRq.")
        finally:
            self._escribir_registro(REGISTRO_FRAMING, bits_ultimo_byte)
            self._escribir_registro(REGISTRO_COMANDO, 0x00)

    def leer_uid(self):
        """Selecciona UID completo de 4, 7 o 10 bytes; None si no hay tarjeta.

        El UID es clonable y se transmite en claro. La demo usa una lista de UID autorizados, sin PIN.
        Este módulo solo entrega identificadores; no decide la apertura.
        """
        # WUPA permite volver a leer tarjetas que dejamos en HALT.
        respuesta = self._transceive([0x52], 7)
        if respuesta is None:
            return None
        if respuesta[1] != 16:
            raise ErrorLectura("ATQA inválido: se esperaban 16 bits.")
        uid = []
        for nivel, comando in enumerate((0x93, 0x95, 0x97)):
            respuesta = self._transceive([comando, 0x20])
            if respuesta is None or respuesta[1] != 40:
                raise ErrorLectura("Respuesta de anticolisión incompleta.")
            bloque = respuesta[0]
            if bloque[0] ^ bloque[1] ^ bloque[2] ^ bloque[3] != bloque[4]:
                raise ErrorLectura("BCC incorrecto en el UID.")
            seleccion = [comando, 0x70] + bloque
            respuesta = self._transceive(seleccion + calcular_crc_a(seleccion))
            if respuesta is None or respuesta[1] != 24:
                raise ErrorLectura("SELECT sin SAK válido.")
            sak = respuesta[0]
            if calcular_crc_a(sak[:1]) != sak[1:]:
                raise ErrorLectura("CRC incorrecto en SAK.")
            continua = bool(sak[0] & 0x04)
            if continua:
                if nivel == 2 or bloque[0] != 0x88:
                    raise ErrorLectura("Cascade Tag inconsistente.")
                uid.extend(bloque[1:4])
            else:
                if nivel < 2 and bloque[0] == 0x88:
                    raise ErrorLectura("UID incompleto: falta cascade bit en SAK.")
                uid.extend(bloque[:4])
                # HALT no responde: el silencio es la respuesta correcta.
                halt = [0x50, 0x00]
                if self._transceive(halt + calcular_crc_a(halt)) is not None:
                    raise ErrorLectura("Respuesta inesperada a HALT.")
                return uid
        raise ErrorLectura("UID excede tres niveles de cascada.")


def principal():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gpiochip", type=int, default=0,
                        help="Número de /dev/gpiochipN; verificar en el Pi (default: 0).")
    parser.add_argument("--diagnostico", action="store_true",
                        help="Inicializa el lector, muestra VersionReg y sale.")
    argumentos = parser.parse_args()
    def terminar(signum, frame):
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, terminar)
    try:
        with LectorMFRC522(argumentos.gpiochip) as lector:
            print(f"VersionReg: 0x{lector.version:02X}", flush=True)
            if lector.version not in (0x91, 0x92):
                print("Versión no estándar: la lectura de UID debe validarse en hardware.", flush=True)
            if argumentos.diagnostico:
                return 0
            print("Acercá tarjeta o llavero, uno por vez. Ctrl+C para salir.", flush=True)
            ultimo_uid = None
            ultima_impresion = 0.0
            ultimo_aviso_error = float('-inf')
            while True:
                try:
                    uid = lector.leer_uid()
                except ErrorLectura as error:
                    # Una retirada o trama dañada no debe terminar el lector.
                    # Nunca se publica un UID parcial durante la recuperación.
                    if time.monotonic() - ultimo_aviso_error >= 2.0:
                        print(f"Lectura incompleta: {error} Reintentando.",
                              file=sys.stderr, flush=True)
                        ultimo_aviso_error = time.monotonic()
                    lector.restablecer_campo()
                    time.sleep(0.1)
                    continue
                ahora = time.monotonic()
                if uid is None:
                    ultimo_uid = None
                elif uid != ultimo_uid or ahora - ultima_impresion >= 1.0:
                    print(f"UID leído: {uid_como_texto_hex(uid)} ({len(uid)} bytes)", flush=True)
                    ultimo_uid, ultima_impresion = uid, ahora
                time.sleep(0.1)
    except KeyboardInterrupt:
        print("\nSaliendo; recursos liberados.")
        return 0
    except (ErrorLectura, OSError, ImportError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(principal())
