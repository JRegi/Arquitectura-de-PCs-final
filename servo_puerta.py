"""Servo posicional con pulsos pigpio en BCM26 (no requiere un pin PWM dedicado)."""
import time


class ServoPuerta:
    def __init__(self, gpio, pulso_cerrado_us, pulso_abierto_us, tiempo_movimiento_s):
        import pigpio
        self.gpio = gpio
        self.pulso_cerrado_us = pulso_cerrado_us
        self.pulso_abierto_us = pulso_abierto_us
        self.tiempo_movimiento_s = tiempo_movimiento_s
        self.conexion = pigpio.pi('localhost')
        if not self.conexion.connected:
            self.conexion.stop()
            raise RuntimeError('pigpiod no responde. Ejecutar: sudo systemctl start pigpiod')

    def _mover(self, pulso_us):
        try:
            resultado = self.conexion.set_servo_pulsewidth(self.gpio, pulso_us)
            if resultado < 0:
                raise RuntimeError(f'pigpio rechazó el pulso: {resultado}')
            time.sleep(self.tiempo_movimiento_s)
        finally:
            # Detach: cesa el tren de pulsos; no hay fuerza de retención garantizada.
            self.conexion.set_servo_pulsewidth(self.gpio, 0)

    def abrir(self):
        self._mover(self.pulso_abierto_us)

    def cerrar(self):
        self._mover(self.pulso_cerrado_us)

    def __enter__(self):
        try:
            self.cerrar()
        except BaseException:
            self.conexion.stop()
            raise
        return self

    def __exit__(self, *argumentos):
        try:
            self.cerrar()
        finally:
            self.conexion.stop()
