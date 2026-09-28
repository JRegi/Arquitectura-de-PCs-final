import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from controlador_acceso import ControladorAcceso
from acceso_rfid import cargar_configuracion
from servo_puerta import ServoPuerta


class PruebasControlador(unittest.TestCase):
    def setUp(self):
        self.ahora = 0.0
        self.servo = Mock()
        self.lcd = Mock()
        self.controlador = ControladorAcceso(
            self.servo, self.lcd,
            lambda uid: uid == 'B2-B3-40-30', lambda: 'ACCESO',
            reloj=lambda: self.ahora,
        )

    def test_autorizado_abre_y_cierra_sin_prolongar_por_lecturas(self):
        self.controlador.actualizar('B2-B3-40-30')
        self.servo.abrir.assert_called_once()
        for instante in (1, 3, 4.99):
            self.ahora = instante
            self.controlador.actualizar('B2-B3-40-30')
        self.servo.cerrar.assert_not_called()
        self.ahora = 5
        self.controlador.actualizar('B2-B3-40-30')
        self.servo.cerrar.assert_called_once()
        self.servo.abrir.assert_called_once()

    def test_uid_no_autorizado_no_mueve_servo(self):
        self.controlador.actualizar('30-83-9E-D3')
        self.servo.abrir.assert_not_called()
        self.lcd.mostrar_lineas.assert_called_with('Acceso', 'incompleto')

    def test_modo_combinacion_sin_secuencias_no_abre(self):
        controlador = ControladorAcceso(
            self.servo, self.lcd, lambda uid: True, lambda: 'COMBINACION',
            reloj=lambda: self.ahora,
        )
        controlador.actualizar('B2-B3-40-30')
        self.servo.abrir.assert_not_called()
        self.lcd.mostrar_lineas.assert_called_with('Control acceso', 'Acerque tarjeta')

    def test_nuevo_ciclo_solo_despues_de_retirar(self):
        self.controlador.actualizar('B2-B3-40-30')
        self.ahora = 5
        self.controlador.actualizar(None)
        self.ahora = 5.5
        self.controlador.actualizar('B2-B3-40-30')
        self.servo.abrir.assert_called_once()
        self.ahora = 6
        self.controlador.actualizar(None)
        self.ahora = 7.1
        self.controlador.actualizar(None)
        self.controlador.actualizar('B2-B3-40-30')
        self.assertEqual(self.servo.abrir.call_count, 2)

    def test_fallo_rf_no_cuenta_como_retiro_y_no_impide_cierre(self):
        self.controlador.actualizar('B2-B3-40-30')
        self.ahora = 2
        self.controlador.actualizar(None)
        self.ahora = 5
        self.controlador.actualizar(None, lectura_valida=False)
        self.servo.cerrar.assert_called_once()
        self.controlador.actualizar('B2-B3-40-30')
        self.servo.abrir.assert_called_once()

    def test_cierre_antes_del_error_lcd(self):
        self.controlador.actualizar('B2-B3-40-30')
        self.lcd.mostrar_lineas.side_effect = OSError('LCD desconectado')
        self.ahora = 5
        with self.assertRaises(OSError):
            self.controlador.actualizar(None)
        self.servo.cerrar.assert_called_once()

    def test_no_refresca_pantalla_sin_cambios(self):
        for instante in (0, 1, 2, 3):
            self.ahora = instante
            self.controlador.actualizar(None)
        self.lcd.mostrar_lineas.assert_called_once()

    def test_detach_si_movimiento_interrumpido(self):
        servo = ServoPuerta.__new__(ServoPuerta)
        servo.gpio = 26
        servo.tiempo_movimiento_s = 0.6
        servo.conexion = Mock()
        servo.conexion.set_servo_pulsewidth.return_value = 0
        with patch('servo_puerta.time.sleep', side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                servo._mover(1500)
        servo.conexion.set_servo_pulsewidth.assert_called_with(26, 0)

    def test_rechaza_configuracion_insegura(self):
        original = json.loads(Path('configuracion.json').read_text())
        for clave, valor in [('tiempo_abierto_s', float('nan')), ('gpio_servo', 5),
                             ('web_puerto', 70000), ('pulso_abierto_us', 3000)]:
            with self.subTest(clave=clave), tempfile.TemporaryDirectory() as carpeta:
                config = dict(original)
                config[clave] = valor
                ruta = Path(carpeta)/'config.json'
                ruta.write_text(json.dumps(config))
                with self.assertRaises(ValueError):
                    cargar_configuracion(ruta)


if __name__ == '__main__':
    unittest.main()
