#!/usr/bin/env python3
"""Hito 3: una tecla por pulsación, filas inactivas en alta impedancia.

Filas BCM12/13/19/26; columnas BCM2/3/7/21. GPIO7 requiere spi0-1cs.
No conectar VCC ni GND al teclado pasivo: únicamente sus ocho líneas.
"""
import argparse
import signal
import time

GPIO_FILAS = (12, 13, 19, 26)
GPIO_COLUMNAS = (2, 3, 7, 21)
TECLAS = (('1', '2', '3', 'A'), ('4', '5', '6', 'B'),
          ('7', '8', '9', 'C'), ('*', '0', '#', 'D'))
INTERVALO_MUESTREO = 0.020


class DebounceTeclado:
    """Dos muestras iguales, separadas >=20 ms. Multitecla bloquea hasta soltar."""
    def __init__(self):
        self.anterior = None
        self.instante_anterior = None
        self.armado = True

    def actualizar(self, teclas, instante):
        teclas = frozenset(teclas)
        if len(teclas) > 1:
            self.armado = False
        if self.instante_anterior is not None and instante - self.instante_anterior < INTERVALO_MUESTREO:
            return None
        coinciden = teclas == self.anterior
        self.anterior = teclas
        self.instante_anterior = instante
        if not coinciden:
            return None
        if not teclas:
            self.armado = True
        elif len(teclas) == 1 and self.armado:
            self.armado = False
            return next(iter(teclas))
        return None


class TecladoMatricial:
    def __init__(self, numero_gpiochip=0):
        import lgpio
        self.gpio = lgpio
        self.gestor = lgpio.gpiochip_open(numero_gpiochip)
        try:
            for pin in GPIO_FILAS:
                lgpio.gpio_claim_input(self.gestor, pin, lgpio.SET_PULL_NONE)
            for pin in GPIO_COLUMNAS:
                # BCM2/3 tienen pull-ups externos de fábrica a 3,3 V.
                pull = lgpio.SET_PULL_NONE if pin in (2, 3) else lgpio.SET_PULL_UP
                lgpio.gpio_claim_input(self.gestor, pin, pull)
        except BaseException:
            self.cerrar()
            raise

    def _configurar_fila(self, pin, activa):
        self.gpio.gpio_free(self.gestor, pin)
        if activa:
            # Reclamar directamente en LOW; nunca producir un pulso HIGH.
            self.gpio.gpio_claim_output(self.gestor, pin, 0, self.gpio.SET_PULL_NONE)
        else:
            self.gpio.gpio_claim_input(self.gestor, pin, self.gpio.SET_PULL_NONE)

    def muestrear(self):
        pulsadas = set()
        for indice_fila, pin in enumerate(GPIO_FILAS):
            try:
                self._configurar_fila(pin, True)
                time.sleep(0.001)  # asentamiento eléctrico, no debounce
                for indice_columna, columna in enumerate(GPIO_COLUMNAS):
                    if self.gpio.gpio_read(self.gestor, columna) == 0:
                        pulsadas.add(TECLAS[indice_fila][indice_columna])
            finally:
                self._configurar_fila(pin, False)
        return frozenset(pulsadas)

    def cerrar(self):
        if self.gestor is not None:
            self.gpio.gpiochip_close(self.gestor)
            self.gestor = None

    def __enter__(self):
        return self

    def __exit__(self, *argumentos):
        self.cerrar()


def principal():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--gpiochip', type=int, default=0)
    argumentos = parser.parse_args()
    def terminar(signum, frame):
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, terminar)
    try:
        with TecladoMatricial(argumentos.gpiochip) as teclado:
            filtro = DebounceTeclado()
            print('Teclado listo. Pulsá una tecla por vez; Ctrl+C para salir.', flush=True)
            while True:
                pulsadas = teclado.muestrear()
                tecla = filtro.actualizar(pulsadas, time.monotonic())
                if tecla is not None:
                    print(f'Tecla: {tecla}', flush=True)
                # Dos barridos completos separados al menos 20 ms.
                time.sleep(INTERVALO_MUESTREO)
    except KeyboardInterrupt:
        print('\nTeclado detenido; GPIO liberados.')
    except Exception as error:
        print(f'Error de teclado: {error}. Revisar pines y overlay spi0-1cs.')
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(principal())
