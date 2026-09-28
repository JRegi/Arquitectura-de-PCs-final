#!/usr/bin/env python3
"""Demo integrada: RC522 + LCD + servo. Configuración junto a este archivo."""
import argparse
import fcntl
import json
import logging
import math
import signal
import time
from contextlib import ExitStack
from pathlib import Path

from controlador_acceso import ControladorAcceso
from estado_sistema import EstadoSistema
from lcd_texto_fijo import PantallaLCD
from padron_rfid import PadronRFID
from rc522_uid_reader import LectorMFRC522, ErrorLectura, uid_como_texto_hex
from servo_puerta import ServoPuerta


def cargar_configuracion(ruta):
    config = json.loads(Path(ruta).read_text())
    if config['gpio_servo'] != 26:
        raise ValueError('Este montaje usa exclusivamente BCM26 para el servo.')
    for nombre in ('pulso_cerrado_us', 'pulso_abierto_us'):
        if type(config[nombre]) is not int or not 500 <= config[nombre] <= 2500:
            raise ValueError(f'{nombre}: debe ser entero entre 500 y 2500 µs.')
    if config['pulso_cerrado_us'] == config['pulso_abierto_us']:
        raise ValueError('Las posiciones abierta y cerrada deben ser distintas.')
    for nombre in ('tiempo_movimiento_s', 'tiempo_abierto_s', 'tiempo_retiro_tarjeta_s'):
        valor = config[nombre]
        if type(valor) not in (int, float) or not math.isfinite(valor) or not 0.1 <= valor <= 60:
            raise ValueError(f'{nombre}: debe estar entre 0,1 y 60 segundos.')
    for nombre, minimo, maximo in (('bus_lcd', 0, 255), ('direccion_lcd', 0x08, 0x77), ('gpiochip', 0, 255)):
        if type(config[nombre]) is not int or not minimo <= config[nombre] <= maximo:
            raise ValueError(f'{nombre} fuera de rango.')
    if not isinstance(config.get('web_host', '0.0.0.0'), str):
        raise ValueError('web_host debe ser texto.')
    puerto = config.get('web_puerto', 5000)
    if type(puerto) is not int or not 1 <= puerto <= 65535:
        raise ValueError('web_puerto fuera de rango.')
    return config


def ejecutar(config):
    from panel_web import ServidorWeb, crear_aplicacion
    detener = False
    def solicitar_salida(signum, frame):
        nonlocal detener
        detener = True
    signal.signal(signal.SIGINT, solicitar_salida)
    signal.signal(signal.SIGTERM, solicitar_salida)
    with ExitStack() as recursos:
        bloqueo = recursos.enter_context(open('/tmp/rfid-acceso.lock', 'a'))
        try:
            fcntl.flock(bloqueo, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError('Ya hay otra instancia de acceso_rfid.py ejecutándose.')
        padron = PadronRFID(Path(__file__).with_name('acceso.sqlite3'))
        estado_sistema = EstadoSistema()
        servidor_web = ServidorWeb(
            crear_aplicacion(padron, estado_sistema, config['tiempo_abierto_s']),
            config.get('web_host', '0.0.0.0'),
            config.get('web_puerto', 5000),
        )
        servidor_web.iniciar()
        recursos.callback(servidor_web.cerrar)
        # Preparar lector/pantalla antes de empezar a mover el servo.
        lector = recursos.enter_context(LectorMFRC522(config['gpiochip']))
        pantalla = recursos.enter_context(PantallaLCD(config['bus_lcd'], config['direccion_lcd']))
        servo = recursos.enter_context(ServoPuerta(config['gpio_servo'],
            config['pulso_cerrado_us'], config['pulso_abierto_us'], config['tiempo_movimiento_s']))
        controlador = ControladorAcceso(
            servo, pantalla, padron.esta_autorizado, padron.modo_control,
            estado_sistema, config['tiempo_abierto_s'], config['tiempo_retiro_tarjeta_s'],
            secuencias=padron, esta_registrado=padron.existe_uid,
            obtener_tiempo_abierto=lambda: padron.tiempo_abierto_s(config['tiempo_abierto_s']))
        estado_sistema.actualizar(lector_activo=True, error=None)
        logging.info('Listo. RC522=0x%02X; servo=BCM26; web=%s:%s', lector.version,
                     config.get('web_host', '0.0.0.0'), config.get('web_puerto', 5000))
        ultimo_error = float('-inf')
        errores_consecutivos = 0
        while not detener:
            try:
                bytes_uid = lector.leer_uid()
            except ErrorLectura as error:
                controlador.actualizar(None, lectura_valida=False)
                estado_sistema.actualizar(error=str(error))
                errores_consecutivos += 1
                if time.monotonic() - ultimo_error >= 2:
                    logging.warning('Lectura RFID incompleta: %s', error)
                    ultimo_error = time.monotonic()
                if errores_consecutivos >= 20:
                    raise RuntimeError('20 errores RFID consecutivos; se detiene y cierra el servo.')
                lector.restablecer_campo()
            else:
                errores_consecutivos = 0
                estado_sistema.actualizar(error=None)
                uid = uid_como_texto_hex(bytes_uid) if bytes_uid is not None else None
                controlador.actualizar(uid)
            time.sleep(0.05)
        # Servo __exit__ cierra antes de liberar el resto de recursos.
        logging.info('Deteniendo y devolviendo servo a cerrado')
        estado_sistema.actualizar(lector_activo=False)


def principal():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, default=Path(__file__).with_name('configuracion.json'))
    parser.add_argument('--validar-config', action='store_true', help='Validar JSON sin usar hardware.')
    argumentos = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s', datefmt='%H:%M:%S')
    try:
        config = cargar_configuracion(argumentos.config)
        if argumentos.validar_config:
            print('Configuración válida:', config)
        else:
            ejecutar(config)
    except Exception as error:
        logging.error('%s', error)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(principal())
