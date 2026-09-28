#!/usr/bin/env python3
"""Hito 2: LCD 16x2 con backpack PCF8574, I2C por GPIO23/5.

Mapeo de backpack esperado: P0=RS, P1=RW, P2=E, P3=backlight,
P4..P7=D4..D7. Debe confirmarse visualmente en el módulo real.
Solo escribe; RW permanece LOW. No lee busy flag ni autoriza acceso.
"""
import argparse
import fcntl
import os
import sys
import time

I2C_SLAVE = 0x0703
MASCARA_RS = 0x01
MASCARA_ENABLE = 0x04
MASCARA_BACKLIGHT = 0x08


class PantallaLCD:
    def __init__(self, numero_bus=3, direccion=0x27):
        self.descriptor_bus = os.open(f'/dev/i2c-{numero_bus}', os.O_RDWR)
        try:
            fcntl.ioctl(self.descriptor_bus, I2C_SLAVE, direccion)
            self._escribir_puerto(MASCARA_BACKLIGHT)
            # Inicio explícito incluso si el LCD quedó en medio de un byte.
            time.sleep(0.05)
            for nibble, espera in ((3, 0.005), (3, 0.001), (3, 0.001), (2, 0.001)):
                self._enviar_nibble(nibble, False)
                time.sleep(espera)
            for comando in (0x28, 0x08, 0x01, 0x06, 0x0C):
                self._enviar_byte(comando, False)
        except BaseException:
            self.cerrar()
            raise

    def _escribir_puerto(self, valor):
        if os.write(self.descriptor_bus, bytes([valor])) != 1:
            raise OSError('Escritura I2C incompleta')

    def _enviar_nibble(self, nibble, es_caracter):
        puerto = ((nibble & 0x0F) << 4) | MASCARA_BACKLIGHT
        if es_caracter:
            puerto |= MASCARA_RS
        # Nunca activar P1/RW. Tres escrituras separan setup, pulso y hold.
        self._escribir_puerto(puerto)
        time.sleep(0.0001)
        self._escribir_puerto(puerto | MASCARA_ENABLE)
        time.sleep(0.0001)
        self._escribir_puerto(puerto)
        time.sleep(0.0001)

    def _enviar_byte(self, valor, es_caracter):
        self._enviar_nibble(valor >> 4, es_caracter)
        self._enviar_nibble(valor & 0x0F, es_caracter)
        # Clear y home requieren más tiempo que las instrucciones normales.
        time.sleep(0.003 if not es_caracter and valor in (1, 2) else 0.0001)

    def mostrar_lineas(self, primera_linea, segunda_linea):
        lineas = (primera_linea, segunda_linea)
        for texto in lineas:
            if len(texto) > 16 or any(not 32 <= ord(caracter) <= 126 for caracter in texto):
                raise ValueError('Cada línea admite hasta 16 caracteres ASCII imprimibles.')
        for direccion_fila, texto in zip((0x80, 0xC0), lineas):
            self._enviar_byte(direccion_fila, False)
            for caracter in texto.ljust(16):
                self._enviar_byte(ord(caracter), True)

    def cerrar(self):
        # El LCD conserva el texto y backlight; no requiere un proceso activo.
        if self.descriptor_bus is not None:
            os.close(self.descriptor_bus)
            self.descriptor_bus = None

    def __enter__(self):
        return self

    def __exit__(self, *argumentos):
        self.cerrar()


def principal():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bus', type=int, default=3)
    parser.add_argument('--direccion', type=lambda valor: int(valor, 0), default=0x27)
    argumentos = parser.parse_args()
    try:
        with PantallaLCD(argumentos.bus, argumentos.direccion) as pantalla:
            pantalla.mostrar_lineas('Control acceso', 'Acerque tarjeta')
        print('Texto enviado al LCD. Confirmar visualmente ambas líneas:')
        print('Control acceso\nAcerque tarjeta')
        return 0
    except (OSError, ValueError) as error:
        print(f'Error: {error}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(principal())
