#!/usr/bin/env python3
"""Lee dos UID distintos y guarda la lista autorizada sin accionar el servo."""
import argparse
import fcntl
import json
import os
import signal
import tempfile
import time
from pathlib import Path
from rc522_uid_reader import LectorMFRC522, ErrorLectura, uid_como_texto_hex


def guardar_atomico(ruta, config):
    ruta = Path(ruta).resolve()
    temporal = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', dir=ruta.parent, prefix='.rfid-', delete=False) as archivo:
            temporal = Path(archivo.name)
            json.dump(config, archivo, indent=2, ensure_ascii=False)
            archivo.write('\n')
            archivo.flush()
            os.fsync(archivo.fileno())
        os.replace(temporal, ruta)
    finally:
        if temporal is not None:
            temporal.unlink(missing_ok=True)


def principal():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, default=Path(__file__).with_name('configuracion.json'))
    parser.add_argument('--tiempo-limite', type=float, default=120)
    argumentos = parser.parse_args()
    def detener(signum, frame):
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, detener)
    try:
        config = json.loads(argumentos.config.read_text())
        with open('/tmp/rfid-acceso.lock', 'a') as bloqueo:
            fcntl.flock(bloqueo, fcntl.LOCK_EX | fcntl.LOCK_NB)
            with LectorMFRC522(config['gpiochip']) as lector:
                encontrados = []
                limite = time.monotonic() + argumentos.tiempo_limite
                ultimo_aviso = float('-inf')
                print('REGISTRO: presentar primer llavero y después el segundo. Servo inactivo.', flush=True)
                while len(encontrados) < 2 and time.monotonic() < limite:
                    try:
                        datos = lector.leer_uid()
                    except ErrorLectura as error:
                        if time.monotonic() - ultimo_aviso >= 2:
                            print(f'Lectura incompleta: {error}; reintentando.', flush=True)
                            ultimo_aviso = time.monotonic()
                        lector.restablecer_campo()
                    else:
                        if datos is not None:
                            uid = uid_como_texto_hex(datos)
                            if uid not in encontrados:
                                encontrados.append(uid)
                                print(f'Llavero {len(encontrados)}: {uid}', flush=True)
                                if len(encontrados) == 1:
                                    print('Retirá el primero y acercá el segundo llavero.', flush=True)
                    time.sleep(0.1)
                if len(encontrados) != 2:
                    print('Registro incompleto: no se modificó la configuración.', flush=True)
                    return 1
                config['uids_autorizados'] = encontrados
                guardar_atomico(argumentos.config, config)
                print('Guardados los dos UID en', argumentos.config, flush=True)
    except KeyboardInterrupt:
        print('Registro cancelado; configuración anterior conservada.')
        return 1
    except Exception as error:
        print(f'Error de registro: {error}')
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(principal())
